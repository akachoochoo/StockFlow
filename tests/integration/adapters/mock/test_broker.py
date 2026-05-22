"""Tests for src.adapters.mock.broker.MockBroker."""
from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.adapters.mock.broker import MockBroker
from src.domain.constants import KST
from src.domain.exceptions import BrokerConnectionError
from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    BrokerHolding,
    Currency,
    Exchange,
    Market,
    Money,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    SlotState,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)


def _asset(code: str = "069500", lot_size: str = "1") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal(lot_size),
        listed_at=date(2002, 10, 14),
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


def _sell_request(
    asset: Asset,
    *,
    slot_number: int,
    quantity: str,
    target_price: str,
    idempotency_key: str = "sell-1",
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=idempotency_key,
        asset=asset,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal(quantity),
        target_price=Decimal(target_price),
        slot_number=slot_number,
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
# get_holdings — reconciliation 대조용 (Phase 1.1 Stage 3.3)
# ---------------------------------------------------------------------------
class TestGetHoldings:
    """get_holdings mirrors get_positions but as the aggregated
    BrokerHolding view (code + quantity + avg_price, no split-slot)."""

    def test_get_holdings_empty_when_no_positions(self):
        broker = MockBroker(initial_balance=_balance(), clock=_FixedClock(UTC_NOW))
        assert broker.get_holdings() == []

    def test_get_holdings_maps_filled_position(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(), clock=_FixedClock(UTC_NOW)
        )
        broker.place_order(
            _request(a, quantity="10", target_price="35000")
        )
        holdings = broker.get_holdings()
        assert holdings == [
            BrokerHolding(
                asset_code="069500",
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
            )
        ]

    def test_get_holdings_multiple_symbols(self):
        a = _asset(code="069500")
        b = _asset(code="005930")
        broker = MockBroker(
            initial_balance=_balance(), clock=_FixedClock(UTC_NOW)
        )
        broker.place_order(
            _request(a, idempotency_key="ka", quantity="10", target_price="35000")
        )
        broker.place_order(
            _request(b, idempotency_key="kb", quantity="7", target_price="71500")
        )
        holdings = broker.get_holdings()
        by_code = {h.asset_code: h for h in holdings}
        assert set(by_code) == {"069500", "005930"}
        assert by_code["069500"].quantity == Decimal("10")
        assert by_code["005930"].quantity == Decimal("7")

    def test_get_holdings_excludes_fully_sold_position(self):
        """A position sold down to quantity 0 must not appear (qty > 0 filter)."""
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(), clock=_FixedClock(UTC_NOW)
        )
        broker.place_order(
            _request(a, quantity="10", target_price="35000")
        )
        broker.place_order(
            _sell_request(
                a, slot_number=1, quantity="10", target_price="36000"
            )
        )
        # Sold-out position is gone from both views.
        assert broker.get_positions() == []
        assert broker.get_holdings() == []

    def test_get_holdings_quantity_and_price_are_decimal(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(), clock=_FixedClock(UTC_NOW)
        )
        broker.place_order(
            _request(a, quantity="10", target_price="35000")
        )
        holding = broker.get_holdings()[0]
        assert isinstance(holding.quantity, Decimal)
        assert isinstance(holding.avg_price, Decimal)


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


# ---------------------------------------------------------------------------
# SELL handling (Phase 0.5 / ADR 0002 §5.7)
# ---------------------------------------------------------------------------
class TestSell:
    """Whole-slot SELL: cash credit + slot EMPTY + last_exit_* recorded."""

    def _seed_two_buys(self, broker: MockBroker, asset: Asset) -> None:
        broker.place_order(
            _request(asset, idempotency_key="b1", quantity="10", target_price="30000")
        )
        broker.place_order(
            _request(asset, idempotency_key="b2", quantity="10", target_price="32000")
        )

    def test_sell_credits_cash_and_empties_slot(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        self._seed_two_buys(broker, a)
        # cash after 2 buys = 10000000 - 10*30000 - 10*32000 = 9380000
        assert broker.get_balance().cash.amount == Decimal("9380000")

        result = broker.place_order(
            _sell_request(a, slot_number=1, quantity="10", target_price="33000")
        )
        assert result.status is OrderStatus.FILLED
        assert result.filled_quantity == Decimal("10")
        assert result.filled_price == Decimal("33000")

        # cash after sell = 9380000 + 10*33000 = 9710000
        assert broker.get_balance().cash.amount == Decimal("9710000")

        p = broker.get_positions()[0]
        assert p.split_level == 1
        assert p.quantity == Decimal("10")
        slot1 = p.get_slot(1)
        assert slot1 is not None
        assert slot1.state is SlotState.EMPTY
        assert slot1.last_exit_price == Decimal("33000")
        assert slot1.last_exit_date == UTC_NOW.astimezone(KST).date()
        # slot 2 still FILLED
        slot2 = p.get_slot(2)
        assert slot2 is not None and slot2.entry is not None
        assert slot2.entry.entry_price == Decimal("32000")

    def test_sell_recomputes_avg_price(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        self._seed_two_buys(broker, a)
        # Pre-sell avg = (10*30000 + 10*32000) / 20 = 31000
        assert broker.get_positions()[0].avg_price == Decimal("31000")

        broker.place_order(
            _sell_request(a, slot_number=1, quantity="10", target_price="33000")
        )
        # Only slot 2 (10 @ 32000) remains → avg = 32000
        assert broker.get_positions()[0].avg_price == Decimal("32000")

    def test_sell_last_slot_returns_empty_position(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, idempotency_key="b1", quantity="10", target_price="30000")
        )
        broker.place_order(
            _sell_request(a, slot_number=1, quantity="10", target_price="33000")
        )
        # All slots EMPTY → no positions returned (get_positions filters qty>0)
        assert broker.get_positions() == []

    def test_sell_idempotency_returns_prior_result(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        self._seed_two_buys(broker, a)
        req = _sell_request(
            a, slot_number=1, quantity="10", target_price="33000",
            idempotency_key="dup-sell",
        )
        first = broker.place_order(req)
        cash_after_first = broker.get_balance().cash.amount
        second = broker.place_order(req)
        assert first.broker_order_id == second.broker_order_id
        # Cash credited only once
        assert broker.get_balance().cash.amount == cash_after_first

    def test_sell_unknown_position_raises(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance(),
            clock=_FixedClock(UTC_NOW),
        )
        with pytest.raises(BrokerConnectionError, match=r"no position"):
            broker.place_order(
                _sell_request(a, slot_number=1, quantity="10", target_price="33000")
            )

    def test_sell_empty_slot_raises(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, idempotency_key="b1", quantity="10", target_price="30000")
        )
        with pytest.raises(BrokerConnectionError, match=r"EMPTY"):
            broker.place_order(
                _sell_request(a, slot_number=2, quantity="10", target_price="33000")
            )

    def test_sell_quantity_mismatch_raises(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        broker.place_order(
            _request(a, idempotency_key="b1", quantity="10", target_price="30000")
        )
        with pytest.raises(BrokerConnectionError, match=r"does not match slot"):
            broker.place_order(
                _sell_request(a, slot_number=1, quantity="5", target_price="33000")
            )

    def test_sell_then_buy_refills_smallest_empty(self):
        # After selling slot 1, the next BUY refills slot 1 (smallest EMPTY)
        # and inherits the slot's last_exit_* history.
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
        )
        self._seed_two_buys(broker, a)
        broker.place_order(
            _sell_request(a, slot_number=1, quantity="10", target_price="33000")
        )
        broker.place_order(
            _request(a, idempotency_key="b3", quantity="8", target_price="29000")
        )
        p = broker.get_positions()[0]
        slot1 = p.get_slot(1)
        assert slot1 is not None and slot1.entry is not None
        assert slot1.state is SlotState.FILLED
        assert slot1.entry.entry_price == Decimal("29000")
        # last_exit_* preserved across the refill
        assert slot1.last_exit_price == Decimal("33000")
        assert slot1.last_exit_date == UTC_NOW.astimezone(KST).date()

    def test_sell_rejection_preserves_state(self):
        a = _asset()
        broker = MockBroker(
            initial_balance=_balance("10000000"),
            clock=_FixedClock(UTC_NOW),
            rng=random.Random(42),
            simulate_rejection_rate=1.0,
        )
        # Reset rate to 0 to seed the buy without rejection.
        broker._rejection_rate = 0.0
        broker.place_order(
            _request(a, idempotency_key="b1", quantity="10", target_price="30000")
        )
        cash_before = broker.get_balance().cash.amount
        broker._rejection_rate = 1.0
        result = broker.place_order(
            _sell_request(a, slot_number=1, quantity="10", target_price="33000")
        )
        assert result.status is OrderStatus.REJECTED
        # No state mutation
        assert broker.get_balance().cash.amount == cash_before
        slot1 = broker.get_positions()[0].get_slot(1)
        assert slot1 is not None
        assert slot1.state is SlotState.FILLED
