"""Idempotency-key construction & parsing (Phase 1.1 Stage 8-2).

The system encodes the target *slot* inside every order's
``idempotency_key`` (CLAUDE.md §4.1):

    BUY:  "{asset_fqn}:{date}:buy:{slot_number}"
    SELL: "{asset_fqn}:{date}:sell:{slot_number}"

where ``asset_fqn = "{exchange}:{code}"`` (exactly one colon — KRX codes are
digit-only) and ``date`` is an ISO date (no colons). So a well-formed key has
exactly **five** ``:``-delimited segments and the slot is the last.

This module is the **single source of truth** for that format: the
orchestrator's :meth:`DailyOrchestrator._buy_idempotency_key` /
``_sell_idempotency_key`` build keys through :func:`build_order_key`, and the
Phase 1.1 async-settlement use-case (``PendingSettler``) recovers the slot via
:func:`parse_order_key`. The persisted :class:`~src.domain.models.Order` does
NOT carry ``slot_number`` (it lives only on the transient ``OrderRequest``;
``Order.from_request_result`` drops it), and G2(d) equivalence compares
``buy_action.slot_number`` (``decision_equivalence.decision_projection``), so
settle MUST recover the *exact* intended slot.

:func:`parse_order_key` is **strict**: any deviation from the canonical format
raises :class:`OrderKeyError` rather than guessing — a malformed key must halt
the caller, never silently mis-assign a money-affecting slot (CLAUDE.md §5 /
§6.3 침묵의 실패 금지, Principle #3 불확실하면 멈춘다).

Pure domain (CLAUDE.md §1.1): stdlib + domain models only. No clock, no IO.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.models import OrderSide

_BUY_TOKEN = "buy"
_SELL_TOKEN = "sell"
_SIDE_TO_TOKEN: dict[OrderSide, str] = {
    OrderSide.BUY: _BUY_TOKEN,
    OrderSide.SELL: _SELL_TOKEN,
}
_TOKEN_TO_SIDE: dict[str, OrderSide] = {
    _BUY_TOKEN: OrderSide.BUY,
    _SELL_TOKEN: OrderSide.SELL,
}
_EXPECTED_SEGMENTS = 5
_MIN_SLOT = 1
_MAX_SLOT = 7


class OrderKeyError(ValueError):
    """An idempotency_key does not match the canonical format.

    Raised by :func:`parse_order_key`. A money-critical parse failure: the
    caller (``PendingSettler``) must halt rather than guess a slot
    (CLAUDE.md §6.3 — no silent failure).
    """


@dataclass(frozen=True)
class ParsedOrderKey:
    """The slot-bearing fields recovered from an idempotency_key."""

    asset_fqn: str
    trade_date: date
    side: OrderSide
    slot_number: int


def build_order_key(
    *,
    asset_fqn: str,
    date_iso: str,
    side: OrderSide,
    slot_number: int,
) -> str:
    """Build the canonical idempotency_key for an order.

    ``date_iso`` is the ISO trade date (``today.isoformat()``). Mirrors the
    orchestrator's historical format exactly so existing keys stay
    byte-identical.
    """
    if not _MIN_SLOT <= slot_number <= _MAX_SLOT:
        raise OrderKeyError(
            f"slot_number must be in [{_MIN_SLOT}, {_MAX_SLOT}], "
            f"got {slot_number}"
        )
    return f"{asset_fqn}:{date_iso}:{_SIDE_TO_TOKEN[side]}:{slot_number}"


def parse_order_key(key: str) -> ParsedOrderKey:
    """Recover (asset_fqn, trade_date, side, slot_number) from ``key``.

    Strict: raises :class:`OrderKeyError` on any deviation from the canonical
    five-segment format — never guesses a slot.
    """
    parts = key.split(":")
    if len(parts) != _EXPECTED_SEGMENTS:
        raise OrderKeyError(
            f"idempotency_key must have {_EXPECTED_SEGMENTS} ':'-segments "
            f"('{{exchange}}:{{code}}:{{date}}:{{side}}:{{slot}}'), "
            f"got {len(parts)} in {key!r}"
        )
    exchange, code, date_iso, side_token, slot_token = parts

    side = _TOKEN_TO_SIDE.get(side_token)
    if side is None:
        raise OrderKeyError(
            f"side segment must be one of {sorted(_TOKEN_TO_SIDE)}, "
            f"got {side_token!r} in {key!r}"
        )

    try:
        trade_date = date.fromisoformat(date_iso)
    except ValueError as exc:
        raise OrderKeyError(
            f"date segment {date_iso!r} is not an ISO date in {key!r}"
        ) from exc

    try:
        slot_number = int(slot_token)
    except ValueError as exc:
        raise OrderKeyError(
            f"slot segment {slot_token!r} is not an integer in {key!r}"
        ) from exc
    if not _MIN_SLOT <= slot_number <= _MAX_SLOT:
        raise OrderKeyError(
            f"slot_number must be in [{_MIN_SLOT}, {_MAX_SLOT}], "
            f"got {slot_number} in {key!r}"
        )

    return ParsedOrderKey(
        asset_fqn=f"{exchange}:{code}",
        trade_date=trade_date,
        side=side,
        slot_number=slot_number,
    )


__all__ = [
    "OrderKeyError",
    "ParsedOrderKey",
    "build_order_key",
    "parse_order_key",
]
