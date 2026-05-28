"""Unit tests for src.use_cases.grid_decision_equivalence.

ADR 0022 §12 D22 — backtest vs dry-run/live GridDecision identity. The
projection EXCLUDES reasoning (free-form context) and uses ``rounded_price``
(actually submitted price) not ``level_price`` (pre-rounding value).
"""
from __future__ import annotations

from decimal import Decimal

from src.domain.models import OrderSide
from src.domain.strategies.grid import GridDecision
from src.use_cases.grid_decision_equivalence import (
    grid_decision_projection,
    grid_decision_sequences_equivalent,
    grid_decisions_equivalent,
)


def _gd(
    *,
    side: OrderSide = OrderSide.BUY,
    level_index: int = 3,
    level_price: Decimal = Decimal("30007.5"),
    rounded_price: Decimal = Decimal("30005"),
    quantity: Decimal = Decimal("10"),
    reasoning: dict[str, str] | None = None,
) -> GridDecision:
    return GridDecision(
        side=side,
        level_index=level_index,
        level_price=level_price,
        rounded_price=rounded_price,
        quantity=quantity,
        reasoning=reasoning or {"trigger": "level_cross"},
    )


def test_projection_returns_canonical_tuple() -> None:
    d = _gd()
    proj = grid_decision_projection(d)
    assert proj == (OrderSide.BUY, 3, Decimal("30005"), Decimal("10"))


def test_equivalence_holds_for_identical_decisions() -> None:
    a = _gd()
    b = _gd()
    assert grid_decisions_equivalent(a, b)


def test_equivalence_ignores_reasoning() -> None:
    """reasoning(자유 dict)이 달라도 동등."""
    a = _gd(reasoning={"trigger": "level_cross", "atr": "150"})
    b = _gd(reasoning={"trigger": "level_cross", "atr": "200", "extra": "x"})
    assert grid_decisions_equivalent(a, b)


def test_equivalence_ignores_level_price_precision() -> None:
    """level_price 가 사전 가격 — rounded_price 만 비교 (체결 기준)."""
    a = _gd(level_price=Decimal("30007.5"), rounded_price=Decimal("30005"))
    b = _gd(level_price=Decimal("30008.3"), rounded_price=Decimal("30005"))
    assert grid_decisions_equivalent(a, b)


def test_equivalence_diverges_on_side() -> None:
    a = _gd(side=OrderSide.BUY)
    b = _gd(side=OrderSide.SELL)
    assert not grid_decisions_equivalent(a, b)


def test_equivalence_diverges_on_level_index() -> None:
    a = _gd(level_index=3)
    b = _gd(level_index=4)
    assert not grid_decisions_equivalent(a, b)


def test_equivalence_diverges_on_rounded_price() -> None:
    a = _gd(rounded_price=Decimal("30005"))
    b = _gd(rounded_price=Decimal("30010"))
    assert not grid_decisions_equivalent(a, b)


def test_equivalence_diverges_on_quantity() -> None:
    a = _gd(quantity=Decimal("10"))
    b = _gd(quantity=Decimal("11"))
    assert not grid_decisions_equivalent(a, b)


def test_sequences_equivalent_empty() -> None:
    assert grid_decision_sequences_equivalent([], [])


def test_sequences_equivalent_same_order() -> None:
    a = [_gd(level_index=3, side=OrderSide.BUY), _gd(level_index=4, side=OrderSide.SELL)]
    b = [_gd(level_index=3, side=OrderSide.BUY), _gd(level_index=4, side=OrderSide.SELL)]
    assert grid_decision_sequences_equivalent(a, b)


def test_sequences_diverge_on_order() -> None:
    """그리드 시퀀스는 순서가 의미 있음 — sort 안 함."""
    a = [_gd(level_index=3, side=OrderSide.BUY), _gd(level_index=4, side=OrderSide.SELL)]
    b = [_gd(level_index=4, side=OrderSide.SELL), _gd(level_index=3, side=OrderSide.BUY)]
    assert not grid_decision_sequences_equivalent(a, b)


def test_sequences_diverge_on_length() -> None:
    a = [_gd()]
    b = [_gd(), _gd(level_index=4)]
    assert not grid_decision_sequences_equivalent(a, b)
