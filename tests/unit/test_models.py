"""Unit tests for src.domain.models.

Per CLAUDE.md §7, domain logic targets 100% coverage. Pure logic — no mocks.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Balance,
    CircuitBreakerSignal,
    Currency,
    Decision,
    Exchange,
    Money,
    Order,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Price,
    SignalLevel,
    SignalSource,
    SplitEntry,
)

# ---------------------------------------------------------------------------
# Common test fixtures (plain helpers, not pytest fixtures, for explicitness)
# ---------------------------------------------------------------------------
UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
UTC_LATER = datetime(2026, 4, 30, 7, 0, 0, tzinfo=UTC)


def make_asset(code: str = "069500", name: str = "KODEX 200") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name=name,
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
class TestMoney:
    def test_construct_from_decimal(self):
        m = Money(amount=Decimal("1000.50"), currency=Currency.KRW)
        assert m.amount == Decimal("1000.50")
        assert m.currency is Currency.KRW

    def test_construct_from_string(self):
        m = Money(amount="1000.50", currency=Currency.KRW)
        assert m.amount == Decimal("1000.50")

    def test_construct_from_int(self):
        m = Money(amount=1000, currency=Currency.KRW)
        assert m.amount == Decimal(1000)

    def test_reject_float_amount(self):
        with pytest.raises(ValidationError):
            Money(amount=1000.5, currency=Currency.KRW)

    def test_reject_bool_amount(self):
        with pytest.raises(ValidationError):
            Money(amount=True, currency=Currency.KRW)

    def test_reject_invalid_amount_type(self):
        with pytest.raises(ValidationError):
            Money(amount=[1, 2], currency=Currency.KRW)

    def test_immutable(self):
        m = Money(amount=Decimal("100"), currency=Currency.KRW)
        with pytest.raises(ValidationError):
            m.amount = Decimal("200")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            Money(amount=Decimal("100"), currency=Currency.KRW, extra="x")

    def test_equality_and_hash(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        b = Money(amount=Decimal("100"), currency=Currency.KRW)
        c = Money(amount=Decimal("101"), currency=Currency.KRW)
        assert a == b
        assert hash(a) == hash(b)
        assert a != c

    def test_addition_same_currency(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        b = Money(amount=Decimal("250"), currency=Currency.KRW)
        c = a + b
        assert c.amount == Decimal("350")
        assert c.currency is Currency.KRW

    def test_addition_currency_mismatch(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        b = Money(amount=Decimal("1"), currency=Currency.USD)
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = a + b

    def test_subtraction_same_currency(self):
        a = Money(amount=Decimal("250"), currency=Currency.KRW)
        b = Money(amount=Decimal("100"), currency=Currency.KRW)
        c = a - b
        assert c.amount == Decimal("150")

    def test_subtraction_currency_mismatch(self):
        a = Money(amount=Decimal("250"), currency=Currency.KRW)
        b = Money(amount=Decimal("1"), currency=Currency.USD)
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = a - b

    def test_multiplication_by_int(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        c = a * 3
        assert c.amount == Decimal("300")
        assert c.currency is Currency.KRW

    def test_multiplication_by_decimal(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        c = a * Decimal("2.5")
        assert c.amount == Decimal("250.0")

    def test_reverse_multiplication(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        c = 3 * a
        assert c.amount == Decimal("300")

    def test_reject_float_multiplication(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        with pytest.raises(TypeError, match="float"):
            _ = a * 2.5

    def test_reject_bool_multiplication(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        with pytest.raises(TypeError, match="bool"):
            _ = a * True

    def test_reject_str_multiplication(self):
        a = Money(amount=Decimal("100"), currency=Currency.KRW)
        with pytest.raises(TypeError):
            _ = a * "3"


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------
class TestAsset:
    def test_construct_happy_path(self):
        a = make_asset()
        assert a.code == "069500"
        assert a.exchange is Exchange.KRX
        assert a.asset_class is AssetClass.KR_ETF
        assert a.currency is Currency.KRW
        assert a.name == "KODEX 200"
        assert a.tick_size == Decimal("5")
        assert a.lot_size == Decimal("1")

    def test_fqn_property(self):
        a = make_asset(code="069500")
        assert a.fqn == "KRX:069500"

    def test_fqn_serializes_in_dump(self):
        a = make_asset()
        dumped = a.model_dump()
        assert dumped["fqn"] == "KRX:069500"

    def test_default_lot_size(self):
        a = Asset(
            code="069500",
            exchange=Exchange.KRX,
            asset_class=AssetClass.KR_ETF,
            currency=Currency.KRW,
            name="KODEX 200",
            tick_size=Decimal("5"),
        )
        assert a.lot_size == Decimal(1)

    def test_empty_code_rejected(self):
        with pytest.raises(ValidationError):
            Asset(
                code="",
                exchange=Exchange.KRX,
                asset_class=AssetClass.KR_ETF,
                currency=Currency.KRW,
                name="x",
                tick_size=Decimal("5"),
            )

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            Asset(
                code="069500",
                exchange=Exchange.KRX,
                asset_class=AssetClass.KR_ETF,
                currency=Currency.KRW,
                name="",
                tick_size=Decimal("5"),
            )

    def test_zero_tick_size_rejected(self):
        with pytest.raises(ValidationError):
            Asset(
                code="069500",
                exchange=Exchange.KRX,
                asset_class=AssetClass.KR_ETF,
                currency=Currency.KRW,
                name="x",
                tick_size=Decimal("0"),
            )

    def test_negative_tick_size_rejected(self):
        with pytest.raises(ValidationError):
            Asset(
                code="069500",
                exchange=Exchange.KRX,
                asset_class=AssetClass.KR_ETF,
                currency=Currency.KRW,
                name="x",
                tick_size=Decimal("-1"),
            )

    def test_float_tick_size_rejected(self):
        with pytest.raises(ValidationError):
            Asset(
                code="069500",
                exchange=Exchange.KRX,
                asset_class=AssetClass.KR_ETF,
                currency=Currency.KRW,
                name="x",
                tick_size=0.05,
            )

    def test_string_tick_size_coerced(self):
        a = Asset(
            code="069500",
            exchange=Exchange.KRX,
            asset_class=AssetClass.KR_ETF,
            currency=Currency.KRW,
            name="x",
            tick_size="5",
        )
        assert a.tick_size == Decimal("5")

    def test_immutable(self):
        a = make_asset()
        with pytest.raises(ValidationError):
            a.code = "999999"


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------
class TestPrice:
    def test_construct_happy_path(self):
        a = make_asset()
        p = Price(asset=a, value=Decimal("35000"), timestamp=UTC_NOW)
        assert p.asset is a
        assert p.value == Decimal("35000")
        assert p.timestamp == UTC_NOW

    def test_zero_value_rejected(self):
        with pytest.raises(ValidationError):
            Price(asset=make_asset(), value=Decimal("0"), timestamp=UTC_NOW)

    def test_negative_value_rejected(self):
        with pytest.raises(ValidationError):
            Price(asset=make_asset(), value=Decimal("-1"), timestamp=UTC_NOW)

    def test_float_value_rejected(self):
        with pytest.raises(ValidationError):
            Price(asset=make_asset(), value=35000.5, timestamp=UTC_NOW)

    def test_string_value_coerced(self):
        p = Price(asset=make_asset(), value="35000", timestamp=UTC_NOW)
        assert p.value == Decimal("35000")

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 4, 30, 6, 0, 0)
        with pytest.raises(ValidationError):
            Price(asset=make_asset(), value=Decimal("35000"), timestamp=naive)

    def test_non_utc_tz_rejected(self):
        kst = timezone(timedelta(hours=9))
        kst_dt = datetime(2026, 4, 30, 15, 0, 0, tzinfo=kst)
        with pytest.raises(ValidationError):
            Price(asset=make_asset(), value=Decimal("35000"), timestamp=kst_dt)

    def test_immutable(self):
        p = Price(asset=make_asset(), value=Decimal("35000"), timestamp=UTC_NOW)
        with pytest.raises(ValidationError):
            p.value = Decimal("36000")


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------
class TestBalance:
    def test_construct(self):
        b = Balance(cash=Money(amount=Decimal("1000000"), currency=Currency.KRW))
        assert b.cash.amount == Decimal("1000000")

    def test_equality(self):
        a = Balance(cash=Money(amount=Decimal("100"), currency=Currency.KRW))
        b = Balance(cash=Money(amount=Decimal("100"), currency=Currency.KRW))
        assert a == b
        assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# OHLCV
# ---------------------------------------------------------------------------
class TestOHLCV:
    def _bar(self, **overrides):
        base = {
            "asset": make_asset(),
            "trade_date": date(2026, 4, 29),
            "open": Decimal("35000"),
            "high": Decimal("35500"),
            "low": Decimal("34500"),
            "close": Decimal("35200"),
            "volume": Decimal("1000000"),
        }
        base.update(overrides)
        return OHLCV(**base)

    def test_construct_happy_path(self):
        bar = self._bar()
        assert bar.open == Decimal("35000")
        assert bar.high == Decimal("35500")
        assert bar.low == Decimal("34500")
        assert bar.close == Decimal("35200")
        assert bar.volume == Decimal("1000000")
        assert bar.trade_date == date(2026, 4, 29)

    def test_zero_volume_allowed(self):
        bar = self._bar(volume=Decimal(0))
        assert bar.volume == Decimal(0)

    def test_negative_volume_rejected(self):
        with pytest.raises(ValidationError):
            self._bar(volume=Decimal("-1"))

    def test_zero_open_rejected(self):
        with pytest.raises(ValidationError):
            self._bar(open=Decimal(0))

    def test_zero_high_rejected(self):
        with pytest.raises(ValidationError):
            self._bar(high=Decimal(0))

    def test_zero_low_rejected(self):
        with pytest.raises(ValidationError):
            self._bar(low=Decimal(0))

    def test_zero_close_rejected(self):
        with pytest.raises(ValidationError):
            self._bar(close=Decimal(0))

    def test_high_below_low_rejected(self):
        with pytest.raises(ValidationError, match="high"):
            self._bar(high=Decimal("34000"), low=Decimal("34500"))

    def test_open_below_low_rejected(self):
        with pytest.raises(ValidationError, match="open"):
            self._bar(open=Decimal("34000"), low=Decimal("34500"))

    def test_open_above_high_rejected(self):
        with pytest.raises(ValidationError, match="open"):
            self._bar(open=Decimal("36000"), high=Decimal("35500"))

    def test_close_below_low_rejected(self):
        with pytest.raises(ValidationError, match="close"):
            self._bar(close=Decimal("34000"), low=Decimal("34500"))

    def test_close_above_high_rejected(self):
        with pytest.raises(ValidationError, match="close"):
            self._bar(close=Decimal("36000"), high=Decimal("35500"))

    def test_open_high_low_close_at_boundary(self):
        # open == low, close == high -> valid
        bar = self._bar(
            open=Decimal("34500"),
            close=Decimal("35500"),
            low=Decimal("34500"),
            high=Decimal("35500"),
        )
        assert bar.open == bar.low
        assert bar.close == bar.high

    def test_float_price_rejected(self):
        with pytest.raises(ValidationError):
            self._bar(open=35000.5)

    def test_immutable(self):
        bar = self._bar()
        with pytest.raises(ValidationError):
            bar.close = Decimal("36000")


# ---------------------------------------------------------------------------
# SplitEntry
# ---------------------------------------------------------------------------
TRADE_DATE = datetime(2026, 4, 29, 6, 0, 0, tzinfo=UTC).date()


class TestSplitEntry:
    def _entry(self, **overrides) -> SplitEntry:
        base = {
            "split_number": 1,
            "entry_date": TRADE_DATE,
            "quantity": Decimal("28"),
            "entry_price": Decimal("35000"),
            "idempotency_key": "KRX:069500:2026-04-29",
        }
        base.update(overrides)
        return SplitEntry(**base)

    # ----------- happy paths -----------
    def test_construct_happy_path(self):
        e = self._entry()
        assert e.split_number == 1
        assert e.entry_date == TRADE_DATE
        assert e.quantity == Decimal("28")
        assert e.entry_price == Decimal("35000")
        assert e.idempotency_key == "KRX:069500:2026-04-29"

    def test_max_split_number_seven(self):
        # split_number=7 is the upper bound (matches Position.split_level)
        e = self._entry(split_number=7)
        assert e.split_number == 7

    # ----------- validation -----------
    def test_split_number_zero_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(split_number=0)

    def test_split_number_negative_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(split_number=-1)

    def test_split_number_above_seven_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(split_number=8)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValidationError):
            self._entry(quantity=Decimal("-1"))

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(quantity=Decimal(0))

    def test_zero_price_raises(self):
        with pytest.raises(ValidationError):
            self._entry(entry_price=Decimal(0))

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(entry_price=Decimal("-100"))

    def test_float_quantity_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(quantity=28.5)

    def test_float_entry_price_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(entry_price=35000.5)

    def test_string_quantity_coerced(self):
        e = self._entry(quantity="28")
        assert e.quantity == Decimal("28")

    def test_string_entry_price_coerced(self):
        e = self._entry(entry_price="35000")
        assert e.entry_price == Decimal("35000")

    def test_empty_idempotency_key_rejected(self):
        with pytest.raises(ValidationError):
            self._entry(idempotency_key="")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            SplitEntry(  # type: ignore[call-arg]
                split_number=1,
                entry_date=TRADE_DATE,
                quantity=Decimal("28"),
                entry_price=Decimal("35000"),
                idempotency_key="k",
                extra="not allowed",
            )

    # ----------- value-object semantics -----------
    def test_equality_and_hash(self):
        a = self._entry()
        b = self._entry()
        c = self._entry(split_number=2)
        assert a == b
        assert hash(a) == hash(b)
        assert a != c

    def test_immutable(self):
        e = self._entry()
        with pytest.raises(ValidationError):
            e.split_number = 2


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------
class TestPosition:
    def test_empty_classmethod(self):
        a = make_asset()
        p = Position.empty(a)
        assert p.asset is a
        assert p.quantity == Decimal(0)
        assert p.avg_price == Decimal(0)
        assert p.split_level == 0
        assert p.last_buy_at is None

    def test_filled_position(self):
        a = make_asset()
        p = Position(
            asset=a,
            quantity=Decimal("10"),
            avg_price=Decimal("35000"),
            split_level=2,
            last_buy_at=UTC_NOW,
        )
        assert p.quantity == Decimal("10")
        assert p.split_level == 2

    def test_split_level_negative_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal(0),
                split_level=-1,
            )

    def test_split_level_above_max_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=8,
                last_buy_at=UTC_NOW,
            )

    def test_negative_quantity_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError):
            Position(
                asset=a,
                quantity=Decimal("-1"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=UTC_NOW,
            )

    def test_negative_avg_price_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("-1"),
                split_level=1,
                last_buy_at=UTC_NOW,
            )

    def test_qty_positive_with_split_level_zero_allowed(self):
        # Partial-only position: quantity > 0 but no split has fully filled yet.
        # Per CLAUDE.md §4.4, partial fills do not increment split_level.
        a = make_asset()
        p = Position(
            asset=a,
            quantity=Decimal("10"),
            avg_price=Decimal("35000"),
            split_level=0,
            last_buy_at=UTC_NOW,
        )
        assert p.quantity == Decimal("10")
        assert p.split_level == 0

    def test_qty_positive_requires_avg_price_positive(self):
        a = make_asset()
        with pytest.raises(ValidationError, match="avg_price"):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal(0),
                split_level=1,
                last_buy_at=UTC_NOW,
            )

    def test_qty_positive_requires_last_buy_at(self):
        a = make_asset()
        with pytest.raises(ValidationError, match="last_buy_at"):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=None,
            )

    def test_qty_zero_must_have_zero_split_level(self):
        a = make_asset()
        with pytest.raises(ValidationError, match="split_level"):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal(0),
                split_level=2,
            )

    def test_qty_zero_must_have_zero_avg_price(self):
        a = make_asset()
        with pytest.raises(ValidationError, match="avg_price"):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal("100"),
                split_level=0,
            )

    def test_naive_last_buy_at_rejected(self):
        a = make_asset()
        naive = datetime(2026, 4, 30, 6, 0, 0)
        with pytest.raises(ValidationError):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=naive,
            )

    def test_immutable(self):
        a = make_asset()
        p = Position.empty(a)
        with pytest.raises(ValidationError):
            p.split_level = 1


# ---------------------------------------------------------------------------
# OrderRequest
# ---------------------------------------------------------------------------
class TestOrderRequest:
    def test_construct_happy_path(self):
        a = make_asset()
        r = OrderRequest(
            idempotency_key="abc-123",
            asset=a,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            target_price=Decimal("35000"),
        )
        assert r.idempotency_key == "abc-123"
        assert r.side is OrderSide.BUY
        assert r.order_type is OrderType.LIMIT

    def test_empty_idempotency_key_rejected(self):
        with pytest.raises(ValidationError):
            OrderRequest(
                idempotency_key="",
                asset=make_asset(),
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                target_price=Decimal("35000"),
            )

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            OrderRequest(
                idempotency_key="k",
                asset=make_asset(),
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal(0),
                target_price=Decimal("35000"),
            )

    def test_zero_target_price_rejected(self):
        with pytest.raises(ValidationError):
            OrderRequest(
                idempotency_key="k",
                asset=make_asset(),
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                target_price=Decimal(0),
            )

    def test_float_quantity_rejected(self):
        with pytest.raises(ValidationError):
            OrderRequest(
                idempotency_key="k",
                asset=make_asset(),
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=10.5,
                target_price=Decimal("35000"),
            )


# ---------------------------------------------------------------------------
# OrderResult
# ---------------------------------------------------------------------------
class TestOrderResult:
    def test_pending_no_fill(self):
        r = OrderResult(
            idempotency_key="k",
            asset=make_asset(),
            broker_order_id="bid-1",
            status=OrderStatus.PENDING,
            filled_quantity=Decimal(0),
            filled_price=None,
            submitted_at=UTC_NOW,
            filled_at=None,
        )
        assert r.status is OrderStatus.PENDING

    def test_filled_state(self):
        r = OrderResult(
            idempotency_key="k",
            asset=make_asset(),
            broker_order_id="bid-1",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("10"),
            filled_price=Decimal("35000"),
            submitted_at=UTC_NOW,
            filled_at=UTC_LATER,
        )
        assert r.status is OrderStatus.FILLED
        assert r.filled_at == UTC_LATER

    def test_rejected_no_broker_id(self):
        r = OrderResult(
            idempotency_key="k",
            asset=make_asset(),
            broker_order_id=None,
            status=OrderStatus.REJECTED,
            filled_quantity=Decimal(0),
            filled_price=None,
            submitted_at=UTC_NOW,
            filled_at=None,
        )
        assert r.broker_order_id is None

    def test_negative_filled_quantity_rejected(self):
        with pytest.raises(ValidationError):
            OrderResult(
                idempotency_key="k",
                asset=make_asset(),
                broker_order_id="bid-1",
                status=OrderStatus.PENDING,
                filled_quantity=Decimal("-1"),
                filled_price=None,
                submitted_at=UTC_NOW,
                filled_at=None,
            )

    def test_zero_filled_price_rejected(self):
        with pytest.raises(ValidationError):
            OrderResult(
                idempotency_key="k",
                asset=make_asset(),
                broker_order_id="bid-1",
                status=OrderStatus.FILLED,
                filled_quantity=Decimal("10"),
                filled_price=Decimal(0),
                submitted_at=UTC_NOW,
                filled_at=UTC_LATER,
            )

    def test_naive_submitted_at_rejected(self):
        naive = datetime(2026, 4, 30, 6, 0, 0)
        with pytest.raises(ValidationError):
            OrderResult(
                idempotency_key="k",
                asset=make_asset(),
                broker_order_id="bid-1",
                status=OrderStatus.PENDING,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=naive,
                filled_at=None,
            )

    def test_naive_filled_at_rejected(self):
        naive = datetime(2026, 4, 30, 7, 0, 0)
        with pytest.raises(ValidationError):
            OrderResult(
                idempotency_key="k",
                asset=make_asset(),
                broker_order_id="bid-1",
                status=OrderStatus.FILLED,
                filled_quantity=Decimal("10"),
                filled_price=Decimal("35000"),
                submitted_at=UTC_NOW,
                filled_at=naive,
            )


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------
class TestOrder:
    def _filled_kwargs(self, **overrides):
        base = {
            "idempotency_key": "k",
            "asset": make_asset(),
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "quantity": Decimal("10"),
            "target_price": Decimal("35000"),
            "status": OrderStatus.FILLED,
            "broker_order_id": "bid-1",
            "filled_quantity": Decimal("10"),
            "filled_price": Decimal("35000"),
            "submitted_at": UTC_NOW,
            "filled_at": UTC_LATER,
        }
        base.update(overrides)
        return base

    def test_filled_happy_path(self):
        o = Order(**self._filled_kwargs())
        assert o.status is OrderStatus.FILLED

    def test_filled_requires_broker_id(self):
        with pytest.raises(ValidationError, match="broker_order_id"):
            Order(**self._filled_kwargs(broker_order_id=None))

    def test_filled_requires_filled_at(self):
        with pytest.raises(ValidationError, match="filled_at"):
            Order(**self._filled_kwargs(filled_at=None))

    def test_filled_requires_filled_price(self):
        with pytest.raises(ValidationError, match="filled_price"):
            Order(**self._filled_kwargs(filled_price=None))

    def test_filled_quantity_must_match_quantity(self):
        with pytest.raises(ValidationError, match="filled_quantity"):
            Order(**self._filled_kwargs(filled_quantity=Decimal("5")))

    def test_partially_filled_happy_path(self):
        o = Order(
            **self._filled_kwargs(
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity=Decimal("5"),
            )
        )
        assert o.status is OrderStatus.PARTIALLY_FILLED

    def test_partially_filled_requires_broker_id(self):
        with pytest.raises(ValidationError, match="broker_order_id"):
            Order(
                **self._filled_kwargs(
                    status=OrderStatus.PARTIALLY_FILLED,
                    broker_order_id=None,
                    filled_quantity=Decimal("5"),
                )
            )

    def test_partially_filled_requires_positive_fill(self):
        with pytest.raises(ValidationError, match="filled_quantity"):
            Order(
                **self._filled_kwargs(
                    status=OrderStatus.PARTIALLY_FILLED,
                    filled_quantity=Decimal(0),
                )
            )

    def test_partially_filled_must_be_below_quantity(self):
        with pytest.raises(ValidationError, match="filled_quantity"):
            Order(
                **self._filled_kwargs(
                    status=OrderStatus.PARTIALLY_FILLED,
                    filled_quantity=Decimal("10"),  # equals quantity
                )
            )

    def test_pending_happy_path(self):
        o = Order(
            **self._filled_kwargs(
                status=OrderStatus.PENDING,
                broker_order_id="bid-1",
                filled_quantity=Decimal(0),
                filled_price=None,
                filled_at=None,
            )
        )
        assert o.status is OrderStatus.PENDING

    def test_pending_must_have_zero_fill(self):
        with pytest.raises(ValidationError, match="filled_quantity"):
            Order(
                **self._filled_kwargs(
                    status=OrderStatus.PENDING,
                    filled_quantity=Decimal("3"),
                    filled_price=None,
                    filled_at=None,
                )
            )

    def test_negative_filled_quantity_rejected(self):
        with pytest.raises(ValidationError, match="filled_quantity"):
            Order(
                **self._filled_kwargs(
                    status=OrderStatus.UNKNOWN,
                    broker_order_id=None,
                    filled_quantity=Decimal("-1"),
                    filled_price=None,
                    filled_at=None,
                )
            )

    def test_zero_filled_price_rejected(self):
        with pytest.raises(ValidationError, match="filled_price"):
            Order(
                **self._filled_kwargs(
                    status=OrderStatus.UNKNOWN,
                    broker_order_id=None,
                    filled_quantity=Decimal(0),
                    filled_price=Decimal(0),
                    filled_at=None,
                )
            )

    def test_unknown_status_permits_anything(self):
        o = Order(
            **self._filled_kwargs(
                status=OrderStatus.UNKNOWN,
                broker_order_id=None,
                filled_quantity=Decimal(0),
                filled_price=None,
                filled_at=None,
            )
        )
        assert o.status is OrderStatus.UNKNOWN

    def test_from_request_result_happy_path(self):
        a = make_asset()
        req = OrderRequest(
            idempotency_key="k",
            asset=a,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            target_price=Decimal("35000"),
        )
        res = OrderResult(
            idempotency_key="k",
            asset=a,
            broker_order_id="bid-1",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("10"),
            filled_price=Decimal("35000"),
            submitted_at=UTC_NOW,
            filled_at=UTC_LATER,
        )
        o = Order.from_request_result(req, res)
        assert o.idempotency_key == "k"
        assert o.asset is a
        assert o.side is OrderSide.BUY
        assert o.order_type is OrderType.LIMIT
        assert o.quantity == Decimal("10")
        assert o.target_price == Decimal("35000")
        assert o.status is OrderStatus.FILLED
        assert o.broker_order_id == "bid-1"
        assert o.filled_quantity == Decimal("10")
        assert o.filled_price == Decimal("35000")
        assert o.submitted_at == UTC_NOW
        assert o.filled_at == UTC_LATER

    def test_from_request_result_idempotency_key_mismatch(self):
        req = OrderRequest(
            idempotency_key="k1",
            asset=make_asset(),
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            target_price=Decimal("35000"),
        )
        res = OrderResult(
            idempotency_key="k2",
            asset=make_asset(),
            broker_order_id="bid-1",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("10"),
            filled_price=Decimal("35000"),
            submitted_at=UTC_NOW,
            filled_at=UTC_LATER,
        )
        with pytest.raises(ValueError, match="idempotency_key mismatch"):
            Order.from_request_result(req, res)

    def test_from_request_result_asset_mismatch(self):
        a = make_asset(code="069500")
        b = make_asset(code="105190")
        req = OrderRequest(
            idempotency_key="k",
            asset=a,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            target_price=Decimal("35000"),
        )
        res = OrderResult(
            idempotency_key="k",
            asset=b,
            broker_order_id="bid-1",
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("10"),
            filled_price=Decimal("35000"),
            submitted_at=UTC_NOW,
            filled_at=UTC_LATER,
        )
        with pytest.raises(ValueError, match="asset mismatch"):
            Order.from_request_result(req, res)


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------
class TestDecision:
    def test_construct_with_order(self):
        d = Decision(
            timestamp=UTC_NOW,
            asset=make_asset(),
            action="buy_split_2",
            reasoning={"current_price": "35000", "drop_pct": "7.5"},
            resulting_order_id="ord-1",
        )
        assert d.action == "buy_split_2"
        assert d.reasoning["current_price"] == "35000"
        assert d.resulting_order_id == "ord-1"

    def test_construct_without_order(self):
        d = Decision(
            timestamp=UTC_NOW,
            asset=make_asset(),
            action="skip:max_split_reached",
            reasoning={"current_split_level": "7"},
        )
        assert d.resulting_order_id is None

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 4, 30, 6, 0, 0)
        with pytest.raises(ValidationError):
            Decision(
                timestamp=naive,
                asset=make_asset(),
                action="x",
                reasoning={"k": "v"},
            )

    def test_empty_action_rejected(self):
        with pytest.raises(ValidationError):
            Decision(
                timestamp=UTC_NOW,
                asset=make_asset(),
                action="",
                reasoning={"k": "v"},
            )

    def test_immutable(self):
        d = Decision(
            timestamp=UTC_NOW,
            asset=make_asset(),
            action="x",
            reasoning={"k": "v"},
        )
        with pytest.raises(ValidationError):
            d.action = "y"


# ---------------------------------------------------------------------------
# CircuitBreakerSignal
# ---------------------------------------------------------------------------
class TestCircuitBreakerSignal:
    def _signal(self, **overrides):
        base = {
            "level": SignalLevel.NORMAL,
            "source": SignalSource.NULL,
            "asset_class": AssetClass.KR_ETF,
            "evaluated_at": UTC_NOW,
            "triggered_by": [],
            "reasoning": {},
            "valid_until": UTC_LATER,
        }
        base.update(overrides)
        return CircuitBreakerSignal(**base)

    def test_normal_null_signal(self):
        sig = self._signal()
        assert sig.level is SignalLevel.NORMAL
        assert sig.source is SignalSource.NULL
        assert sig.triggered_by == []
        assert sig.reasoning == {}

    def test_halt_with_triggers(self):
        sig = self._signal(
            level=SignalLevel.HALT,
            source=SignalSource.RULE_BASED,
            triggered_by=["vix_above_40", "fx_spike"],
            reasoning={"vix": "42.5", "fx_change_pct": "3.2"},
        )
        assert sig.level is SignalLevel.HALT
        assert sig.triggered_by == ["vix_above_40", "fx_spike"]

    def test_valid_until_must_exceed_evaluated_at(self):
        with pytest.raises(ValidationError, match="valid_until"):
            self._signal(evaluated_at=UTC_LATER, valid_until=UTC_NOW)

    def test_valid_until_equal_to_evaluated_at_rejected(self):
        with pytest.raises(ValidationError, match="valid_until"):
            self._signal(evaluated_at=UTC_NOW, valid_until=UTC_NOW)

    def test_naive_evaluated_at_rejected(self):
        naive = datetime(2026, 4, 30, 6, 0, 0)
        with pytest.raises(ValidationError):
            self._signal(evaluated_at=naive)

    def test_naive_valid_until_rejected(self):
        naive = datetime(2026, 4, 30, 7, 0, 0)
        with pytest.raises(ValidationError):
            self._signal(valid_until=naive)

    def test_immutable(self):
        sig = self._signal()
        with pytest.raises(ValidationError):
            sig.level = SignalLevel.HALT


# ---------------------------------------------------------------------------
# Enums (sanity checks for required values)
# ---------------------------------------------------------------------------
class TestEnums:
    def test_order_type_only_has_limit(self):
        assert {m.value for m in OrderType} == {"LIMIT"}

    def test_order_side_has_buy_and_sell(self):
        assert {m.value for m in OrderSide} == {"BUY", "SELL"}

    def test_asset_class_has_kr_stock_and_etf(self):
        values = {m.value for m in AssetClass}
        assert "KR_STOCK" in values
        assert "KR_ETF" in values

    def test_exchange_has_krx(self):
        assert "KRX" in {m.value for m in Exchange}

    def test_signal_level_has_all_severities(self):
        assert {m.value for m in SignalLevel} == {
            "NORMAL",
            "CAUTION",
            "HALT",
            "EMERGENCY",
        }

    def test_signal_source_has_null_rule_ai_manual(self):
        assert {m.value for m in SignalSource} == {
            "NULL",
            "RULE_BASED",
            "AI_BASED",
            "MANUAL",
        }
