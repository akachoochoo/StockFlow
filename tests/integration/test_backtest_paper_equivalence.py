"""Backtest vs paper trading equivalence regression (ADR §10.8 / step 10.k).

The single most important Phase 0 invariant (CLAUDE.md §7.4): backtesting
historical data via ``BacktestRunner`` and replaying the same data
day-by-day through the ``trading paper`` CLI (cron simulation) MUST
produce identical decisions and the same final state. If this regression
ever breaks, something has crept in that depends on wall-clock time or
external state (a violation of §3.2 / §1.2).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from src.application.backtest_runner import BacktestRunner
from src.cli import composition, safety
from src.cli.main import main
from src.domain.models import Currency, Money
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.infrastructure.csv_market_data_loader import load_ohlcv_csv
from src.infrastructure.db import connect
from src.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# 9-day fixture engineered to fire 5 sequential buy_split levels
# ---------------------------------------------------------------------------
CSV_ROWS: list[tuple[str, str, str, str, str, str]] = [
    # date          open    high    low     close   volume
    ("2026-04-20", "30000", "30200", "29800", "30000", "1000"),
    ("2026-04-21", "30000", "30100", "29900", "30000", "1000"),
    ("2026-04-22", "30000", "30050", "29950", "30000", "1000"),
    ("2026-04-23", "29000", "29100", "27900", "28000", "2000"),
    ("2026-04-24", "28000", "28200", "27900", "28100", "1500"),
    ("2026-04-27", "28000", "28200", "26100", "26200", "2000"),
    ("2026-04-28", "26000", "26200", "25900", "26000", "1500"),
    ("2026-04-29", "25000", "25500", "23500", "24000", "2500"),
    ("2026-04-30", "24000", "24500", "23800", "24300", "1500"),
]
START = date(2026, 4, 20)
END = date(2026, 4, 30)
CAPITAL = 5_000_000
SHARED_FLAGS: list[str] = [
    "--capital", str(CAPITAL),
    "--drop-pct", "5",
    "--max-split", "7",
    "--per-split-amount", "500000",
    "--max-split-per-day", "1",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "_DEFAULT_LOCK_PATH", tmp_path / "test.lock")
    # Stub the NTP gate (no reachable server in CI/sandbox). The real
    # fail-closed behaviour is covered in tests/unit/cli/test_safety_ntp_halt.py.
    monkeypatch.setattr(safety, "verify_ntp_sync", lambda **_: None)


@pytest.fixture
def csv_path(tmp_path) -> Path:
    p = tmp_path / "kodex.csv"
    body = "date,open,high,low,close,volume\n" + "\n".join(
        ",".join(r) for r in CSV_ROWS
    )
    p.write_text(body + "\n")
    return p


def _trading_dates() -> list[date]:
    return [date.fromisoformat(r[0]) for r in CSV_ROWS]


def _build_config() -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal("5"),
        max_split_count=7,
        per_split_amount=Money(amount=Decimal(500_000), currency=Currency.KRW),
        max_split_per_day=1,
    )


def _decision_keys(decisions):
    """Return the comparison key for each decision.

    We compare on (date, action, filled_quantity, filled_price) — the
    timestamps differ in nanos because backtest swaps the clock holder
    while paper rebuilds it per CLI run, but the *date* part is what
    matters for "same outcome on the same day".
    """
    keys = []
    for d in decisions:
        if d.buy_action is not None:
            buy_summary = (
                d.buy_action.slot_number,
                str(d.buy_action.filled_quantity),
                str(d.buy_action.filled_price),
            )
        else:
            buy_summary = None
        sells_summary = tuple(
            (sa.slot_number, str(sa.filled_quantity), str(sa.filled_price))
            for sa in d.sell_actions
        )
        keys.append((
            d.timestamp.date(),
            tuple(d.action_kinds()),
            sells_summary,
            buy_summary,
        ))
    return keys


# ---------------------------------------------------------------------------
# The regression test itself
# ---------------------------------------------------------------------------
def test_backtest_and_paper_produce_identical_outcomes(tmp_path, csv_path):
    asset = composition.kodex200()
    bars = load_ohlcv_csv(csv_path, asset)
    config = _build_config()
    initial_capital = Money(
        amount=Decimal(CAPITAL), currency=Currency.KRW
    )

    # ---------- Path A: BacktestRunner (one call, in-memory state) ----------
    runner = BacktestRunner(
        assets=[asset],
        strategy_config=config,
        initial_capital=initial_capital,
        ohlcv_by_asset={asset: bars},
    )
    bt_result = runner.run(START, END)

    # ---------- Path B: trading paper, cron-simulated day-by-day ----------
    db = tmp_path / "paper.db"
    cli = CliRunner()
    base_args = [
        "paper",
        "--csv", str(csv_path),
        "--db", str(db),
        *SHARED_FLAGS,
    ]
    for d in _trading_dates():
        result = cli.invoke(
            main, [*base_args, "--date", d.isoformat()]
        )
        assert result.exit_code == 0, (
            f"paper failed on {d}: exception={result.exception!r}"
            f"\n{result.output}"
        )

    conn = connect(db)
    try:
        with SqliteUnitOfWork(conn) as uow:
            paper_decisions = uow.decisions.list_by_date_range(START, END)
            paper_positions = uow.positions.list_all()
            paper_last_snap = uow.snapshots.get_last()
    finally:
        conn.close()

    # ---------- Compare decision sequences ----------
    bt_keys = _decision_keys(bt_result.decisions)
    paper_keys = _decision_keys(paper_decisions)
    assert bt_keys == paper_keys, (
        "\nBacktest and paper diverged on decision sequence:"
        f"\n  backtest: {bt_keys}"
        f"\n  paper:    {paper_keys}"
    )

    # The fixture is engineered for ≥ 4 buys — a too-quiet sequence would
    # let a regression hide. Lock that floor in.
    buy_count = sum(
        1 for d in bt_result.decisions if d.buy_action is not None
    )
    assert buy_count >= 4, (
        f"fixture produced only {buy_count} buys — strengthen scenario"
    )

    # ---------- Compare final cash + valuations ----------
    bt_final_snap = bt_result.snapshots[-1]
    assert paper_last_snap is not None
    assert paper_last_snap.snapshot_date == bt_final_snap.snapshot_date
    assert paper_last_snap.cash == bt_final_snap.cash, (
        f"cash diverged: backtest={bt_final_snap.cash} "
        f"paper={paper_last_snap.cash}"
    )
    assert paper_last_snap.total_value == bt_final_snap.total_value
    assert (
        paper_last_snap.total_unrealized_pnl
        == bt_final_snap.total_unrealized_pnl
    )

    bt_vals = {v.asset.fqn: v for v in bt_final_snap.valuations}
    paper_vals = {v.asset.fqn: v for v in paper_last_snap.valuations}
    assert bt_vals.keys() == paper_vals.keys(), (
        f"valuation asset sets differ: "
        f"backtest={set(bt_vals)} paper={set(paper_vals)}"
    )
    for fqn, bv in bt_vals.items():
        pv = paper_vals[fqn]
        assert bv.quantity == pv.quantity, (
            f"qty diverged for {fqn}: backtest={bv.quantity} paper={pv.quantity}"
        )
        assert bv.avg_price == pv.avg_price, (
            f"avg_price diverged for {fqn}: "
            f"backtest={bv.avg_price} paper={pv.avg_price}"
        )
        assert bv.split_level == pv.split_level, (
            f"split_level diverged for {fqn}: "
            f"backtest={bv.split_level} paper={pv.split_level}"
        )

    # ---------- positions table ↔ snapshot.valuations consistency ----------
    # This is the §10.4 sanity check invariant — the two SQLite truth
    # sources must agree at the end of the run, otherwise the next paper
    # invocation would refuse to start.
    pos_by_fqn = {p.asset.fqn: p for p in paper_positions}
    assert pos_by_fqn.keys() == paper_vals.keys()
    for fqn, pos in pos_by_fqn.items():
        val = paper_vals[fqn]
        assert pos.quantity == val.quantity
        assert pos.avg_price == val.avg_price
        assert pos.split_level == val.split_level


# ---------------------------------------------------------------------------
# Phase 0.5 sells-then-buys equivalence (ADR §10.2 step 0.5.23)
# ---------------------------------------------------------------------------
# Drop down → drop down → recovery to +10 % sell trigger → cascade buy →
# cooldown reentry on Days 5 / 6. Engineered so the orchestrator's sells-
# then-buys cascade flows through both BacktestRunner and the paper CLI.
SELL_CSV_ROWS: list[tuple[str, str, str, str, str, str]] = [
    # date          open    high    low     close   volume
    ("2026-04-20", "30000", "30200", "29800", "30000", "1000"),  # T-1
    ("2026-04-21", "28000", "30000", "27800", "28000", "1500"),  # Day1
    ("2026-04-22", "27000", "28000", "26900", "27000", "2000"),  # Day2
    ("2026-04-23", "33000", "33500", "30000", "33000", "3000"),  # Day3
    ("2026-04-24", "31000", "33000", "30800", "31000", "1500"),  # Day4
    ("2026-04-27", "30000", "31000", "29800", "30000", "1500"),  # Day5
    ("2026-04-28", "30000", "30200", "29800", "30000", "1000"),  # Day6
]
SELL_START = date(2026, 4, 21)
SELL_END = date(2026, 4, 28)


@pytest.fixture
def csv_path_sells(tmp_path) -> Path:
    p = tmp_path / "kodex_sells.csv"
    body = "date,open,high,low,close,volume\n" + "\n".join(
        ",".join(r) for r in SELL_CSV_ROWS
    )
    p.write_text(body + "\n")
    return p


def _slot_summary(position):
    """Compact slot summary for assertion error messages."""
    return [
        (
            s.slot_number,
            s.state.value,
            None if s.entry is None else (
                str(s.entry.entry_date),
                str(s.entry.quantity),
                str(s.entry.entry_price),
            ),
            None if s.last_exit_price is None else str(s.last_exit_price),
            None if s.last_exit_date is None else str(s.last_exit_date),
        )
        for s in position.slots
    ]


def test_equivalence_with_sells_and_cascade_buys(tmp_path, csv_path_sells):
    """ADR §10.2: backtest ↔ paper produce identical sequences AND slot
    states under sells-then-buys cascade.

    The fixture engineers:
        Days 1-3: progressive splits (slot 1 / 2 / 3)
        Day 4:    +10 % recovery → 3 sells + cascade buy on slot 4
        Day 5:    cooldown reentry on slot 1
        Day 6:    cooldown reentry on slot 2

    Both paths must produce identical:
        - Decision sequence (sells + buys included)
        - Final cash + total_value + valuations
        - Slot-by-slot byte-identical state (slot_number / state / entry /
          last_exit_*)  — the Phase 0.5 §10.2 byte-identical invariant.
    """
    asset = composition.kodex200()
    bars = load_ohlcv_csv(csv_path_sells, asset)
    config = _build_config()
    initial_capital = Money(amount=Decimal(CAPITAL), currency=Currency.KRW)

    # ---------- Path A: BacktestRunner ----------
    runner = BacktestRunner(
        assets=[asset],
        strategy_config=config,
        initial_capital=initial_capital,
        ohlcv_by_asset={asset: bars},
    )
    bt_result = runner.run(SELL_START, SELL_END)

    # ---------- Path B: paper CLI cron-simulated ----------
    db = tmp_path / "paper_sells.db"
    cli = CliRunner()
    base_args = [
        "paper",
        "--csv", str(csv_path_sells),
        "--db", str(db),
        *SHARED_FLAGS,
    ]
    trading_dates = [
        date.fromisoformat(r[0])
        for r in SELL_CSV_ROWS
        if SELL_START <= date.fromisoformat(r[0]) <= SELL_END
    ]
    for d in trading_dates:
        result = cli.invoke(main, [*base_args, "--date", d.isoformat()])
        assert result.exit_code == 0, (
            f"paper failed on {d}: exception={result.exception!r}\n"
            f"{result.output}"
        )

    conn = connect(db)
    try:
        with SqliteUnitOfWork(conn) as uow:
            paper_decisions = uow.decisions.list_by_date_range(
                SELL_START, SELL_END
            )
            paper_positions = uow.positions.list_all()
            paper_last_snap = uow.snapshots.get_last()
    finally:
        conn.close()

    # ---------- 1. Decision sequence (sells included) ----------
    bt_keys = _decision_keys(bt_result.decisions)
    paper_keys = _decision_keys(paper_decisions)
    assert bt_keys == paper_keys, (
        f"decision diverged:\n  backtest: {bt_keys}\n  paper:    {paper_keys}"
    )

    # ---------- 2. Engineered floors (regression-proof signal) ----------
    sell_count = sum(len(d.sell_actions) for d in bt_result.decisions)
    buy_count = sum(
        1 for d in bt_result.decisions if d.buy_action is not None
    )
    cascade_days = sum(
        1 for d in bt_result.decisions
        if d.sell_actions and d.buy_action is not None
    )
    assert sell_count >= 3, (
        f"fixture produced only {sell_count} sells — strengthen scenario"
    )
    assert buy_count >= 5, (
        f"fixture produced only {buy_count} buys — strengthen scenario"
    )
    assert cascade_days >= 1, (
        "fixture must trigger at least one same-day sell+buy cascade "
        "(ADR §5.3 cascade flow)"
    )

    # ---------- 3. Final cash + total value ----------
    bt_final_snap = bt_result.snapshots[-1]
    assert paper_last_snap is not None
    assert paper_last_snap.snapshot_date == bt_final_snap.snapshot_date
    assert paper_last_snap.cash == bt_final_snap.cash, (
        f"cash diverged: backtest={bt_final_snap.cash} "
        f"paper={paper_last_snap.cash}"
    )
    assert paper_last_snap.total_value == bt_final_snap.total_value
    assert (
        paper_last_snap.total_unrealized_pnl
        == bt_final_snap.total_unrealized_pnl
    )

    # ---------- 4. Slot-by-slot byte-identical state (§10.2) ----------
    bt_pos_map = {p.asset.fqn: p for p in bt_result.final_positions}
    paper_pos_map = {p.asset.fqn: p for p in paper_positions}
    assert bt_pos_map.keys() == paper_pos_map.keys(), (
        f"position asset sets differ: "
        f"backtest={set(bt_pos_map)} paper={set(paper_pos_map)}"
    )
    for fqn in bt_pos_map:
        bp = bt_pos_map[fqn]
        pp = paper_pos_map[fqn]
        # quantity / avg_price / split_level are derived; check them too.
        assert bp.quantity == pp.quantity
        assert bp.avg_price == pp.avg_price
        assert bp.split_level == pp.split_level
        # last_buy_at: set at decision time (09:00 KST). Both paths use
        # the same decision clock so the timestamp matches exactly.
        assert bp.last_buy_at == pp.last_buy_at
        # The byte-identical assertion: slot list equality covers
        # slot_number / state / entry (split_number / entry_date /
        # quantity / entry_price / idempotency_key) / last_exit_price /
        # last_exit_date.
        assert bp.slots == pp.slots, (
            f"slot state diverged for {fqn}:\n"
            f"  backtest: {_slot_summary(bp)}\n"
            f"  paper:    {_slot_summary(pp)}"
        )
