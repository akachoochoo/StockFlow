"""Unit tests for src.domain.strategies.price_drop (Phase 0.5).

Domain logic — pure functions, no mocks beyond the injected
ReentryPriceStrategyPort. Tests use HybridTimeBasedReentry for the
"Phase 0 D fallback (avg_price-anchor)" coverage and a stub policy for
edge cases (insufficient data → None).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    Money,
    Position,
    Price,
    SkipReason,
    SplitEntry,
    SplitSlot,
)
from src.domain.strategies.price_drop import (
    BuyDecision,
    BuyEvaluationResult,
    PriceDropStrategy,
    SplitStrategyConfig,
)
from src.domain.strategies.reentry import HybridTimeBasedReentry

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
TODAY = date(2026, 4, 30)
YESTERDAY = date(2026, 4, 29)


def _asset(
    code: str = "069500",
    asset_class: AssetClass = AssetClass.KR_ETF,
    currency: Currency = Currency.KRW,
    lot_size: str = "1",
) -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=asset_class,
        currency=currency,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal(lot_size),
    )


def _config(
    drop_threshold_pct: str = "7.0",
    max_split_count: int = 7,
    per_split_amount_krw: str = "1000000",
) -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal(drop_threshold_pct),
        max_split_count=max_split_count,
        per_split_amount=Money(
            amount=Decimal(per_split_amount_krw), currency=Currency.KRW
        ),
    )


def _balance(amount_krw: str = "100000000") -> Balance:
    return Balance(cash=Money(amount=Decimal(amount_krw), currency=Currency.KRW))


def _price(value: str, asset: Asset | None = None) -> Price:
    return Price(asset=asset or _asset(), value=Decimal(value), timestamp=UTC_NOW)


def _strategy() -> PriceDropStrategy:
    """Default strategy fixture using HybridTimeBasedReentry — its
    fresh-slot fallback (avg_price) preserves Phase 0 drop semantics
    so existing scenarios keep working."""
    return PriceDropStrategy(reentry=HybridTimeBasedReentry(cooldown_days=60))


def _filled_position(
    asset: Asset,
    *,
    quantity: str,
    avg_price: str,
    split_level: int,
    entry_date: date | None = None,
    max_split_count: int = 7,
) -> Position:
    qty = Decimal(quantity)
    avg = Decimal(avg_price)
    d = entry_date or YESTERDAY
    if split_level == 0:
        return Position.empty(asset, max_split_count=max_split_count)

    base = qty // Decimal(split_level)
    remainder = qty - base * Decimal(split_level - 1)
    entries: list[SplitEntry] = [
        SplitEntry(
            split_number=i,
            entry_date=d,
            quantity=base,
            entry_price=avg,
            idempotency_key=f"k{i}",
        )
        for i in range(1, split_level)
    ]
    entries.append(
        SplitEntry(
            split_number=split_level,
            entry_date=d,
            quantity=remainder,
            entry_price=avg,
            idempotency_key=f"k{split_level}",
        )
    )
    slots: list[SplitSlot] = [SplitSlot.filled(entry=e) for e in entries]
    slots.extend(
        SplitSlot.empty(slot_number=i)
        for i in range(split_level + 1, max_split_count + 1)
    )
    return Position(
        asset=asset,
        quantity=qty,
        avg_price=avg,
        split_level=split_level,
        last_buy_at=UTC_NOW,
        slots=slots,
    )


# ---------------------------------------------------------------------------
# BuyDecision / BuyEvaluationResult invariants
# ---------------------------------------------------------------------------
class TestBuyDecisionAndResult:
    def test_buy_decision_construct(self):
        bd = BuyDecision(
            slot_number=2,
            target_quantity=Decimal("28"),
            target_price=Decimal("32000"),
            reasoning={"trigger_price": "33250"},
        )
        assert bd.slot_number == 2

    def test_evaluation_result_must_have_xor(self):
        # Both set → ValidationError
        with pytest.raises(ValidationError, match=r"exactly one"):
            BuyEvaluationResult(
                buy=BuyDecision(
                    slot_number=1,
                    target_quantity=Decimal("10"),
                    target_price=Decimal("30000"),
                    reasoning={},
                ),
                skip_reason=SkipReason.STRATEGY_NO_BUY,
                reasoning={},
            )

    def test_evaluation_result_must_have_at_least_one(self):
        with pytest.raises(ValidationError, match=r"exactly one"):
            BuyEvaluationResult(buy=None, skip_reason=None, reasoning={})


# ---------------------------------------------------------------------------
# First-buy bypass (position is None / split_level == 0)
# ---------------------------------------------------------------------------
class TestFirstBuy:
    def setup_method(self):
        self.strategy = _strategy()
        self.asset = _asset()

    def test_no_position_triggers_slot_one(self):
        # 1,000,000 / 35,000 = 28.57... → floor → 28
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.skip_reason is None
        assert result.buy is not None
        assert result.buy.slot_number == 1
        assert result.buy.target_quantity == Decimal("28")
        assert result.buy.target_price == Decimal("35000")

    def test_empty_position_triggers_slot_one(self):
        empty = Position.empty(self.asset)
        result = self.strategy.evaluate(
            position=empty,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is not None
        assert result.buy.slot_number == 1

    def test_target_price_rounded_to_tick(self):
        # current 35003 with tick=5 → target=35000
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35003", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is not None
        assert result.buy.target_price == Decimal("35000")


# ---------------------------------------------------------------------------
# Subsequent split using HybridTimeBasedReentry's avg_price fallback
# (preserves Phase 0 drop-from-avg semantics for fresh slots)
# ---------------------------------------------------------------------------
class TestSubsequentSplit:
    def setup_method(self):
        self.strategy = _strategy()
        self.asset = _asset()
        self.position = _filled_position(
            self.asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
        )

    def test_drop_above_threshold_triggers_next_split(self):
        # Hybrid's fresh-slot fallback: trigger = avg(35000) * 0.93 = 32550
        # current=32000 ≤ 32550 → fire on slot 2
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("32000", self.asset),
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
        )
        assert result.buy is not None
        assert result.buy.slot_number == 2
        # 1,000,000 / 32,000 = 31.25 → floor → 31
        assert result.buy.target_quantity == Decimal("31")
        assert result.buy.target_price == Decimal("32000")

    def test_drop_at_exact_threshold_triggers_next_split(self):
        # avg=35000, drop_pct=7 → trigger=32550. current=32550 → fires.
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("32550", self.asset),
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
        )
        assert result.buy is not None
        assert result.buy.slot_number == 2

    def test_drop_below_threshold_skips(self):
        # current=33500 > trigger=32550 → no fire
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("33500", self.asset),
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.STRATEGY_NO_BUY

    def test_price_above_avg_skips(self):
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("36000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.STRATEGY_NO_BUY

    def test_max_split_reached_skips(self):
        position = _filled_position(
            self.asset,
            quantity="100",
            avg_price="30000",
            split_level=7,
        )
        result = self.strategy.evaluate(
            position=position,
            current_price=_price("20000", self.asset),
            balance=_balance(),
            config=_config(max_split_count=7),
            today=TODAY,
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.STRATEGY_NO_BUY
        assert result.reasoning.get("max_split_reached") == "True"


# ---------------------------------------------------------------------------
# Slot-priority + insufficient-data routing — uses a stub reentry policy
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _AlwaysNoneReentry:
    """Stub reentry policy that returns None for every slot — except
    when split_level==0 (then current_price for first-buy bypass)."""

    def get_trigger_price(self, *, slot, position, current_price, drop_threshold_pct, as_of) -> Decimal | None:
        if position.split_level == 0:
            return current_price
        return None


@dataclass(frozen=True)
class _PartialNoneReentry:
    """Returns None for slot_number < 4, MA-like trigger for >=4."""

    def get_trigger_price(self, *, slot, position, current_price, drop_threshold_pct, as_of) -> Decimal | None:
        if position.split_level == 0:
            return current_price
        if slot.slot_number < 4:
            return None
        return current_price * (Decimal(2))  # absurdly permissive — always fires


class TestSlotPriorityWithPartialTriggers:
    def test_priority_drop_strategy_handles_none_trigger(self):
        # All EMPTY slots return None → INSUFFICIENT_HISTORICAL_DATA
        strategy = PriceDropStrategy(reentry=_AlwaysNoneReentry())
        asset = _asset()
        position = _filled_position(
            asset, quantity="10", avg_price="35000", split_level=1
        )
        result = strategy.evaluate(
            position=position,
            current_price=_price("32000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.INSUFFICIENT_HISTORICAL_DATA

    def test_slot_priority_with_partial_triggers(self):
        # Slots 2, 3 → None; slots 4-7 trigger. Smallest qualified = slot 4.
        strategy = PriceDropStrategy(reentry=_PartialNoneReentry())
        asset = _asset()
        position = _filled_position(
            asset, quantity="10", avg_price="35000", split_level=1
        )
        result = strategy.evaluate(
            position=position,
            current_price=_price("32000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is not None
        assert result.buy.slot_number == 4

    def test_decision_with_insufficient_historical_data_skip(self):
        # Mixed: some None, some don't qualify (current too high) → STRATEGY_NO_BUY
        @dataclass(frozen=True)
        class _MixedReentry:
            def get_trigger_price(self, *, slot, position, current_price, drop_threshold_pct, as_of):
                if position.split_level == 0:
                    return current_price
                if slot.slot_number == 2:
                    return None
                # All other slots return a trigger that current_price exceeds
                return current_price * Decimal("0.5")  # never fires

        strategy = PriceDropStrategy(reentry=_MixedReentry())
        asset = _asset()
        position = _filled_position(
            asset, quantity="10", avg_price="35000", split_level=1
        )
        result = strategy.evaluate(
            position=position,
            current_price=_price("32000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is None
        # Some slots returned None but not all → STRATEGY_NO_BUY (not INSUFFICIENT)
        assert result.skip_reason is SkipReason.STRATEGY_NO_BUY


# ---------------------------------------------------------------------------
# Quantity / balance constraints
# ---------------------------------------------------------------------------
class TestQuantityConstraints:
    def setup_method(self):
        self.strategy = _strategy()

    def test_quantity_rounds_below_lot_size_skips(self):
        asset = _asset(lot_size="100")
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.QUANTITY_TOO_SMALL

    def test_lot_size_rounding(self):
        asset = _asset(lot_size="10")
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is not None
        assert result.buy.target_quantity == Decimal("20")

    def test_insufficient_balance_skips(self):
        asset = _asset()
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(amount_krw="500000"),
            config=_config(per_split_amount_krw="1000000"),
            today=TODAY,
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.INSUFFICIENT_BALANCE

    def test_balance_exactly_equal_to_cost_buys(self):
        asset = _asset()
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(amount_krw="980000"),
            config=_config(per_split_amount_krw="1000000"),
            today=TODAY,
        )
        assert result.buy is not None


# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------
class TestPreconditions:
    def setup_method(self):
        self.strategy = _strategy()

    def test_position_asset_mismatch_raises(self):
        asset_a = _asset(code="069500")
        asset_b = _asset(code="105190")
        position_a = _filled_position(
            asset_a, quantity="10", avg_price="35000", split_level=1
        )
        with pytest.raises(ValueError, match=r"position\.asset"):
            self.strategy.evaluate(
                position=position_a,
                current_price=_price("35000", asset_b),
                balance=_balance(),
                config=_config(),
                today=TODAY,
            )

    def test_config_currency_mismatch_raises(self):
        asset = _asset(currency=Currency.KRW)
        config = SplitStrategyConfig(
            drop_threshold_pct=Decimal("7.0"),
            max_split_count=7,
            per_split_amount=Money(amount=Decimal("1000"), currency=Currency.USD),
        )
        with pytest.raises(ValueError, match=r"config\.per_split_amount\.currency"):
            self.strategy.evaluate(
                position=None,
                current_price=_price("35000", asset),
                balance=_balance(),
                config=config,
                today=TODAY,
            )

    def test_balance_currency_mismatch_raises(self):
        asset = _asset(currency=Currency.KRW)
        balance = Balance(
            cash=Money(amount=Decimal("1000"), currency=Currency.USD)
        )
        with pytest.raises(ValueError, match=r"balance\.cash\.currency"):
            self.strategy.evaluate(
                position=None,
                current_price=_price("35000", asset),
                balance=balance,
                config=_config(),
                today=TODAY,
            )


# ---------------------------------------------------------------------------
# max_split_per_day guard (ADR §7.11)
# ---------------------------------------------------------------------------
class TestMaxSplitPerDay:
    def setup_method(self):
        self.strategy = _strategy()
        self.asset = _asset()

    def test_default_max_split_per_day_is_one(self):
        cfg = SplitStrategyConfig(
            drop_threshold_pct=Decimal("7.0"),
            max_split_count=7,
            per_split_amount=Money(amount=Decimal("1000000"), currency=Currency.KRW),
        )
        assert cfg.max_split_per_day == 1

    def test_max_split_per_day_zero_rejected(self):
        with pytest.raises(ValidationError):
            SplitStrategyConfig(
                drop_threshold_pct=Decimal("7.0"),
                max_split_count=7,
                per_split_amount=Money(amount=Decimal("1000000"), currency=Currency.KRW),
                max_split_per_day=0,
            )

    def test_today_entry_blocks_next_buy_with_default_cap(self):
        position = _filled_position(
            self.asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
            entry_date=TODAY,
        )
        result = self.strategy.evaluate(
            position=position,
            current_price=_price("32000", self.asset),  # would otherwise fire
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is None
        assert result.skip_reason is SkipReason.MAX_SPLIT_PER_DAY_REACHED

    def test_yesterday_entries_do_not_count_against_cap(self):
        position = _filled_position(
            self.asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
        )
        result = self.strategy.evaluate(
            position=position,
            current_price=_price("32000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is not None

    def test_max_split_per_day_higher_cap_allows_more(self):
        position = _filled_position(
            self.asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
            entry_date=TODAY,
        )
        cfg = SplitStrategyConfig(
            drop_threshold_pct=Decimal("7.0"),
            max_split_count=7,
            per_split_amount=Money(amount=Decimal("1000000"), currency=Currency.KRW),
            max_split_per_day=2,
        )
        result = self.strategy.evaluate(
            position=position,
            current_price=_price("32000", self.asset),
            balance=_balance(),
            config=cfg,
            today=TODAY,
        )
        assert result.buy is not None


# ---------------------------------------------------------------------------
# excluded_slot_numbers (ADR 0002 §5.9.3 — same-day rebuy block)
# ---------------------------------------------------------------------------
class TestExcludedSlotNumbers:
    """Orchestrator passes the slots it just sold this evaluation; the
    strategy must skip them so the resulting Decision can never have a
    buy_slot ∈ sell_slots (Decision Invariant 3).
    """

    def setup_method(self):
        self.strategy = _strategy()
        self.asset = _asset()

    def test_default_none_preserves_existing_behavior(self):
        # No excluded set passed → behaves exactly as before.
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
        )
        assert result.buy is not None
        assert result.buy.slot_number == 1

    def test_empty_set_preserves_existing_behavior(self):
        # Empty set explicitly passed → identical to None.
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            excluded_slot_numbers=set(),
        )
        assert result.buy is not None
        assert result.buy.slot_number == 1

    def test_excluded_slot_skips_to_next_smallest(self):
        # First-buy bypass picks smallest EMPTY. Excluding slot 1 should
        # forward to slot 2 (Hybrid's first-buy bypass returns current_price
        # which trivially qualifies every remaining EMPTY slot).
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            excluded_slot_numbers={1},
        )
        assert result.buy is not None
        assert result.buy.slot_number == 2

    def test_all_empty_excluded_yields_dedicated_skip(self):
        # max_split_count=7 → exclude all seven EMPTY slots → no candidate
        # remains → ALL_EMPTY_SLOTS_EXCLUDED_BY_SAME_DAY_SELL.
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            excluded_slot_numbers={1, 2, 3, 4, 5, 6, 7},
        )
        assert result.buy is None
        assert (
            result.skip_reason
            is SkipReason.ALL_EMPTY_SLOTS_EXCLUDED_BY_SAME_DAY_SELL
        )
        # Skip reasoning surfaces the excluded set for retrospective debugging.
        assert (
            result.reasoning["excluded_slot_numbers"]
            == "1,2,3,4,5,6,7"
        )

    def test_excluded_with_non_empty_position(self):
        # Slot 1 FILLED + 2..7 EMPTY. Exclude slot 2 (just sold this
        # evaluation). Drop is large enough for Hybrid's avg_price fallback
        # to fire, so the smallest unexcluded EMPTY slot (3) wins.
        position = _filled_position(
            self.asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
        )
        result = self.strategy.evaluate(
            position=position,
            current_price=_price("32000", self.asset),  # 8.57% drop
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
            excluded_slot_numbers={2},
        )
        assert result.buy is not None
        assert result.buy.slot_number == 3
