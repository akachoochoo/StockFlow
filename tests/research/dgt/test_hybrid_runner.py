"""Tests for Phase 0.11.g — _HybridCoreRunner (Core-Satellite B&H+DGT)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.domain.models import Asset, AssetClass, Currency, Exchange, Market, Money, OHLCV
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.hybrid_runner import (
    _CoreState,
    _HybridBacktestResult,
    _HybridConfig,
    _HybridCoreRunner,
    _HybridSnapshot,
    _RebalanceEvent,
)
from src.research.dgt.adaptive_runner import _AdaptiveConfig
from src.research.dgt.runner import _DGTConfig


@pytest.fixture
def asset() -> Asset:
    return Asset(
        code="005930",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="삼성전자",
        tick_size=Decimal("1"),
        listed_at=date(1975, 6, 11),
    )


@pytest.fixture
def cost_model() -> _KoreanMarketCostModel:
    return _KoreanMarketCostModel()


@pytest.fixture
def dgt_config() -> _DGTConfig:
    return _DGTConfig(
        grid_count=11,
        grid_spacing_pct=Decimal("0.02"),
        levels_above=5,
    )


@pytest.fixture
def adaptive_config() -> _AdaptiveConfig:
    return _AdaptiveConfig(
        atr_period=14,
        multiplier=Decimal("1.0"),
        k_min=Decimal("0.005"),
        k_max=Decimal("0.05"),
    )


def _make_asset() -> Asset:
    return Asset(
        code="005930",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="삼성전자",
        tick_size=Decimal("1"),
        listed_at=date(1975, 6, 11),
    )


def _make_ohlcv(prices: list[int], start_date: date = date(2024, 1, 2)) -> list[OHLCV]:
    """Generate OHLCV bars from close prices with reasonable H/L/Volume."""
    asset = _make_asset()
    bars = []
    for i, p in enumerate(prices):
        d = date.fromordinal(start_date.toordinal() + i)
        close = Decimal(str(p))
        high = close * Decimal("1.01")
        low = close * Decimal("0.99")
        bars.append(OHLCV(
            asset=asset,
            trade_date=d,
            open=close,
            high=high,
            low=low,
            close=close,
            volume=Decimal("1000000"),
        ))
    return bars


class TestHybridCoreRunner:
    """Core-Satellite runner basic functionality."""

    def test_run_returns_result(self, asset, cost_model, dgt_config, adaptive_config):
        prices = [70000 + i * 100 for i in range(30)]
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.7"), rebalance_mode="static"),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert isinstance(result, _HybridBacktestResult)
        assert result.core_ratio == Decimal("0.7")
        assert result.rebalance_mode == "static"
        assert len(result.daily_snapshots) == 30

    def test_empty_ohlcv_raises(self, asset, cost_model, dgt_config, adaptive_config):
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            volume_gate=False,
        )
        with pytest.raises(ValueError, match="non-empty"):
            runner.run(
                asset=asset,
                start=date(2024, 1, 1),
                end=date(2024, 1, 1),
                initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
                ohlcv=[],
            )

    def test_capital_split_respects_ratio(self, asset, cost_model, dgt_config, adaptive_config):
        prices = [70000] * 5  # flat price
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.6"), rebalance_mode="static"),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        # Core should be ~60% of total
        snap = result.daily_snapshots[0]
        ratio = snap.core_value / snap.total_value
        assert Decimal("0.55") < ratio < Decimal("0.65")

    def test_static_mode_no_rebalancing(self, asset, cost_model, dgt_config, adaptive_config):
        # Trending up -> core grows faster -> ratio drifts
        prices = [70000 + i * 1000 for i in range(50)]
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.7"), rebalance_mode="static"),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert len(result.rebalance_events) == 0
        assert result.rebalancing_alpha_annualized == Decimal("0")

    def test_drift_rebalancing_triggers(self, asset, cost_model, dgt_config, adaptive_config):
        # Large price swing to trigger drift
        prices = [70000] * 25 + [100000] * 25  # big jump at bar 25
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(
                core_ratio=Decimal("0.7"),
                rebalance_mode="drift",
                drift_threshold=Decimal("0.05"),
                cooldown_days=20,
            ),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        # Should have at least one rebalance event after the jump
        assert len(result.rebalance_events) >= 1

    def test_cooldown_prevents_rapid_rebalancing(self, asset, cost_model, dgt_config, adaptive_config):
        # Oscillating prices should not trigger rebalance too often
        prices = []
        for i in range(100):
            prices.append(70000 if i % 2 == 0 else 100000)
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(
                core_ratio=Decimal("0.7"),
                rebalance_mode="drift",
                drift_threshold=Decimal("0.05"),
                cooldown_days=20,
            ),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        # Max 5 rebalances in 100 bars with 20-day cooldown
        assert len(result.rebalance_events) <= 5

    def test_calendar_rebalancing(self, asset, cost_model, dgt_config, adaptive_config):
        prices = [70000 + i * 200 for i in range(130)]
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(
                core_ratio=Decimal("0.7"),
                rebalance_mode="calendar",
                calendar_period=60,
                cooldown_days=20,
            ),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        # Should rebalance at approximately bar 60 and 120
        assert len(result.rebalance_events) >= 1

    def test_dgt_satellite_generates_trades(self, asset, cost_model, dgt_config, adaptive_config):
        # Oscillating prices to trigger grid crosses
        prices = []
        for i in range(60):
            prices.append(70000 + (i % 10) * 500)
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.7"), rebalance_mode="static"),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        # DGT satellite should generate some trades
        assert len(result.dgt_trades) > 0

    def test_total_value_preserved_approximately(self, asset, cost_model, dgt_config, adaptive_config):
        """Total value should not deviate wildly from initial + market movement."""
        prices = [70000] * 20  # flat market
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.7"), rebalance_mode="static"),
            volume_gate=False,
        )
        capital = Decimal("100000000")
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=capital, currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        # In flat market, total value should be close to initial (minus tiny costs)
        deviation = abs(result.final_total_value - capital) / capital
        assert deviation < Decimal("0.02")  # less than 2% deviation in flat market


class TestCoreState:
    """_CoreState value computation."""

    def test_value_cash_plus_holdings(self):
        state = _CoreState(cash=Decimal("1000000"), holdings=Decimal("100"))
        assert state.value(Decimal("70000")) == Decimal("8000000")

    def test_value_zero_holdings(self):
        state = _CoreState(cash=Decimal("5000000"), holdings=Decimal("0"))
        assert state.value(Decimal("70000")) == Decimal("5000000")


class TestHybridSnapshot:
    """_HybridSnapshot frozen dataclass."""

    def test_creation(self):
        snap = _HybridSnapshot(
            trade_date=date(2024, 6, 1),
            core_value=Decimal("70000000"),
            satellite_value=Decimal("30000000"),
            total_value=Decimal("100000000"),
            actual_core_ratio=Decimal("0.7"),
        )
        assert snap.total_value == Decimal("100000000")
        assert snap.actual_core_ratio == Decimal("0.7")


class TestRebalanceEvent:
    """_RebalanceEvent frozen dataclass."""

    def test_creation(self):
        event = _RebalanceEvent(
            trade_date=date(2024, 6, 1),
            direction="satellite_to_core",
            amount=Decimal("5000000"),
            cost=Decimal("1500"),
            core_ratio_before=Decimal("0.65"),
            core_ratio_after=Decimal("0.70"),
        )
        assert event.direction == "satellite_to_core"
        assert event.cost == Decimal("1500")


class TestHybridBacktestResult:
    """_HybridBacktestResult frozen dataclass."""

    def test_creation(self, asset):
        result = _HybridBacktestResult(
            asset=asset,
            start=date(2024, 1, 1),
            end=date(2024, 12, 31),
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            core_ratio=Decimal("0.7"),
            rebalance_mode="drift",
            final_core_value=Decimal("75000000"),
            final_satellite_value=Decimal("32000000"),
            final_total_value=Decimal("107000000"),
            total_return_pct=Decimal("7.0"),
            dgt_trades=[],
            rebalance_events=[],
            daily_snapshots=[],
            rebalancing_alpha_annualized=Decimal("1.5"),
        )
        assert result.total_return_pct == Decimal("7.0")
        assert result.rebalancing_alpha_annualized == Decimal("1.5")


class TestRebalancingAlpha:
    """Rebalancing alpha computation."""

    def test_static_mode_alpha_is_zero(self, asset, cost_model, dgt_config, adaptive_config):
        prices = [70000 + i * 500 for i in range(30)]
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.7"), rebalance_mode="static"),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert result.rebalancing_alpha_annualized == Decimal("0")

    def test_drift_mode_computes_alpha(self, asset, cost_model, dgt_config, adaptive_config):
        # Volatile market to trigger rebalancing
        prices = [70000] * 25 + [90000] * 25 + [70000] * 25
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(
                core_ratio=Decimal("0.7"),
                rebalance_mode="drift",
                drift_threshold=Decimal("0.05"),
                cooldown_days=20,
            ),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        # Alpha should be a Decimal (could be positive or negative)
        assert isinstance(result.rebalancing_alpha_annualized, Decimal)


class TestVolumeGateIntegration:
    """Volume gate works in hybrid runner."""

    def test_volume_gate_disabled(self, asset, cost_model, dgt_config, adaptive_config):
        prices = [70000 + i * 100 for i in range(30)]
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.7"), rebalance_mode="static"),
            volume_gate=False,
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert isinstance(result, _HybridBacktestResult)

    def test_volume_gate_enabled(self, asset, cost_model, dgt_config, adaptive_config):
        prices = [70000 + i * 100 for i in range(30)]
        ohlcv = _make_ohlcv(prices)
        runner = _HybridCoreRunner(
            cost_model=cost_model,
            dgt_config=dgt_config,
            adaptive=adaptive_config,
            hybrid=_HybridConfig(core_ratio=Decimal("0.7"), rebalance_mode="static"),
            volume_gate=True,
            volume_gate_period=10,
            volume_gate_multiplier=Decimal("1.5"),
        )
        result = runner.run(
            asset=asset,
            start=ohlcv[0].trade_date,
            end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert isinstance(result, _HybridBacktestResult)
