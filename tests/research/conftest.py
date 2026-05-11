"""Phase 0.11.a — fixtures for `src/research/` tests.

ADR 0007 §2.4 박제: AC1~AC4 의 pseudo-code `Asset.kr_etf(...)` /
`Asset.kr_stock(...)` 는 실제 Asset 모델 9 필수 필드 instantiate 로 정정.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
)
from src.research.dgt.cost_model import _KoreanMarketCostModel


@pytest.fixture
def kr_etf_069500() -> Asset:
    """KODEX 200 (069500) — Phase 0.10.bb 박제 정합 (tick_size=5)."""
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


@pytest.fixture
def kr_stock_005930() -> Asset:
    """삼성전자 (005930) — KR_STOCK, tick = 가격대별 동적 (tick_size.py:18-57).

    `tick_size=Decimal("1")` 은 placeholder — round_to_tick 분기에서 미사용
    (ADR 0005 §3.3.1 박제).
    """
    return Asset(
        code="005930",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="삼성전자",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(1975, 6, 11),
    )


@pytest.fixture
def cost_model() -> _KoreanMarketCostModel:
    """ADR 0007 §1.3 default — commission 0.015% / etf_tax 0.18% / stock_tax 0.15%."""
    return _KoreanMarketCostModel()
