"""ReentryPriceStrategyPort (Phase 0.5 / ADR 0002 §4.1).

Computes the trigger price at which an EMPTY slot becomes eligible for
re-entry. Phase 0.5 ships two implementations in
``src.domain.strategies.reentry``:

* ``MovingAverageReentry`` — N-day moving-average anchored (policy D-2).
  Returns ``None`` when historical OHLCV data is insufficient
  (window not yet satisfied).
* ``HybridTimeBasedReentry`` — last-exit anchored within cooldown
  (policy F). Always returns a ``Decimal`` (no external data needed).

Per ADR §4.7, slots without ``last_exit_*`` history (system start, or a
slot that has never been bought) bypass the policy entirely: the strategy
returns ``current_price`` unchanged so the caller can issue a market
entry on slot 1.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from src.domain.models import Position, SplitSlot


class ReentryPriceStrategyPort(Protocol):
    """Trigger price calculator for an EMPTY slot.

    Returns:
        ``Decimal`` — the trigger price; caller fires the buy when
        ``current_price <= trigger``.
        ``None`` — data is insufficient (e.g., MA window not yet
        satisfied). Caller treats the slot as not evaluable and excludes
        it from buy consideration this evaluation.
    """

    def get_trigger_price(
        self,
        *,
        slot: SplitSlot,
        position: Position,
        current_price: Decimal,
        drop_threshold_pct: Decimal,
        as_of: date,
    ) -> Decimal | None:
        ...
