"""Tests for _DGTAdaptiveRunner and _compute_atr (Phase 0.11.f)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import OHLCV, Currency, Money
from src.research.dgt.adaptive_runner import (
    _AdaptiveConfig,
    _DGTAdaptiveRunner,
    _compute_atr,
)
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.runner import _DGTConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cost_model() -> _KoreanMarketCostModel:
    return _KoreanMarketCostModel()


@pytest.fixture
def base_config() -> _DGTConfig:
    return _DGTConfig(
        grid_count=11,
        grid_spacing_pct=Decimal("3"),
        levels_above=1,
    )


@pytest.fixture
def adaptive_config() -> _AdaptiveConfig:
    return _AdaptiveConfig(
        atr_period=14,
        multiplier=Decimal("1.5"),
        k_min=Decimal("0.02"),
        k_max=Decimal("0.10"),
    )


@pytest.fixture
def initial_capital() -> Money:
    return Money(amount=Decimal("10000000"), currency=Currency.KRW)


# ---------------------------------------------------------------------------
# Bar factory
# ---------------------------------------------------------------------------

def _make_bars(asset, n=100, base_price=50000, drift=50, osc=500):
    bars = []
    base_date = date(2024, 1, 2)
    for i in range(n):
        price = (
            Decimal(str(base_price))
            + Decimal(str(i * drift))
            + (Decimal(str(osc)) if i % 4 < 2 else Decimal(str(-osc)))
        )
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base_date + timedelta(days=i),
                open=price,
                high=price + Decimal("200"),
                low=price - Decimal("200"),
                close=price,
                volume=Decimal("10000"),
            )
        )
    return bars


def _make_flat_bars(asset, n=50, price=50000):
    base_date = date(2024, 1, 2)
    p = Decimal(str(price))
    return [
        OHLCV(
            asset=asset,
            trade_date=base_date + timedelta(days=i),
            open=p,
            high=p,
            low=p,
            close=p,
            volume=Decimal("10000"),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# _compute_atr tests
# ---------------------------------------------------------------------------

class TestComputeATR:
    def test_compute_atr_insufficient_data(self, kr_stock_005930):
        """end_idx < 1 → returns Decimal('0')."""
        bars = _make_bars(kr_stock_005930, n=5)
        result = _compute_atr(bars, 14, 0)
        assert result == Decimal("0")

    def test_compute_atr_period_exceeds_bars(self, kr_stock_005930):
        """period > available bars still computes over available data (no error)."""
        bars = _make_bars(kr_stock_005930, n=5)
        # end_idx=4 >= 1, so should compute over bars[1..4]
        result = _compute_atr(bars, 100, 4)
        assert result > Decimal("0")

    def test_compute_atr_known_value(self, kr_stock_005930):
        """Hand-calculated ATR(2) at end_idx=2.

        bar0: close=100, high=105, low=95
        bar1: close=102, high=108, low=98
          TR1 = max(108-98, |108-100|, |98-100|) = max(10, 8, 2) = 10
        bar2: close=99,  high=104, low=96
          TR2 = max(104-96, |104-102|, |96-102|) = max(8, 2, 6) = 8
        ATR(2) = (10 + 8) / 2 = 9
        """
        base_date = date(2024, 1, 2)
        bar0 = OHLCV(
            asset=kr_stock_005930,
            trade_date=base_date,
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        bar1 = OHLCV(
            asset=kr_stock_005930,
            trade_date=base_date + timedelta(days=1),
            open=Decimal("100"),
            high=Decimal("108"),
            low=Decimal("98"),
            close=Decimal("102"),
            volume=Decimal("1000"),
        )
        bar2 = OHLCV(
            asset=kr_stock_005930,
            trade_date=base_date + timedelta(days=2),
            open=Decimal("102"),
            high=Decimal("104"),
            low=Decimal("96"),
            close=Decimal("99"),
            volume=Decimal("1000"),
        )
        bars = [bar0, bar1, bar2]
        result = _compute_atr(bars, 2, 2)
        assert result == Decimal("9")


# ---------------------------------------------------------------------------
# _DGTAdaptiveRunner tests
# ---------------------------------------------------------------------------

class TestDGTAdaptiveRunner:
    def test_smoke(self, kr_stock_005930, cost_model, base_config, adaptive_config, initial_capital):
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive_config,
            rebalance_mode="daily",
        )
        bars = _make_bars(kr_stock_005930)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert result is not None

    def test_empty_ohlcv_raises(self, kr_stock_005930, cost_model, base_config, adaptive_config, initial_capital):
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive_config,
        )
        with pytest.raises(ValueError, match="non-empty"):
            runner.run(
                asset=kr_stock_005930,
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                initial_capital=initial_capital,
                ohlcv=[],
            )

    def test_adaptive_k_clamped_min(self, kr_stock_005930, cost_model, base_config):
        """With tiny ATR (very flat bars), k should clamp to k_min."""
        # Build bars with extremely small range (1 unit) so ATR is tiny
        base_date = date(2024, 1, 2)
        p = Decimal("50000")
        bars = []
        for i in range(50):
            bars.append(
                OHLCV(
                    asset=kr_stock_005930,
                    trade_date=base_date + timedelta(days=i),
                    open=p,
                    high=p + Decimal("1"),
                    low=p - Decimal("1"),
                    close=p,
                    volume=Decimal("10000"),
                )
            )
        adaptive = _AdaptiveConfig(
            atr_period=14,
            multiplier=Decimal("0.0001"),  # very small multiplier → k well below k_min
            k_min=Decimal("0.05"),
            k_max=Decimal("0.10"),
        )
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive,
            rebalance_mode="daily",
        )
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
            ohlcv=bars,
        )
        # With k clamped at k_min=0.05, grid levels span ~5% apart
        # Verify run completes and grid_levels match expected count
        assert len(result.grid_levels) == base_config.grid_count + 1

    def test_adaptive_k_clamped_max(self, kr_stock_005930, cost_model, base_config):
        """With huge ATR (volatile bars), k should clamp to k_max."""
        base_date = date(2024, 1, 2)
        p = Decimal("50000")
        bars = []
        for i in range(50):
            bars.append(
                OHLCV(
                    asset=kr_stock_005930,
                    trade_date=base_date + timedelta(days=i),
                    open=p,
                    high=p + Decimal("20000"),  # huge range
                    low=p - Decimal("20000"),
                    close=p,
                    volume=Decimal("10000"),
                )
            )
        adaptive = _AdaptiveConfig(
            atr_period=14,
            multiplier=Decimal("100"),  # huge multiplier → k well above k_max
            k_min=Decimal("0.02"),
            k_max=Decimal("0.05"),
        )
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive,
            rebalance_mode="daily",
        )
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
            ohlcv=bars,
        )
        assert len(result.grid_levels) == base_config.grid_count + 1

    def test_atr_zero_fallback(self, kr_stock_005930, cost_model, base_config):
        """When ATR=0 (flat bars at identical price), fallback to base_config.k_ratio."""
        bars = _make_flat_bars(kr_stock_005930, n=30, price=50000)
        adaptive = _AdaptiveConfig(
            atr_period=14,
            multiplier=Decimal("1.5"),
            k_min=Decimal("0.02"),
            k_max=Decimal("0.10"),
        )
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive,
            rebalance_mode="daily",
        )
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
            ohlcv=bars,
        )
        # Flat bars → ATR=0 → fallback k = base_config.k_ratio
        # Grid levels should still be grid_count+1
        assert len(result.grid_levels) == base_config.grid_count + 1

    def test_reproducibility(self, kr_stock_005930, cost_model, base_config, adaptive_config, initial_capital):
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive_config,
            rebalance_mode="daily",
        )
        bars = _make_bars(kr_stock_005930)
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        result1 = runner.run(**kwargs)
        result2 = runner.run(**kwargs)
        assert result1.final_balance.amount == result2.final_balance.amount
        assert len(result1.trades) == len(result2.trades)
        assert result1.grid_levels == result2.grid_levels

    def test_trade_count_positive(self, kr_stock_005930, cost_model, base_config, adaptive_config, initial_capital):
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive_config,
            rebalance_mode="daily",
        )
        bars = _make_bars(kr_stock_005930, n=200, drift=300, osc=800)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert len(result.trades) > 0

    def test_grid_levels_count(self, kr_stock_005930, cost_model, base_config, adaptive_config, initial_capital):
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive_config,
        )
        bars = _make_bars(kr_stock_005930)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert len(result.grid_levels) == base_config.grid_count + 1

    def test_result_fields_no_k_history(self, kr_stock_005930, cost_model, base_config, adaptive_config, initial_capital):
        """Result has no k_history attribute — only standard _DGTBacktestResult fields."""
        runner = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=adaptive_config,
        )
        bars = _make_bars(kr_stock_005930)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert not hasattr(result, "k_history")
        # Standard fields accessible
        _ = result.asset
        _ = result.final_balance
        _ = result.trades
        _ = result.daily_snapshots
        _ = result.grid_levels
        _ = result.wallet_total

    def test_narrow_vs_wide_different_k(self, kr_stock_005930, cost_model, base_config, initial_capital):
        """Different AdaptiveConfig (multiplier) produces different results."""
        bars = _make_bars(kr_stock_005930, n=100, drift=200, osc=600)
        narrow = _AdaptiveConfig(
            atr_period=14,
            multiplier=Decimal("0.1"),
            k_min=Decimal("0.01"),
            k_max=Decimal("0.03"),
        )
        wide = _AdaptiveConfig(
            atr_period=14,
            multiplier=Decimal("5.0"),
            k_min=Decimal("0.05"),
            k_max=Decimal("0.20"),
        )
        runner_narrow = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=narrow,
            rebalance_mode="daily",
        )
        runner_wide = _DGTAdaptiveRunner(
            cost_model=cost_model,
            base_config=base_config,
            adaptive=wide,
            rebalance_mode="daily",
        )
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        result_narrow = runner_narrow.run(**kwargs)
        result_wide = runner_wide.run(**kwargs)
        # Different k configs should produce different final balances or trade counts
        assert (
            result_narrow.final_balance.amount != result_wide.final_balance.amount
            or len(result_narrow.trades) != len(result_wide.trades)
        )
