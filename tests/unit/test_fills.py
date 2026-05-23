"""Unit tests for src.domain.fills (Phase 1.1 Stage 8-2 / C3 carve-out).

``apply_buy_fill`` / ``apply_sell_fill`` are the shared pure functions that the
MockBroker (sync) and PendingSettler (async settle) both call, so split-level
transitions can never drift. These tests pin the pure behaviour AND prove the
MockBroker stays byte-identical after delegating to them.
"""
from __future__ import annotations

import random
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.adapters.mock.broker import MockBroker
from src.domain.exceptions import BrokerConnectionError
from src.domain.fills import apply_buy_fill, apply_sell_fill
from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    Market,
    Money,
    OrderRequest,
    OrderSide,
    OrderType,
    Position,
    SlotState,
    SplitEntry,
    SplitSlot,
)

NOW = datetime(2026, 5, 22, 6, 0, 0, tzinfo=UTC)  # 15:00 KST, in-session → date 05-22


def _asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _filled_position(asset: Asset, *, slot: int, qty: str, price: str) -> Position:
    entry = SplitEntry(
        split_number=slot,
        entry_date=NOW.date(),
        quantity=Decimal(qty),
        entry_price=Decimal(price),
        idempotency_key=f"seed-{slot}",
    )
    slots: list[SplitSlot] = []
    for i in range(1, 8):
        slots.append(
            SplitSlot.filled(entry=entry) if i == slot else SplitSlot.empty(slot_number=i)
        )
    return Position(
        asset=asset,
        quantity=Decimal(qty),
        avg_price=Decimal(price),
        split_level=1,
        last_buy_at=NOW,
        slots=slots,
    )


# ---------------------------------------------------------------------------
# apply_buy_fill (pure)
# ---------------------------------------------------------------------------
def test_apply_buy_fill_pure_domain_first_buy() -> None:
    a = _asset()
    pos = apply_buy_fill(
        existing=None,
        asset=a,
        filled_qty=Decimal("10"),
        filled_price=Decimal("35000"),
        now=NOW,
        idempotency_key="k1",
        max_split_count=7,
        slot_model=SplitSlot,
    )
    assert pos.split_level == 1
    assert pos.quantity == Decimal("10")
    assert pos.avg_price == Decimal("35000")
    # smallest EMPTY slot wins (slot 1)
    filled = pos.filled_slots
    assert len(filled) == 1
    assert filled[0].slot_number == 1
    assert filled[0].entry is not None
    assert filled[0].entry.idempotency_key == "k1"
    assert filled[0].entry.entry_date == NOW.date()
    assert pos.last_buy_at == NOW


def test_apply_buy_fill_targets_explicit_slot_and_preserves_last_exit() -> None:
    a = _asset()
    # slot 2 EMPTY but carrying exit history; target it explicitly.
    slots: list[SplitSlot] = [SplitSlot.empty(slot_number=1)]
    slots.append(
        SplitSlot.empty(
            slot_number=2,
            last_exit_price=Decimal("40000"),
            last_exit_date=date(2026, 5, 1),
        )
    )
    slots.extend(SplitSlot.empty(slot_number=i) for i in range(3, 8))
    existing = Position(
        asset=a, quantity=Decimal(0), avg_price=Decimal(0),
        split_level=0, last_buy_at=NOW, slots=slots,
    )
    pos = apply_buy_fill(
        existing=existing, asset=a, filled_qty=Decimal("5"),
        filled_price=Decimal("38000"), now=NOW, idempotency_key="k2",
        max_split_count=7, slot_model=SplitSlot, target_slot_number=2,
    )
    slot2 = pos.get_slot(2)
    assert slot2 is not None and slot2.state is SlotState.FILLED
    # last_exit_* history preserved across the refill (feeds reentry policy).
    assert slot2.last_exit_price == Decimal("40000")
    assert slot2.last_exit_date == date(2026, 5, 1)


def test_apply_buy_fill_does_not_mutate_existing() -> None:
    a = _asset()
    existing = _filled_position(a, slot=1, qty="10", price="35000")
    before = existing.model_dump()
    apply_buy_fill(
        existing=existing, asset=a, filled_qty=Decimal("10"),
        filled_price=Decimal("30000"), now=NOW, idempotency_key="k3",
        max_split_count=7, slot_model=SplitSlot,
    )
    assert existing.model_dump() == before  # input untouched (pure)


def test_apply_buy_fill_raises_when_target_not_empty() -> None:
    a = _asset()
    existing = _filled_position(a, slot=1, qty="10", price="35000")
    with pytest.raises(BrokerConnectionError):
        apply_buy_fill(
            existing=existing, asset=a, filled_qty=Decimal("10"),
            filled_price=Decimal("30000"), now=NOW, idempotency_key="k4",
            max_split_count=7, slot_model=SplitSlot, target_slot_number=1,
        )


# ---------------------------------------------------------------------------
# apply_sell_fill (pure)
# ---------------------------------------------------------------------------
def test_apply_sell_fill_pure_domain() -> None:
    a = _asset()
    existing = _filled_position(a, slot=1, qty="10", price="35000")
    pos = apply_sell_fill(
        existing=existing, asset=a, slot_number=1,
        filled_qty=Decimal("10"), filled_price=Decimal("40250"), now=NOW,
    )
    assert pos.split_level == 0
    assert pos.quantity == Decimal(0)
    slot1 = pos.get_slot(1)
    assert slot1 is not None and slot1.state is SlotState.EMPTY
    # last_exit recorded for HybridTimeBasedReentry.
    assert slot1.last_exit_price == Decimal("40250")
    assert slot1.last_exit_date == NOW.date()


def test_apply_sell_fill_raises_on_missing_position() -> None:
    with pytest.raises(BrokerConnectionError):
        apply_sell_fill(
            existing=None, asset=_asset(), slot_number=1,
            filled_qty=Decimal("10"), filled_price=Decimal("40000"), now=NOW,
        )


def test_apply_sell_fill_raises_on_non_filled_slot() -> None:
    a = _asset()
    existing = _filled_position(a, slot=1, qty="10", price="35000")
    with pytest.raises(BrokerConnectionError):
        apply_sell_fill(
            existing=existing, asset=a, slot_number=2,  # slot 2 is EMPTY
            filled_qty=Decimal("10"), filled_price=Decimal("40000"), now=NOW,
        )


def test_apply_sell_fill_raises_on_quantity_mismatch() -> None:
    a = _asset()
    existing = _filled_position(a, slot=1, qty="10", price="35000")
    with pytest.raises(BrokerConnectionError):
        apply_sell_fill(
            existing=existing, asset=a, slot_number=1,
            filled_qty=Decimal("5"), filled_price=Decimal("40000"), now=NOW,
        )


# ---------------------------------------------------------------------------
# MockBroker byte-identical after the carve-out
# ---------------------------------------------------------------------------
def _mock_clock() -> datetime:
    return NOW


def test_mock_broker_apply_fill_unchanged() -> None:
    """MockBroker buy then sell produce the expected Position after delegating
    to the shared fill functions (carve-out regression proof)."""
    a = _asset()
    broker = MockBroker(
        initial_balance=Balance(cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)),
        clock=_mock_clock,
        rng=random.Random(7),
    )
    buy = OrderRequest(
        idempotency_key="b1", asset=a, side=OrderSide.BUY,
        order_type=OrderType.LIMIT, quantity=Decimal("10"), target_price=Decimal("35000"),
    )
    broker.place_order(buy)
    pos = broker.get_positions()[0]
    assert pos.split_level == 1
    assert pos.quantity == Decimal("10")
    assert pos.get_slot(1) is not None and pos.get_slot(1).state is SlotState.FILLED  # type: ignore[union-attr]

    sell = OrderRequest(
        idempotency_key="s1", asset=a, side=OrderSide.SELL,
        order_type=OrderType.LIMIT, quantity=Decimal("10"), target_price=Decimal("40000"),
        slot_number=1,
    )
    broker.place_order(sell)
    assert broker.get_positions() == []  # fully sold → no non-empty positions
