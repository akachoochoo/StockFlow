"""Unit tests for src.domain.tick_size.

Phase 0.9 — ADR 0005 §1.7.3 + §3 박제.
KRX 개별 주식 호가 단위 가격대별 산정 검증.

CLAUDE.md §7.1 — 도메인 helper 100% 커버 목표.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.tick_size import calculate_krx_stock_tick_size


class TestCalculateKrxStockTickSize:
    """가격대별 호가 단위 산정 (ADR 0005 §1.7.3 표).

    7 brackets:
        < 1,000      → 1
        < 5,000      → 5
        < 10,000     → 10
        < 50,000     → 50
        < 100,000    → 100
        < 500,000    → 500
        ≥ 500,000    → 1,000
    """

    @pytest.mark.parametrize(
        "price, expected",
        [
            # bracket 1: < 1,000 → 1
            (Decimal("1"), Decimal("1")),
            (Decimal("500"), Decimal("1")),
            (Decimal("999"), Decimal("1")),
            (Decimal("999.99"), Decimal("1")),
            # bracket 2: 1,000 ≤ < 5,000 → 5
            (Decimal("1000"), Decimal("5")),
            (Decimal("3000"), Decimal("5")),
            (Decimal("4999"), Decimal("5")),
            # bracket 3: 5,000 ≤ < 10,000 → 10
            (Decimal("5000"), Decimal("10")),
            (Decimal("7500"), Decimal("10")),
            (Decimal("9999"), Decimal("10")),
            # bracket 4: 10,000 ≤ < 50,000 → 50
            (Decimal("10000"), Decimal("50")),
            (Decimal("25000"), Decimal("50")),
            (Decimal("49999"), Decimal("50")),
            # bracket 5: 50,000 ≤ < 100,000 → 100
            (Decimal("50000"), Decimal("100")),
            (Decimal("75000"), Decimal("100")),
            (Decimal("99999"), Decimal("100")),
            # bracket 6: 100,000 ≤ < 500,000 → 500
            (Decimal("100000"), Decimal("500")),
            (Decimal("250000"), Decimal("500")),
            (Decimal("499999"), Decimal("500")),
            # bracket 7: ≥ 500,000 → 1,000
            (Decimal("500000"), Decimal("1000")),
            (Decimal("999999"), Decimal("1000")),
            (Decimal("9999999"), Decimal("1000")),
        ],
    )
    def test_bracket_returns_expected_tick(
        self, price: Decimal, expected: Decimal
    ) -> None:
        assert calculate_krx_stock_tick_size(price) == expected

    def test_zero_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            calculate_krx_stock_tick_size(Decimal("0"))

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            calculate_krx_stock_tick_size(Decimal("-1"))

    # 실제 Phase 0.9 종목 가격대 회귀 (2026-05-07 기준 추정)
    def test_samsung_electronics_price_range(self) -> None:
        """005930 삼성전자 ~50,000-90,000원 → 50/100원 호가."""
        assert calculate_krx_stock_tick_size(Decimal("49999")) == Decimal("50")
        assert calculate_krx_stock_tick_size(Decimal("70000")) == Decimal("100")

    def test_hyundai_motor_price_range(self) -> None:
        """005380 현대차 ~150,000-250,000원 → 500원 호가."""
        assert calculate_krx_stock_tick_size(Decimal("200000")) == Decimal("500")

    def test_kepco_price_range(self) -> None:
        """015760 한국전력 ~20,000원 → 50원 호가."""
        assert calculate_krx_stock_tick_size(Decimal("22000")) == Decimal("50")

    def test_returns_decimal_type(self) -> None:
        """반환 타입은 항상 Decimal (CLAUDE.md §2.1)."""
        result = calculate_krx_stock_tick_size(Decimal("1500"))
        assert isinstance(result, Decimal)
