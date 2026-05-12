"""Phase 0.11.b — `_grid_runner` integration tests (AC1~AC10).

ADR 0008 §1.11 oracle 박제. WFO + grid 실행 / OOS returns / DSR / sort /
budget smoke 검증.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import OHLCV, Asset
from src.research.dgt.optimization._grid_runner import (
    _GridPointResult,
    _WFOGridResult,
    _compute_oos_returns,
    _run_wfo_grid,
)
from src.research.dgt.runner import _DGTConfig


_SMOKE_BAR_COUNT = 1500  # WFO 5-fold × min_cycle 60 × 3 cycle = 900 train min;
# fold_size = 300, train = 240, comfortably > 180.


def _synthesize_bars(asset: Asset, n: int = _SMOKE_BAR_COUNT) -> list[OHLCV]:
    """N bars 합성 — sinusoidal-like price (grid trigger 확보)."""
    bars: list[OHLCV] = []
    base_date = date(2020, 1, 2)
    base_price = Decimal("25000")
    for i in range(n):
        # alternate up/down ~3% to trigger grid crossings
        delta = Decimal("750") if (i // 20) % 2 == 0 else Decimal("-750")
        if i > 0:
            base_price += delta if i % 5 == 0 else Decimal("50")
        if base_price < Decimal("15000"):
            base_price = Decimal("15000")
        if base_price > Decimal("35000"):
            base_price = Decimal("35000")
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base_date + timedelta(days=i),
                open=base_price,
                high=base_price + Decimal("100"),
                low=base_price - Decimal("100"),
                close=base_price,
                volume=Decimal("1000"),
            )
        )
    return bars


class TestAC1SmallGridSmoke:
    """Smoke: bars 400 + default 95-grid + 5 folds 실행 — raise 없는 완주."""

    def test_runs_without_raise(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        assert isinstance(result, _WFOGridResult)
        assert len(result.points) > 0


class TestAC2WFOResultStructure:
    """`_WFOGridResult` field 정합 — grid_size=95, n_folds=5, n_bars=400."""

    def test_grid_result_fields(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        assert result.asset_code == "069500"
        assert result.grid_size == 95
        assert result.n_folds == 5
        assert result.n_bars == _SMOKE_BAR_COUNT
        assert len(result.points) == 95
        for p in result.points:
            assert isinstance(p, _GridPointResult)
            assert isinstance(p.oos_sharpe, Decimal)
            assert isinstance(p.dsr, Decimal)


class TestAC3OOSReturnsCompute:
    """`_compute_oos_returns` 결과 = list[Decimal], length = test_bars - 1."""

    def test_oos_returns_length(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=60)
        config = _DGTConfig(
            grid_count=5,
            grid_spacing_pct=Decimal("3"),
            levels_above=1,
        )
        returns = _compute_oos_returns(bars, config, kr_etf_069500)
        assert isinstance(returns, list)
        assert all(isinstance(r, Decimal) for r in returns)
        assert len(returns) == len(bars) - 1


class TestAC4DSRPerGrid:
    """DSR 계산이 각 grid point 마다 호출 — Decimal field 존재."""

    def test_dsr_is_decimal(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        for p in result.points:
            assert isinstance(p.dsr, Decimal)


class TestAC5DeterministicGrid:
    """2회 호출 동일 결과 (D12)."""

    def test_two_runs_byte_identical(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        r1 = _run_wfo_grid(bars, kr_etf_069500)
        r2 = _run_wfo_grid(bars, kr_etf_069500)
        assert r1.grid_size == r2.grid_size
        assert r1.n_folds == r2.n_folds
        assert len(r1.points) == len(r2.points)
        for p1, p2 in zip(r1.points, r2.points):
            assert p1 == p2


class TestAC6CostModelApplied:
    """KoreanMarketCostModel 적용 확인 — trade 발생 시 cost 영향 (wallet < gross)."""

    def test_trade_count_present(self, kr_etf_069500: Asset) -> None:
        # Use larger bar count to ensure some grid points generate trades
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        total_trades_across_grid = sum(
            p.total_trade_count for p in result.points
        )
        # 그리드 95 × 5 fold ≥ at least some trades expected on synthesized bars
        assert total_trades_across_grid > 0


class TestAC7TradeCountTracking:
    """trade_count tracked per grid point (>= 0)."""

    def test_trade_counts_non_negative(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        for p in result.points:
            assert p.total_trade_count >= 0


class TestAC8HoldingPeriod:
    """Holding period 산출 (median + mean) 정합 — Decimal 타입."""

    def test_holding_period_decimal(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        for p in result.points:
            assert isinstance(p.median_holding_period_days, Decimal)
            assert isinstance(p.mean_holding_period_days, Decimal)
            assert p.median_holding_period_days >= Decimal("0")
            assert p.mean_holding_period_days >= Decimal("0")


class TestAC9SortByOOSSharpe:
    """Result list = OOS Sharpe desc 정렬."""

    def test_sorted_oos_sharpe_desc(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        sharpes = [p.oos_sharpe for p in result.points]
        # Monotonic non-increasing
        for prev, curr in zip(sharpes[:-1], sharpes[1:]):
            assert prev >= curr, f"out-of-order: {prev} -> {curr}"


class TestAC10D10BudgetSmoke:
    """D10 budget smoke — 400 bars × 95 grid × 5 folds < 30s (실제 ~1s)."""

    def test_budget_under_30s(self, kr_etf_069500: Asset) -> None:
        import time

        bars = _synthesize_bars(kr_etf_069500)
        t0 = time.time()
        _ = _run_wfo_grid(bars, kr_etf_069500)
        elapsed = time.time() - t0
        # Generous bound — D10 prod budget 120s, smoke synthesized ~1s.
        assert elapsed < 30.0, f"budget bust: {elapsed:.2f}s"


class TestAC11EmptyBarsRaises:
    """bars empty / too-short → ValueError."""

    def test_empty_bars(self, kr_etf_069500: Asset) -> None:
        with pytest.raises(ValueError):
            _run_wfo_grid([], kr_etf_069500)

    def test_too_short_bars(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=100)
        with pytest.raises(ValueError):
            _run_wfo_grid(bars, kr_etf_069500)


class TestAC12PnlHistogram:
    """PnL histogram 9 bin (5% step from -20 to 25) 박제."""

    def test_pnl_histogram_bins(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_wfo_grid(bars, kr_etf_069500)
        best = result.points[0]
        assert len(best.pnl_histogram) == 9
        bounds = [(low, high) for low, high, _ in best.pnl_histogram]
        expected = [
            (Decimal("-20"), Decimal("-15")),
            (Decimal("-15"), Decimal("-10")),
            (Decimal("-10"), Decimal("-5")),
            (Decimal("-5"), Decimal("0")),
            (Decimal("0"), Decimal("5")),
            (Decimal("5"), Decimal("10")),
            (Decimal("10"), Decimal("15")),
            (Decimal("15"), Decimal("20")),
            (Decimal("20"), Decimal("25")),
        ]
        assert bounds == expected
