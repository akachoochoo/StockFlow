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
        assert payload["decision"]["buy_action"]["slot_number"] == 1
        assert payload["decision"]["skip_reason"] is None
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
# --config option (Phase 0.5 step 0.5.20, ADR §6.3)
# ---------------------------------------------------------------------------
def _yaml_config(
    tmp_path: Path,
    *,
    code: str = "069500",
    drop: str = "5.0",
    profit_target: str = "10.0",
    reentry: str = "hybrid",
    cooldown: int = 60,
    window: int | None = None,
) -> Path:
    """Write a Phase 0.5 strategies YAML and return its path."""
    reentry_block = (
        f"reentry_strategy: \"{reentry}\"\n"
        f"    reentry_parameters:\n"
        + (f"      window: {window}\n" if window is not None else "")
        + (
            f"      cooldown_days: {cooldown}\n"
            if reentry == "hybrid" or window is None
            else ""
        )
    )
    body = f"""\
version: "0.5"
assets:
  "{code}":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters:
      drop_threshold_pct: {drop}
      max_split_count: 7
      per_split_amount: 500000
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: {profit_target}
    {reentry_block.rstrip()}
"""
    path = tmp_path / "strategies.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class TestConfigOption:
    def test_backtest_with_config_runs(self, csv_path, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--capital", "5000000",
                "--config", str(_yaml_config(tmp_path)),
                "--start", "2026-04-27", "--end", "2026-04-30",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Backtest result" in result.output
        # YAML drop=5.0 + per_split=500000 produces the same buys as the
        # flag-only happy path. Spot-check via splits.
        assert "buy_split_1" in result.output

    def test_paper_with_config_runs(self, csv_path, tmp_path):
        runner = CliRunner()
        db = tmp_path / "paper.db"
        result = runner.invoke(
            main,
            [
                "paper",
                "--csv", str(csv_path),
                "--db", str(db),
                "--capital", "5000000",
                "--config", str(_yaml_config(tmp_path)),
                "--date", "2026-04-28",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Paper trading" in result.output
        assert db.exists()

    def test_config_with_strategy_flag_rejected(self, csv_path, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--config", str(_yaml_config(tmp_path)),
                "--drop-pct", "5.0",  # mutually exclusive
                "--start", "2026-04-27", "--end", "2026-04-30",
            ],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output
        assert "--drop-pct" in result.output

    def test_config_with_multiple_strategy_flags_lists_all(self, csv_path, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--config", str(_yaml_config(tmp_path)),
                "--drop-pct", "5.0",
                "--cooldown-days", "30",
                "--start", "2026-04-27", "--end", "2026-04-30",
            ],
        )
        assert result.exit_code != 0
        assert "--drop-pct" in result.output
        assert "--cooldown-days" in result.output

    def test_config_with_meta_only_options_allowed(self, csv_path, tmp_path):
        # --capital + --json + --csv + --start + --end are meta options;
        # they may coexist with --config without raising (ADR §6.3).
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--capital", "8000000",
                "--config", str(_yaml_config(tmp_path)),
                "--start", "2026-04-27", "--end", "2026-04-30",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["initial_capital"]["amount"] == "8000000"

    def test_moving_average_flag_without_config_rejected(self, csv_path):
        # ADR §6.3: flag-only path supports hybrid only; moving_average
        # has window/ma_type only via YAML.
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--reentry-strategy", "moving_average",
                "--start", "2026-04-27", "--end", "2026-04-30",
            ],
        )
        assert result.exit_code != 0
        assert "moving_average" in result.output
        assert "--config" in result.output

    def test_config_asset_code_mismatch_rejected(self, csv_path, tmp_path):
        # Phase 0.5 single-asset hardcoded to KODEX 200 (069500); arbitrary
        # YAML codes raise UsageError until the Phase 0.7 ADR round.
        runner = CliRunner()
        config = _yaml_config(tmp_path, code="999999")
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--config", str(config),
                "--start", "2026-04-27", "--end", "2026-04-30",
            ],
        )
        assert result.exit_code != 0
        assert "999999" in result.output
        assert "069500" in result.output

    def test_flag_only_path_unchanged_when_config_absent(self, csv_path):
        # Regression: explicit strategy flags still work without --config
        # (Phase 0 compatibility, ADR §6.3 last bullet).
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--capital", "5000000",
                "--drop-pct", "5.0",
                "--per-split-amount", "500000",
                "--profit-target-pct", "10.0",
                "--max-sells-per-day", "3",
                "--cooldown-days", "30",
                "--start", "2026-04-27", "--end", "2026-04-30",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Backtest result" in result.output


# ---------------------------------------------------------------------------
# trading config validate (Phase 0.5 step 0.5.21, ADR §6.3)
# ---------------------------------------------------------------------------
class TestConfigValidate:
    def test_validates_valid_config(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "config",
                "validate",
                "--config",
                str(_yaml_config(tmp_path)),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Config valid: 1 asset(s)" in result.output
        assert "069500" in result.output
        assert "KODEX 200" in result.output
        # Per-asset summary surfaces the strategy fingerprint.
        assert "buy=price_drop" in result.output
        assert "drop=5.0%" in result.output
        assert "profit_target=+10.0%" in result.output
        assert "reentry=hybrid" in result.output

    def test_validates_moving_average_config(self, tmp_path):
        # Confirms the validate command reports the D-2 reentry policy
        # with its window parameter (the path the flag-only CLI rejects).
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "config",
                "validate",
                "--config",
                str(
                    _yaml_config(
                        tmp_path, reentry="moving_average", window=20
                    )
                ),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "reentry=moving_average" in result.output
        assert "window" in result.output

    def test_invalid_yaml_exits_with_error(self, tmp_path):
        # ADR §6.2 strict + extra='forbid': missing version surfaces here.
        path = tmp_path / "broken.yaml"
        path.write_text("assets: {}\n", encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(main, ["config", "validate", "--config", str(path)])
        assert result.exit_code != 0
        # Error goes to stderr per click conventions; CliRunner mixes
        # streams into ``result.output``.
        assert "Config invalid" in result.output

    def test_unknown_strategy_name_rejected(self, tmp_path):
        # ADR §4.1.1 deprecated 'current_market'; loader rejects it.
        path = tmp_path / "deprecated.yaml"
        path.write_text(
            """\
version: "0.5"
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters:
      drop_threshold_pct: 5.0
      max_split_count: 7
      per_split_amount: 500000
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: 10.0
    reentry_strategy: "current_market"
    reentry_parameters:
      cooldown_days: 60
""",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["config", "validate", "--config", str(path)])
        assert result.exit_code != 0
        assert "Config invalid" in result.output

    def test_validate_does_not_run_anything(self, tmp_path):
        # Validate is read-only: no SQLite DB or other artefact created.
        runner = CliRunner()
        before = set(tmp_path.iterdir())
        runner.invoke(
            main,
            [
                "config",
                "validate",
                "--config",
                str(_yaml_config(tmp_path)),
            ],
        )
        after = set(tmp_path.iterdir())
        new_files = after - before
        # Only the YAML itself exists (created by _yaml_config); no DB,
        # no lock, no snapshot.
        assert all(p.suffix == ".yaml" for p in new_files), (
            f"validate left side-effects: {new_files}"
        )


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


# ---------------------------------------------------------------------------
# Phase 0.7.1.e — multi-asset YAML UsageError (0.7.1.f/h 전까지 단일 CSV)
# ---------------------------------------------------------------------------
class TestMultiAssetUsageError:
    """Phase 0.7.1.e: multi-asset YAML + single --csv → UsageError.

    The full multi-asset CSV flow is gated behind 0.7.1.f (download) +
    0.7.1.h (backtest execution). Until then, enabled > 1 asset with a
    single --csv must surface a clear UsageError pointing to the future steps.
    """

    def _multi_asset_config(self, tmp_path: Path) -> Path:
        from pathlib import Path as _Path
        repo_root = _Path(__file__).resolve().parents[2]
        return repo_root / "config" / "strategies-0.7.1-F.yaml"

    def test_backtest_multi_asset_yaml_raises_usage_error(self, csv_path, tmp_path):
        runner = CliRunner()
        config = self._multi_asset_config(tmp_path)
        result = runner.invoke(
            main,
            [
                "backtest",
                "--csv", str(csv_path),
                "--config", str(config),
                "--start", "2026-04-27",
                "--end", "2026-04-30",
            ],
        )
        assert result.exit_code != 0
        # UsageError must mention the blocking reason and the phase gate.
        assert "0.7.1" in result.output
        assert "multi-asset" in result.output.lower() or "069500" in result.output

    def test_paper_multi_asset_yaml_raises_usage_error(self, csv_path, tmp_path):
        db = tmp_path / "paper.db"
        runner = CliRunner()
        config = self._multi_asset_config(tmp_path)
        result = runner.invoke(
            main,
            [
                "paper",
                "--csv", str(csv_path),
                "--config", str(config),
                "--date", "2026-04-28",
                "--db", str(db),
            ],
        )
        assert result.exit_code != 0
        assert "0.7.1" in result.output
