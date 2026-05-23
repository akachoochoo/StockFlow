"""Unit tests for src.use_cases.decision_equivalence.

ADR 0012 §2.3 B2 / G2(d) — backtest vs live Decision identity. The projection
EXCLUDES timestamp / top-level reasoning / per-action filled_price / order_id;
target_price is compared tick-normalized. Function names carry the
``decision_equiv`` / ``decisions_equivalent`` keyword.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.models import (
    Asset,
    AssetClass,
    BuyActionRecord,
    Currency,
    Decision,
    Exchange,
    Market,
    SellActionRecord,
    SkipReason,
)
from src.use_cases.decision_equivalence import (
    decision_projection,
    decisions_equivalent,
)

TS_A = datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)
TS_B = datetime(2026, 5, 1, 7, 30, 0, tzinfo=UTC)


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


def _buy(
    *,
    slot_number: int = 1,
    split_level_after: int = 1,
    filled_quantity: str = "10",
    filled_price: str = "35000",
    target_price: str = "35000",
    order_id: str | None = "ord-1",
    reasoning: dict[str, str] | None = None,
) -> BuyActionRecord:
    return BuyActionRecord(
        slot_number=slot_number,
        split_level_after=split_level_after,
        filled_quantity=Decimal(filled_quantity),
        filled_price=Decimal(filled_price),
        target_price=Decimal(target_price),
        idempotency_key=f"idem-{slot_number}",
        order_id=order_id,
        reasoning=reasoning or {},
    )


def _sell(
    *,
    slot_number: int,
    filled_quantity: str = "10",
    filled_price: str = "40000",
    profit_pct: str = "14.0",
    order_id: str | None = "sell-ord",
) -> SellActionRecord:
    return SellActionRecord(
        slot_number=slot_number,
        filled_quantity=Decimal(filled_quantity),
        filled_price=Decimal(filled_price),
        profit_pct=Decimal(profit_pct),
        idempotency_key=f"sidem-{slot_number}",
        order_id=order_id,
        reasoning={},
    )


def _decision(
    *,
    timestamp: datetime = TS_A,
    sell_actions: list[SellActionRecord] | None = None,
    buy_action: BuyActionRecord | None = None,
    skip_reason: SkipReason | None = None,
    reasoning: dict[str, str] | None = None,
) -> Decision:
    return Decision(
        timestamp=timestamp,
        asset=_asset(),
        sell_actions=sell_actions or [],
        buy_action=buy_action,
        skip_reason=skip_reason,
        reasoning=reasoning or {},
    )


class TestDecisionEquivExcludesNonDecisionFields:
    def test_decisions_equivalent_ignores_timestamp_reasoning_filled_price(self):
        # Two buy Decisions differing only in timestamp + reasoning +
        # per-action filled_price + order_id → equivalent True.
        a = _decision(
            timestamp=TS_A,
            buy_action=_buy(filled_price="35000", order_id="ord-A"),
            reasoning={"ctx": "live"},
        )
        b = _decision(
            timestamp=TS_B,
            buy_action=_buy(filled_price="34985", order_id="ord-B"),
            reasoning={"ctx": "backtest"},
        )
        assert decisions_equivalent(a, b) is True
        # ...and they are NOT raw-equal (proves projection is doing real work).
        assert a != b


class TestDecisionEquivDistinguishesRealDifferences:
    def test_skip_vs_buy_not_equivalent(self):
        skip = _decision(skip_reason=SkipReason.STRATEGY_NO_BUY)
        buy = _decision(buy_action=_buy())
        assert decisions_equivalent(skip, buy) is False

    def test_different_buy_quantity_not_equivalent(self):
        a = _decision(buy_action=_buy(filled_quantity="10"))
        b = _decision(buy_action=_buy(filled_quantity="20"))
        assert decisions_equivalent(a, b) is False


class TestDecisionEquivSellCanonicalSort:
    def test_multi_sell_order_independent(self):
        # Same two sells in different list order → equivalent (canonical sort).
        a = _decision(
            sell_actions=[
                _sell(slot_number=1),
                _sell(slot_number=2),
            ]
        )
        b = _decision(
            sell_actions=[
                _sell(slot_number=2, order_id="x"),
                _sell(slot_number=1, order_id="y"),
            ]
        )
        assert decisions_equivalent(a, b) is True


class TestDecisionEquivTargetPriceTick:
    def test_buy_target_price_tick_rounding_matches(self):
        # Live target 34999 floors to a 5-tick = 34995; backtest 34996 → 34995.
        # Same tick-rounded target → equivalent (filled_price still excluded).
        a = _decision(buy_action=_buy(target_price="34999", filled_price="34999"))
        b = _decision(buy_action=_buy(target_price="34996", filled_price="35000"))
        assert decisions_equivalent(a, b) is True
        # The projection's buy target_price is the rounded value.
        proj = decision_projection(a)
        assert proj[2] is not None
        assert proj[2][3] == Decimal("34995")


class TestDecisionEquivSkip:
    def test_skip_equivalent_to_empty_actions_skip(self):
        # skip ⇔ empty sell/buy: same skip_reason → equivalent.
        a = _decision(skip_reason=SkipReason.MAX_SPLIT_PER_DAY_REACHED)
        b = _decision(
            skip_reason=SkipReason.MAX_SPLIT_PER_DAY_REACHED,
            timestamp=TS_B,
            reasoning={"a": "b"},
        )
        assert decisions_equivalent(a, b) is True
        proj = decision_projection(a)
        assert proj == (SkipReason.MAX_SPLIT_PER_DAY_REACHED, (), None)

    def test_different_skip_reasons_not_equivalent(self):
        a = _decision(skip_reason=SkipReason.STRATEGY_NO_BUY)
        b = _decision(skip_reason=SkipReason.INSUFFICIENT_BALANCE)
        assert decisions_equivalent(a, b) is False
