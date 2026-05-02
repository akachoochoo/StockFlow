"""Tests for src.adapters.mock.broker.MockBroker."""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.adapters.mock.broker import MockBroker
from src.domain.constants import KST
from src.domain.exceptions import BrokerConnectionError
from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    Money,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)


def _asset(code: str = "069500", lot_size: str = "1") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal(lot_size),
    )


def _balance(amount: str = "100000000") -> Balance:
    return Balance(cash=Money(amount=Decimal(amount), currency=Currency.KRW))


def _request(
    asset: Asset,
    *,
    idempotency_key: str = "k1",
    quantity: str = "10",
    target_price: str = "35000",
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=idempotency_key,
        asset=asset,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(quantity),
        target_price=Decimal(target_price),
    )


class _FixedClock:
    """Callable returning successive UTC datetimes for deterministic timestamps."""

    def __init__(self, start: datetime, step: timedelta = timedelta(minutes=1)):
        self._now = start
        self._step = step

    def __call__(self) -> datetime:
        result = self._now
        self._now = self._now + self._step
        return result


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------
class TestConstruction:
    @pytest.mark.parametrize(
        "param",
        ["simulate_timeout_rate", "simulate_rejection_rate"],
    )
    def test_invalid_rate_rejected(self, param):
        kwargs = {"initial_balance": _balance(), "clock": lambda: UTC_NOW, param: 1.5}
        with pytest.raises(ValueError, match=param):
            MockBroker(**kwargs)

    def test_partial_fill_rate_must_be_zero(self):
        # ADR 0002 §3.2.1: Phase 0.5 blocks partial fills end-to-end.
        with pytest.raises(ValueError, match="simulate_partial_fill_rate"):
            MockBroker(
                initial_balance=_balance(),
                clock=lambda: UTC_NOW,
                simulate_partial_fill_rate=0.5,
            )

    def test_partial_fill_rate_zero_accepted(self):
        # 0.0 explicitly is the only allowed value.
        broker = MockBroker(
            initial_balance=_balance(),
            clock=lambda: UTC_NOW,
            simulate_partial_fill_rate=0.0,
        )
        assert broker.get_balance() == _balance()

    def test_max_split_count_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="max_split_count"):
            MockBroker(
                initial_balance=_balance(),
                clock=lambda: UTC_NOW,
                max_split_count=8,
            )

    def test_default_rng_used_when_not_provided(self):
        # Should not raise; default rng is created
        broker = MockBroker(initial_balance=_balance(), clock=lambda: UTC_NOW)
        assert broker.get_balance() == _balance()


# ---------------------------------------------------------------------------
# Default (no simulation): immediate FILLED
# ---------------------------------------------------------------------------
class TestDefaultFill:
    def test_place_order_fills_and_debits_balance(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        result = broker.place_order(_request(a, quantity="10", target_price="35000"))
        assert result.status is OrderStatus.FILLED
        assert result.filled_quantity == Decimal("10")
        assert result.filled_price == Decimal("35000")
        assert result.broker_order_id == "mock-1"
        assert result.asset == a
        # 10 * 35,000 = 350,000 debited
        assert broker.get_balance().cash.amount == Decimal("99650000")

    def test_first_fill_creates_position_with_split_level_one(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(_request(a, quantity="10", target_price="35000"))
        positions = broker.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p.asset == a
        assert p.quantity == Decimal("10")
        assert p.avg_price == Decimal("35000")
        assert p.split_level == 1

    def test_subsequent_fill_weighted_average(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, idempotency_key="k1", quantity="10", target_price="35000")
        )
        broker.place_order(
            _request(a, idempotency_key="k2", quantity="5", target_price="32000")
        )
        position = broker.get_positions()[0]
        # qty = 15, total cost = 350000 + 160000 = 510000, avg = 34000
        assert position.quantity == Decimal("15")
        assert position.avg_price == Decimal("34000")
        assert position.split_level == 2

    def test_idempotency_returns_prior_result_without_re_executing(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        req = _request(a, idempotency_key="dup", quantity="10", target_price="35000")
        first = broker.place_order(req)
        second = broker.place_order(req)
        assert first.broker_order_id == second.broker_order_id
        # Balance debited only once
        assert broker.get_balance().cash.amount == Decimal("99650000")
        # Only one order recorded
        assert len(broker.all_orders()) == 1


# ---------------------------------------------------------------------------
# Simulated rejection
# ---------------------------------------------------------------------------
class TestRejection:
    def test_rejection_at_rate_one(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_rejection_rate=1.0,
        )
        result = broker.place_order(_request(a))
        assert result.status is OrderStatus.REJECTED
        assert result.broker_order_id is None
        # Balance unchanged
        assert broker.get_balance() == _balance()
        # No position
        assert broker.get_positions() == []
        # But order is recorded for inspection
        assert len(broker.all_orders()) == 1


# ---------------------------------------------------------------------------
# Simulated timeout (CLAUDE.md §4.3 flow)
# ---------------------------------------------------------------------------
class TestTimeout:
    def test_timeout_raises_but_records_order_as_filled(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_timeout_rate=1.0,
        )
        req = _request(a, idempotency_key="t1", quantity="10", target_price="35000")
        with pytest.raises(BrokerConnectionError, match="timeout"):
            broker.place_order(req)
        # The order is FILLED internally — caller can recover via get_order_status
        recovered = broker.get_order_status("t1")
        assert recovered is not None
        assert recovered.status is OrderStatus.FILLED
        assert recovered.filled_quantity == Decimal("10")
        # Balance was debited (the order really happened)
        assert broker.get_balance().cash.amount == Decimal("99650000")
        # Position created
        assert len(broker.get_positions()) == 1

    def test_idempotent_after_timeout_recovery(self):
        # After timeout, retrying with same idempotency_key returns the
        # original FILLED result — no duplicate order.
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_timeout_rate=1.0,
        )
        req = _request(a, idempotency_key="t2")
        with pytest.raises(BrokerConnectionError):
            broker.place_order(req)
        # Retry with same idempotency_key
        result = broker.place_order(req)
        assert result.status is OrderStatus.FILLED
        assert len(broker.all_orders()) == 1


# ---------------------------------------------------------------------------
# Simulated partial fill (CLAUDE.md §4.4)
# ---------------------------------------------------------------------------
class TestPartialFillBlocked:
    """Phase 0.5 (ADR 0002 §3.2.1) blocks partial fills end-to-end.

    The constructor raises on any non-zero ``simulate_partial_fill_rate``;
    no test path can produce a PARTIALLY_FILLED OrderResult. Phase 1 KIS
    will reintroduce partial-fill handling with a slot-aware redesign.
    """

    def test_constructor_blocks_nonzero_rate(self):
        with pytest.raises(ValueError, match="simulate_partial_fill_rate"):
            MockBroker(
                initial_balance=_balance(),
                clock=lambda: UTC_NOW,
                simulate_partial_fill_rate=1.0,
            )


# ---------------------------------------------------------------------------
# get_order_status / cancel_order
# ---------------------------------------------------------------------------
class TestQueries:
    def test_get_order_status_returns_none_for_unknown_key(self):
        broker = MockBroker(initial_balance=_balance(), clock=lambda: UTC_NOW)
        assert broker.get_order_status("nonexistent") is None

    def test_cancel_order_returns_false_in_phase_0(self):
        # Phase 0 immediate-fill broker has nothing pending to cancel.
        broker = MockBroker(initial_balance=_balance(), clock=lambda: UTC_NOW)
        assert broker.cancel_order("mock-1") is False


# ---------------------------------------------------------------------------
# Insufficient cash safety net
# ---------------------------------------------------------------------------
class TestCashSafety:
    def test_oversized_order_raises_broker_connection_error(self):
        # Mock has a safety net — should never let balance go negative.
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100"),
            clock=_FixedClock(UTC_NOW),
        )
        req = _request(a, quantity="10", target_price="35000")  # cost = 350,000
        with pytest.raises(BrokerConnectionError, match="insufficient"):
            broker.place_order(req)


# ---------------------------------------------------------------------------
# SplitEntry recording on Position (ADR §7.5/§7.9)
# ---------------------------------------------------------------------------
class TestSlotRecording:
    """Phase 0.5 (ADR 0002 §3.1 / §4.4): each FILLED order lands in the
    smallest EMPTY slot; ``last_exit_*`` history is preserved across the
    refill so the HybridTimeBasedReentry policy can use it."""

    def test_first_fill_lands_in_slot_one(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, idempotency_key="k1", quantity="10", target_price="35000")
        )
        p = broker.get_positions()[0]
        assert len(p.slots) == 7
        assert p.split_level == 1
        slot1 = p.get_slot(1)
        assert slot1 is not None
        assert slot1.entry is not None
        assert slot1.entry.split_number == 1
        assert slot1.entry.quantity == Decimal("10")
        assert slot1.entry.entry_price == Decimal("35000")
        assert slot1.entry.idempotency_key == "k1"

    def test_subsequent_fill_lands_in_slot_two(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, idempotency_key="k1", quantity="10", target_price="35000")
        )
        broker.place_order(
            _request(a, idempotency_key="k2", quantity="5", target_price="32000")
        )
        p = broker.get_positions()[0]
        assert p.split_level == 2
        assert [s.slot_number for s in p.filled_slots] == [1, 2]
        slot2 = p.get_slot(2)
        assert slot2 is not None and slot2.entry is not None
        assert slot2.entry.quantity == Decimal("5")
        assert slot2.entry.entry_price == Decimal("32000")
        assert slot2.entry.idempotency_key == "k2"

    def test_idempotency_key_persists_on_filled_slot(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, idempotency_key="unique-key-99", quantity="10", target_price="35000")
        )
        p = broker.get_positions()[0]
        slot1 = p.get_slot(1)
        assert slot1 is not None and slot1.entry is not None
        assert slot1.entry.idempotency_key == "unique-key-99"

    def test_entry_date_uses_kst_business_date(self):
        # 06:00 UTC = 15:00 KST (within KRX hours; same calendar date both ways).
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),  # 2026-04-30 06:00 UTC = 15:00 KST
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, quantity="10", target_price="35000")
        )
        p = broker.get_positions()[0]
        slot1 = p.get_slot(1)
        assert slot1 is not None and slot1.entry is not None
        assert slot1.entry.entry_date == UTC_NOW.astimezone(KST).date()

    def test_seven_full_fills_reach_max_split(self):
        # All seven slots get FILLED; further buys would fail (no EMPTY slot).
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        for i in range(1, 8):
            broker.place_order(
                _request(a, idempotency_key=f"s{i}", quantity="1", target_price="1000")
            )
        p = broker.get_positions()[0]
        assert p.split_level == 7
        assert [s.slot_number for s in p.filled_slots] == [1, 2, 3, 4, 5, 6, 7]
        assert p.next_empty_slot_number() is None

    def test_eighth_fill_with_all_slots_filled_raises(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        for i in range(1, 8):
            broker.place_order(
                _request(a, idempotency_key=f"s{i}", quantity="1", target_price="1000")
            )
        with pytest.raises(BrokerConnectionError, match=r"all .* slots already FILLED"):
            broker.place_order(
                _request(a, idempotency_key="overflow", quantity="1", target_price="1000")
            )
