"""Unit tests for src.domain.order_keys (Phase 1.1 Stage 8-2).

The idempotency_key is the single source that encodes the target slot; the
async-settlement use-case recovers slot_number from it, so the parser must be
strict (halt, never guess) and the builder must stay byte-identical to the
orchestrator's historical format.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.domain.models import OrderSide
from src.domain.order_keys import (
    OrderKeyError,
    build_order_key,
    parse_order_key,
)

_FQN = "KRX:069500"
_DAY = date(2026, 5, 22)


def test_build_order_key_matches_orchestrator_historical_format() -> None:
    # Byte-identical to DailyOrchestrator's legacy f-string (single source).
    assert build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, slot_number=3
    ) == f"{_FQN}:{_DAY.isoformat()}:buy:3"
    assert build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.SELL, slot_number=7
    ) == f"{_FQN}:{_DAY.isoformat()}:sell:7"


def test_build_rejects_out_of_range_slot() -> None:
    for bad in (0, 8, -1):
        with pytest.raises(OrderKeyError):
            build_order_key(
                asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, slot_number=bad
            )


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
@pytest.mark.parametrize("slot", [1, 4, 7])
def test_parse_round_trips_build(side: OrderSide, slot: int) -> None:
    key = build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=side, slot_number=slot
    )
    parsed = parse_order_key(key)
    assert parsed.asset_fqn == _FQN
    assert parsed.trade_date == _DAY
    assert parsed.side is side
    assert parsed.slot_number == slot


def test_parse_recovers_slot_from_orchestrator_format() -> None:
    # Exactly the orchestrator's emitted format (not via build_order_key).
    parsed = parse_order_key(f"{_FQN}:2026-05-22:sell:5")
    assert parsed.side is OrderSide.SELL
    assert parsed.slot_number == 5
    assert parsed.asset_fqn == _FQN


def test_parse_rejects_wrong_segment_count() -> None:
    for bad in ("KRX:069500:2026-05-22:buy", "KRX:069500:2026-05-22:buy:1:extra", "nope"):
        with pytest.raises(OrderKeyError):
            parse_order_key(bad)


def test_parse_rejects_unknown_side() -> None:
    with pytest.raises(OrderKeyError):
        parse_order_key(f"{_FQN}:2026-05-22:hold:1")


def test_parse_rejects_non_integer_slot() -> None:
    with pytest.raises(OrderKeyError):
        parse_order_key(f"{_FQN}:2026-05-22:buy:x")


def test_parse_rejects_out_of_range_slot() -> None:
    for bad in ("0", "8", "-1"):
        with pytest.raises(OrderKeyError):
            parse_order_key(f"{_FQN}:2026-05-22:buy:{bad}")


def test_parse_rejects_bad_date() -> None:
    with pytest.raises(OrderKeyError):
        parse_order_key(f"{_FQN}:not-a-date:buy:1")
