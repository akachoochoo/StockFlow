"""Phase 0.11.c.4 — `_align_results_for_overlay` adapter tests.

ADR 0009 §1.3 D6 정합:
  - `BacktestResult` ↔ `_DGTBacktestResult` 공통 축 (time + pnl + drawdown)
    매핑 정확성.
  - `_OverlayPayload` Decimal invariant (CLAUDE.md §2.1).
  - drawdown ≤ 0 invariant.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.application.backtest_runner import BacktestResult
from src.domain.models import (
    Asset,
    Currency,
    Money,
    PortfolioSnapshot,
    PositionValuation,
)
from src.research.dgt.results import (
    _DGTBacktestResult,
    _DGTSnapshot,
)
from src.research.visualization._align import (
    _align_backtest_result_for_overlay,
    _align_dgt_result_for_overlay,
    _align_results_for_overlay,
)
from src.research.visualization._visualization_renderer import _OverlayPayload


def _make_backtest_result(
    asset: Asset,
    initial_amount: Decimal,
    snapshot_values: list[Decimal],
) -> BacktestResult:
    """Helper — build a BacktestResult from a value series."""
    base_date = date(2024, 1, 2)
    initial = Money(amount=initial_amount, currency=Currency.KRW)
    snaps: list[PortfolioSnapshot] = []
    for i, value in enumerate(snapshot_values):
        d = date.fromordinal(base_date.toordinal() + i)
        snap_at = datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)
        # All value in cash, no positions (simpler PnL math).
        snap = PortfolioSnapshot.build(
            snapshot_date=d,
            snapshot_at=snap_at,
            initial_capital=initial,
            cash=Money(amount=value, currency=Currency.KRW),
            valuations=cast_empty_valuations(),
        )
        snaps.append(snap)
    return BacktestResult.from_run(
        start_date=base_date,
        end_date=snaps[-1].snapshot_date if snaps else base_date,
        initial_capital=initial,
        decisions=[],
        snapshots=snaps,
    )


def cast_empty_valuations() -> list[PositionValuation]:
    """Cast helper for empty valuations list typing."""
    return []


def _make_dgt_result(
    asset: Asset,
    initial_amount: Decimal,
    snapshot_values: list[Decimal],
) -> _DGTBacktestResult:
    """Helper — build a _DGTBacktestResult with synthesized snapshots."""
    base_date = date(2024, 1, 2)
    initial = Money(amount=initial_amount, currency=Currency.KRW)
    snaps: list[_DGTSnapshot] = []
    for i, value in enumerate(snapshot_values):
        d = date.fromordinal(base_date.toordinal() + i)
        snaps.append(
            _DGTSnapshot(
                trade_date=d,
                cash=value,
                holdings=Decimal("0"),
                close_price=Decimal("100"),
                total_value=value,
            )
        )
    return _DGTBacktestResult(
        asset=asset,
        start=base_date,
        end=snaps[-1].trade_date if snaps else base_date,
        initial_capital=initial,
        final_cash=snapshot_values[-1] if snapshot_values else initial_amount,
        final_holdings=Decimal("0"),
        final_close_price=Decimal("100"),
        final_balance=Money(
            amount=snapshot_values[-1] if snapshot_values else initial_amount,
            currency=Currency.KRW,
        ),
        wallet_total=Decimal("0"),
        reference_price=Decimal("100"),
        grid_levels=[Decimal("90"), Decimal("100"), Decimal("110")],
        trades=[],
        daily_snapshots=snaps,
    )


# ---------------------------------------------------------------------------
# AC1 — BacktestResult adapter
# ---------------------------------------------------------------------------
class TestAC1BacktestResultAdapter:
    """Production `BacktestResult` → `_OverlayPayload` 매핑."""

    def test_basic_pnl(self, kr_etf_069500: Asset) -> None:
        result = _make_backtest_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[
                Decimal("1000"),
                Decimal("1100"),
                Decimal("1050"),
                Decimal("1200"),
            ],
        )
        payload = _align_backtest_result_for_overlay(
            result, strategy_id="test_bt",
        )
        assert payload.strategy_id == "test_bt"
        assert payload.pnl_cumulative == [
            Decimal("0"),
            Decimal("100"),
            Decimal("50"),
            Decimal("200"),
        ]

    def test_drawdown_non_positive(self, kr_etf_069500: Asset) -> None:
        result = _make_backtest_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[
                Decimal("1000"),
                Decimal("1200"),  # peak +200
                Decimal("900"),   # -300 from peak
                Decimal("1100"),  # -100 from peak
            ],
        )
        payload = _align_backtest_result_for_overlay(
            result, strategy_id="test_bt",
        )
        # Peak = +200 (at index 1). Drawdowns relative to peak.
        # index 0: pnl=0, peak=0 → dd=0
        # index 1: pnl=200, peak=200 → dd=0
        # index 2: pnl=-100, peak=200 → dd=-300
        # index 3: pnl=100, peak=200 → dd=-100
        assert payload.drawdown == [
            Decimal("0"),
            Decimal("0"),
            Decimal("-300"),
            Decimal("-100"),
        ]
        for dd in payload.drawdown:
            assert dd <= 0

    def test_empty_snapshots(self, kr_etf_069500: Asset) -> None:
        result = _make_backtest_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[],
        )
        payload = _align_backtest_result_for_overlay(
            result, strategy_id="empty",
        )
        assert payload.time_series == []
        assert payload.pnl_cumulative == []
        assert payload.drawdown == []

    def test_utc_datetimes(self, kr_etf_069500: Asset) -> None:
        result = _make_backtest_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[Decimal("1000"), Decimal("1100")],
        )
        payload = _align_backtest_result_for_overlay(
            result, strategy_id="t",
        )
        for ts in payload.time_series:
            assert ts.tzinfo is UTC


# ---------------------------------------------------------------------------
# AC2 — _DGTBacktestResult adapter
# ---------------------------------------------------------------------------
class TestAC2DGTResultAdapter:
    """Research `_DGTBacktestResult` → `_OverlayPayload` 매핑."""

    def test_basic_pnl(self, kr_etf_069500: Asset) -> None:
        result = _make_dgt_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[
                Decimal("1000"),
                Decimal("950"),
                Decimal("1100"),
                Decimal("1050"),
            ],
        )
        payload = _align_dgt_result_for_overlay(result)
        assert payload.strategy_id == "dgt"
        assert payload.pnl_cumulative == [
            Decimal("0"),
            Decimal("-50"),
            Decimal("100"),
            Decimal("50"),
        ]

    def test_drawdown_correctness(self, kr_etf_069500: Asset) -> None:
        result = _make_dgt_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[
                Decimal("1000"),
                Decimal("1200"),
                Decimal("800"),
            ],
        )
        payload = _align_dgt_result_for_overlay(result)
        # index 0: pnl=0, peak=0 → dd=0
        # index 1: pnl=200, peak=200 → dd=0
        # index 2: pnl=-200, peak=200 → dd=-400
        assert payload.drawdown == [
            Decimal("0"),
            Decimal("0"),
            Decimal("-400"),
        ]

    def test_decimal_invariant(self, kr_etf_069500: Asset) -> None:
        result = _make_dgt_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[Decimal("1000"), Decimal("1050")],
        )
        payload = _align_dgt_result_for_overlay(result)
        for v in payload.pnl_cumulative:
            assert isinstance(v, Decimal)
        for v in payload.drawdown:
            assert isinstance(v, Decimal)

    def test_custom_strategy_id(self, kr_etf_069500: Asset) -> None:
        result = _make_dgt_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[Decimal("1000")],
        )
        payload = _align_dgt_result_for_overlay(
            result, strategy_id="dgt_n11_k3",
        )
        assert payload.strategy_id == "dgt_n11_k3"


# ---------------------------------------------------------------------------
# AC3 — Dispatcher
# ---------------------------------------------------------------------------
class TestAC3Dispatcher:
    """`_align_results_for_overlay` dispatch — BacktestResult / _DGTBacktestResult."""

    def test_backtest_result_dispatched(self, kr_etf_069500: Asset) -> None:
        result = _make_backtest_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[Decimal("1000"), Decimal("1200")],
        )
        payload = _align_results_for_overlay(result, strategy_id="bh")
        assert isinstance(payload, _OverlayPayload)
        assert payload.strategy_id == "bh"
        assert payload.pnl_cumulative == [Decimal("0"), Decimal("200")]

    def test_dgt_result_dispatched(self, kr_etf_069500: Asset) -> None:
        result = _make_dgt_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=[Decimal("1000"), Decimal("950")],
        )
        payload = _align_results_for_overlay(result, strategy_id="dgt")
        assert isinstance(payload, _OverlayPayload)
        assert payload.strategy_id == "dgt"
        assert payload.pnl_cumulative == [Decimal("0"), Decimal("-50")]

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Unsupported result type"):
            _align_results_for_overlay(
                {"not_a_result": True}, strategy_id="x",
            )


# ---------------------------------------------------------------------------
# AC4 — Cross-strategy consistency (D6 핵심 — 공통 축 매핑)
# ---------------------------------------------------------------------------
class TestAC4CrossStrategyConsistency:
    """동일 value 시계열 → BacktestResult / _DGTBacktestResult 양쪽 동일 pnl."""

    def test_same_value_series_same_pnl(
        self, kr_etf_069500: Asset,
    ) -> None:
        values = [
            Decimal("1000"), Decimal("1100"), Decimal("1050"), Decimal("1200"),
        ]
        bt_result = _make_backtest_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=values,
        )
        dgt_result = _make_dgt_result(
            kr_etf_069500,
            initial_amount=Decimal("1000"),
            snapshot_values=values,
        )
        bt_payload = _align_results_for_overlay(
            bt_result, strategy_id="a",
        )
        dgt_payload = _align_results_for_overlay(
            dgt_result, strategy_id="b",
        )
        # 공통 축 매핑 — 동일 value → 동일 pnl + drawdown.
        assert bt_payload.pnl_cumulative == dgt_payload.pnl_cumulative
        assert bt_payload.drawdown == dgt_payload.drawdown
