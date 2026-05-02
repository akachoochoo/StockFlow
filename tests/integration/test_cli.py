"""CLI integration tests via Click's CliRunner (ADR §10.9 step 10.h).

Exercises ``trading backtest`` and ``trading paper`` end-to-end including
the kill-switch (CLAUDE.md §11.1) and lock-file (§10.2) paths. Cross-day
state restoration is also covered here (single-DB happy path); the
backtest-vs-paper *equivalence* regression lives in step 10.i.
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from src.cli import safety
from src.cli.main import main

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path, monkeypatch):
    """Redirect the lock file into the test tmp dir so no two CLI tests
    fight over ``~/.trading-system.lock``.
    """
    lock_path = tmp_path / "test.lock"
    monkeypatch.setattr(safety, "_DEFAULT_LOCK_PATH", lock_path)
    return lock_path


@pytest.fixture
def csv_path(tmp_path) -> Path:
    """Write a 4-day OHLCV fixture and return its path.

    Day 3 has a deliberate close-vs-T-1 drop > 7 % so PriceDropStrategy
    triggers ``buy_split_2`` on day 4.
    """
    rows = [
        ("2026-04-27", "30000", "30200", "29800", "30000", "1000"),
        ("2026-04-28", "30000", "30100", "29900", "30000", "1000"),
        ("2026-04-29", "29000", "29100", "27900", "28000", "2000"),
        ("2026-04-30", "28000", "28200", "27900", "28100", "1500"),
    ]
    csv = tmp_path / "kodex.csv"
    body = "date,open,high,low,close,volume\n" + "\n".join(
        ",".join(r) for r in rows
    )
    csv.write_text(body + "\n")
    return csv


def _shared_args(csv_path: Path) -> list[str]:
    """Strategy-config flags reused across most tests."""
    return [
        "--csv", str(csv_path),
        "--capital", "5000000",
        "--drop-pct", "5.0",
        "--per-split-amount", "500000",
    ]


# ---------------------------------------------------------------------------
# trading backtest
# ---------------------------------------------------------------------------
class TestBacktest:
    def test_text_output_happy_path(self, csv_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", *_shared_args(csv_path),
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert result.exit_code == 0, result.output
        assert "Backtest result" in result.output
        assert "Total return:" in result.output
        # 2 buys triggered: split_1 on 2026-04-28, split_2 on 2026-04-30
        assert "buy_split_1" in result.output
        assert "buy_split_2" in result.output

    def test_json_output_parses(self, csv_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", *_shared_args(csv_path),
             "--start", "2026-04-27", "--end", "2026-04-30",
             "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["start_date"] == "2026-04-27"
        assert payload["end_date"] == "2026-04-30"
        assert payload["initial_capital"]["amount"] == "5000000"
        assert payload["initial_capital"]["currency"] == "KRW"
        # Decimal-as-string preserved
        assert isinstance(payload["total_return_pct"], str)
        assert isinstance(payload["cagr_pct"], str)
        assert payload["n_trading_days"] == 4
        assert len(payload["decisions"]) == 4
        assert len(payload["snapshots"]) == 4

    def test_missing_required_csv_arg(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert result.exit_code != 0
        assert "Missing option" in result.output and "--csv" in result.output

    def test_invalid_csv_path_rejected_before_run(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", "--csv", str(tmp_path / "missing.csv"),
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert result.exit_code != 0
        # Click's exists=True validation
        assert "does not exist" in result.output

    def test_invalid_date_format_rejected(self, csv_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", *_shared_args(csv_path),
             "--start", "2026/04/27", "--end", "2026-04-30"],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# trading paper
# ---------------------------------------------------------------------------
class TestPaper:
    def test_first_run_creates_db_and_uses_initial_capital(
        self, csv_path, tmp_path
    ):
        db = tmp_path / "paper.db"
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["paper", *_shared_args(csv_path),
             "--date", "2026-04-29", "--db", str(db)],
        )
        assert result.exit_code == 0, result.output
        assert db.exists()
        assert "Paper trading" in result.output
        assert "buy_split_1" in result.output
        # qty=floor(500_000 / 30_000) = 16; cash=5_000_000 - 16*30_000
        assert "qty=16" in result.output
        assert "Cash:            4520000" in result.output

    def test_second_run_restores_state_from_sqlite(self, csv_path, tmp_path):
        db = tmp_path / "paper.db"
        runner = CliRunner()
        # Day 1 — establishes split_1
        first = runner.invoke(
            main,
            ["paper", *_shared_args(csv_path),
             "--date", "2026-04-29", "--db", str(db)],
        )
        assert first.exit_code == 0, first.output

        # Day 2 — must see the restored position; T-1 close (28000) vs
        # avg (30000) is a 6.67 % drop → buy_split_2 fires
        second = runner.invoke(
            main,
            ["paper", *_shared_args(csv_path),
             "--date", "2026-04-30", "--db", str(db)],
        )
        assert second.exit_code == 0, second.output
        assert "buy_split_2" in second.output
        assert "level=2" in second.output
        # 16 + 17 = 33 shares total (split_2 qty = floor(500_000/28_000) = 17)
        assert "qty=33" in second.output

    def test_json_output_paper(self, csv_path, tmp_path):
        db = tmp_path / "paper.db"
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["paper", *_shared_args(csv_path),
             "--date", "2026-04-29", "--db", str(db),
             "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["decision"]["action"] == "buy_split_1"
        assert payload["snapshot"]["snapshot_date"] == "2026-04-29"
        assert payload["snapshot"]["cash"]["currency"] == "KRW"
        # Decimal precision survives the round-trip
        assert payload["snapshot"]["cash"]["amount"] == "4520000"

    def test_missing_required_db_arg(self, csv_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["paper", "--csv", str(csv_path), "--date", "2026-04-29"],
        )
        assert result.exit_code != 0
        assert "Missing option" in result.output and "--db" in result.output


# ---------------------------------------------------------------------------
# Kill switch (CLAUDE.md §11.1)
# ---------------------------------------------------------------------------
class TestKillSwitch:
    def test_halt_blocks_backtest_with_clean_exit(self, csv_path, monkeypatch):
        monkeypatch.setenv("TRADING_HALT", "1")
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", *_shared_args(csv_path),
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        # Operator-requested halt → clean exit (0), no traceback.
        assert result.exit_code == 0
        assert "Backtest result" not in result.output

    def test_halt_blocks_paper_with_clean_exit(
        self, csv_path, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("TRADING_HALT", "1")
        db = tmp_path / "paper.db"
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["paper", *_shared_args(csv_path),
             "--date", "2026-04-29", "--db", str(db)],
        )
        assert result.exit_code == 0
        assert "Paper trading" not in result.output
        assert not db.exists()


# ---------------------------------------------------------------------------
# Lock contention (CLAUDE.md §10.2)
# ---------------------------------------------------------------------------
class TestLock:
    def test_alive_concurrent_holder_raises_concurrent_run_error(
        self, csv_path, _isolated_lock
    ):
        # Pre-stage the lock file with the *current* PID — that PID is
        # obviously alive, and acquire_lock treats same-PID as idempotent
        # by design. So we use a different alive PID: pid 1 (init) which
        # exists on every POSIX system.
        _isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        _isolated_lock.write_text("1\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", *_shared_args(csv_path),
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert result.exit_code != 0
        assert isinstance(result.exception, safety.ConcurrentRunError)

    def test_stale_lock_is_cleaned_and_run_proceeds(
        self, csv_path, _isolated_lock
    ):
        # Use a PID guaranteed not to be alive (very large, well past PID_MAX).
        # acquire_lock detects stale and clears it.
        _isolated_lock.parent.mkdir(parents=True, exist_ok=True)
        _isolated_lock.write_text("2999999\n")

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", *_shared_args(csv_path),
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert result.exit_code == 0, result.output
        # Lock released after normal exit
        assert not _isolated_lock.exists()

    def test_lock_released_after_normal_exit(self, csv_path, _isolated_lock):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["backtest", *_shared_args(csv_path),
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert result.exit_code == 0, result.output
        assert not _isolated_lock.exists()


# ---------------------------------------------------------------------------
# Sanity check (ADR §10.4)
# ---------------------------------------------------------------------------
class TestSanityCheck:
    def test_snapshot_position_mismatch_halts_paper(
        self, csv_path, tmp_path
    ):
        """Snapshot has a position that the positions table no longer
        reflects → IntegrityError, no new decisions.
        """
        from datetime import UTC, date, datetime
        from decimal import Decimal

        from src.domain.exceptions import IntegrityError
        from src.domain.models import (
            Currency,
            Money,
            PortfolioSnapshot,
            PositionValuation,
        )
        from src.infrastructure.db import connect
        from src.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

        db = tmp_path / "paper.db"
        # Pre-stage a snapshot referencing KODEX 200 but DON'T save the
        # corresponding position row → §10.4 sanity check must fire.
        from src.cli.composition import kodex200
        asset = kodex200()
        valuation = PositionValuation(
            asset=asset,
            quantity=Decimal("10"),
            avg_price=Decimal("30000"),
            market_price=Decimal("30000"),
            market_value=Money(amount=Decimal("300000"), currency=Currency.KRW),
            unrealized_pnl=Money(
                amount=Decimal("0"), currency=Currency.KRW
            ),
            split_level=1,
        )
        snap = PortfolioSnapshot(
            snapshot_date=date(2026, 4, 28),
            snapshot_at=datetime(2026, 4, 28, 7, 0, tzinfo=UTC),
            initial_capital=Money(
                amount=Decimal("5000000"), currency=Currency.KRW
            ),
            cash=Money(amount=Decimal("4700000"), currency=Currency.KRW),
            valuations=[valuation],
            total_market_value=Money(
                amount=Decimal("300000"), currency=Currency.KRW
            ),
            total_value=Money(
                amount=Decimal("5000000"), currency=Currency.KRW
            ),
            total_cost_basis=Money(
                amount=Decimal("300000"), currency=Currency.KRW
            ),
            total_unrealized_pnl=Money(
                amount=Decimal("0"), currency=Currency.KRW
            ),
        )
        conn = connect(db)
        try:
            with SqliteUnitOfWork(conn) as uow:
                uow.snapshots.save(snap)
                uow.commit()
        finally:
            conn.close()

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["paper", *_shared_args(csv_path),
             "--date", "2026-04-29", "--db", str(db)],
        )
        assert result.exit_code != 0
        assert isinstance(result.exception, IntegrityError)
        assert "Snapshot/position mismatch" in str(result.exception)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------
def test_top_level_help_lists_both_commands():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "backtest" in result.output
    assert "paper" in result.output


def test_unknown_subcommand_fails():
    runner = CliRunner()
    result = runner.invoke(main, ["nonsense"])
    assert result.exit_code != 0


# Sanity: make sure the kill-switch fixture didn't leak between tests
def test_kill_switch_env_not_set_by_default():
    assert os.environ.get("TRADING_HALT") != "1"
