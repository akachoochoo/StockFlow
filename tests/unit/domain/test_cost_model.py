"""KoreanMarketCostModel — research 동치 잠금 (ADR 0022 G1 증분 3a).

`src/domain/cost_model.py` 가 `src/research/dgt/cost_model.py` 와 매수/매도
비용을 **bit-identical Decimal** 로 산출하는지 잠근다 (ETF/STOCK 양쪽).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.cli.composition import asset_from_code
from src.domain.cost_model import KoreanMarketCostModel
from src.research.dgt.cost_model import _KoreanMarketCostModel

_ETF = asset_from_code("069500")  # KR_ETF, tick 5
_STOCK = asset_from_code("005930")  # KR_STOCK, 가격대별 tick

_PRICES = [Decimal("35000"), Decimal("35123"), Decimal("132030"), Decimal("9999")]
_QTYS = [Decimal("1"), Decimal("10"), Decimal("237")]


class TestBuyCostEquivalence:
    @pytest.mark.parametrize("asset", [_ETF, _STOCK])
    @pytest.mark.parametrize("price", _PRICES)
    @pytest.mark.parametrize("qty", _QTYS)
    def test_matches_research(self, asset, price: Decimal, qty: Decimal):
        dom = KoreanMarketCostModel().compute_buy_cost(
            price=price, quantity=qty, asset=asset
        )
        res = _KoreanMarketCostModel().compute_buy_cost(price, qty, asset)
        assert dom.rounded_price == res.rounded_price
        assert dom.gross == res.gross
        assert dom.commission == res.commission
        assert dom.tax == res.tax == Decimal("0")
        assert dom.total_cost == res.total_cost


class TestSellCostEquivalence:
    @pytest.mark.parametrize("asset", [_ETF, _STOCK])
    @pytest.mark.parametrize("price", _PRICES)
    @pytest.mark.parametrize("qty", _QTYS)
    def test_matches_research(self, asset, price: Decimal, qty: Decimal):
        dom = KoreanMarketCostModel().compute_sell_cost(
            price=price, quantity=qty, asset=asset
        )
        res = _KoreanMarketCostModel().compute_sell_cost(price, qty, asset)
        assert dom.rounded_price == res.rounded_price
        assert dom.gross == res.gross
        assert dom.commission == res.commission
        assert dom.tax == res.tax
        assert dom.net_proceeds == res.net_proceeds

    def test_etf_vs_stock_tax_differs(self):
        m = KoreanMarketCostModel()
        etf = m.compute_sell_cost(price=Decimal("35000"), quantity=Decimal("10"), asset=_ETF)
        stock = m.compute_sell_cost(price=Decimal("35000"), quantity=Decimal("10"), asset=_STOCK)
        # ETF 0.18% > STOCK 0.15% (동일 gross 기준)
        assert etf.tax > stock.tax


class TestZeroCost:
    def test_zero_rates_no_friction(self):
        m = KoreanMarketCostModel(
            commission_rate=Decimal("0"),
            etf_tax_rate=Decimal("0"),
            stock_tax_rate=Decimal("0"),
        )
        buy = m.compute_buy_cost(price=Decimal("35000"), quantity=Decimal("10"), asset=_ETF)
        sell = m.compute_sell_cost(price=Decimal("35000"), quantity=Decimal("10"), asset=_ETF)
        assert buy.total_cost == buy.gross
        assert sell.net_proceeds == sell.gross
