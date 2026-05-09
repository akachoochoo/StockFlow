"""Unit tests for src.application.reporting.trade_view (Phase 0.10 — ADR 0006 §3).

Pure function tests for ``trades_from_decisions`` — Decision/BuyActionRecord/
SellActionRecord → TradeView 변환 검증.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.reporting.trade_view import TradeView, trades_from_decisions
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

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
UTC_LATER = datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)


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


def _buy_record(
    *,
    slot_number: int = 1,
    split_level_after: int = 1,
    quantity: str = "10",
    price: str = "35000",
    target_price: str = "35000",
    key: str = "buy-1",
    reasoning: dict[str, str] | None = None,
) -> BuyActionRecord:
    """Phase 0.10.z (ADR 0006 §16): default reasoning is empty — application
    layer enriches view annotations with ``slot_number`` from typed field.
    Strategy reasoning must not pre-populate ``slot_number`` (strict invariant).
    """
    return BuyActionRecord(
        slot_number=slot_number,
        split_level_after=split_level_after,
        filled_quantity=Decimal(quantity),
        filled_price=Decimal(price),
        target_price=Decimal(target_price),
        idempotency_key=key,
        order_id="ord-1",
        reasoning=reasoning if reasoning is not None else {},
    )


def _sell_record(
    *,
    slot_number: int = 1,
    quantity: str = "10",
    price: str = "38500",
    profit_pct: str = "10.0",
    key: str = "sell-1",
    reasoning: dict[str, str] | None = None,
) -> SellActionRecord:
    """Phase 0.10.z (ADR 0006 §16): default reasoning is empty — see _buy_record."""
    return SellActionRecord(
        slot_number=slot_number,
        filled_quantity=Decimal(quantity),
        filled_price=Decimal(price),
        profit_pct=Decimal(profit_pct),
        idempotency_key=key,
        order_id="ord-2",
        reasoning=reasoning if reasoning is not None else {},
    )


def _decision(
    *,
    timestamp: datetime = UTC_NOW,
    asset: Asset | None = None,
    buy_action: BuyActionRecord | None = None,
    sell_actions: list[SellActionRecord] | None = None,
    skip_reason: SkipReason | None = None,
    reasoning: dict[str, str] | None = None,
) -> Decision:
    return Decision(
        timestamp=timestamp,
        asset=asset or _asset(),
        buy_action=buy_action,
        sell_actions=sell_actions or [],
        skip_reason=skip_reason,
        reasoning=reasoning or {"current_price": "35000"},
    )


class TestTradesFromDecisions:
    def test_empty_decisions_returns_empty(self):
        assert trades_from_decisions([], "price_drop") == []

    def test_skip_only_decision_yields_no_trades(self):
        d = _decision(
            buy_action=None,
            sell_actions=[],
            skip_reason=SkipReason.STRATEGY_NO_BUY,
        )
        trades = trades_from_decisions([d], "price_drop")
        assert trades == []

    def test_buy_only_decision(self):
        d = _decision(buy_action=_buy_record(slot_number=2))
        trades = trades_from_decisions([d], "price_drop")
        assert len(trades) == 1
        t = trades[0]
        assert t.timestamp == UTC_NOW
        assert t.symbol == "069500"
        assert t.side == "BUY"
        assert t.price == Decimal("35000")
        assert t.quantity == Decimal("10")
        assert t.strategy_id == "price_drop"
        # Phase 0.10.z (ADR §16): annotations enriched with uniform
        # slot_number from typed BuyActionRecord.slot_number field.
        assert t.annotations == {"slot_number": "2"}

    def test_sell_only_decision(self):
        d = _decision(sell_actions=[_sell_record(slot_number=3)])
        trades = trades_from_decisions([d], "price_drop")
        assert len(trades) == 1
        t = trades[0]
        assert t.side == "SELL"
        assert t.price == Decimal("38500")
        # Phase 0.10.z (ADR §16): uniform slot_number for both sides.
        assert t.annotations == {"slot_number": "3"}

    def test_sell_then_buy_in_one_decision_keeps_order(self):
        """ADR 0002 §5.4 — sells-then-buys 흐름 그대로 (sells 먼저, buy 나중)."""
        d = _decision(
            buy_action=_buy_record(slot_number=4),
            sell_actions=[
                _sell_record(slot_number=1, key="s1"),
                _sell_record(slot_number=2, key="s2"),
            ],
        )
        trades = trades_from_decisions([d], "price_drop")
        assert [t.side for t in trades] == ["SELL", "SELL", "BUY"]

    def test_multiple_decisions_preserve_order(self):
        d1 = _decision(timestamp=UTC_NOW, buy_action=_buy_record(key="b1"))
        d2 = _decision(timestamp=UTC_LATER, sell_actions=[_sell_record(key="s1")])
        trades = trades_from_decisions([d1, d2], "price_drop")
        assert len(trades) == 2
        assert trades[0].timestamp == UTC_NOW
        assert trades[0].side == "BUY"
        assert trades[1].timestamp == UTC_LATER
        assert trades[1].side == "SELL"

    def test_strategy_id_passed_through(self):
        d = _decision(buy_action=_buy_record())
        for sid in ("price_drop", "support_level", "ma_cross_dummy"):
            trades = trades_from_decisions([d], sid)
            assert trades[0].strategy_id == sid

    def test_annotations_copied_not_shared(self):
        """reasoning dict 변경이 view model 에 영향 없어야 함."""
        # Phase 0.10.z (ADR §16): existing reasoning keys preserved (additive
        # enrichment). New uniform `slot_number` added from record field.
        reasoning = {"trigger_price": "32550", "drop_pct": "7.0"}
        d = _decision(
            buy_action=_buy_record(slot_number=2, reasoning=reasoning),
        )
        trades = trades_from_decisions([d], "price_drop")
        # mutate source — view model 보존되어야
        reasoning["trigger_price"] = "999"
        assert trades[0].annotations == {
            "trigger_price": "32550",
            "drop_pct": "7.0",
            "slot_number": "2",  # AC7 — uniform key, additive enrichment
        }

    def test_symbol_from_asset_code(self):
        for code in ("005930", "005380", "055550"):
            d = _decision(asset=_asset(code=code), buy_action=_buy_record())
            trades = trades_from_decisions([d], "price_drop")
            assert trades[0].symbol == code

    def test_buy_uses_filled_price_not_target(self):
        d = _decision(buy_action=_buy_record(price="34995", target_price="35000"))
        trades = trades_from_decisions([d], "price_drop")
        assert trades[0].price == Decimal("34995")

    def test_view_model_is_frozen(self):
        d = _decision(buy_action=_buy_record())
        trades = trades_from_decisions([d], "price_drop")
        # frozen dataclass → assignment 차단
        try:
            trades[0].symbol = "FAIL"  # type: ignore[misc]
        except (AttributeError, Exception):
            return
        raise AssertionError("TradeView should be frozen")

    def test_view_model_type(self):
        d = _decision(buy_action=_buy_record())
        trades = trades_from_decisions([d], "price_drop")
        assert isinstance(trades[0], TradeView)


class TestSlotNumberEnrichment:
    """Phase 0.10.z / ADR 0006 §16 — application layer enrichment of
    ``TradeView.annotations`` with uniform ``slot_number`` from typed record
    fields. Domain ``reasoning`` dict unchanged (Clean Architecture preserved).
    """

    def test_buy_annotations_carry_uniform_slot_number_key(self):
        # AC7 — uniform `slot_number` for BUY (regardless of strategy)
        d = _decision(buy_action=_buy_record(slot_number=5, reasoning={
            "trigger_price": "32550",
        }))
        trades = trades_from_decisions([d], "price_drop")
        assert "slot_number" in trades[0].annotations
        assert trades[0].annotations["slot_number"] == "5"
        # Original reasoning keys preserved (additive enrichment)
        assert trades[0].annotations["trigger_price"] == "32550"

    def test_sell_annotations_carry_uniform_slot_number_key(self):
        # AC7 — uniform `slot_number` for SELL too
        d = _decision(sell_actions=[_sell_record(slot_number=3, reasoning={
            "entry_price": "35000", "profit_pct": "10.0",
        })])
        trades = trades_from_decisions([d], "price_drop")
        assert trades[0].annotations["slot_number"] == "3"
        assert trades[0].annotations["entry_price"] == "35000"

    def test_collision_buy_raises_assertion(self):
        # AC11 — strict no-collision invariant. If a strategy emits
        # `slot_number` in its reasoning, enrichment must fail loudly.
        import pytest
        d = _decision(buy_action=_buy_record(
            slot_number=2, reasoning={"slot_number": "999"},
        ))
        with pytest.raises(AssertionError, match="slot_number"):
            trades_from_decisions([d], "price_drop")

    def test_collision_sell_raises_assertion(self):
        import pytest
        d = _decision(sell_actions=[_sell_record(
            slot_number=4, reasoning={"slot_number": "777"},
        )])
        with pytest.raises(AssertionError, match="slot_number"):
            trades_from_decisions([d], "price_drop")

    def test_strategy_neutral_uniform_key(self):
        # AC12 — a hypothetical second renderer reading `slot_number` for
        # BOTH sides works without any application-layer change. Proves
        # application layer doesn't capture renderer key conventions.
        d = _decision(
            buy_action=_buy_record(slot_number=4),
            sell_actions=[_sell_record(slot_number=2)],
        )
        trades = trades_from_decisions([d], "ma_cross_dummy")
        # Same key for both sides — renderer-agnostic
        for t in trades:
            assert "slot_number" in t.annotations
            assert int(t.annotations["slot_number"]) in (2, 4)
        # No legacy `split_number` key — application layer doesn't know
        # any renderer's read-key convention.
        for t in trades:
            assert "split_number" not in t.annotations

    def test_domain_reasoning_dict_unchanged(self):
        # Clean Architecture invariant — application layer must not mutate
        # the domain record's reasoning dict.
        domain_reasoning = {"trigger_price": "32550"}
        record = _buy_record(slot_number=2, reasoning=domain_reasoning)
        d = _decision(buy_action=record)
        trades_from_decisions([d], "price_drop")
        # Domain reasoning unchanged — only view-side dict was enriched
        assert "slot_number" not in domain_reasoning
        assert record.reasoning == {"trigger_price": "32550"}
