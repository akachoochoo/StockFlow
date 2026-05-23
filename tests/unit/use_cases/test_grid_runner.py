"""GridRunner — research end-to-end 동치 + 결정론 (ADR 0022 G1 증분 3b).

GridRunner(zero-cost) 가 research ``_DGTPaperAdaptiveRunner``(zero-cost) 와
trades(비용 분해 포함) + 최종 cash/holdings + 일별 total_value 까지 bit-identical
임을 잠근다 — 도메인 grid 엔진의 end-to-end 포트 충실성. + 결정론(G2 §7.4) +
with-cost 스모크.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.cli.composition import asset_from_code
from src.domain.cost_model import KoreanMarketCostModel
from src.domain.models import OHLCV, Currency, Money
from src.domain.strategies.grid import GridConfig
from src.research.dgt.adaptive_runner import _AdaptiveConfig
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.paper_adaptive_runner import _DGTPaperAdaptiveRunner
from src.research.dgt.runner import _DGTConfig
from src.use_cases.grid_runner import GridRunner

_ASSET = asset_from_code("069500")
_CAPITAL = Money(amount=Decimal("100000000"), currency=Currency.KRW)

_CLOSES = [
    "35000", "36400", "38200", "37100", "34500", "32800", "31000", "33200",
    "35600", "38800", "41200", "39500", "36900", "34100", "31500", "29800",
    "32400", "35100", "37800", "40500", "42100", "39700", "36300", "33800",
    "30900", "28500", "31200", "34600", "37200", "39900",
]
_VOLS = [Decimal("1000000")] * len(_CLOSES)
_VOLS[20] = Decimal("6000000")


def _bars() -> list[OHLCV]:
    base = date(2024, 1, 1)
    closes = [Decimal(c) for c in _CLOSES]
    out: list[OHLCV] = []
    for i, c in enumerate(closes):
        opn = closes[i - 1] if i > 0 else c
        out.append(
            OHLCV(
                asset=_ASSET,
                trade_date=base + timedelta(days=i),
                open=opn,
                high=max(opn, c) * Decimal("1.01"),
                low=min(opn, c) * Decimal("0.99"),
                close=c,
                volume=_VOLS[i],
            )
        )
    return out


def _domain_config() -> GridConfig:
    return GridConfig(
        grid_count=11,
        fallback_k=Decimal("0.05"),
        rebalance_mode="daily",
        volatility_measure="adr",
        atr_period=14,
        multiplier=Decimal("1.5"),
        k_min=Decimal("0.02"),
        k_max=Decimal("0.10"),
        volume_gate=True,
        volume_gate_period=10,
        volume_gate_multiplier=Decimal("1.5"),
    )


def _research_zero() -> _DGTPaperAdaptiveRunner:
    return _DGTPaperAdaptiveRunner(
        cost_model=_KoreanMarketCostModel(
            commission_rate=Decimal("0"),
            etf_tax_rate=Decimal("0"),
            stock_tax_rate=Decimal("0"),
        ),
        config=_DGTConfig(grid_count=11, grid_spacing_pct=Decimal("5"), levels_above=5),
        adaptive=_AdaptiveConfig(),
        rebalance_mode="daily",
        volatility_measure="adr",
        volume_gate=True,
        volume_gate_period=10,
        volume_gate_multiplier=Decimal("1.5"),
    )


class TestResearchEndToEndEquivalence:
    def test_trades_balance_daily_bit_identical_zero_cost(self):
        bars = _bars()
        zero_cost = KoreanMarketCostModel(
            commission_rate=Decimal("0"),
            etf_tax_rate=Decimal("0"),
            stock_tax_rate=Decimal("0"),
        )
        result = GridRunner(cost_model=zero_cost).run(
            asset=_ASSET, bars=bars, config=_domain_config(), initial_capital=_CAPITAL
        )
        res = _research_zero().run(
            _ASSET, bars[0].trade_date, bars[-1].trade_date, _CAPITAL, bars
        )

        my_trades = [
            (t.side.value, t.level_price, t.quantity, t.rounded_price,
             t.gross, t.tax, t.commission, t.cash_delta)
            for t in result.trades
        ]
        res_trades = [
            (t.side, t.grid_level_price, t.quantity, t.rounded_price,
             t.gross, t.tax, t.commission, t.cash_delta)
            for t in res.trades
        ]
        assert my_trades == res_trades
        assert result.final_cash == res.final_cash
        assert result.final_holdings == res.final_holdings
        assert [(d.trade_date, d.total_value) for d in result.daily_values] == [
            (s.trade_date, s.total_value) for s in res.daily_snapshots
        ]

    def test_non_trivial(self):
        bars = _bars()
        result = GridRunner().run(
            asset=_ASSET, bars=bars, config=_domain_config(), initial_capital=_CAPITAL
        )
        # non-vacuous: 실제 거래 발생 (zero-cost 동치 테스트가 양방향을 정밀 검증).
        assert len(result.trades) >= 2


class TestDeterminism:
    def test_same_bars_same_result(self):
        bars = _bars()
        cfg = _domain_config()
        r1 = GridRunner().run(asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL)
        r2 = GridRunner().run(asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL)
        assert r1 == r2


class TestWithCost:
    def test_cost_reduces_value_and_records_friction(self):
        bars = _bars()
        cfg = _domain_config()
        zero = GridRunner(
            cost_model=KoreanMarketCostModel(
                commission_rate=Decimal("0"),
                etf_tax_rate=Decimal("0"),
                stock_tax_rate=Decimal("0"),
            )
        ).run(asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL)
        costed = GridRunner().run(
            asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL
        )
        # 실비용 적용 시 매도 tax/commission > 0 기록.
        sells = [t for t in costed.trades if t.side.value == "SELL"]
        assert sells and all(t.tax > 0 and t.commission > 0 for t in sells)
        # 비용은 가치를 잠식 (동일 거래라면 final_value 비용판 <= 무비용판).
        assert costed.final_value <= zero.final_value

    def test_mdd_computable_from_daily(self):
        bars = _bars()
        result = GridRunner().run(
            asset=_ASSET, bars=bars, config=_domain_config(), initial_capital=_CAPITAL
        )
        values = [d.total_value for d in result.daily_values]
        peak = values[0]
        mdd = Decimal("0")
        for v in values:
            peak = max(peak, v)
            dd = (v - peak) / peak
            mdd = min(mdd, dd)
        assert mdd <= 0  # drawdown 은 음수 또는 0
        assert len(values) == len(bars)


class TestGuards:
    def test_empty_bars_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            GridRunner().run(
                asset=_ASSET, bars=[], config=_domain_config(), initial_capital=_CAPITAL
            )

    def test_currency_mismatch_raises(self):
        with pytest.raises(ValueError, match="currency"):
            GridRunner().run(
                asset=_ASSET,
                bars=_bars(),
                config=_domain_config(),
                initial_capital=Money(amount=Decimal("1000"), currency=Currency.USD),
            )
