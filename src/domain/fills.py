"""Pure fill-application domain functions (Phase 1.1 Stage 8-2 / C3 carve-out).

``apply_buy_fill`` / ``apply_sell_fill`` compute the *new* :class:`Position`
that results from a fully-FILLED buy or sell against a single split slot. They
are pure: given an ``existing`` Position (or None for a first buy) plus the fill
economics they return a brand-new Position without mutating any input or
reading a clock (the fill instant ``now`` is injected, CLAUDE.md §3.2).

These are carved out of ``MockBroker._apply_buy_fill`` / ``_apply_sell_fill``
verbatim so that **two** call-sites share the *same* slot transition and can
never drift (ADR 0012 Stage 8 §3 Option B, C3):

  - the synchronous FILLED path inside ``MockBroker`` (backtest / paper), and
  - the asynchronous PENDING→FILLED settle path in ``PendingSettler`` (live).

The shared function is the structural guarantee against split_level drift →
reconciliation halt (CLAUDE.md §11.2). ``MockBroker`` keeps byte-identical
behaviour after the carve-out (its existing test suite is the regression
proof).

Slot-targeting / slot-state violations raise ``BrokerConnectionError`` — the
exact exception type ``MockBroker`` raised before the carve-out, preserved for
byte-identical behaviour. In the live settle path a raise aborts the settle
UoW (rollback) and propagates → the runner halts (Principle #3 불확실하면 멈춘다).

Pure domain (CLAUDE.md §1.1): stdlib + domain models/exceptions only.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, TypeAlias, cast

from src.domain.constants import KST
from src.domain.exceptions import BrokerConnectionError
from src.domain.models import (
    Position,
    SlotState,
    SplitEntry,
    SplitSlot,
    SupportSlot,
)

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.models import Asset

# Internal slot list type (ADR 0004 §5.6): heterogeneous in the type system,
# homogeneous at runtime per Position invariant. Cast back to the
# Position-facing union type at the construction boundary.
_Slot: TypeAlias = SplitSlot | SupportSlot
_SlotsList: TypeAlias = "list[SplitSlot] | list[SupportSlot]"


def apply_buy_fill(
    *,
    existing: Position | None,
    asset: Asset,
    filled_qty: Decimal,
    filled_price: Decimal,
    now: datetime,
    idempotency_key: str,
    max_split_count: int,
    slot_model: type[SplitSlot] | type[SupportSlot],
    target_slot_number: int | None = None,
) -> Position:
    """Return the Position after applying a fully-filled BUY into a slot.

    ADR 0002 §3.1 / §4.4 / §5.9.3. When ``target_slot_number`` is provided
    (Phase 0.5 sells-then-buys cascade, and Phase 1.1 settle which recovers the
    slot from the idempotency_key) that exact slot is filled — the strategy's
    choice authoritative. When None (Phase 0 / paper-trading first buy with no
    cascade), fall back to "smallest EMPTY slot wins" deterministic allocation.
    Existing slots' ``last_exit_*`` history is preserved when the slot is
    refilled — that history feeds the HybridTimeBasedReentry policy.

    ``existing`` is None for the first buy of an asset (a fresh slot ladder of
    ``max_split_count`` EMPTY ``slot_model`` slots is created). The input
    Position is never mutated.
    """
    slots: list[_Slot]
    if existing is None:
        slots = [
            slot_model.empty(slot_number=i)
            for i in range(1, max_split_count + 1)
        ]
    else:
        slots = cast("list[_Slot]", list(existing.slots))

    target_idx: int | None = None
    if target_slot_number is not None:
        for i, s in enumerate(slots):
            if s.slot_number == target_slot_number:
                if s.state is not SlotState.EMPTY:
                    raise BrokerConnectionError(
                        f"BUY targets slot {target_slot_number} on "
                        f"{asset.fqn} but slot is "
                        f"{s.state.value}, not EMPTY"
                    )
                target_idx = i
                break
        if target_idx is None:
            raise BrokerConnectionError(
                f"BUY targets slot {target_slot_number} on {asset.fqn} "
                f"but slot does not exist (slots: "
                f"{[s.slot_number for s in slots]})"
            )
    else:
        for i, s in enumerate(slots):
            if s.state is SlotState.EMPTY:
                target_idx = i
                break
        if target_idx is None:
            raise BrokerConnectionError(
                f"all {len(slots)} slots already FILLED for {asset.fqn}; "
                "refusing to place buy without first selling a slot"
            )

    target_slot = slots[target_idx]
    # KRX session is fully inside one UTC date (KST=UTC+9, hours
    # 09:00-15:30 KST = 00:00-06:30 UTC), so KST date == UTC date for
    # any in-session timestamp. Convert explicitly to keep the
    # business-date semantic intact for off-hours fixtures.
    new_entry = SplitEntry(
        split_number=target_slot.slot_number,
        entry_date=now.astimezone(KST).date(),
        quantity=filled_qty,
        entry_price=filled_price,
        idempotency_key=idempotency_key,
    )
    # Preserve slot model (ADR 0004 §5.6 — homogeneous list per Position).
    existing_slot_model = type(target_slot)
    slots[target_idx] = existing_slot_model(
        slot_number=target_slot.slot_number,
        state=SlotState.FILLED,
        entry=new_entry,
        last_exit_price=target_slot.last_exit_price,
        last_exit_date=target_slot.last_exit_date,
    )

    filled = [s for s in slots if s.state is SlotState.FILLED]
    new_qty = sum(
        (s.entry.quantity for s in filled if s.entry is not None),
        Decimal(0),
    )
    total_cost = sum(
        (
            s.entry.quantity * s.entry.entry_price
            for s in filled
            if s.entry is not None
        ),
        Decimal(0),
    )
    new_avg = total_cost / new_qty
    new_split_level = len(filled)

    return Position(
        asset=asset,
        quantity=new_qty,
        avg_price=new_avg,
        split_level=new_split_level,
        last_buy_at=now,
        slots=cast("_SlotsList", slots),
    )


def apply_sell_fill(
    *,
    existing: Position | None,
    asset: Asset,
    slot_number: int,
    filled_qty: Decimal,
    filled_price: Decimal,
    now: datetime,
) -> Position:
    """Return the Position after closing a single FILLED slot via a SELL.

    ADR 0002 §5.7 / §3.2.1 — Phase 0.5 sells whole slots only. Validates:
    position exists, target slot is FILLED, request quantity matches the slot's
    entry quantity exactly. On success the slot transitions FILLED → EMPTY and
    records ``last_exit_price`` / ``last_exit_date`` for HybridTimeBasedReentry
    to use. ``split_level`` decreases. The input Position is never mutated.
    """
    if existing is None:
        raise BrokerConnectionError(
            f"no position for {asset.fqn} — cannot SELL"
        )
    slots: list[_Slot] = cast("list[_Slot]", list(existing.slots))
    target_idx: int | None = next(
        (i for i, s in enumerate(slots) if s.slot_number == slot_number),
        None,
    )
    if target_idx is None:
        raise BrokerConnectionError(
            f"slot_number={slot_number} not found on {asset.fqn} "
            f"(slots: {[s.slot_number for s in slots]})"
        )
    target_slot = slots[target_idx]
    if target_slot.state is not SlotState.FILLED:
        raise BrokerConnectionError(
            f"slot_number={slot_number} on {asset.fqn} is "
            f"{target_slot.state.value}, not FILLED — cannot SELL"
        )
    assert target_slot.entry is not None  # FILLED invariant
    if filled_qty != target_slot.entry.quantity:
        raise BrokerConnectionError(
            f"SELL quantity {filled_qty} does not match slot "
            f"{slot_number} entry quantity ({target_slot.entry.quantity}); "
            "Phase 0.5 sells whole slots only (ADR 0002 §3.2.1)"
        )

    # Preserve slot model (ADR 0004 §5.6 — homogeneous list per Position).
    existing_slot_model = type(target_slot)
    slots[target_idx] = existing_slot_model(
        slot_number=target_slot.slot_number,
        state=SlotState.EMPTY,
        entry=None,
        last_exit_price=filled_price,
        last_exit_date=now.astimezone(KST).date(),
    )

    filled = [s for s in slots if s.state is SlotState.FILLED]
    if filled:
        new_qty = sum(
            (s.entry.quantity for s in filled if s.entry is not None),
            Decimal(0),
        )
        total_cost = sum(
            (
                s.entry.quantity * s.entry.entry_price
                for s in filled
                if s.entry is not None
            ),
            Decimal(0),
        )
        new_avg = total_cost / new_qty
    else:
        # Last slot sold — empty position. Keep last_buy_at as historical
        # marker (Position invariant only requires last_buy_at when qty>0).
        new_qty = Decimal(0)
        new_avg = Decimal(0)
    new_split_level = len(filled)

    return Position(
        asset=asset,
        quantity=new_qty,
        avg_price=new_avg,
        split_level=new_split_level,
        last_buy_at=existing.last_buy_at,
        slots=cast("_SlotsList", slots),
    )


__all__ = ["apply_buy_fill", "apply_sell_fill"]
