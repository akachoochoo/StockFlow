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
    return BuyActionRecord(
        slot_number=slot_number,
        split_level_after=split_level_after,
        filled_quantity=Decimal(quantity),
        filled_price=Decimal(price),
        target_price=Decimal(target_price),
        idempotency_key=key,
        order_id="ord-1",
        reasoning=reasoning or {"split_number": str(slot_number)},
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
    return SellActionRecord(
        slot_number=slot_number,
        filled_quantity=Decimal(quantity),
        filled_price=Decimal(price),
        profit_pct=Decimal(profit_pct),
        idempotency_key=key,
        order_id="ord-2",
        reasoning=reasoning or {"slot_number": str(slot_number)},
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
        assert t.annotations == {"split_number": "2"}

    def test_sell_only_decision(self):
        d = _decision(sell_actions=[_sell_record(slot_number=3)])
        trades = trades_from_decisions([d], "price_drop")
        assert len(trades) == 1
        t = trades[0]
        assert t.side == "SELL"
        assert t.price == Decimal("38500")
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
        reasoning = {"split_number": "2", "drop_pct": "7.0"}
        d = _decision(buy_action=_buy_record(reasoning=reasoning))
        trades = trades_from_decisions([d], "price_drop")
        # mutate source — view model 보존되어야
        reasoning["split_number"] = "999"
        assert trades[0].annotations == {"split_number": "2", "drop_pct": "7.0"}

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
