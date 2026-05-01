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
        ["simulate_timeout_rate", "simulate_rejection_rate", "simulate_partial_fill_rate"],
    )
    def test_invalid_rate_rejected(self, param):
        kwargs = {"initial_balance": _balance(), "clock": lambda: UTC_NOW, param: 1.5}
        with pytest.raises(ValueError, match=param):
            MockBroker(**kwargs)

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
class TestPartialFill:
    def test_partial_fill_at_rate_one(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("100000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_partial_fill_rate=1.0,
        )
        result = broker.place_order(
            _request(a, quantity="10", target_price="35000")
        )
        # Half rounded down to lot_size = 5
        assert result.status is OrderStatus.PARTIALLY_FILLED
        assert result.filled_quantity == Decimal("5")
        # Position updated, but split_level stays at 0 (per CLAUDE.md §4.4)
        position = broker.get_positions()[0]
        assert position.quantity == Decimal("5")
        assert position.split_level == 0

    def test_partial_fill_falls_through_to_filled_when_unachievable(self):
        # When request.quantity is below lot_size threshold for partial,
        # fall through to FILLED.
        a = _asset(lot_size="1")
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_partial_fill_rate=1.0,
        )
        # quantity=1 → half=0 → not achievable → falls through to FILLED
        result = broker.place_order(_request(a, quantity="1"))
        assert result.status is OrderStatus.FILLED
        assert result.filled_quantity == Decimal("1")

    def test_partial_then_full_keeps_split_level_correct(self):
        # 1st: partial → split_level stays 0
        # 2nd: full   → split_level becomes 1 (counts as the first complete split)
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_partial_fill_rate=1.0,
        )
        broker.place_order(
            _request(a, idempotency_key="p1", quantity="10", target_price="35000")
        )
        # Reset partial rate so next call is full fill
        broker._partial_fill_rate = 0.0  # test-only access
        broker.place_order(
            _request(a, idempotency_key="p2", quantity="10", target_price="34000")
        )
        position = broker.get_positions()[0]
        # qty = 5 (partial) + 10 (full) = 15
        # cost = 5*35000 + 10*34000 = 175000 + 340000 = 515000
        # avg = 515000 / 15 = 34333.33...
        assert position.quantity == Decimal("15")
        assert position.split_level == 1  # only the full fill counted


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
class TestSplitEntryRecording:
    def test_first_fill_records_split_entry(self):
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
        assert len(p.entries) == 1
        e = p.entries[0]
        assert e.split_number == 1
        assert e.quantity == Decimal("10")
        assert e.entry_price == Decimal("35000")
        assert e.idempotency_key == "k1"

    def test_subsequent_fill_appends_split_entry(self):
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
        assert [e.split_number for e in p.entries] == [1, 2]
        assert p.entries[1].quantity == Decimal("5")
        assert p.entries[1].entry_price == Decimal("32000")
        assert p.entries[1].idempotency_key == "k2"
        assert p.has_pending_partial() is False

    def test_partial_fill_does_not_create_split_entry(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_partial_fill_rate=1.0,
        )
        broker.place_order(
            _request(a, idempotency_key="p1", quantity="10", target_price="35000")
        )
        p = broker.get_positions()[0]
        # No split entry created on partial; entries stay empty
        assert p.entries == []
        assert p.split_level == 0
        # The partial 5-share fill is exposed via pending_partial_quantity
        assert p.pending_partial_quantity == Decimal("5")
        assert p.has_pending_partial() is True

    def test_partial_then_full_only_full_appears_in_entries(self):
        # Partial leaves pending_partial; subsequent full only adds 1 entry
        # (CLAUDE.md §4.4 / ADR §7.5 — partial is never retroactively promoted).
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_partial_fill_rate=1.0,
        )
        broker.place_order(
            _request(a, idempotency_key="p1", quantity="10", target_price="35000")
        )
        broker._partial_fill_rate = 0.0
        broker.place_order(
            _request(a, idempotency_key="p2", quantity="10", target_price="34000")
        )
        p = broker.get_positions()[0]
        # Only the full fill became a SplitEntry
        assert len(p.entries) == 1
        assert p.entries[0].split_number == 1
        assert p.entries[0].quantity == Decimal("10")
        assert p.entries[0].entry_price == Decimal("34000")
        assert p.entries[0].idempotency_key == "p2"
        # Partial 5 still pending on top of 10 in entries → quantity = 15
        assert p.quantity == Decimal("15")
        assert p.pending_partial_quantity == Decimal("5")

    def test_split_entry_idempotency_key_matches_request(self):
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
        assert p.entries[0].idempotency_key == "unique-key-99"

    def test_split_entry_entry_date_uses_kst_business_date(self):
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
        assert p.entries[0].entry_date == UTC_NOW.astimezone(KST).date()

    def test_seven_full_fills_reach_max_split(self):
        # Position invariant caps split_level at 7 (Field le=7). Seven full
        # fills land at split_level=7 with seven entries.
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
        assert [e.split_number for e in p.entries] == [1, 2, 3, 4, 5, 6, 7]
        # No pending partial
        assert p.pending_partial_quantity == Decimal(0)
