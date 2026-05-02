"""Profit-target sell strategy (Phase 0.5 / ADR 0002 §2 + §5.2).

Per-slot independent sell evaluation: each FILLED slot is checked against
``profit_target_pct`` of its own ``entry_price``. Slots that exceed the
threshold are returned as SellDecision values (smallest ``slot_number``
first), capped at ``max_sells_per_day``.

Phase 0.5 ships exactly one sell strategy. Multiple strategies + a Port
selector arrive in Phase 1+ alongside the KIS adapter.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import Field

from src.domain.models import DomainModel, ValueObject

if TYPE_CHECKING:
    from datetime import date

    from src.domain.models import Position, Price


class SellStrategyConfig(DomainModel):
    """Configuration for ProfitTargetSell.

    `profit_target_pct` is the per-slot threshold (e.g., 10.0 → +10 %
    over the slot's entry_price). All slots use the same threshold per
    ADR 0002 §2.2 — slot-tiered thresholds are deferred to Phase 0.7+.

    `max_sells_per_day` caps the number of slots that may be sold in a
    single evaluation. Default 7 (== max splits) means "no limit beyond
    the natural ceiling".
    """

    profit_target_pct: Decimal = Field(gt=Decimal(0), lt=Decimal(100))
    max_sells_per_day: int = Field(default=7, ge=1, le=7)


class SellDecision(ValueObject):
    """A single slot's sell trigger output (Phase 0.5 / ADR 0002 §5.1).

    The strategy emits one SellDecision per slot that hit the threshold.
    The orchestrator turns each SellDecision into a SELL OrderRequest
    using ``slot_number`` + ``expected_price``.
    """

    slot_number: int = Field(ge=1, le=7)
    expected_price: Decimal = Field(gt=Decimal(0))
    reasoning: dict[str, str]


class ProfitTargetSell:
    """Stateless evaluator: per-slot +X% profit target.

    Iterates ``position.filled_slots`` (already sorted by ``slot_number``)
    and emits a SellDecision for every slot whose profit-vs-entry meets
    or exceeds ``profit_target_pct``. The smallest ``slot_number`` wins
    when ``max_sells_per_day`` caps the result.

    Empty position / all-EMPTY slots → empty list (no trigger).
    """

    def evaluate(
        self,
        *,
        position: Position,
        current_price: Price,
        config: SellStrategyConfig,
        as_of: date,
    ) -> list[SellDecision]:
        if position.quantity <= 0:
            return []

        triggers: list[SellDecision] = []
        for slot in position.filled_slots:
            assert slot.entry is not None  # FILLED invariant
            entry_price = slot.entry.entry_price
            profit_pct = (
                (current_price.value - entry_price) / entry_price * Decimal(100)
            )
            if profit_pct >= config.profit_target_pct:
                triggers.append(
                    SellDecision(
                        slot_number=slot.slot_number,
                        expected_price=current_price.value,
                        reasoning={
                            "entry_price": str(entry_price),
                            "current_price": str(current_price.value),
                            "profit_pct": str(profit_pct),
                            "profit_target_pct": str(config.profit_target_pct),
                        },
                    )
                )
        # Cap per ADR 0002 §5.1 — smallest slot_number wins (already sorted).
        if len(triggers) > config.max_sells_per_day:
            triggers = triggers[: config.max_sells_per_day]
        return triggers
