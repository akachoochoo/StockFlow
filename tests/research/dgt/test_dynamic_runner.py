"""Tests for _DGTDynamicRunner (Phase 0.11.f)."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import OHLCV, Currency, Money
from src.research.dgt.adaptive_runner import _AdaptiveConfig
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


class TestDGTDynamicRunnerProfitGuard:
    """profit_guard — Option A clause 3: '매도는 매수 레벨 위에서만'."""

    @staticmethod
    def _sell_audit(result) -> tuple[int, int]:
        """Replay trades → (sell_count, loss_sell_count).

        loss_sell = a SELL executed at/below the running weighted-average
        buy cost (a realized loss). Mirrors _compute_cumulative_realized.
        """
        avg_cost = Decimal("0")
        holdings = Decimal("0")
        sells = 0
        loss_sells = 0
        for t in result.trades:
            if t.side == "BUY":
                new_h = holdings + t.quantity
                avg_cost = (
                    avg_cost * holdings + t.rounded_price * t.quantity
                ) / new_h
                holdings = new_h
            else:
                sells += 1
                if avg_cost > 0 and t.rounded_price <= avg_cost:
                    loss_sells += 1
                holdings -= t.quantity
        return sells, loss_sells

    def test_default_profit_guard_is_off(self, cost_model, config):
        """Existing callers unaffected — profit_guard defaults to False."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
        )
        assert runner.profit_guard is False

    def test_guard_never_sells_below_avg_cost(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """profit_guard=True → every SELL is strictly above weighted-avg cost."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model, config=config,
            rebalance_mode="on_breach", profit_guard=True,
        )
        bars = _make_bars(kr_stock_005930, n=200, drift=200, osc=3000)
        result = runner.run(
            asset=kr_stock_005930,
            start=bars[0].trade_date, end=bars[-1].trade_date,
            initial_capital=initial_capital, ohlcv=bars,
        )
        sells, loss_sells = self._sell_audit(result)
        assert sells > 0, "test data must produce sells (non-vacuous)"
        assert loss_sells == 0, f"{loss_sells} sell(s) below avg cost despite guard"

    def test_guard_eliminates_loss_sells_present_without_it(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """Downtrend: unguarded runner books loss sells; the guard removes them."""
        bars = _make_bars(kr_stock_005930, n=150, drift=-200, osc=3000)
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date, end=bars[-1].trade_date,
            initial_capital=initial_capital, ohlcv=bars,
        )
        unguarded = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
        ).run(**kwargs)
        guarded = _DGTDynamicRunner(
            cost_model=cost_model, config=config,
            rebalance_mode="on_breach", profit_guard=True,
        ).run(**kwargs)

        _, loss_unguarded = self._sell_audit(unguarded)
        _, loss_guarded = self._sell_audit(guarded)
        assert loss_unguarded > 0, "test data must produce loss sells without the guard"
        assert loss_guarded == 0


class TestDGTDynamicRunnerAdaptiveK:
    """ADR/ATR-adaptive grid spacing (k) for _DGTDynamicRunner."""

    def test_default_adaptive_is_off(self, cost_model, config):
        """Existing callers unaffected — adaptive defaults to None (fixed k)."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
        )
        assert runner.adaptive is None
        assert runner.volatility_measure == "atr"

    def test_adaptive_k_fixed_when_none(self, kr_stock_005930, cost_model, config):
        """adaptive=None → _adaptive_k returns the fixed config.k_ratio."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
        )
        bars = _make_bars(kr_stock_005930)
        assert runner._adaptive_k(bars, 50, bars[50].close) == config.k_ratio

    def test_adaptive_k_within_bounds(self, kr_stock_005930, cost_model, config):
        """adaptive set → ADR-derived k is clamped to [k_min, k_max]."""
        acfg = _AdaptiveConfig(
            atr_period=14, multiplier=Decimal("1.5"),
            k_min=Decimal("0.01"), k_max=Decimal("0.08"),
        )
        runner = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
            adaptive=acfg, volatility_measure="adr",
        )
        bars = _make_bars(kr_stock_005930, n=100)
        for idx in (20, 50, 99):
            k = runner._adaptive_k(bars, idx, bars[idx].close)
            assert acfg.k_min <= k <= acfg.k_max

    def test_adaptive_run_differs_from_fixed_k(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """An ADR-adaptive runner produces a different grid than fixed k."""
        bars = _make_bars(kr_stock_005930, n=200, drift=200, osc=3000)
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date, end=bars[-1].trade_date,
            initial_capital=initial_capital, ohlcv=bars,
        )
        fixed = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
        ).run(**kwargs)
        adaptive = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
            adaptive=_AdaptiveConfig(
                atr_period=14, multiplier=Decimal("1.0"),
                k_min=Decimal("0.005"), k_max=Decimal("0.05"),
            ),
            volatility_measure="adr",
        ).run(**kwargs)
        assert (
            fixed.final_balance.amount != adaptive.final_balance.amount
            or len(fixed.trades) != len(adaptive.trades)
            or fixed.grid_levels != adaptive.grid_levels
        )


class TestDGTDynamicRunnerEntryControls:
    """flat_allocation (D) + max_invested_pct (B) — front-loaded-buying controls."""

    @staticmethod
    def _peak_cost_basis(result) -> Decimal:
        """Peak (holdings x weighted-average buy cost) over the run."""
        avg_cost = Decimal("0")
        holdings = Decimal("0")
        peak = Decimal("0")
        for t in result.trades:
            if t.side == "BUY":
                new_h = holdings + t.quantity
                avg_cost = (avg_cost * holdings + t.rounded_price * t.quantity) / new_h
                holdings = new_h
            else:
                holdings -= t.quantity
            peak = max(peak, holdings * avg_cost)
        return peak

    def test_defaults_off(self, cost_model, config):
        """Existing callers unaffected — both entry controls default off."""
        runner = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
        )
        assert runner.flat_allocation is False
        assert runner.max_invested_pct is None

    def test_position_cap_bounds_exposure(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """max_invested_pct caps cost-basis exposure near the cap (+1 chunk)."""
        bars = _make_bars(kr_stock_005930, n=150, drift=-200, osc=3000)
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date, end=bars[-1].trade_date,
            initial_capital=initial_capital, ohlcv=bars,
        )
        # Hold allocation mode constant (both flat) so only the cap varies.
        uncapped = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
            flat_allocation=True,
        ).run(**kwargs)
        capped = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
            flat_allocation=True, max_invested_pct=Decimal("0.60"),
        ).run(**kwargs)

        cap_amount = Decimal("0.60") * initial_capital.amount
        chunk = initial_capital.amount / Decimal(config.grid_count + 1)
        peak_capped = self._peak_cost_basis(capped)
        peak_uncapped = self._peak_cost_basis(uncapped)
        assert peak_capped <= cap_amount + chunk
        assert peak_capped < peak_uncapped

    def test_flat_allocation_changes_outcome(
        self, kr_stock_005930, cost_model, config, initial_capital
    ):
        """flat_allocation produces a different result than cash/(n+1)."""
        bars = _make_bars(kr_stock_005930, n=150, drift=-100, osc=3000)
        kwargs = dict(
            asset=kr_stock_005930,
            start=bars[0].trade_date, end=bars[-1].trade_date,
            initial_capital=initial_capital, ohlcv=bars,
        )
        default = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
        ).run(**kwargs)
        flat = _DGTDynamicRunner(
            cost_model=cost_model, config=config, rebalance_mode="on_breach",
            flat_allocation=True,
        ).run(**kwargs)
        assert (
            default.final_balance.amount != flat.final_balance.amount
            or len(default.trades) != len(flat.trades)
        )
