"""Unit tests for src.cli.composition — asset registry (Phase 0.7.1 + 0.9)."""
from __future__ import annotations

from datetime import date

import pytest

from src.cli.composition import (
    asset_from_code,
    cj_cheiljedang,
    hyundai_motor,
    kepco,
    kodex200,
    kodex_gold,
    kodex_short_bond_plus,
    samsung_electronics,
    shinhan_financial,
)
from src.domain.models import AssetClass, Currency, Exchange, Market


class TestAssetFromCode:
    def test_kodex200_registered(self):
        asset = asset_from_code("069500")
        assert asset.code == "069500"
        assert asset.exchange is Exchange.KRX
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_ETF
        assert asset.currency is Currency.KRW
        assert asset.name == "KODEX 200"
        assert asset.listed_at == date(2002, 10, 14)

    def test_kodex200_factory_matches_direct(self):
        assert asset_from_code("069500") == kodex200()

    def test_kodex_short_bond_plus_registered(self):
        asset = asset_from_code("214980")
        assert asset.code == "214980"
        assert asset.exchange is Exchange.KRX
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_ETF
        assert asset.currency is Currency.KRW
        assert asset.name == "KODEX 단기채권 PLUS"
        assert asset.listed_at == date(2014, 4, 22)

    def test_kodex_short_bond_plus_factory_matches_direct(self):
        assert asset_from_code("214980") == kodex_short_bond_plus()

    def test_kodex_gold_registered(self):
        asset = asset_from_code("132030")
        assert asset.code == "132030"
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_ETF
        assert asset.name == "KODEX 골드선물(H)"
        assert asset.listed_at == date(2010, 10, 1)

    def test_kodex_gold_factory_matches_direct(self):
        assert asset_from_code("132030") == kodex_gold()

    def test_unknown_code_raises_key_error(self):
        with pytest.raises(KeyError) as exc_info:
            asset_from_code("999999")
        msg = str(exc_info.value)
        # Error message must name the unknown code and list supported codes.
        assert "999999" in msg
        assert "069500" in msg
        assert "214980" in msg


class TestPhase09KrStockFactories:
    """Phase 0.9 — 개별 주식 5 종 (ADR 0005 §1.6.2 + §3 합병 박제).

    Phase 0.9.1 = 005930 + 005380 (인프라 검증).
    Phase 0.9.2 = + 055550 + 097950 + 015760 (분산 효과).
    """

    def test_samsung_electronics_registered(self):
        asset = asset_from_code("005930")
        assert asset.code == "005930"
        assert asset.exchange is Exchange.KRX
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_STOCK
        assert asset.currency is Currency.KRW
        assert asset.name == "삼성전자"
        assert asset.listed_at == date(1975, 6, 11)
        assert asset.delisted_at is None

    def test_samsung_electronics_factory_matches_direct(self):
        assert asset_from_code("005930") == samsung_electronics()

    def test_hyundai_motor_registered(self):
        asset = asset_from_code("005380")
        assert asset.code == "005380"
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_STOCK
        assert asset.name == "현대차"
        assert asset.listed_at == date(1974, 6, 28)

    def test_hyundai_motor_factory_matches_direct(self):
        assert asset_from_code("005380") == hyundai_motor()

    def test_shinhan_financial_registered(self):
        asset = asset_from_code("055550")
        assert asset.code == "055550"
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_STOCK
        assert asset.name == "신한지주"
        assert asset.listed_at == date(2001, 9, 10)

    def test_shinhan_financial_factory_matches_direct(self):
        assert asset_from_code("055550") == shinhan_financial()

    def test_cj_cheiljedang_registered(self):
        asset = asset_from_code("097950")
        assert asset.code == "097950"
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_STOCK
        assert asset.name == "CJ제일제당"
        assert asset.listed_at == date(2007, 9, 19)

    def test_cj_cheiljedang_factory_matches_direct(self):
        assert asset_from_code("097950") == cj_cheiljedang()

    def test_kepco_registered(self):
        asset = asset_from_code("015760")
        assert asset.code == "015760"
        assert asset.market is Market.KOSPI
        assert asset.asset_class is AssetClass.KR_STOCK
        assert asset.name == "한국전력"
        assert asset.listed_at == date(1989, 8, 10)

    def test_kepco_factory_matches_direct(self):
        assert asset_from_code("015760") == kepco()

    def test_kr_stock_factories_listed_before_2019(self):
        """ADR 0005 §1.6.2 — 5 종 모두 2019-01-02 이전 상장 (5-year 백테스트
        가용성). sub-step 0.9.c 사전 검증 PASS 정합."""
        backtest_start = date(2019, 1, 2)
        for factory in (
            samsung_electronics,
            hyundai_motor,
            shinhan_financial,
            cj_cheiljedang,
            kepco,
        ):
            asset = factory()
            assert asset.listed_at < backtest_start, (
                f"{asset.code} ({asset.name}) listed_at "
                f"{asset.listed_at} >= {backtest_start}"
            )

    def test_kr_stock_factories_use_dynamic_tick(self):
        """KR_STOCK 의 round_to_tick 은 helper 분기 (가격대별 동적).

        Asset.tick_size = Decimal("1") placeholder 는 무시되어야 함.
        """
        from decimal import Decimal

        # 삼성전자 ~70,000원 → tick=100 → floor 70000
        a = samsung_electronics()
        assert a.round_to_tick(Decimal("70049")) == Decimal("70000")
        # 현대차 ~200,000원 → tick=500 → floor 200000
        b = hyundai_motor()
        assert b.round_to_tick(Decimal("200499")) == Decimal("200000")
