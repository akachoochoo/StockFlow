"""SellStrategy port (Phase 0.5 / ADR 0002 §5.1).

Mirrors the buy-side ``PriceDropStrategy`` shape but returns 0+ SellDecisions
instead of one StrategyEvaluation — Phase 0.5 §2.1 requires per-slot
independent sell evaluation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from src.domain.models import Position, Price
    from src.domain.strategies.profit_target import (
        SellDecision,
        SellStrategyConfig,
    )


class SellStrategyPort(Protocol):
    """Evaluate per-slot sell triggers for a single asset."""

    def evaluate(
        self,
        *,
        position: Position,
        current_price: Price,
        config: SellStrategyConfig,
        as_of: date,
    ) -> list[SellDecision]:
        """Return the slots to sell (possibly empty)."""
        ...
