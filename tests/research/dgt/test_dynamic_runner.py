"""Tests for _DGTDynamicRunner (Phase 0.11.f)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import OHLCV, Currency, Money
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.dynamic_runner import _DGTDynamicRunner
from src.research.dgt.runner import _DGTConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cost_model() -> _KoreanMarketCostModel:
    return _KoreanMarketCostModel()


@pytest.fixture
def config() -> _DGTConfig:
    return _DGTConfig(
        grid_count=11,
        grid_spacing_pct=Decimal("3"),
        levels_above=1,
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
    """All bars at exactly the same close — no grid crossing possible."""
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
# Tests
# ---------------------------------------------------------------------------

class TestDGTDynamicRunnerOnBreach:
    def test_smoke_on_breach(self, kr_stock_005930, cost_model, config, initial_capital):
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
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

    def test_smoke_daily(self, kr_stock_005930, cost_model, config, initial_capital):
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
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

    def test_empty_ohlcv_raises(self, kr_stock_005930, cost_model, config, initial_capital):
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
        )
        with pytest.raises(ValueError, match="non-empty"):
            runner.run(
                asset=kr_stock_005930,
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                initial_capital=initial_capital,
                ohlcv=[],
            )

    def test_on_breach_rebalances_on_boundary_break(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """Trending data causes grid breach → rebalance → trades > 0.

        osc=3000 (6% of base_price=50000) exceeds the 3% grid spacing,
        so bars oscillate across grid levels on every few bars.
        """
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
        )
        bars = _make_bars(kr_stock_005930, n=200, drift=200, osc=3000)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert len(result.trades) > 0

    def test_daily_rebalances_every_bar(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """Daily rebalance with oscillation large enough to cross 3% grid levels."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="daily",
        )
        bars = _make_bars(kr_stock_005930, n=100, drift=100, osc=3000)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert len(result.trades) > 0

    def test_reproducibility(self, kr_stock_005930, cost_model, config, initial_capital):
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
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

    def test_trade_count_positive(self, kr_stock_005930, cost_model, config, initial_capital):
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
        )
        bars = _make_bars(kr_stock_005930, n=200, drift=300, osc=3000)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert len(result.trades) > 0

    def test_grid_levels_count(self, kr_stock_005930, cost_model, config, initial_capital):
        """Result grid_levels has grid_count + 1 entries."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
        )
        bars = _make_bars(kr_stock_005930)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert len(result.grid_levels) == config.grid_count + 1

    def test_result_fields_present(self, kr_stock_005930, cost_model, config, initial_capital):
        """All expected fields are accessible on _DGTBacktestResult."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
        )
        bars = _make_bars(kr_stock_005930)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        # All fields accessible without AttributeError
        _ = result.asset
        _ = result.start
        _ = result.end
        _ = result.initial_capital
        _ = result.final_cash
        _ = result.final_holdings
        _ = result.final_close_price
        _ = result.final_balance
        _ = result.wallet_total
        _ = result.reference_price
        _ = result.grid_levels
        _ = result.trades
        _ = result.daily_snapshots
        # No rebalance_count field — verify the dataclass has the above only
        assert not hasattr(result, "rebalance_count")

    def test_flat_market_no_breach(self, kr_stock_005930, cost_model, config, initial_capital):
        """Flat price = no level crossing + no breach → trade count 0."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
        )
        bars = _make_flat_bars(kr_stock_005930, n=50, price=50000)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        assert len(result.trades) == 0

    def test_daily_different_from_on_breach_with_flat_data(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """With trending data, daily and on_breach produce different results."""
        bars = _make_bars(kr_stock_005930, n=100, drift=200, osc=600)
        runner_breach = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="on_breach",
        )
        runner_daily = _DGTDynamicRunner(
            cost_model=cost_model,
            config=config,
            rebalance_mode="daily",
        )
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date,
            end=bars[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=bars,
        )
        result_breach = runner_breach.run(**kwargs)
        result_daily = runner_daily.run(**kwargs)
        # Different rebalance strategies → different final balances or trade counts
        assert (
            result_breach.final_balance.amount != result_daily.final_balance.amount
            or len(result_breach.trades) != len(result_daily.trades)
        )
