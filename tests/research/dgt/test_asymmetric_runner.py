"""Tests for Phase 0.11.g.3 — _AsymmetricGridRunner (INFORMATIONAL)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.domain.models import Asset, AssetClass, Currency, Exchange, Market, Money, OHLCV
from src.research.dgt.adaptive_runner import _AdaptiveConfig
from src.research.dgt.asymmetric_runner import (
    _AsymmetricGridRunner,
    _TrailingState,
    _grid_levels_asymmetric,
)
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.results import _DGTBacktestResult
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
    return _DGTConfig(grid_count=11, grid_spacing_pct=Decimal("0.02"), levels_above=5)


@pytest.fixture
def adaptive() -> _AdaptiveConfig:
    return _AdaptiveConfig(
        atr_period=14, multiplier=Decimal("1.0"),
        k_min=Decimal("0.005"), k_max=Decimal("0.05"),
    )


def _make_ohlcv(prices: list[int], asset: Asset) -> list[OHLCV]:
    bars = []
    for i, p in enumerate(prices):
        d = date.fromordinal(date(2024, 1, 2).toordinal() + i)
        c = Decimal(str(p))
        bars.append(OHLCV(
            asset=asset, trade_date=d, open=c,
            high=c * Decimal("1.01"), low=c * Decimal("0.99"),
            close=c, volume=Decimal("1000000"),
        ))
    return bars


class TestGridLevelsAsymmetric:
    """_grid_levels_asymmetric produces correct spacing."""

    def test_basic_asymmetric(self):
        buy, sell = _grid_levels_asymmetric(
            n=11, reference_price=Decimal("100"),
            k_buy=Decimal("0.02"), k_sell=Decimal("0.04"),
            levels_above=5,
        )
        # 6 buy levels below (spacing 2%), 5 sell levels above (spacing 4%)
        assert len(buy) == 6
        assert len(sell) == 5
        # Buy levels closer together than sell levels
        buy_gap = buy[1] - buy[0]
        sell_gap = sell[1] - sell[0]
        assert sell_gap > buy_gap

    def test_sell_spacing_is_multiplied(self):
        buy, sell = _grid_levels_asymmetric(
            n=11, reference_price=Decimal("1000"),
            k_buy=Decimal("0.01"), k_sell=Decimal("0.03"),
            levels_above=5,
        )
        # First sell level should be at 1000 * (1 + 0.03) = 1030
        assert sell[0] == Decimal("1030")
        # First buy level below ref should be 1000 * (1 - 0.01*6) = 940
        assert buy[0] == Decimal("940")


class TestTrailingState:
    """_TrailingState tracks HWM and triggers correctly."""

    def test_inactive_by_default(self):
        ts = _TrailingState(trailing_pct=Decimal("0.05"))
        should_sell, _ = ts.update(Decimal("100"))
        assert not should_sell

    def test_activate_and_trigger(self):
        ts = _TrailingState(trailing_pct=Decimal("0.05"))
        ts.activate(Decimal("100"), Decimal("101"))
        # Price rises
        should_sell, _ = ts.update(Decimal("110"))
        assert not should_sell
        assert ts.high_water_mark == Decimal("110")
        # Price drops 5% from HWM (110 * 0.95 = 104.5)
        should_sell, price = ts.update(Decimal("104"))
        assert should_sell
        assert price == Decimal("104")
        assert not ts.activated  # deactivated after trigger

    def test_no_trigger_if_within_trailing(self):
        ts = _TrailingState(trailing_pct=Decimal("0.05"))
        ts.activate(Decimal("100"), Decimal("105"))
        ts.update(Decimal("110"))  # HWM = 110
        # 110 * 0.95 = 104.5, price = 105 > 104.5 -> no trigger
        should_sell, _ = ts.update(Decimal("105"))
        assert not should_sell


class TestAsymmetricGridRunner:
    """_AsymmetricGridRunner basic functionality."""

    def test_run_returns_result(self, asset, cost_model, dgt_config, adaptive):
        prices = [70000 + i * 100 for i in range(30)]
        ohlcv = _make_ohlcv(prices, asset)
        runner = _AsymmetricGridRunner(
            cost_model=cost_model, config=dgt_config, adaptive=adaptive,
            sell_multiplier=Decimal("2.0"), use_trailing=False, volume_gate=False,
        )
        result = runner.run(
            asset=asset, start=ohlcv[0].trade_date, end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert isinstance(result, _DGTBacktestResult)
        assert len(result.daily_snapshots) == 30

    def test_empty_raises(self, asset, cost_model, dgt_config, adaptive):
        runner = _AsymmetricGridRunner(
            cost_model=cost_model, config=dgt_config, adaptive=adaptive,
            volume_gate=False,
        )
        with pytest.raises(ValueError, match="non-empty"):
            runner.run(
                asset=asset, start=date(2024, 1, 1), end=date(2024, 1, 1),
                initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
                ohlcv=[],
            )

    def test_wider_sell_reduces_sell_count(self, asset, cost_model, dgt_config, adaptive):
        """Wider sell spacing should result in fewer sells than symmetric."""
        prices = [70000 + i * 500 for i in range(50)]  # uptrend
        ohlcv = _make_ohlcv(prices, asset)
        capital = Money(amount=Decimal("100000000"), currency=Currency.KRW)

        # Symmetric (mult=1)
        sym_runner = _AsymmetricGridRunner(
            cost_model=cost_model, config=dgt_config, adaptive=adaptive,
            sell_multiplier=Decimal("1.0"), use_trailing=False, volume_gate=False,
        )
        sym_result = sym_runner.run(
            asset=asset, start=ohlcv[0].trade_date, end=ohlcv[-1].trade_date,
            initial_capital=capital, ohlcv=ohlcv,
        )

        # Asymmetric (mult=3)
        asym_runner = _AsymmetricGridRunner(
            cost_model=cost_model, config=dgt_config, adaptive=adaptive,
            sell_multiplier=Decimal("3.0"), use_trailing=False, volume_gate=False,
        )
        asym_result = asym_runner.run(
            asset=asset, start=ohlcv[0].trade_date, end=ohlcv[-1].trade_date,
            initial_capital=capital, ohlcv=ohlcv,
        )

        sym_sells = sum(1 for t in sym_result.trades if t.side == "SELL")
        asym_sells = sum(1 for t in asym_result.trades if t.side == "SELL")
        # Wider spacing → fewer sells
        assert asym_sells <= sym_sells

    def test_trailing_mode_runs(self, asset, cost_model, dgt_config, adaptive):
        prices = [70000 + i * 300 for i in range(20)] + [75000 - i * 500 for i in range(20)]
        ohlcv = _make_ohlcv(prices, asset)
        runner = _AsymmetricGridRunner(
            cost_model=cost_model, config=dgt_config, adaptive=adaptive,
            sell_multiplier=Decimal("2.0"), use_trailing=True,
            trailing_pct=Decimal("0.03"), volume_gate=False,
        )
        result = runner.run(
            asset=asset, start=ohlcv[0].trade_date, end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert isinstance(result, _DGTBacktestResult)

    def test_volume_gate_integration(self, asset, cost_model, dgt_config, adaptive):
        prices = [70000 + i * 100 for i in range(30)]
        ohlcv = _make_ohlcv(prices, asset)
        runner = _AsymmetricGridRunner(
            cost_model=cost_model, config=dgt_config, adaptive=adaptive,
            sell_multiplier=Decimal("2.0"), volume_gate=True,
            volume_gate_period=10, volume_gate_multiplier=Decimal("1.5"),
        )
        result = runner.run(
            asset=asset, start=ohlcv[0].trade_date, end=ohlcv[-1].trade_date,
            initial_capital=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ohlcv=ohlcv,
        )
        assert isinstance(result, _DGTBacktestResult)
