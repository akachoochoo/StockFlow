"""Unit tests for src.application.reporting.cycle_pairing (Phase 0.10.j).

Critic patch C2: 7 cases — case #7 locks list-order primacy over annotation
``entry_price`` (synth #4 disambiguation).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.reporting.cycle_pairing import (
    Cycle,
    match_realized_pnl,
    pair_cycles,
)
from src.application.reporting.trade_view import TradeView


def _trade(
    *,
    side: str,
    when: datetime,
    price: int,
    qty: int,
    symbol: str = "069500",
    annotations: dict[str, object] | None = None,
) -> TradeView:
    return TradeView(
        timestamp=when,
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        price=Decimal(price),
        quantity=Decimal(qty),
        strategy_id="price_drop",
        annotations=annotations or {},
    )


def _t(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 0, 0, 0, tzinfo=UTC)


class TestPairCyclesCase1SimpleBuySell:
    """Case 1: 1 BUY → 1 SELL = 1 closed cycle."""

    def test_simple_match(self):
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=10),
            _trade(side="SELL", when=_t(2024, 1, 5), price=110, qty=10),
        ]
        cycles = pair_cycles(trades)
        assert len(cycles) == 1
        c = cycles[0]
        assert c.entry_date == _t(2024, 1, 1).date()
        assert c.exit_date == _t(2024, 1, 5).date()
        assert c.quantity == Decimal(10)
        assert c.entry_price == Decimal(100)
        assert c.exit_price == Decimal(110)
        assert c.realized_pnl == Decimal(100)  # (110-100)*10
        assert c.realized_pnl_pct == Decimal(10)
        assert c.hold_days == 4
        assert not c.is_open
        assert not c.is_orphan_sell


class TestPairCyclesCase2MultiBuyOneSell:
    """Case 2: BUY 5 + BUY 3 → SELL 8 = 2 closed cycles (FIFO)."""

    def test_multi_buy_one_sell_fifo(self):
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=5),
            _trade(side="BUY", when=_t(2024, 1, 2), price=110, qty=3),
            _trade(side="SELL", when=_t(2024, 1, 5), price=120, qty=8),
        ]
        cycles = pair_cycles(trades)
        assert len(cycles) == 2
        # FIFO: first BUY matched first
        c1, c2 = cycles
        assert c1.entry_date == _t(2024, 1, 1).date()
        assert c1.entry_price == Decimal(100)
        assert c1.quantity == Decimal(5)
        assert c1.realized_pnl == Decimal(100)  # (120-100)*5
        assert c2.entry_date == _t(2024, 1, 2).date()
        assert c2.entry_price == Decimal(110)
        assert c2.quantity == Decimal(3)
        assert c2.realized_pnl == Decimal(30)  # (120-110)*3


class TestPairCyclesCase3OrphanSell:
    """Case 3: SELL only (no matching BUY) = orphan sell."""

    def test_orphan_sell(self):
        trades = [
            _trade(side="SELL", when=_t(2024, 1, 5), price=110, qty=10),
        ]
        cycles = pair_cycles(trades)
        assert len(cycles) == 1
        c = cycles[0]
        assert c.is_orphan_sell
        assert c.entry_date is None
        assert c.entry_price is None
        assert c.exit_date == _t(2024, 1, 5).date()
        assert c.quantity == Decimal(10)
        assert c.realized_pnl is None
        assert c.realized_pnl_pct is None
        assert c.hold_days is None


class TestPairCyclesCase4OpenBuy:
    """Case 4: BUY only (no matching SELL at end of stream) = open."""

    def test_open_buy(self):
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=10),
        ]
        cycles = pair_cycles(trades)
        assert len(cycles) == 1
        c = cycles[0]
        assert c.is_open
        assert c.entry_date == _t(2024, 1, 1).date()
        assert c.exit_date is None
        assert c.exit_price is None
        assert c.quantity == Decimal(10)
        assert c.realized_pnl is None


class TestPairCyclesCase5SameDaySellThenBuy:
    """Case 5: same-day SELL → BUY = SELL closes prior cycle, BUY starts new.

    ADR 0002 §5.4 sells-then-buys ordering. ``trades_from_decisions``
    preserves this in TradeView list order.
    """

    def test_same_day_sell_then_buy_creates_two_cycles(self):
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=10),
            # 2020-02-14 phenomenon: SELL fires first (full position),
            # then BUY re-enters (reentry strategy).
            _trade(side="SELL", when=_t(2024, 1, 5), price=120, qty=10),
            _trade(side="BUY", when=_t(2024, 1, 5), price=120, qty=8),
        ]
        cycles = pair_cycles(trades)
        # Closed cycle (BUY1 → SELL) emitted first; the post-SELL BUY
        # remains open.
        assert len(cycles) == 2
        closed, open_buy = cycles
        assert closed.entry_date == _t(2024, 1, 1).date()
        assert closed.exit_date == _t(2024, 1, 5).date()
        assert closed.realized_pnl == Decimal(200)  # (120-100)*10
        assert open_buy.is_open
        assert open_buy.entry_date == _t(2024, 1, 5).date()
        assert open_buy.quantity == Decimal(8)


class TestPairCyclesCase6PartialFill:
    """Case 6: SELL larger than head BUY = consumes head, then matches next."""

    def test_partial_fill_across_two_buys(self):
        # Verifies consumption + remainder logic specifically: BUY 5 +
        # BUY 5 → SELL 7 should produce closed (5) + closed (2) + open (3).
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=5),
            _trade(side="BUY", when=_t(2024, 1, 2), price=110, qty=5),
            _trade(side="SELL", when=_t(2024, 1, 10), price=120, qty=7),
        ]
        cycles = pair_cycles(trades)
        assert len(cycles) == 3
        c1, c2, c3 = cycles
        # First closed (BUY1 fully consumed = 5)
        assert c1.entry_price == Decimal(100)
        assert c1.quantity == Decimal(5)
        assert c1.exit_date == _t(2024, 1, 10).date()
        # Second closed (BUY2 partially consumed = 2)
        assert c2.entry_price == Decimal(110)
        assert c2.quantity == Decimal(2)
        assert c2.exit_date == _t(2024, 1, 10).date()
        # Open BUY (BUY2 remainder = 3)
        assert c3.is_open
        assert c3.entry_price == Decimal(110)
        assert c3.quantity == Decimal(3)


class TestPairCyclesCase7ListOrderBeatsAnnotation:
    """Case 7 (Critic patch C2): list-order FIFO trumps annotation entry_price.

    Two BUYs at 100 / 110 in list order. SELL annotation says
    ``entry_price=105`` (slot-level avg). Cycle pairing MUST match BUY1
    (price=100) by list order, not synthesize a 105-priced match.
    """

    def test_annotation_entry_price_is_diagnostic_only(self):
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=10),
            _trade(side="BUY", when=_t(2024, 1, 2), price=110, qty=10),
            _trade(
                side="SELL", when=_t(2024, 1, 5), price=120, qty=10,
                annotations={
                    # Strategy-level avg-cost = 105 (10 + 10 = 20 @ avg)
                    "entry_price": "105",
                    "profit_pct": "14.28",
                },
            ),
        ]
        cycles = pair_cycles(trades)
        # Expect: 1 closed (BUY1 @100, FIFO), 1 open (BUY2 @110)
        assert len(cycles) == 2
        closed = cycles[0]
        # Entry price = list-order BUY1 price (100), NOT annotation 105
        assert closed.entry_price == Decimal(100)
        assert closed.exit_price == Decimal(120)
        assert closed.realized_pnl == Decimal(200)  # (120-100)*10
        # Open BUY2 still in queue
        assert cycles[1].is_open
        assert cycles[1].entry_price == Decimal(110)


class TestMatchRealizedPnl:
    def test_no_closed_returns_none(self):
        # Open BUY only — no closed cycles
        trades = [_trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=10)]
        assert match_realized_pnl(trades) is None

    def test_orphan_sell_only_returns_none(self):
        trades = [_trade(side="SELL", when=_t(2024, 1, 5), price=110, qty=10)]
        assert match_realized_pnl(trades) is None

    def test_sums_closed_cycles(self):
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=10),
            _trade(side="SELL", when=_t(2024, 1, 5), price=110, qty=10),
            _trade(side="BUY", when=_t(2024, 1, 6), price=100, qty=5),
            _trade(side="SELL", when=_t(2024, 1, 10), price=90, qty=5),
        ]
        # (110-100)*10 + (90-100)*5 = 100 - 50 = 50
        assert match_realized_pnl(trades) == Decimal(50)

    def test_ignores_open_when_summing_closed(self):
        trades = [
            _trade(side="BUY", when=_t(2024, 1, 1), price=100, qty=10),
            _trade(side="SELL", when=_t(2024, 1, 5), price=110, qty=10),
            _trade(side="BUY", when=_t(2024, 1, 6), price=120, qty=5),
        ]
        # Only first cycle closed = (110-100)*10 = 100
        assert match_realized_pnl(trades) == Decimal(100)


class TestCycleProperties:
    def test_closed_cycle_hold_days(self):
        c = Cycle(
            entry_date=_t(2024, 1, 1).date(),
            entry_price=Decimal(100),
            quantity=Decimal(10),
            exit_date=_t(2024, 1, 11).date(),
            exit_price=Decimal(120),
            realized_pnl=Decimal(200),
            realized_pnl_pct=Decimal(20),
        )
        assert c.hold_days == 10
        assert not c.is_open
        assert not c.is_orphan_sell

    def test_open_cycle_hold_days_none(self):
        c = Cycle(
            entry_date=_t(2024, 1, 1).date(),
            entry_price=Decimal(100),
            quantity=Decimal(10),
            exit_date=None,
            exit_price=None,
            realized_pnl=None,
            realized_pnl_pct=None,
        )
        assert c.hold_days is None
        assert c.is_open

    def test_orphan_cycle_hold_days_none(self):
        c = Cycle(
            entry_date=None,
            entry_price=None,
            quantity=Decimal(10),
            exit_date=_t(2024, 1, 5).date(),
            exit_price=Decimal(110),
            realized_pnl=None,
            realized_pnl_pct=None,
        )
        assert c.hold_days is None
        assert c.is_orphan_sell
