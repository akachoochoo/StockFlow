"""run_grid_portfolio — 멀티에셋 DGT 집계 (ADR 0022 §11 D13).

종목별 GridRunner 독립 실행(D9) + 균등 자본 분할 + 일별 합산이 단일 실행과
정합하는지(단일=GridRunner 동일, 동일 2종=2배+나머지) 잠근다.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.application.grid_portfolio_backtest import (
    GridAssetInput,
    run_grid_portfolio,
)
from src.cli.composition import asset_from_code
from src.domain.models import OHLCV, Currency, Money
from src.domain.strategies.grid import GridConfig
from src.use_cases.grid_runner import GridRunner

_CLOSES = [
    "35000", "36400", "38200", "37100", "34500", "32800", "31000", "33200",
    "35600", "38800", "41200", "39500", "36900", "34100", "31500", "29800",
    "32400", "35100", "37800", "40500", "42100", "39700", "36300", "33800",
]


def _bars(asset) -> list[OHLCV]:
    base = date(2024, 1, 1)
    closes = [Decimal(c) for c in _CLOSES]
    out: list[OHLCV] = []
    for i, c in enumerate(closes):
        opn = closes[i - 1] if i > 0 else c
        out.append(
            OHLCV(
                asset=asset,
                trade_date=base + timedelta(days=i),
                open=opn,
                high=max(opn, c) * Decimal("1.01"),
                low=min(opn, c) * Decimal("0.99"),
                close=c,
                volume=Decimal("1000000"),
            )
        )
    return out


def _config() -> GridConfig:
    return GridConfig(grid_count=11, fallback_k=Decimal("0.05"))


def _krw(n: str) -> Money:
    return Money(amount=Decimal(n), currency=Currency.KRW)


class TestRunGridPortfolio:
    def test_single_asset_matches_grid_runner(self):
        asset = asset_from_code("069500")
        bars = _bars(asset)
        cap = _krw("50000000")
        port = run_grid_portfolio(
            [GridAssetInput(asset=asset, bars=bars, config=_config())],
            initial_capital=cap,
        )
        single = GridRunner().run(
            asset=asset, bars=bars, config=_config(), initial_capital=cap
        )
        assert port.unallocated == Decimal("0")
        assert len(port.per_asset) == 1
        assert port.final_value == single.final_value
        assert len(port.daily_values) == len(bars)
        # portfolio series == single run's per-day total_value (unallocated 0)
        assert port.daily_values[-1][1] == single.daily_values[-1].total_value

    def test_two_identical_assets_double_plus_remainder(self):
        a, b = asset_from_code("069500"), asset_from_code("132030")
        cap = _krw("100000001")  # odd → 1 KRW unallocated
        port = run_grid_portfolio(
            [
                GridAssetInput(asset=a, bars=_bars(a), config=_config()),
                GridAssetInput(asset=b, bars=_bars(b), config=_config()),
            ],
            initial_capital=cap,
        )
        assert port.unallocated == Decimal("1")
        assert port.per_asset[0].allocated.amount == Decimal("50000000")
        # both ETFs, identical bars/config → identical single run
        single = GridRunner().run(
            asset=a, bars=_bars(a), config=_config(),
            initial_capital=_krw("50000000"),
        )
        assert port.final_value == single.final_value * 2 + Decimal("1")
        assert port.daily_values[-1][1] == (
            single.daily_values[-1].total_value * 2 + Decimal("1")
        )

    def test_daily_values_intersect_dates(self):
        a, b = asset_from_code("069500"), asset_from_code("132030")
        bars_a = _bars(a)
        bars_b = _bars(b)[:-3]  # shorter window
        port = run_grid_portfolio(
            [
                GridAssetInput(asset=a, bars=bars_a, config=_config()),
                GridAssetInput(asset=b, bars=bars_b, config=_config()),
            ],
            initial_capital=_krw("100000000"),
        )
        # intersection → the shorter series length
        assert len(port.daily_values) == len(bars_b)

    def test_empty_inputs_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            run_grid_portfolio([], initial_capital=_krw("1000000"))
