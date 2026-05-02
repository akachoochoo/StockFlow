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
    BuyActionRecord,
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
    PortfolioSnapshot,
    Position,
    PositionValuation,
    Price,
    SellActionRecord,
    SignalLevel,
    SignalSource,
    SkipReason,
    SlotState,
    SplitEntry,
    SplitSlot,
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


def make_entries(
    *quantities_prices: tuple[str, str],
    entry_date: date | None = None,
) -> list[SplitEntry]:
    """Build sequential SplitEntry list from (qty, price) tuples.

    `make_entries(("10", "35000"), ("5", "32000"))` -> 2 entries with
    split_number 1 and 2.
    """
    d = entry_date or UTC_NOW.date()
    return [
        SplitEntry(
            split_number=i + 1,
            entry_date=d,
            quantity=Decimal(q),
            entry_price=Decimal(p),
            idempotency_key=f"k{i + 1}",
        )
        for i, (q, p) in enumerate(quantities_prices)
    ]


def make_slots(
    *quantities_prices: tuple[str, str],
    max_split_count: int = 7,
    entry_date: date | None = None,
) -> list[SplitSlot]:
    """Build a list of SplitSlots — first N FILLED, then EMPTY up to max.

    `make_slots(("10", "35000"))` returns [FILLED slot 1, EMPTY 2..7].
    """
    if len(quantities_prices) > max_split_count:
        raise ValueError("more entries than max_split_count")
    entries = make_entries(*quantities_prices, entry_date=entry_date)
    slots: list[SplitSlot] = [SplitSlot.filled(entry=e) for e in entries]
    slots.extend(
        SplitSlot.empty(slot_number=i)
        for i in range(len(entries) + 1, max_split_count + 1)
    )
    return slots


def make_position(
    *quantities_prices: tuple[str, str],
    asset: Asset | None = None,
    max_split_count: int = 7,
    last_buy_at: datetime | None = None,
    entry_date: date | None = None,
) -> Position:
    """Build a Position with N FILLED slots (1..N) + EMPTY slots up to max.

    quantity / avg_price / split_level are derived from the entries.
    """
    a = asset or make_asset()
    n = len(quantities_prices)
    if n == 0:
        return Position.empty(a, max_split_count=max_split_count)
    slots = make_slots(
        *quantities_prices,
        max_split_count=max_split_count,
        entry_date=entry_date,
    )
    total_qty = sum(
        (Decimal(q) for q, _ in quantities_prices), Decimal(0)
    )
    total_cost = sum(
        (Decimal(q) * Decimal(p) for q, p in quantities_prices),
        Decimal(0),
    )
    return Position(
        asset=a,
        quantity=total_qty,
        avg_price=total_cost / total_qty,
        split_level=n,
        last_buy_at=last_buy_at or UTC_NOW,
        slots=slots,
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

    def test_fqn_excluded_from_dump_for_round_trip_safety(self):
        # fqn is a plain @property, not a serialized field, so model_dump
        # / model_dump_json output stays compatible with extra="forbid" on
        # round-trip via Asset.model_validate(...).
        a = make_asset()
        dumped = a.model_dump()
        assert "fqn" not in dumped
        # And the canonical form is still recoverable on the rebuilt model.
        rebuilt = Asset.model_validate(dumped)
        assert rebuilt.fqn == "KRX:069500"

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

    # ---- round_to_tick (ADR §7.10) ----
    def test_round_to_tick_exact_multiple(self):
        a = make_asset()  # tick_size = 5
        assert a.round_to_tick(Decimal("35000")) == Decimal("35000")

    def test_round_to_tick_floors_above_multiple(self):
        a = make_asset()
        # 35003 / 5 = 7000.6 → floor 7000 → 35000
        assert a.round_to_tick(Decimal("35003")) == Decimal("35000")

    def test_round_to_tick_just_below_next_multiple(self):
        a = make_asset()
        # 34999 / 5 = 6999.8 → floor 6999 → 34995
        assert a.round_to_tick(Decimal("34999")) == Decimal("34995")

    def test_round_to_tick_with_decimal_tick(self):
        a = Asset(
            code="X",
            exchange=Exchange.KRX,
            asset_class=AssetClass.KR_ETF,
            currency=Currency.KRW,
            name="X",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
        )
        assert a.round_to_tick(Decimal("35.034")) == Decimal("35.03")

    def test_round_to_tick_returns_zero_when_below_tick(self):
        # Edge case: price < tick_size → result == 0. Won't happen for KODEX 200
        # in practice (price ~35,000 vs tick 5), but documents the behavior.
        a = make_asset()  # tick_size = 5
        assert a.round_to_tick(Decimal("3")) == Decimal("0")


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
    def _entry(self, **overrides):
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
            SplitEntry(
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
        assert len(p.slots) == 7
        assert all(s.state is SlotState.EMPTY for s in p.slots)

    def test_empty_with_custom_max_split_count(self):
        p = Position.empty(make_asset(), max_split_count=3)
        assert len(p.slots) == 3
        assert [s.slot_number for s in p.slots] == [1, 2, 3]

    def test_empty_with_invalid_max_split_count(self):
        with pytest.raises(ValueError, match=r"max_split_count"):
            Position.empty(make_asset(), max_split_count=8)

    def test_filled_position(self):
        # Two FILLED slots (1, 2) + five EMPTY slots
        p = make_position(("4", "36000"), ("6", "34000"))
        assert p.quantity == Decimal("10")
        assert p.split_level == 2
        assert len(p.slots) == 7
        assert len(p.filled_slots) == 2
        assert len(p.empty_slots) == 5

    def test_split_level_negative_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal(0),
                split_level=-1,
                slots=[SplitSlot.empty(slot_number=1)],
            )

    def test_split_level_above_max_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError):
            # Field constraint le=7 catches this before the slot-count check.
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=8,
                last_buy_at=UTC_NOW,
                slots=make_slots(("10", "35000")),
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
                slots=make_slots(("10", "35000")),
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
                slots=make_slots(("10", "35000")),
            )

    def test_qty_positive_requires_avg_price_positive(self):
        # avg_price must equal weighted-avg of FILLED slots (Phase 0.5
        # equality invariant); zero avg_price + non-zero entry price is
        # impossible by construction so the avg-mismatch error fires first.
        a = make_asset()
        with pytest.raises(ValidationError, match=r"avg_price"):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal(0),
                split_level=1,
                last_buy_at=UTC_NOW,
                slots=make_slots(("10", "35000")),
            )

    def test_qty_positive_requires_last_buy_at(self):
        a = make_asset()
        with pytest.raises(ValidationError, match=r"last_buy_at"):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=None,
                slots=make_slots(("10", "35000")),
            )

    def test_qty_zero_must_have_zero_split_level(self):
        a = make_asset()
        with pytest.raises(ValidationError, match=r"split_level"):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal(0),
                split_level=2,
                slots=[SplitSlot.empty(slot_number=i) for i in range(1, 3)],
            )

    def test_qty_zero_must_have_zero_avg_price(self):
        a = make_asset()
        with pytest.raises(ValidationError, match=r"avg_price"):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal("100"),
                split_level=0,
                slots=[SplitSlot.empty(slot_number=1)],
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
                slots=make_slots(("10", "35000")),
            )

    def test_immutable(self):
        p = Position.empty(make_asset())
        with pytest.raises(ValidationError):
            p.split_level = 1


# ---------------------------------------------------------------------------
# SplitSlot value object (Phase 0.5 / ADR 0002 §3.1)
# ---------------------------------------------------------------------------
class TestSplitSlot:
    def test_empty_factory(self):
        s = SplitSlot.empty(slot_number=3)
        assert s.slot_number == 3
        assert s.state is SlotState.EMPTY
        assert s.entry is None
        assert s.last_exit_price is None
        assert s.last_exit_date is None

    def test_empty_with_exit_history(self):
        s = SplitSlot.empty(
            slot_number=2,
            last_exit_price=Decimal("33000"),
            last_exit_date=date(2026, 3, 1),
        )
        assert s.state is SlotState.EMPTY
        assert s.last_exit_price == Decimal("33000")
        assert s.last_exit_date == date(2026, 3, 1)

    def test_filled_factory(self):
        e = SplitEntry(
            split_number=4,
            entry_date=date(2026, 4, 1),
            quantity=Decimal("10"),
            entry_price=Decimal("30000"),
            idempotency_key="k4",
        )
        s = SplitSlot.filled(entry=e)
        assert s.slot_number == 4
        assert s.state is SlotState.FILLED
        assert s.entry is e

    def test_filled_state_requires_entry(self):
        with pytest.raises(ValidationError, match=r"FILLED slot"):
            SplitSlot(
                slot_number=1,
                state=SlotState.FILLED,
                entry=None,
            )

    def test_empty_state_must_not_carry_entry(self):
        e = SplitEntry(
            split_number=1,
            entry_date=date(2026, 4, 1),
            quantity=Decimal("10"),
            entry_price=Decimal("30000"),
            idempotency_key="k",
        )
        with pytest.raises(ValidationError, match=r"EMPTY slot"):
            SplitSlot(
                slot_number=1,
                state=SlotState.EMPTY,
                entry=e,
            )

    def test_entry_split_number_must_match_slot_number(self):
        e = SplitEntry(
            split_number=2,
            entry_date=date(2026, 4, 1),
            quantity=Decimal("10"),
            entry_price=Decimal("30000"),
            idempotency_key="k",
        )
        with pytest.raises(ValidationError, match=r"split_number"):
            SplitSlot(
                slot_number=3,
                state=SlotState.FILLED,
                entry=e,
            )

    def test_last_exit_date_without_price_rejected(self):
        with pytest.raises(ValidationError, match=r"last_exit_price"):
            SplitSlot(
                slot_number=1,
                state=SlotState.EMPTY,
                last_exit_date=date(2026, 4, 1),
            )

    def test_negative_last_exit_price_rejected(self):
        with pytest.raises(ValidationError, match=r"last_exit_price"):
            SplitSlot(
                slot_number=1,
                state=SlotState.EMPTY,
                last_exit_price=Decimal("-1"),
            )

    def test_immutable(self):
        s = SplitSlot.empty(slot_number=1)
        with pytest.raises(ValidationError):
            s.slot_number = 2


# ---------------------------------------------------------------------------
# Position — slot-based invariants and helpers (Phase 0.5)
# ---------------------------------------------------------------------------
class TestPositionSlots:
    # ----------- invariant: slot_number sequence -----------
    def test_slots_must_be_sequential_from_one(self):
        a = make_asset()
        bad = [
            SplitSlot.empty(slot_number=2),
            SplitSlot.empty(slot_number=3),
        ]
        with pytest.raises(ValidationError, match=r"sequential"):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal(0),
                split_level=0,
                slots=bad,
            )

    def test_slots_with_duplicate_numbers_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError, match=r"sequential"):
            Position(
                asset=a,
                quantity=Decimal(0),
                avg_price=Decimal(0),
                split_level=0,
                slots=[
                    SplitSlot.empty(slot_number=1),
                    SplitSlot.empty(slot_number=1),
                ],
            )

    # ----------- invariant: split_level == FILLED count -----------
    def test_split_level_below_filled_count_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError, match=r"split_level"):
            Position(
                asset=a,
                quantity=Decimal("28"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=UTC_NOW,
                slots=make_slots(("14", "35000"), ("14", "35000")),
            )

    def test_split_level_above_filled_count_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError, match=r"split_level"):
            Position(
                asset=a,
                quantity=Decimal("28"),
                avg_price=Decimal("35000"),
                split_level=2,
                last_buy_at=UTC_NOW,
                slots=make_slots(("28", "35000")),
            )

    # ----------- invariant: sparse slot_number allowed -----------
    def test_sparse_filled_pattern_allowed(self):
        # Slot 2 EMPTY while slot 3 FILLED is valid — captures "sold slot 2,
        # then bought slot 3" cycles in Phase 0.5.
        a = make_asset()
        e1 = SplitEntry(
            split_number=1,
            entry_date=UTC_NOW.date(),
            quantity=Decimal("10"),
            entry_price=Decimal("30000"),
            idempotency_key="k1",
        )
        e3 = SplitEntry(
            split_number=3,
            entry_date=UTC_NOW.date(),
            quantity=Decimal("8"),
            entry_price=Decimal("28000"),
            idempotency_key="k3",
        )
        slots = [
            SplitSlot.filled(entry=e1),
            SplitSlot.empty(
                slot_number=2,
                last_exit_price=Decimal("33000"),
                last_exit_date=date(2026, 3, 15),
            ),
            SplitSlot.filled(entry=e3),
            SplitSlot.empty(slot_number=4),
            SplitSlot.empty(slot_number=5),
            SplitSlot.empty(slot_number=6),
            SplitSlot.empty(slot_number=7),
        ]
        total_qty = Decimal("18")
        total_cost = Decimal(10) * Decimal(30000) + Decimal(8) * Decimal(28000)
        p = Position(
            asset=a,
            quantity=total_qty,
            avg_price=total_cost / total_qty,
            split_level=2,
            last_buy_at=UTC_NOW,
            slots=slots,
        )
        assert p.split_level == 2
        assert [s.slot_number for s in p.filled_slots] == [1, 3]
        assert p.next_empty_slot_number() == 2

    # ----------- invariant: quantity equality -----------
    def test_quantity_below_filled_sum_rejected(self):
        a = make_asset()
        with pytest.raises(ValidationError, match=r"FILLED slot quantities"):
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=UTC_NOW,
                slots=make_slots(("20", "35000")),
            )

    def test_quantity_above_filled_sum_rejected(self):
        # Phase 0.5 equality (no partial-fill carry).
        a = make_asset()
        with pytest.raises(ValidationError, match=r"FILLED slot quantities"):
            Position(
                asset=a,
                quantity=Decimal("15"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=UTC_NOW,
                slots=make_slots(("10", "35000")),
            )

    # ----------- invariant: avg_price equality -----------
    def test_avg_price_must_equal_weighted_average(self):
        a = make_asset()
        # 14 @ 36000 + 14 @ 34000 → weighted avg 35000. Set 35001 to fail.
        with pytest.raises(ValidationError, match=r"weighted average"):
            Position(
                asset=a,
                quantity=Decimal("28"),
                avg_price=Decimal("35001"),
                split_level=2,
                last_buy_at=UTC_NOW,
                slots=make_slots(("14", "36000"), ("14", "34000")),
            )

    # ----------- properties: filled_slots / empty_slots / next_empty -----------
    def test_filled_and_empty_slot_partitions(self):
        p = make_position(("10", "30000"), ("8", "28000"))
        assert [s.slot_number for s in p.filled_slots] == [1, 2]
        assert [s.slot_number for s in p.empty_slots] == [3, 4, 5, 6, 7]

    def test_next_empty_slot_number_first_buy(self):
        p = Position.empty(make_asset())
        assert p.next_empty_slot_number() == 1

    def test_next_empty_slot_number_after_fills(self):
        p = make_position(("10", "30000"), ("8", "28000"))
        assert p.next_empty_slot_number() == 3

    def test_next_empty_slot_number_when_all_filled(self):
        p = make_position(*[("1", "30000")] * 7)
        assert p.next_empty_slot_number() is None

    # ----------- get_slot / get_entry -----------
    def test_get_slot_returns_match(self):
        p = make_position(("10", "30000"))
        s = p.get_slot(1)
        assert s is not None
        assert s.state is SlotState.FILLED

    def test_get_slot_returns_none_when_out_of_range(self):
        p = make_position(("10", "30000"))
        assert p.get_slot(99) is None

    def test_get_entry_returns_filled_entry(self):
        p = make_position(("14", "36000"), ("14", "34000"))
        e1 = p.get_entry(1)
        assert e1 is not None
        assert e1.entry_price == Decimal("36000")

    def test_get_entry_none_for_empty_slot(self):
        p = make_position(("10", "30000"))
        assert p.get_entry(3) is None  # slot 3 is EMPTY

    # ----------- split_pnl / split_pnl_pct -----------
    def test_split_pnl_empty_position(self):
        p = Position.empty(make_asset())
        assert p.split_pnl(Decimal("35000")) == {}
        assert p.split_pnl_pct(Decimal("35000")) == {}

    def test_split_pnl_filled_slots(self):
        # slot 1: 14 @ 36000, current 35000 → (35000-36000)*14 = -14000
        # slot 2: 14 @ 34000, current 35000 → (35000-34000)*14 = +14000
        p = make_position(("14", "36000"), ("14", "34000"))
        pnl = p.split_pnl(Decimal("35000"))
        assert pnl == {1: Decimal("-14000"), 2: Decimal("14000")}

    def test_split_pnl_pct_filled_slots(self):
        p = make_position(("14", "36000"), ("14", "34000"))
        pct = p.split_pnl_pct(Decimal("35000"))
        assert pct[1] < 0
        assert pct[2] > 0
        assert pct[1] == (Decimal("35000") - Decimal("36000")) / Decimal("36000") * Decimal(100)
        assert pct[2] == (Decimal("35000") - Decimal("34000")) / Decimal("34000") * Decimal(100)

    def test_max_split_count_property(self):
        p = Position.empty(make_asset(), max_split_count=5)
        assert p.max_split_count == 5


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
def _buy(slot_number: int = 1) -> BuyActionRecord:
    return BuyActionRecord(
        slot_number=slot_number,
        split_level_after=slot_number,
        filled_quantity=Decimal("10"),
        filled_price=Decimal("35000"),
        target_price=Decimal("35000"),
        idempotency_key=f"buy-{slot_number}",
        order_id="ord-1",
        reasoning={"strategy_reason": "buy_split_1"},
    )


def _sell(slot_number: int) -> SellActionRecord:
    return SellActionRecord(
        slot_number=slot_number,
        filled_quantity=Decimal("10"),
        filled_price=Decimal("38500"),
        profit_pct=Decimal("10"),
        idempotency_key=f"sell-{slot_number}",
        order_id=f"ord-s{slot_number}",
        reasoning={"trigger": "profit_target"},
    )


class TestDecision:
    def test_construct_buy_only(self):
        d = Decision(
            timestamp=UTC_NOW,
            asset=make_asset(),
            buy_action=_buy(slot_number=2),
            reasoning={"current_price": "35000"},
        )
        assert d.buy_action is not None
        assert d.buy_action.slot_number == 2
        assert d.skip_reason is None
        assert d.sell_actions == []
        assert d.action_kinds() == ["buy_split_2"]
        assert d.is_skip() is False

    def test_construct_skip(self):
        d = Decision(
            timestamp=UTC_NOW,
            asset=make_asset(),
            skip_reason=SkipReason.STRATEGY_NO_BUY,
            reasoning={"strategy_reason": "skip:no_drop"},
        )
        assert d.is_skip()
        assert d.action_kinds() == ["skip:strategy_no_buy"]

    def test_construct_sells_then_buy(self):
        d = Decision(
            timestamp=UTC_NOW,
            asset=make_asset(),
            sell_actions=[_sell(slot_number=2), _sell(slot_number=4)],
            buy_action=_buy(slot_number=3),
            reasoning={"current_price": "35000"},
        )
        assert d.action_kinds() == [
            "sell_slot_2",
            "sell_slot_4",
            "buy_split_3",
        ]

    def test_skip_with_actions_rejected(self):
        with pytest.raises(ValidationError, match=r"skip_reason"):
            Decision(
                timestamp=UTC_NOW,
                asset=make_asset(),
                buy_action=_buy(),
                skip_reason=SkipReason.STRATEGY_NO_BUY,
                reasoning={"k": "v"},
            )

    def test_empty_decision_rejected(self):
        with pytest.raises(ValidationError, match=r"at least one"):
            Decision(
                timestamp=UTC_NOW,
                asset=make_asset(),
                reasoning={"k": "v"},
            )

    def test_duplicate_sell_slot_rejected(self):
        with pytest.raises(ValidationError, match=r"duplicate slot_numbers"):
            Decision(
                timestamp=UTC_NOW,
                asset=make_asset(),
                sell_actions=[_sell(slot_number=2), _sell(slot_number=2)],
                reasoning={"k": "v"},
            )

    def test_buy_collides_with_sell_rejected(self):
        with pytest.raises(ValidationError, match=r"collides"):
            Decision(
                timestamp=UTC_NOW,
                asset=make_asset(),
                sell_actions=[_sell(slot_number=2)],
                buy_action=_buy(slot_number=2),
                reasoning={"k": "v"},
            )

    def test_naive_timestamp_rejected(self):
        naive = datetime(2026, 4, 30, 6, 0, 0)
        with pytest.raises(ValidationError):
            Decision(
                timestamp=naive,
                asset=make_asset(),
                skip_reason=SkipReason.STRATEGY_NO_BUY,
                reasoning={"k": "v"},
            )

    def test_immutable(self):
        d = Decision(
            timestamp=UTC_NOW,
            asset=make_asset(),
            skip_reason=SkipReason.STRATEGY_NO_BUY,
            reasoning={"k": "v"},
        )
        with pytest.raises(ValidationError):
            d.skip_reason = SkipReason.MARKET_CLOSED


class TestSellActionRecord:
    def test_construct_happy_path(self):
        sa = _sell(slot_number=3)
        assert sa.slot_number == 3
        assert sa.filled_quantity == Decimal("10")
        assert sa.profit_pct == Decimal("10")

    def test_negative_profit_pct_allowed(self):
        # Sells at a loss are technically possible (Phase 1+ stop loss); the
        # ValueObject must not reject negative profit_pct.
        sa = SellActionRecord(
            slot_number=1,
            filled_quantity=Decimal("10"),
            filled_price=Decimal("30000"),
            profit_pct=Decimal("-5"),
            idempotency_key="k",
            reasoning={},
        )
        assert sa.profit_pct == Decimal("-5")

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            SellActionRecord(
                slot_number=1,
                filled_quantity=Decimal(0),
                filled_price=Decimal("30000"),
                profit_pct=Decimal(0),
                idempotency_key="k",
                reasoning={},
            )


class TestBuyActionRecord:
    def test_construct_happy_path(self):
        ba = _buy(slot_number=4)
        assert ba.slot_number == 4
        assert ba.split_level_after == 4
        assert ba.target_price == Decimal("35000")

    def test_zero_target_price_rejected(self):
        with pytest.raises(ValidationError):
            BuyActionRecord(
                slot_number=1,
                split_level_after=1,
                filled_quantity=Decimal("10"),
                filled_price=Decimal("30000"),
                target_price=Decimal(0),
                idempotency_key="k",
                reasoning={},
            )


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
# PositionValuation
# ---------------------------------------------------------------------------
class TestPositionValuation:
    def _valuation(self, **overrides):
        a = make_asset()
        base = {
            "asset": a,
            "quantity": Decimal("10"),
            "avg_price": Decimal("35000"),
            "market_price": Decimal("36000"),
            "market_value": Money(amount=Decimal("360000"), currency=Currency.KRW),
            "unrealized_pnl": Money(amount=Decimal("10000"), currency=Currency.KRW),
            "split_level": 1,
        }
        base.update(overrides)
        return PositionValuation(**base)

    def test_construct_happy_path(self):
        v = self._valuation()
        assert v.asset.fqn == "KRX:069500"
        assert v.market_value.amount == Decimal("360000")
        assert v.unrealized_pnl.amount == Decimal("10000")

    def test_market_value_must_match_quantity_times_market_price(self):
        with pytest.raises(ValidationError, match="market_value"):
            self._valuation(
                market_value=Money(amount=Decimal("999"), currency=Currency.KRW),
            )

    def test_unrealized_pnl_must_match_formula(self):
        with pytest.raises(ValidationError, match="unrealized_pnl"):
            self._valuation(
                unrealized_pnl=Money(amount=Decimal("999"), currency=Currency.KRW),
            )

    def test_market_value_currency_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="market_value"):
            self._valuation(
                market_value=Money(amount=Decimal("360000"), currency=Currency.USD),
            )

    def test_unrealized_pnl_currency_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="unrealized_pnl"):
            self._valuation(
                unrealized_pnl=Money(amount=Decimal("10000"), currency=Currency.USD),
            )

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            self._valuation(
                quantity=Decimal("0"),
                market_value=Money(amount=Decimal("0"), currency=Currency.KRW),
                unrealized_pnl=Money(amount=Decimal("0"), currency=Currency.KRW),
            )

    def test_zero_market_price_rejected(self):
        with pytest.raises(ValidationError):
            self._valuation(market_price=Decimal("0"))

    def test_split_level_negative_rejected(self):
        with pytest.raises(ValidationError):
            self._valuation(split_level=-1)

    def test_split_level_above_seven_rejected(self):
        with pytest.raises(ValidationError):
            self._valuation(split_level=8)

    def test_split_level_zero_allowed_partial_only(self):
        # partial-only Position has split_level=0 yet quantity>0; valuation OK
        v = self._valuation(split_level=0)
        assert v.split_level == 0

    def test_unrealized_pnl_pct_property(self):
        v = self._valuation()
        # (36000 - 35000) / 35000 * 100 = 2.857142...
        expected = (Decimal("36000") - Decimal("35000")) / Decimal("35000") * Decimal(100)
        assert v.unrealized_pnl_pct == expected

    def test_unrealized_pnl_pct_negative_when_market_below_avg(self):
        v = self._valuation(
            market_price=Decimal("34000"),
            market_value=Money(amount=Decimal("340000"), currency=Currency.KRW),
            unrealized_pnl=Money(amount=Decimal("-10000"), currency=Currency.KRW),
        )
        assert v.unrealized_pnl_pct < 0

    def test_immutable(self):
        v = self._valuation()
        with pytest.raises(ValidationError):
            v.market_price = Decimal("37000")

    # ---- from_position factory ----
    def test_from_position_factory(self):
        position = make_position(("10", "35000"))
        v = PositionValuation.from_position(position, market_price=Decimal("36000"))
        assert v.market_price == Decimal("36000")
        assert v.market_value.amount == Decimal("360000")
        assert v.unrealized_pnl.amount == Decimal("10000")
        assert v.split_level == 1

    def test_from_position_rejects_empty_quantity(self):
        a = make_asset()
        empty = Position.empty(a)
        with pytest.raises(ValueError, match="non-positive"):
            PositionValuation.from_position(empty, market_price=Decimal("36000"))

    def test_from_position_aggregates_multiple_filled_slots(self):
        # Phase 0.5 (ADR 0002 §3.2): Position.quantity equals the sum of
        # FILLED slot quantities exactly. PositionValuation must reflect
        # that aggregate, not just the first slot. Use clean numbers so
        # the weighted-average is exact in Decimal (no precision drift).
        # Slot 1: 10 @ 35000, Slot 2: 10 @ 31000 → avg = 33000 exactly.
        position = make_position(("10", "35000"), ("10", "31000"))
        v = PositionValuation.from_position(position, market_price=Decimal("36000"))
        assert v.quantity == Decimal("20")
        assert v.market_value.amount == Decimal("720000")  # 20 * 36000
        # PnL = (36000 - 33000) * 20 = 60000
        assert v.unrealized_pnl.amount == Decimal("60000")


# ---------------------------------------------------------------------------
# PortfolioSnapshot
# ---------------------------------------------------------------------------
class TestPortfolioSnapshot:
    def _val(
        self,
        *,
        code: str = "069500",
        quantity: str = "10",
        avg_price: str = "35000",
        market_price: str = "36000",
        split_level: int = 1,
    ) -> PositionValuation:
        a = make_asset(code=code)
        qty = Decimal(quantity)
        avg = Decimal(avg_price)
        mp = Decimal(market_price)
        return PositionValuation(
            asset=a,
            quantity=qty,
            avg_price=avg,
            market_price=mp,
            market_value=Money(amount=qty * mp, currency=Currency.KRW),
            unrealized_pnl=Money(
                amount=(mp - avg) * qty, currency=Currency.KRW
            ),
            split_level=split_level,
        )

    def _build(self, **overrides):
        defaults = {
            "snapshot_date": date(2026, 4, 30),
            "snapshot_at": UTC_NOW,
            "initial_capital": Money(amount=Decimal("4000000"), currency=Currency.KRW),
            "cash": Money(amount=Decimal("3640000"), currency=Currency.KRW),
            "valuations": [self._val()],  # market_value 360000
        }
        defaults.update(overrides)
        return PortfolioSnapshot.build(**defaults)

    # ---- happy paths ----
    def test_build_with_one_valuation(self):
        snap = self._build()
        assert snap.total_market_value.amount == Decimal("360000")
        assert snap.total_value.amount == Decimal("4000000")  # 3640000 + 360000
        assert snap.total_cost_basis.amount == Decimal("350000")  # 10 * 35000
        assert snap.total_unrealized_pnl.amount == Decimal("10000")

    def test_build_with_no_valuations_cash_only(self):
        snap = self._build(
            cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            valuations=[],
        )
        assert snap.total_market_value.amount == Decimal("0")
        assert snap.total_value.amount == Decimal("4000000")
        assert snap.total_cost_basis.amount == Decimal("0")
        assert snap.total_unrealized_pnl.amount == Decimal("0")

    def test_build_with_multiple_valuations(self):
        v1 = self._val(code="069500", quantity="10", avg_price="35000", market_price="36000")
        v2 = self._val(code="105190", quantity="5", avg_price="20000", market_price="22000")
        snap = self._build(
            cash=Money(amount=Decimal("3530000"), currency=Currency.KRW),
            valuations=[v1, v2],
        )
        # total_market_value = 360000 + 110000 = 470000
        assert snap.total_market_value.amount == Decimal("470000")
        # total_cost_basis = 350000 + 100000 = 450000
        assert snap.total_cost_basis.amount == Decimal("450000")
        # total_unrealized_pnl = 10000 + 10000 = 20000
        assert snap.total_unrealized_pnl.amount == Decimal("20000")

    # ---- invariants ----
    def test_total_market_value_mismatch_rejected(self):
        v = self._val()
        with pytest.raises(ValidationError, match="total_market_value"):
            PortfolioSnapshot(
                snapshot_date=date(2026, 4, 30),
                snapshot_at=UTC_NOW,
                initial_capital=Money(amount=Decimal("4000000"), currency=Currency.KRW),
                cash=Money(amount=Decimal("3640000"), currency=Currency.KRW),
                valuations=[v],
                total_market_value=Money(amount=Decimal("999"), currency=Currency.KRW),
                total_value=Money(amount=Decimal("3640999"), currency=Currency.KRW),
                total_cost_basis=Money(amount=Decimal("350000"), currency=Currency.KRW),
                total_unrealized_pnl=Money(amount=Decimal("-349001"), currency=Currency.KRW),
            )

    def test_total_value_mismatch_rejected(self):
        v = self._val()
        with pytest.raises(ValidationError, match="total_value"):
            PortfolioSnapshot(
                snapshot_date=date(2026, 4, 30),
                snapshot_at=UTC_NOW,
                initial_capital=Money(amount=Decimal("4000000"), currency=Currency.KRW),
                cash=Money(amount=Decimal("3640000"), currency=Currency.KRW),
                valuations=[v],
                total_market_value=Money(amount=Decimal("360000"), currency=Currency.KRW),
                total_value=Money(amount=Decimal("999"), currency=Currency.KRW),  # wrong
                total_cost_basis=Money(amount=Decimal("350000"), currency=Currency.KRW),
                total_unrealized_pnl=Money(amount=Decimal("10000"), currency=Currency.KRW),
            )

    def test_total_cost_basis_mismatch_rejected(self):
        v = self._val()
        with pytest.raises(ValidationError, match="total_cost_basis"):
            PortfolioSnapshot(
                snapshot_date=date(2026, 4, 30),
                snapshot_at=UTC_NOW,
                initial_capital=Money(amount=Decimal("4000000"), currency=Currency.KRW),
                cash=Money(amount=Decimal("3640000"), currency=Currency.KRW),
                valuations=[v],
                total_market_value=Money(amount=Decimal("360000"), currency=Currency.KRW),
                total_value=Money(amount=Decimal("4000000"), currency=Currency.KRW),
                total_cost_basis=Money(amount=Decimal("999"), currency=Currency.KRW),
                total_unrealized_pnl=Money(amount=Decimal("10000"), currency=Currency.KRW),
            )

    def test_total_unrealized_pnl_mismatch_rejected(self):
        v = self._val()
        with pytest.raises(ValidationError, match="total_unrealized_pnl"):
            PortfolioSnapshot(
                snapshot_date=date(2026, 4, 30),
                snapshot_at=UTC_NOW,
                initial_capital=Money(amount=Decimal("4000000"), currency=Currency.KRW),
                cash=Money(amount=Decimal("3640000"), currency=Currency.KRW),
                valuations=[v],
                total_market_value=Money(amount=Decimal("360000"), currency=Currency.KRW),
                total_value=Money(amount=Decimal("4000000"), currency=Currency.KRW),
                total_cost_basis=Money(amount=Decimal("350000"), currency=Currency.KRW),
                total_unrealized_pnl=Money(amount=Decimal("999"), currency=Currency.KRW),
            )

    def test_currency_mismatch_rejected_initial_capital(self):
        with pytest.raises(ValidationError, match="initial_capital"):
            self._build(
                initial_capital=Money(amount=Decimal("4000000"), currency=Currency.USD),
            )

    def test_currency_mismatch_rejected_valuation_asset(self):
        a_usd = Asset(
            code="SPY",
            exchange=Exchange.KRX,
            asset_class=AssetClass.KR_ETF,
            currency=Currency.USD,
            name="SPY",
            tick_size=Decimal("1"),
            lot_size=Decimal("1"),
        )
        v_usd = PositionValuation(
            asset=a_usd,
            quantity=Decimal("10"),
            avg_price=Decimal("400"),
            market_price=Decimal("420"),
            market_value=Money(amount=Decimal("4200"), currency=Currency.USD),
            unrealized_pnl=Money(amount=Decimal("200"), currency=Currency.USD),
            split_level=1,
        )
        with pytest.raises(ValidationError, match="valuation"):
            self._build(valuations=[v_usd])

    def test_initial_capital_zero_rejected(self):
        with pytest.raises(ValidationError, match="initial_capital"):
            self._build(
                initial_capital=Money(amount=Decimal("0"), currency=Currency.KRW),
            )

    def test_naive_snapshot_at_rejected(self):
        with pytest.raises(ValidationError):
            self._build(snapshot_at=datetime(2026, 4, 30, 6, 0, 0))

    # ---- total_return_pct property ----
    def test_total_return_pct_zero_when_value_equals_capital(self):
        snap = self._build(
            cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            valuations=[],
        )
        assert snap.total_return_pct == Decimal("0")

    def test_total_return_pct_positive(self):
        snap = self._build(
            cash=Money(amount=Decimal("3690000"), currency=Currency.KRW),
            valuations=[
                self._val(quantity="10", avg_price="35000", market_price="40000"),
            ],
        )
        # total_value = 3690000 + 10*40000 = 4090000
        # initial_capital = 4000000
        # return_pct = 90000 / 4000000 * 100 = 2.25
        assert snap.total_return_pct == Decimal("2.25")

    def test_total_return_pct_negative(self):
        snap = self._build(
            cash=Money(amount=Decimal("3500000"), currency=Currency.KRW),
            valuations=[
                self._val(quantity="10", avg_price="35000", market_price="30000"),
            ],
        )
        # total_value = 3500000 + 300000 = 3800000
        # return_pct = (3800000 - 4000000) / 4000000 * 100 = -5
        assert snap.total_return_pct == Decimal("-5")

    def test_immutable(self):
        snap = self._build(valuations=[])
        with pytest.raises(ValidationError):
            snap.snapshot_date = date(2026, 5, 1)

    def test_aggregate_valuation_reflected_in_snapshot_totals(self):
        # ADR §8.6: PositionValuation flows through into snapshot totals
        # using the full position quantity (Phase 0.5 equality invariant —
        # no partial-fill carry).
        a = make_asset()
        v = PositionValuation(
            asset=a,
            quantity=Decimal("20"),
            avg_price=Decimal("35000"),
            market_price=Decimal("36000"),
            market_value=Money(amount=Decimal("720000"), currency=Currency.KRW),
            unrealized_pnl=Money(amount=Decimal("20000"), currency=Currency.KRW),
            split_level=1,
        )
        snap = PortfolioSnapshot.build(
            snapshot_date=date(2026, 4, 30),
            snapshot_at=UTC_NOW,
            initial_capital=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            cash=Money(amount=Decimal("3280000"), currency=Currency.KRW),
            valuations=[v],
        )
        assert snap.total_market_value.amount == Decimal("720000")
        assert snap.total_value.amount == Decimal("4000000")  # 3280000 + 720000
        # Partial fill is therefore valued; ADR §8.6 option A confirmed.


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
