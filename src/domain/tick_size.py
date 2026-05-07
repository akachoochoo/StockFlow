"""KRX 호가 단위 helper (Phase 0.9 — ADR 0005 §1.7.3 + §3 박제).

Asset 모델 외부에 분리한 이유 (ADR 0005 §1.7.3 옵션 B 채택):
- ``src/domain/indicators/`` 패턴 (Phase 0.8) 일관 — 도메인 보조 helper
  모듈
- Asset 모델 비대화 회피 (asset_class 분기 로직을 모델 내부에 두지 않음)

본 모듈은 KR_STOCK 호가 단위 산정만 담당. KR_ETF 는 ``Asset.tick_size``
단일값 그대로 사용 (helper 미호출, 회귀 invariant 보존).

Pure stdlib (Decimal). CLAUDE.md §1.1 도메인 import 규칙 준수.
"""
from __future__ import annotations

from decimal import Decimal


def calculate_krx_stock_tick_size(price: Decimal) -> Decimal:
    """KRX 개별 주식 호가 단위 (가격대별, 2023~ 기준).

    KRX 호가 단위 표 (개별 주식)::

        가격 < 1,000원              : 1원
        1,000 ≤ 가격 < 5,000원      : 5원
        5,000 ≤ 가격 < 10,000원     : 10원
        10,000 ≤ 가격 < 50,000원    : 50원
        50,000 ≤ 가격 < 100,000원   : 100원
        100,000 ≤ 가격 < 500,000원  : 500원
        500,000 ≤ 가격              : 1,000원

    KR_ETF 는 본 helper 미사용 — ``Asset.tick_size`` 단일값 (KOSPI ETF
    표준 5원). ADR 0005 §1.7.3 박제 + §3 합병 박제.

    Args:
        price: 양수 Decimal. 0 또는 음수는 ValueError.

    Returns:
        해당 가격대의 호가 단위 Decimal.

    Raises:
        ValueError: ``price <= 0`` 일 때.
    """
    if price <= 0:
        raise ValueError(f"price must be > 0, got {price}")
    if price < Decimal("1000"):
        return Decimal("1")
    if price < Decimal("5000"):
        return Decimal("5")
    if price < Decimal("10000"):
        return Decimal("10")
    if price < Decimal("50000"):
        return Decimal("50")
    if price < Decimal("100000"):
        return Decimal("100")
    if price < Decimal("500000"):
        return Decimal("500")
    return Decimal("1000")
