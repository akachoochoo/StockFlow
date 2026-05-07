"""Unit tests for src.domain.strategies.profit_target.

Pure domain logic — no mocks. Targets 100% coverage of ProfitTargetSell
+ SellStrategyConfig + SellDecision per CLAUDE.md §7.1.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Position,
    Price,
    SplitEntry,
    SplitSlot,
)
from src.domain.strategies.profit_target import (
    ProfitTargetSell,
    SellDecision,
    SellStrategyConfig,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
TODAY = date(2026, 4, 30)
ENTRY_DATE = date(2026, 4, 1)


def _asset() -> Asset:
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _config(
    *,
    profit_target_pct: str = "10.0",
    max_sells_per_day: int = 7,
) -> SellStrategyConfig:
    return SellStrategyConfig(
        profit_target_pct=Decimal(profit_target_pct),
        max_sells_per_day=max_sells_per_day,
    )


def _price(value: str, asset: Asset | None = None) -> Price:
    return Price(
        asset=asset or _asset(),
        value=Decimal(value),
        timestamp=UTC_NOW,
    )


def _position_from_entries(*qty_price: tuple[str, str]) -> Position:
    """Build a Position from (qty, price) tuples filling slots 1..N."""
    asset = _asset()
    entries = [
        SplitEntry(
            split_number=i + 1,
            entry_date=ENTRY_DATE,
            quantity=Decimal(q),
            entry_price=Decimal(p),
            idempotency_key=f"k{i + 1}",
        )
        for i, (q, p) in enumerate(qty_price)
    ]
    slots = [SplitSlot.filled(entry=e) for e in entries]
    slots.extend(
        SplitSlot.empty(slot_number=i)
        for i in range(len(entries) + 1, 8)
    )
    total_qty = sum((Decimal(q) for q, _ in qty_price), Decimal(0))
    total_cost = sum(
        (Decimal(q) * Decimal(p) for q, p in qty_price),
        Decimal(0),
    )
    return Position(
        asset=asset,
        quantity=total_qty,
        avg_price=total_cost / total_qty if total_qty > 0 else Decimal(0),
        split_level=len(entries),
        last_buy_at=UTC_NOW,
        slots=slots,
    )


# ---------------------------------------------------------------------------
# SellStrategyConfig validation
# ---------------------------------------------------------------------------
class TestSellStrategyConfig:
    def test_construct_happy_path(self):
        c = _config()
        assert c.profit_target_pct == Decimal("10.0")
        assert c.max_sells_per_day == 7

    def test_zero_profit_target_rejected(self):
        with pytest.raises(ValidationError):
            SellStrategyConfig(
                profit_target_pct=Decimal(0),
                max_sells_per_day=7,
            )

    def test_one_hundred_profit_target_rejected(self):
        # exclusive upper bound — 100% means "double" which is unrealistic
        with pytest.raises(ValidationError):
            SellStrategyConfig(
                profit_target_pct=Decimal(100),
                max_sells_per_day=7,
            )

    def test_max_sells_per_day_zero_rejected(self):
        with pytest.raises(ValidationError):
            SellStrategyConfig(
                profit_target_pct=Decimal("10"),
                max_sells_per_day=0,
            )

    def test_max_sells_per_day_above_seven_rejected(self):
        with pytest.raises(ValidationError):
            SellStrategyConfig(
                profit_target_pct=Decimal("10"),
                max_sells_per_day=8,
            )


# ---------------------------------------------------------------------------
# SellDecision validation
# ---------------------------------------------------------------------------
class TestSellDecision:
    def test_construct_happy_path(self):
        sd = SellDecision(
            slot_number=2,
            expected_price=Decimal("38500"),
            reasoning={"profit_pct": "10.0"},
        )
        assert sd.slot_number == 2
        assert sd.expected_price == Decimal("38500")

    def test_zero_expected_price_rejected(self):
        with pytest.raises(ValidationError):
            SellDecision(
                slot_number=1,
                expected_price=Decimal(0),
                reasoning={},
            )

    def test_slot_number_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            SellDecision(
                slot_number=8,
                expected_price=Decimal("100"),
                reasoning={},
            )


# ---------------------------------------------------------------------------
# ProfitTargetSell.evaluate
# ---------------------------------------------------------------------------
class TestProfitTargetSell:
    def test_empty_position_returns_no_triggers(self):
        strategy = ProfitTargetSell()
        triggers = strategy.evaluate(
            position=Position.empty(_asset()),
            current_price=_price("40000"),
            config=_config(),
            as_of=TODAY,
        )
        assert triggers == []

    def test_single_slot_below_threshold_skips(self):
        # entry 30000, current 32000 → +6.67% < 10% threshold → no sell
        strategy = ProfitTargetSell()
        position = _position_from_entries(("10", "30000"))
        triggers = strategy.evaluate(
            position=position,
            current_price=_price("32000"),
            config=_config(profit_target_pct="10.0"),
            as_of=TODAY,
        )
        assert triggers == []

    def test_single_slot_at_threshold_triggers(self):
        # entry 30000, current 33000 → +10.0% == threshold → sell
        strategy = ProfitTargetSell()
        position = _position_from_entries(("10", "30000"))
        triggers = strategy.evaluate(
            position=position,
            current_price=_price("33000"),
            config=_config(profit_target_pct="10.0"),
            as_of=TODAY,
        )
        assert len(triggers) == 1
        assert triggers[0].slot_number == 1
        assert triggers[0].expected_price == Decimal("33000")

    def test_multiple_slots_only_above_threshold_trigger(self):
        # slot 1: entry 30000, current 33000 → +10% triggers
        # slot 2: entry 35000, current 33000 → -5.7% no trigger
        # slot 3: entry 28000, current 33000 → +17.86% triggers
        strategy = ProfitTargetSell()
        position = _position_from_entries(
            ("10", "30000"), ("10", "35000"), ("10", "28000"),
        )
        triggers = strategy.evaluate(
            position=position,
            current_price=_price("33000"),
            config=_config(profit_target_pct="10.0"),
            as_of=TODAY,
        )
        slot_numbers = [t.slot_number for t in triggers]
        assert slot_numbers == [1, 3]

    def test_max_sells_per_day_caps_smallest_slot_first(self):
        # All 5 slots above threshold; cap at 2 → slots 1 and 2 win.
        strategy = ProfitTargetSell()
        position = _position_from_entries(*[("10", "30000")] * 5)
        triggers = strategy.evaluate(
            position=position,
            current_price=_price("40000"),  # +33% on every slot
            config=_config(max_sells_per_day=2),
            as_of=TODAY,
        )
        assert [t.slot_number for t in triggers] == [1, 2]

    def test_reasoning_contains_required_keys(self):
        strategy = ProfitTargetSell()
        position = _position_from_entries(("10", "30000"))
        triggers = strategy.evaluate(
            position=position,
            current_price=_price("33000"),
            config=_config(profit_target_pct="10.0"),
            as_of=TODAY,
        )
        r = triggers[0].reasoning
        assert r["entry_price"] == "30000"
        assert r["current_price"] == "33000"
        assert r["profit_target_pct"] == "10.0"
        # profit_pct present (some long Decimal representation)
        assert "profit_pct" in r

    def test_zero_quantity_position_returns_empty(self):
        # Position.empty creates qty=0 / split_level=0 — strategy short-circuits
        strategy = ProfitTargetSell()
        triggers = strategy.evaluate(
            position=Position.empty(_asset()),
            current_price=_price("100000"),  # huge price, irrelevant
            config=_config(profit_target_pct="10"),
            as_of=TODAY,
        )
        assert triggers == []
