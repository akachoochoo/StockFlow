"""Grid decision equivalence — backtest vs dry-run/live GridDecision identity.

ADR 0022 §12 D22 (Q8/G2 진성 동등성). Mirror of
:mod:`src.use_cases.decision_equivalence` but for ``GridDecision`` —
DGT 다중 주문 (하루 같은 side 다수 거래) + slot 부재 (level_index 만 보유).

Same shape as split equivalence: a canonical *projection* tuple of fields
that legitimately must match between a backtest and a live/dry-run grid
trade, deliberately excluding fields that legitimately differ:

    - top-level ``reasoning``  — free-form context dict
    - any timing/order_id metadata (not on GridDecision itself, but mirrored
      from split equivalence for principled symmetry)

The projection IS:

    (side, level_index, rounded_price, quantity)

``rounded_price`` (already tick-rounded by ``asset.round_to_tick``) is the
체결 기준 가격 — backtest 과 live 가 같은 OHLCV 입력에서 같은 level_price
를 산출하므로 동일성이 강하게 보장된다 (deterministic premise).

Layering (CLAUDE.md §1.1): pure use_case. domain only (GridDecision,
OrderSide). No adapters / cli / clock / IO.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

    from src.domain.models import OrderSide
    from src.domain.strategies.grid import GridDecision


# Canonical projection: (side, level_index, rounded_price, quantity).
# excluded: reasoning (free-form context dict).
_GridDecisionProjection = tuple["OrderSide", int, "Decimal", "Decimal"]


def grid_decision_projection(d: GridDecision) -> _GridDecisionProjection:
    """Project ``d`` to canonical decision-relevant fields (ADR 0022 §12 D22).

    Returns ``(side, level_index, rounded_price, quantity)``. Excludes
    ``reasoning`` (free-form) and ``level_price`` (the *unrounded* level value
    — `rounded_price` is the actually submitted price and is what equivalence
    must match).

    Determinism premise: same OHLCV input + same GridConfig → same level
    crossing → same level_index → same rounded_price → equivalence holds.
    """
    return (d.side, d.level_index, d.rounded_price, d.quantity)


def grid_decisions_equivalent(a: GridDecision, b: GridDecision) -> bool:
    """True when ``a`` and ``b`` project to the same canonical grid decision.

    ADR 0022 §12 D22 — backtest vs dry-run/live identity for DGT trades.
    Two GridDecisions that differ only in ``reasoning`` (or in
    ``level_price`` precision pre-rounding) are equivalent.
    """
    return grid_decision_projection(a) == grid_decision_projection(b)


def grid_decision_sequences_equivalent(
    a: list[GridDecision], b: list[GridDecision]
) -> bool:
    """True when two *ordered* sequences of GridDecisions project identically.

    Unlike split sell_actions (which we sort because sell ordering does not
    affect outcome), grid decisions in a single day may have a *meaningful*
    order (e.g., a buy on level 3 followed by a sell on level 4 must be
    distinguishable from the reverse). So we compare position-by-position.
    """
    if len(a) != len(b):
        return False
    return all(
        grid_decision_projection(x) == grid_decision_projection(y)
        for x, y in zip(a, b, strict=True)
    )
