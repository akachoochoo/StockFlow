"""Unit tests for src.domain.strategies.support_level (Phase 0.8 / ADR 0004).

Pure domain logic — no mocks. Tests cover all 8 ADR §2.2.6 cases plus
edge cases (max_split_per_day, max_split_count, quantity, balance,
first_buy_excluded).

OHLCV fixtures are 60+ trading days so slot 5 (recent_high(60)) is
always evaluable (ADR 0004 §4.5 δ decision).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    Market,
    Money,
    Position,
    Price,
    SkipReason,
    SplitEntry,
    SupportSlot,
)
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.domain.strategies.support_level import SupportLevelStrategy

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
TODAY = date(2026, 4, 30)
YESTERDAY = date(2026, 4, 29)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _asset(
    code: str = "069500",
    asset_class: AssetClass = AssetClass.KR_ETF,
    currency: Currency = Currency.KRW,
    lot_size: str = "1",
) -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=asset_class,
        currency=currency,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal(lot_size),
        listed_at=date(2002, 10, 14),
    )


def _config(
    max_split_count: int = 5,
    per_split_amount_krw: str = "1000000",
    max_split_per_day: int = 1,
) -> SplitStrategyConfig:
    # drop_threshold_pct retained for re-use; SupportLevelStrategy ignores it
    # (ADR 0004 §4.7).
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal("5"),
        max_split_count=max_split_count,
        per_split_amount=Money(
            amount=Decimal(per_split_amount_krw), currency=Currency.KRW
        ),
        max_split_per_day=max_split_per_day,
    )


def _balance(amount_krw: str = "100000000") -> Balance:
    return Balance(cash=Money(amount=Decimal(amount_krw), currency=Currency.KRW))


def _price(value: str, asset: Asset | None = None) -> Price:
    return Price(asset=asset or _asset(), value=Decimal(value), timestamp=UTC_NOW)


def _make_ohlcv_history(
    closes: list[Decimal | str | int], asset: Asset | None = None
) -> list[OHLCV]:
    """Build OHLCV bars with all OHLC == close for clean indicator fixtures.

    ``trade_date`` advances by 1 calendar day per bar (last bar is one
    day before TODAY). Caller responsibility: provide enough closes so
    indicator windows are sufficient (ADR 0004 §4.5 δ — 60+ for slot 5).
    """
    a = asset or _asset()
    n = len(closes)
    bars: list[OHLCV] = []
    for i, c in enumerate(closes):
        close_dec = Decimal(str(c)) if not isinstance(c, Decimal) else c
        # last bar = TODAY - 1 day
        d = TODAY - timedelta(days=n - i)
        bars.append(
            OHLCV(
                asset=a,
                trade_date=d,
                open=close_dec,
                high=close_dec,
                low=close_dec,
                close=close_dec,
                volume=Decimal("1000"),
            )
        )
    return bars


def _flat_history(close: str, n: int = 70) -> list[OHLCV]:
    """N bars with all closes == ``close``. MA = recent_high = close."""
    return _make_ohlcv_history([close] * n)


def _filled_position(
    asset: Asset,
    *,
    quantity: str,
    avg_price: str,
    slot_number: int,
    entry_date: date | None = None,
    max_split_count: int = 5,
) -> Position:
    """Position with one FILLED SupportSlot at ``slot_number``."""
    qty = Decimal(quantity)
    avg = Decimal(avg_price)
    d = entry_date or YESTERDAY
    entry = SplitEntry(
        split_number=slot_number,
        entry_date=d,
        quantity=qty,
        entry_price=avg,
        idempotency_key=f"k{slot_number}",
    )
    slots = [
        SupportSlot.empty(slot_number=i) if i != slot_number
        else SupportSlot.filled(entry=entry)
        for i in range(1, max_split_count + 1)
    ]
    return Position(
        asset=asset,
        quantity=qty,
        avg_price=avg,
        split_level=1,
        last_buy_at=UTC_NOW,
        slots=slots,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestSupportLevelFirstBuy:
    def test_first_buy_when_position_none(self):
        # ADR §2.2.1 슬롯 1 — position is None → slot 1 fires.
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=None,
            current_price=_price("30000"),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is not None
        assert result.buy.slot_number == 1
        assert result.buy.reasoning["slot_label"] == "first_buy"

    def test_first_buy_when_split_level_zero(self):
        # Position exists with all EMPTY slots → slot 1 fires.
        a = _asset()
        p = Position.empty_with_support_slots(a, max_split_count=5)
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=p,
            current_price=_price("30000", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is not None
        assert result.buy.slot_number == 1


class TestSupportLevelIndicatorTriggers:
    def test_ma5_breach_triggers_slot_2(self):
        # split_level=1 (slot 2 already filled), candidate slots = {1,3,4,5}
        # but slot 1 only fires when split_level==0. Slot 3 (MA10), 4 (MA20),
        # 5 (recent_high(60)) only — slot 2 is FILLED so excluded.
        # We need slot 2 EMPTY → fill slot 1 instead.
        a = _asset()
        # Fill slot 1 → split_level=1, slot 2~5 EMPTY
        position = _filled_position(
            a, quantity="10", avg_price="30000", slot_number=1
        )
        # Closes flat at 30000 → MA5 = MA10 = MA20 = recent_high = 30000.
        # current_price = 29999 < 30000 → all of slots 2/3/4/5 trigger.
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("29999", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        # Smallest slot_number wins → slot 2.
        assert result.buy is not None
        assert result.buy.slot_number == 2
        assert result.buy.reasoning["slot_label"] == "MA5"

    def test_ma_at_value_no_trigger(self):
        # current == MA → strict less than fails (이탈 안 됨, ADR §2.2.3).
        a = _asset()
        position = _filled_position(
            a, quantity="10", avg_price="30000", slot_number=1
        )
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("30000", a),  # == MA5/MA10/MA20/recent_high
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.ALL_SLOTS_EMPTY_NO_TRIGGER

    def test_ma_above_value_no_trigger(self):
        # current > MA → not "이탈".
        a = _asset()
        position = _filled_position(
            a, quantity="10", avg_price="30000", slot_number=1
        )
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("30100", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.ALL_SLOTS_EMPTY_NO_TRIGGER

    def test_recent_high_only_triggers_slot_5(self):
        # MA5/10/20 all = 30000, but recent_high(60) = 31500.
        # current = 30100 → above MAs (no trigger 2/3/4) but below recent_high
        # (trigger 5).
        a = _asset()
        position = _filled_position(
            a, quantity="10", avg_price="30000", slot_number=1
        )
        # 60 closes: first 30 = 30000, one spike to 31500, then 30000s.
        closes = ["30000"] * 30 + ["31500"] + ["30000"] * 39
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("30100", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_make_ohlcv_history(closes, a),
        )
        assert result.buy is not None
        assert result.buy.slot_number == 5
        assert result.buy.reasoning["slot_label"] == "recent_high(60)"

    def test_priority_smallest_slot_number(self):
        # MA5 < MA10 < MA20 < recent_high — current breaks all of them.
        # smallest slot wins (slot 2).
        a = _asset()
        position = _filled_position(
            a, quantity="10", avg_price="30000", slot_number=1
        )
        # Strictly increasing closes — recent values higher → MA5 highest.
        closes = [str(30000 + i * 50) for i in range(70)]  # 30000..33450
        # MA5 ~ avg of last 5 ~ 33300
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("30000", a),  # below all averages
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_make_ohlcv_history(closes, a),
        )
        assert result.buy is not None
        assert result.buy.slot_number == 2  # MA5

    def test_excluded_slots_skip(self):
        # Phase 0.5 §5.5 일관 — exclude slot 2 → slot 3 wins.
        a = _asset()
        position = _filled_position(
            a, quantity="10", avg_price="30000", slot_number=1
        )
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("29999", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
            excluded_slot_numbers={2},
        )
        assert result.buy is not None
        assert result.buy.slot_number == 3  # MA10

    def test_first_buy_excluded_falls_through(self):
        # Slot 1 in excluded but split_level == 0 → first-buy bypass denied.
        # Slots 2~5 evaluated against indicators.
        a = _asset()
        p = Position.empty_with_support_slots(a, max_split_count=5)
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=p,
            current_price=_price("29999", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
            excluded_slot_numbers={1},
        )
        # Falls through to slots 2~5; smallest = 2 (MA5).
        assert result.buy is not None
        assert result.buy.slot_number == 2

    def test_insufficient_data_returns_none(self):
        # Only 4 closes — slots 2 (MA5) / 3 (MA10) / 4 (MA20) / 5 (60)
        # all return None.
        a = _asset()
        position = _filled_position(
            a, quantity="10", avg_price="30000", slot_number=1
        )
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("29999", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_make_ohlcv_history(["30000"] * 4, a),
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.INSUFFICIENT_HISTORICAL_DATA


class TestSupportLevelGuards:
    def test_max_split_per_day(self):
        # split_level=1 with entry_date=TODAY → today_buys=1
        a = _asset()
        position = _filled_position(
            a,
            quantity="10",
            avg_price="30000",
            slot_number=1,
            entry_date=TODAY,
        )
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("29999", a),
            balance=_balance(),
            config=_config(max_split_per_day=1),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.MAX_SPLIT_PER_DAY_REACHED

    def test_max_split_count_reached(self):
        # All max_split_count=2 slots FILLED → STRATEGY_NO_BUY.
        a = _asset()
        e1 = SplitEntry(
            split_number=1,
            entry_date=YESTERDAY,
            quantity=Decimal("5"),
            entry_price=Decimal("30000"),
            idempotency_key="k1",
        )
        e2 = SplitEntry(
            split_number=2,
            entry_date=YESTERDAY,
            quantity=Decimal("5"),
            entry_price=Decimal("30000"),
            idempotency_key="k2",
        )
        slots = [SupportSlot.filled(entry=e1), SupportSlot.filled(entry=e2)]
        position = Position(
            asset=a,
            quantity=Decimal("10"),
            avg_price=Decimal("30000"),
            split_level=2,
            last_buy_at=UTC_NOW,
            slots=slots,
        )
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=position,
            current_price=_price("29999", a),
            balance=_balance(),
            config=_config(max_split_count=2),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.STRATEGY_NO_BUY

    def test_quantity_too_small(self):
        # per_split_amount < target_price → quantity floors to 0.
        a = _asset(lot_size="1")
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=None,
            current_price=_price("30000", a),
            balance=_balance(),
            config=_config(per_split_amount_krw="1000"),  # < 30000
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.QUANTITY_TOO_SMALL

    def test_insufficient_balance(self):
        # First-buy slot 1 — actual_cost > balance → INSUFFICIENT_BALANCE.
        a = _asset()
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=None,
            current_price=_price("30000", a),
            balance=_balance(amount_krw="100"),  # too small
            config=_config(per_split_amount_krw="1000000"),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.INSUFFICIENT_BALANCE

    def test_all_excluded_returns_excluded_skip(self):
        # All EMPTY slots excluded by same-day sell.
        a = _asset()
        p = Position.empty_with_support_slots(a, max_split_count=5)
        strategy = SupportLevelStrategy()
        result = strategy.evaluate(
            position=p,
            current_price=_price("29999", a),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            ohlcv_history=_flat_history("30000"),
            excluded_slot_numbers={1, 2, 3, 4, 5},
        )
        assert result.buy is None
        assert (
            result.skip_reason
            is SkipReason.ALL_EMPTY_SLOTS_EXCLUDED_BY_SAME_DAY_SELL
        )


class TestSupportLevelPreconditions:
    def test_position_asset_mismatch_raises(self):
        a1 = _asset(code="069500")
        a2 = _asset(code="132030")
        p = Position.empty_with_support_slots(a1)
        strategy = SupportLevelStrategy()
        with pytest.raises(ValueError, match=r"position\.asset"):
            strategy.evaluate(
                position=p,
                current_price=_price("30000", a2),
                balance=_balance(),
                config=_config(),
                today=TODAY,
                ohlcv_history=_flat_history("30000", n=70),
            )

    def test_currency_mismatch_raises(self):
        a = _asset(currency=Currency.USD)
        strategy = SupportLevelStrategy()
        with pytest.raises(ValueError, match=r"per_split_amount\.currency"):
            strategy.evaluate(
                position=None,
                current_price=_price("30000", a),
                balance=Balance(
                    cash=Money(amount=Decimal("100000"), currency=Currency.USD)
                ),
                config=_config(),  # KRW
                today=TODAY,
                ohlcv_history=_flat_history("30000"),
            )

    def test_balance_currency_mismatch_raises(self):
        a = _asset()  # KRW
        bad_balance = Balance(
            cash=Money(amount=Decimal("100000000"), currency=Currency.USD)
        )
        strategy = SupportLevelStrategy()
        with pytest.raises(ValueError, match=r"balance\.cash\.currency"):
            strategy.evaluate(
                position=None,
                current_price=_price("30000", a),
                balance=bad_balance,
                config=_config(),
                today=TODAY,
                ohlcv_history=_flat_history("30000"),
            )
