"""Unit tests for src.use_cases.pending_settler.PendingSettler (Stage 8-2).

Covers the adopted §8 decisions: post-settle corrected Decision (C1 매수),
buy/sell symmetric settle (NF-1 매도 settle-only), strict slot recovery,
terminal transition out of list_pending (gap a), re-settle idempotency,
PARTIAL/PENDING day-order max-age=1 halt (gap b), single-UoW atomicity, and the
NF-1 observability event. Money-critical halts raise StateMismatchError.

Fakes only — zero real network / DB.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.domain.exceptions import StateMismatchError
from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    Currency,
    Decision,
    Exchange,
    Market,
    Money,
    Order,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    SellActionRecord,
    SplitEntry,
    SplitSlot,
)
from src.domain.order_keys import OrderKeyError, build_order_key
from src.ports.notifications import NotificationLevel
from src.use_cases.decision_equivalence import decisions_equivalent
from src.use_cases.pending_settler import PendingSettler

DAY = date(2026, 5, 22)
TODAY = date(2026, 5, 23)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
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


def _utc(d: date, hour: int = 6) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=UTC)


def _pending_order(
    asset: Asset,
    *,
    side: OrderSide,
    slot: int,
    day: date = DAY,
    hour: int = 6,
    qty: str = "10",
    price: str = "35000",
) -> Order:
    key = build_order_key(
        asset_fqn=asset.fqn, date_iso=day.isoformat(), side=side, slot_number=slot
    )
    return Order(
        idempotency_key=key,
        asset=asset,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        target_price=Decimal(price),
        status=OrderStatus.PENDING,
        broker_order_id=f"ODNO-{side.value}-{slot}",
        filled_quantity=Decimal(0),
        filled_price=None,
        submitted_at=_utc(day, hour),
        filled_at=None,
        broker_org_no="ORG-1",
    )


def _result(
    order: Order,
    *,
    status: OrderStatus,
    filled_qty: Decimal | None = None,
    filled_price: Decimal | None = None,
    filled_at: datetime | None = None,
) -> OrderResult:
    return OrderResult(
        idempotency_key=order.idempotency_key,
        asset=order.asset,
        broker_order_id=order.broker_order_id,
        status=status,
        filled_quantity=filled_qty if filled_qty is not None else Decimal(0),
        filled_price=filled_price,
        submitted_at=order.submitted_at,
        filled_at=filled_at,
        broker_org_no=order.broker_org_no,
    )


def _filled(order: Order, *, filled_at: datetime | None = None) -> OrderResult:
    return _result(
        order,
        status=OrderStatus.FILLED,
        filled_qty=order.quantity,
        filled_price=order.target_price,
        filled_at=filled_at or _utc(order.submitted_at.date(), 6),
    )


def _filled_position(
    asset: Asset, *, slot: int, qty: str, price: str, entry_key: str = "seed"
) -> Position:
    entry = SplitEntry(
        split_number=slot,
        entry_date=DAY,
        quantity=Decimal(qty),
        entry_price=Decimal(price),
        idempotency_key=entry_key,
    )
    slots: list[SplitSlot] = [
        SplitSlot.filled(entry=entry) if i == slot else SplitSlot.empty(slot_number=i)
        for i in range(1, 8)
    ]
    return Position(
        asset=asset,
        quantity=Decimal(qty),
        avg_price=Decimal(price),
        split_level=1,
        last_buy_at=_utc(DAY),
        slots=slots,
    )


class _FakeStatusBroker:
    """OrderStatusReaderPort: returns canned get_order_status results."""

    def __init__(self, results: dict[str, OrderResult]) -> None:
        self._results = results

    def get_order_status(self, idempotency_key: str) -> OrderResult | None:
        return self._results.get(idempotency_key)


def _settler(
    uow: InMemoryUnitOfWork, broker: _FakeStatusBroker
) -> PendingSettler:
    return PendingSettler(uow_factory=lambda: uow, broker=broker)


# ---------------------------------------------------------------------------
# No-op
# ---------------------------------------------------------------------------
def test_pending_settler_no_pending_is_noop() -> None:
    uow = InMemoryUnitOfWork()
    settler = _settler(uow, _FakeStatusBroker({}))
    outcome = settler.settle(TODAY)
    assert outcome.settled_buys == []
    assert outcome.settled_sells == []
    assert outcome.transitioned_keys == []
    assert outcome.events == []


# ---------------------------------------------------------------------------
# Buy settle
# ---------------------------------------------------------------------------
def test_pending_settler_filled_increments_split() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    outcome = _settler(uow, broker).settle(TODAY)

    assert len(outcome.settled_buys) == 1
    pos = uow.positions.get(a.fqn)
    assert pos is not None
    assert pos.split_level == 1
    assert pos.quantity == Decimal("10")
    decision = outcome.settled_buys[0]
    assert decision.buy_action is not None
    assert decision.buy_action.slot_number == 1
    assert decision.buy_action.split_level_after == 1
    # Order is now FILLED (terminal).
    settled_order = uow.orders.get_by_idempotency_key(order.idempotency_key)
    assert settled_order is not None
    assert settled_order.status is OrderStatus.FILLED


def test_settled_order_drops_from_list_pending() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    _settler(uow, broker).settle(TODAY)

    assert order.idempotency_key not in [
        o.idempotency_key for o in uow.orders.list_pending()
    ]


def test_resettle_is_idempotent_no_double_split() -> None:
    # Defensive guard: a PENDING order whose fill is ALREADY reflected in the
    # Position (slot entry carries the same key) must NOT split++ a second time.
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    # Position already carries this exact buy (entry idempotency_key == key).
    uow.positions.save(
        _filled_position(a, slot=1, qty="10", price="35000", entry_key=order.idempotency_key)
    )
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    outcome = _settler(uow, broker).settle(TODAY)

    pos = uow.positions.get(a.fqn)
    assert pos is not None
    assert pos.split_level == 1  # NOT 2 — no double apply
    assert outcome.settled_buys == []  # no new corrected Decision
    assert order.idempotency_key in outcome.transitioned_keys
    assert uow.orders.get_by_idempotency_key(order.idempotency_key).status is OrderStatus.FILLED  # type: ignore[union-attr]


def test_pending_settler_uses_shared_apply_fill() -> None:
    # PendingSettler (async) and MockBroker (sync) must produce the SAME
    # Position for the same fill — they share apply_buy_fill (C3).
    a = _asset()
    now = _utc(DAY)
    order = _pending_order(a, side=OrderSide.BUY, slot=1)

    uow = InMemoryUnitOfWork()
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order, filled_at=now)})
    _settler(uow, broker).settle(TODAY)
    pos_settler = uow.positions.get(a.fqn)

    mock = MockBroker(
        initial_balance=Balance(cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)),
        clock=lambda: now,
    )
    mock.place_order(
        OrderRequest(
            idempotency_key=order.idempotency_key,
            asset=a,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            target_price=Decimal("35000"),
            slot_number=1,
        )
    )
    pos_mock = mock.get_positions()[0]
    assert pos_settler == pos_mock


# ---------------------------------------------------------------------------
# Sell settle (NF-1)
# ---------------------------------------------------------------------------
def test_pending_sell_settle_applies_apply_sell_fill() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    uow.positions.save(_filled_position(a, slot=2, qty="10", price="35000"))
    order = _pending_order(a, side=OrderSide.SELL, slot=2, qty="10", price="40250")
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    outcome = _settler(uow, broker).settle(TODAY)

    pos = uow.positions.get(a.fqn)
    assert pos is not None
    assert pos.split_level == 0
    slot2 = pos.get_slot(2)
    assert slot2 is not None and slot2.state.value == "EMPTY"
    assert slot2.last_exit_price == Decimal("40250")
    assert len(outcome.settled_sells) == 1
    sell_dec = outcome.settled_sells[0]
    assert sell_dec.sell_actions[0].slot_number == 2
    assert sell_dec.sell_actions[0].profit_pct == (
        (Decimal("40250") - Decimal("35000")) / Decimal("35000") * Decimal(100)
    )


def test_g2d_sell_equivalent_after_settle_true() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    uow.positions.save(_filled_position(a, slot=2, qty="10", price="35000"))
    order = _pending_order(a, side=OrderSide.SELL, slot=2, qty="10", price="40250")
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    settled = _settler(uow, broker).settle(TODAY).settled_sells[0]

    # Backtest Decision for the same sell (slot 2, qty 10) — price/profit differ
    # but are excluded from the projection.
    backtest = Decision(
        timestamp=_utc(DAY, 7),
        asset=a,
        sell_actions=[
            SellActionRecord(
                slot_number=2,
                filled_quantity=Decimal("10"),
                filled_price=Decimal("40000"),
                profit_pct=Decimal("14.28"),
                idempotency_key="backtest-sell",
                reasoning={},
            )
        ],
        reasoning={},
    )
    assert decisions_equivalent(settled, backtest)


def test_sell_pending_buy_skip_emits_observability_event() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    uow.positions.save(_filled_position(a, slot=2, qty="10", price="35000"))
    order = _pending_order(a, side=OrderSide.SELL, slot=2, qty="10", price="40250")
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    outcome = _settler(uow, broker).settle(TODAY)

    events = [e for e in outcome.events if e.kind == "sell_pending_buy_skip"]
    assert len(events) == 1
    assert events[0].level is NotificationLevel.WARNING


def test_pending_sell_abort_short_circuits_buy_documented() -> None:
    # The NF-1 event must document the next-cron recovery (not auto catch-up).
    uow = InMemoryUnitOfWork()
    a = _asset()
    uow.positions.save(_filled_position(a, slot=2, qty="10", price="35000"))
    order = _pending_order(a, side=OrderSide.SELL, slot=2, qty="10", price="40250")
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    outcome = _settler(uow, broker).settle(TODAY)
    body = next(e.body for e in outcome.events if e.kind == "sell_pending_buy_skip")
    assert "다음 cron" in body  # recovery is the next decision cron


# ---------------------------------------------------------------------------
# Partial / cancel / reject — no split, D5
# ---------------------------------------------------------------------------
def test_partial_fill_settle_blocks_split() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    # submitted TODAY so the day-order max-age does not fire (stays pending).
    order = _pending_order(a, side=OrderSide.BUY, slot=1, day=TODAY)
    uow.orders.save(order)
    broker = _FakeStatusBroker({
        order.idempotency_key: _result(
            order, status=OrderStatus.PARTIALLY_FILLED,
            filled_qty=Decimal("5"), filled_price=Decimal("35000"),
            filled_at=_utc(TODAY),
        )
    })

    outcome = _settler(uow, broker).settle(TODAY)

    assert uow.positions.get(a.fqn) is None  # no buy applied → no split
    assert outcome.settled_buys == []
    assert order.idempotency_key in outcome.still_pending_keys
    assert order.idempotency_key in [o.idempotency_key for o in uow.orders.list_pending()]


def test_partial_sell_settle_blocks_slot_exit() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    uow.positions.save(_filled_position(a, slot=2, qty="10", price="35000"))
    order = _pending_order(a, side=OrderSide.SELL, slot=2, day=TODAY, qty="10", price="40000")
    uow.orders.save(order)
    broker = _FakeStatusBroker({
        order.idempotency_key: _result(
            order, status=OrderStatus.PARTIALLY_FILLED,
            filled_qty=Decimal("4"), filled_price=Decimal("40000"),
            filled_at=_utc(TODAY),
        )
    })

    _settler(uow, broker).settle(TODAY)

    pos = uow.positions.get(a.fqn)
    assert pos is not None
    slot2 = pos.get_slot(2)
    assert slot2 is not None and slot2.state.value == "FILLED"  # slot not exited
    assert pos.split_level == 1


def test_canceled_pending_no_split() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _result(order, status=OrderStatus.CANCELED)})

    outcome = _settler(uow, broker).settle(TODAY)

    assert uow.positions.get(a.fqn) is None
    assert outcome.settled_buys == []
    assert uow.orders.get_by_idempotency_key(order.idempotency_key).status is OrderStatus.CANCELED  # type: ignore[union-attr]


def test_canceled_pending_transitions_out_of_list_pending() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _result(order, status=OrderStatus.EXPIRED)})

    _settler(uow, broker).settle(TODAY)

    assert order.idempotency_key not in [o.idempotency_key for o in uow.orders.list_pending()]


def test_canceled_pending_sell_no_slot_change() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    uow.positions.save(_filled_position(a, slot=2, qty="10", price="35000"))
    order = _pending_order(a, side=OrderSide.SELL, slot=2, qty="10", price="40000")
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _result(order, status=OrderStatus.CANCELED)})

    _settler(uow, broker).settle(TODAY)

    pos = uow.positions.get(a.fqn)
    assert pos is not None
    slot2 = pos.get_slot(2)
    assert slot2 is not None and slot2.state.value == "FILLED"


def test_rejected_pending_no_split_halts() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _result(order, status=OrderStatus.REJECTED)})

    with pytest.raises(StateMismatchError):
        _settler(uow, broker).settle(TODAY)
    assert uow.positions.get(a.fqn) is None  # no split applied


def test_canceled_with_nonzero_fill_halts() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({
        order.idempotency_key: _result(
            order, status=OrderStatus.CANCELED,
            filled_qty=Decimal("3"), filled_price=Decimal("35000"), filled_at=_utc(DAY),
        )
    })
    with pytest.raises(StateMismatchError):
        _settler(uow, broker).settle(TODAY)


# ---------------------------------------------------------------------------
# Max-age halt (gap b)
# ---------------------------------------------------------------------------
def test_partial_fill_max_age_escalates_halt() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    # submitted on a PRIOR day (DAY) but still PARTIAL at TODAY's cron → halt.
    order = _pending_order(a, side=OrderSide.BUY, slot=1, day=DAY)
    uow.orders.save(order)
    broker = _FakeStatusBroker({
        order.idempotency_key: _result(
            order, status=OrderStatus.PARTIALLY_FILLED,
            filled_qty=Decimal("5"), filled_price=Decimal("35000"), filled_at=_utc(DAY),
        )
    })
    with pytest.raises(StateMismatchError):
        _settler(uow, broker).settle(TODAY)


def test_stale_pending_max_age_escalates_halt() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1, day=DAY)
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _result(order, status=OrderStatus.PENDING)})
    with pytest.raises(StateMismatchError):
        _settler(uow, broker).settle(TODAY)


# ---------------------------------------------------------------------------
# Halt: lost order / malformed key
# ---------------------------------------------------------------------------
def test_get_order_status_none_halts() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({})  # broker has no record → None
    with pytest.raises(StateMismatchError):
        _settler(uow, broker).settle(TODAY)


def test_malformed_idempotency_key_halts() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    bad = Order(
        idempotency_key="not-a-canonical-key",
        asset=a,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        target_price=Decimal("35000"),
        status=OrderStatus.PENDING,
        broker_order_id="ODNO-x",
        filled_quantity=Decimal(0),
        filled_price=None,
        submitted_at=_utc(DAY),
        filled_at=None,
    )
    uow.orders.save(bad)
    broker = _FakeStatusBroker({bad.idempotency_key: _filled(bad)})
    with pytest.raises(OrderKeyError):
        _settler(uow, broker).settle(TODAY)


# ---------------------------------------------------------------------------
# Single-UoW atomicity + durability (M2)
# ---------------------------------------------------------------------------
class _LogPositions:
    def __init__(self, inner: object, log: list[str]) -> None:
        self._i = inner
        self._log = log

    def get(self, fqn: str) -> object:
        return self._i.get(fqn)  # type: ignore[attr-defined]

    def save(self, pos: object) -> None:
        self._log.append("positions.save")
        self._i.save(pos)  # type: ignore[attr-defined]


class _LogOrders:
    def __init__(self, inner: object, log: list[str]) -> None:
        self._i = inner
        self._log = log

    def list_pending(self) -> object:
        return self._i.list_pending()  # type: ignore[attr-defined]

    def get_by_idempotency_key(self, k: str) -> object:
        return self._i.get_by_idempotency_key(k)  # type: ignore[attr-defined]

    def update_status(self, *a: object, **k: object) -> None:
        self._log.append("orders.update_status")
        self._i.update_status(*a, **k)  # type: ignore[attr-defined]


class _LogDecisions:
    def __init__(self, inner: object, log: list[str]) -> None:
        self._i = inner
        self._log = log

    def save(self, d: object) -> None:
        self._log.append("decisions.save")
        self._i.save(d)  # type: ignore[attr-defined]


class _LoggingUoW:
    def __init__(self, backing: InMemoryUnitOfWork, log: list[str]) -> None:
        self._log = log
        self.positions = _LogPositions(backing.positions, log)
        self.orders = _LogOrders(backing.orders, log)
        self.decisions = _LogDecisions(backing.decisions, log)
        self.snapshots = backing.snapshots

    def __enter__(self) -> _LoggingUoW:
        self._log.append("enter")
        return self

    def __exit__(self, *exc: object) -> None:
        self._log.append("exit")

    def commit(self) -> None:
        self._log.append("commit")

    def rollback(self) -> None:
        self._log.append("rollback")


def test_settle_fill_and_status_transition_single_uow() -> None:
    backing = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    backing.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})
    log: list[str] = []

    settler = PendingSettler(
        uow_factory=lambda: _LoggingUoW(backing, log), broker=broker
    )
    settler.settle(TODAY)

    # Exactly one commit, and all three writes happen inside the same UoW
    # window (last enter → commit).
    assert log.count("commit") == 1
    commit_idx = log.index("commit")
    last_enter = max(i for i, e in enumerate(log[:commit_idx]) if e == "enter")
    window = log[last_enter:commit_idx]
    assert "positions.save" in window
    assert "orders.update_status" in window
    assert "decisions.save" in window


def test_settle_commits_each_settle_durably() -> None:
    uow = InMemoryUnitOfWork()
    a = _asset()
    order = _pending_order(a, side=OrderSide.BUY, slot=1)
    uow.orders.save(order)
    broker = _FakeStatusBroker({order.idempotency_key: _filled(order)})

    _settler(uow, broker).settle(TODAY)

    # State is durable after settle returns (committed before any later phase).
    assert uow.positions.get(a.fqn) is not None
    assert uow.orders.get_by_idempotency_key(order.idempotency_key).status is OrderStatus.FILLED  # type: ignore[union-attr]


def test_settle_partial_then_halt_leaves_consistent_db() -> None:
    # Order A (FILLED, processed first) commits durably; order B (REJECTED)
    # halts. A's settle survives the halt.
    uow = InMemoryUnitOfWork()
    a = _asset()
    order_a = _pending_order(a, side=OrderSide.BUY, slot=1, day=TODAY, hour=6)
    order_b = _pending_order(a, side=OrderSide.BUY, slot=2, day=TODAY, hour=7)
    uow.orders.save(order_a)
    uow.orders.save(order_b)
    broker = _FakeStatusBroker({
        order_a.idempotency_key: _filled(order_a),
        order_b.idempotency_key: _result(order_b, status=OrderStatus.REJECTED),
    })

    with pytest.raises(StateMismatchError):
        _settler(uow, broker).settle(TODAY)

    # A is durable (committed before B halted); B stays PENDING.
    pos = uow.positions.get(a.fqn)
    assert pos is not None and pos.split_level == 1
    assert uow.orders.get_by_idempotency_key(order_a.idempotency_key).status is OrderStatus.FILLED  # type: ignore[union-attr]
    assert uow.orders.get_by_idempotency_key(order_b.idempotency_key).status is OrderStatus.PENDING  # type: ignore[union-attr]
