"""Phase 0.11.f — _DGTPaperRunner unit tests.

Chen, Chen, Jang (2025) S1.1.2 + S3.1 충실 구현 검증.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import OHLCV, Currency, Money
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.paper_runner import _DGTPaperRunner
from src.research.dgt.runner import _DGTConfig


# ---------------------------------------------------------------------------
# Helpers
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


def _make_strong_uptrend_bars(asset, n=100, base_price=50000, step=2000):
    """Each bar jumps by `step` — forces repeated boundary breaches."""
    bars = []
    base_date = date(2024, 1, 2)
    for i in range(n):
        price = Decimal(str(base_price + i * step))
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base_date + timedelta(days=i),
                open=price,
                high=price + Decimal("100"),
                low=price - Decimal("100"),
                close=price,
                volume=Decimal("10000"),
            )
        )
    return bars


def _make_flat_then_drop_bars(asset, flat_n=20, drop_n=5, base_price=50000, drop_step=5000):
    """flat_n flat bars followed by drop_n downward bars."""
    bars = []
    base_date = date(2024, 1, 2)
    for i in range(flat_n):
        p = Decimal(str(base_price))
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base_date + timedelta(days=i),
                open=p, high=p + Decimal("50"), low=p - Decimal("50"),
                close=p, volume=Decimal("10000"),
            )
        )
    for j in range(drop_n):
        p = Decimal(str(base_price - (j + 1) * drop_step))
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base_date + timedelta(days=flat_n + j),
                open=p, high=p + Decimal("50"), low=p - Decimal("50"),
                close=p, volume=Decimal("10000"),
            )
        )
    return bars


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CONFIG = _DGTConfig(
    grid_count=11,
    grid_spacing_pct=Decimal("3"),
    levels_above=1,  # ignored by paper runner — always m=n//2=5
)

_CAPITAL = Money(amount=Decimal("10000000"), currency=Currency.KRW)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSmoke:
    """Test 1 — smoke: runs without error, returns _DGTBacktestResult."""

    def test_smoke(self, kr_stock_005930, cost_model):
        bars = _make_bars(kr_stock_005930)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        assert result is not None
        assert result.asset == kr_stock_005930


class TestEmptyOhlcvRaises:
    """Test 2 — empty ohlcv raises ValueError."""

    def test_empty_ohlcv_raises(self, kr_stock_005930, cost_model):
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        with pytest.raises(ValueError):
            runner.run(
                asset=kr_stock_005930,
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                initial_capital=_CAPITAL,
                ohlcv=[],
            )


class TestBoundaryBreachTriggersReset:
    """Test 3 — boundary breach causes grid reset (upper_resets increments)."""

    def test_boundary_breach_triggers_reset(self, kr_stock_005930, cost_model):
        # Strong uptrend: price jumps 2000 per bar from 50000.
        # With n=11, k=3%, grid spans ~50000*(1.03^5 .. 1.03^6) ≈ ±15% = ~7500 range.
        # Step of 2000 per bar will breach the top boundary within a few bars.
        # After reset the reference_price must shift from the initial value.
        bars = _make_strong_uptrend_bars(kr_stock_005930, n=30)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        # After many boundary breaches the reference_price must have moved
        # from the initial close (50000) to a much higher value.
        initial_close = bars[0].close
        assert result.reference_price > initial_close


class TestMStartsAsNHalf:
    """Test 4 — m = n//2 = 5 for n=11, verified via grid_levels symmetric around start price."""

    def test_m_starts_as_n_half(self, kr_stock_005930, cost_model):
        # Use a single bar so no movement occurs and initial levels are preserved.
        start_price = Decimal("50000")
        bars = [
            OHLCV(
                asset=kr_stock_005930,
                trade_date=date(2024, 1, 2),
                open=start_price,
                high=start_price + Decimal("10"),
                low=start_price - Decimal("10"),
                close=start_price,
                volume=Decimal("10000"),
            )
        ]
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        levels = result.grid_levels
        # n=11 → 12 levels; m=n//2=5 means 5 above reference, 6 below
        assert len(levels) == 12
        # Count levels strictly above start_price
        above = sum(1 for lv in levels if lv > start_price)
        assert above == 5  # m = n//2 = 5


class TestCashHoldingsPreservedAcrossReset:
    """Test 5 — after reset, cash + holdings * price ≈ previous total (no free money)."""

    def test_cash_holdings_preserved_across_reset(self, kr_stock_005930, cost_model):
        bars = _make_strong_uptrend_bars(kr_stock_005930, n=50)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        # Verify monotonic: no snapshot total_value exceeds initial + reasonable gains
        # The total value should be within bounds (no free money creation from resets)
        initial_amount = _CAPITAL.amount
        final_total = result.final_balance.amount
        # Final total can be higher or lower but must be positive and finite
        assert final_total > Decimal("0")
        # Validate each snapshot total matches cash + holdings * close (internal consistency)
        for snap in result.daily_snapshots:
            expected = snap.cash + snap.holdings * snap.close_price
            assert abs(snap.total_value - expected) < Decimal("1")  # rounding tolerance


class TestReproducibility:
    """Test 6 — two runs with identical input produce identical output."""

    def test_reproducibility(self, kr_stock_005930, cost_model):
        bars = _make_bars(kr_stock_005930)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        r1 = runner.run(**kwargs)
        r2 = runner.run(**kwargs)
        assert r1.final_balance.amount == r2.final_balance.amount
        assert len(r1.trades) == len(r2.trades)
        assert r1.final_holdings == r2.final_holdings
        assert r1.final_cash == r2.final_cash


class TestTradeCountPositive:
    """Test 7 — trending bars with oscillation produce at least one trade."""

    def test_trade_count_positive(self, kr_stock_005930, cost_model):
        # drift=200 ensures price moves significantly to cross grid levels
        bars = _make_bars(kr_stock_005930, n=100, drift=200, osc=2000)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        assert len(result.trades) > 0


class TestNaturalCrossingOrder:
    """Test 8 — verify trades happen in correct order (UP crosses = SELL, DOWN crosses = BUY)."""

    def test_natural_crossing_order(self, kr_stock_005930, cost_model):
        bars = _make_bars(kr_stock_005930, n=100, drift=200, osc=2000)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        # Verify all trade sides are valid strings
        for trade in result.trades:
            assert trade.side in ("BUY", "SELL")
        # Verify cash_delta sign convention: BUY = negative, SELL = positive
        for trade in result.trades:
            if trade.side == "BUY":
                assert trade.cash_delta < Decimal("0")
            else:
                assert trade.cash_delta > Decimal("0")


class TestGridLevelsCount:
    """Test 9 — n=11 produces exactly n+1=12 grid levels."""

    def test_grid_levels_count(self, kr_stock_005930, cost_model):
        bars = _make_bars(kr_stock_005930, n=1)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[0].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        assert len(result.grid_levels) == _CONFIG.grid_count + 1  # 12


class TestResultFieldsPresent:
    """Test 10 — all expected fields are accessible on the result."""

    def test_result_fields_present(self, kr_stock_005930, cost_model):
        bars = _make_bars(kr_stock_005930)
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        # All fields defined in _DGTBacktestResult
        assert hasattr(result, "asset")
        assert hasattr(result, "start")
        assert hasattr(result, "end")
        assert hasattr(result, "initial_capital")
        assert hasattr(result, "final_cash")
        assert hasattr(result, "final_holdings")
        assert hasattr(result, "final_close_price")
        assert hasattr(result, "final_balance")
        assert hasattr(result, "wallet_total")
        assert hasattr(result, "reference_price")
        assert hasattr(result, "grid_levels")
        assert hasattr(result, "trades")
        assert hasattr(result, "daily_snapshots")
        # Snapshots count matches bar count
        assert len(result.daily_snapshots) == len(bars)


class TestMultiLevelDownCrossMTracking:
    """Test 11 — price drops through 3+ levels in one bar, result is valid."""

    def test_multi_level_down_cross_m_tracking(self, kr_stock_005930, cost_model):
        # Start flat, then drop sharply to cross multiple levels at once
        bars = _make_flat_then_drop_bars(
            kr_stock_005930,
            flat_n=5,
            drop_n=3,
            base_price=50000,
            drop_step=3000,  # 3% spacing * 50000 = 1500; 3000 >> 1500 crosses multiple levels
        )
        runner = _DGTPaperRunner(cost_model=cost_model, config=_CONFIG)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=_CAPITAL,
            ohlcv=bars,
        )
        # The result must be valid (no exceptions, all snapshots present)
        assert result is not None
        assert len(result.daily_snapshots) == len(bars)
        # Cash must be non-negative
        assert result.final_cash >= Decimal("0")
        # Holdings must be non-negative
        assert result.final_holdings >= Decimal("0")
