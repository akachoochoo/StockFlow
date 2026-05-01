"""Tests for InMemoryUnitOfWork — backtest persistence + no-op transactions."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.adapters.mock.in_memory_unit_of_work import (
    InMemoryDecisionRepo,
    InMemoryOrderRepo,
    InMemoryPortfolioSnapshotRepo,
    InMemoryPositionRepo,
    InMemoryUnitOfWork,
)
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Decision,
    Exchange,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    Position,
    SplitEntry,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)


def _asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


def _order(
    *,
    idempotency_key: str = "k1",
    status: OrderStatus = OrderStatus.FILLED,
    submitted_at: datetime = UTC_NOW,
) -> Order:
    # Match Order's per-status invariants:
    # FILLED requires full fill at price; PARTIALLY_FILLED requires 0 < q < 10;
    # PENDING / REJECTED have no fill.
    if status == OrderStatus.FILLED:
        filled_q = Decimal("10")
        filled_p: Decimal | None = Decimal("35000")
        broker_id: str | None = "bid-1"
        filled_at: datetime | None = UTC_NOW
    elif status == OrderStatus.PARTIALLY_FILLED:
        filled_q = Decimal("5")
        filled_p = Decimal("35000")
        broker_id = "bid-1"
        filled_at = UTC_NOW
    else:
        filled_q = Decimal("0")
        filled_p = None
        broker_id = (
            None if status == OrderStatus.REJECTED else "bid-1"
        )
        filled_at = None
    return Order(
        idempotency_key=idempotency_key,
        asset=_asset(),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        target_price=Decimal("35000"),
        status=status,
        broker_order_id=broker_id,
        filled_quantity=filled_q,
        filled_price=filled_p,
        submitted_at=submitted_at,
        filled_at=filled_at,
    )


def _position(asset: Asset) -> Position:
    return Position(
        asset=asset,
        quantity=Decimal("10"),
        avg_price=Decimal("35000"),
        split_level=1,
        last_buy_at=UTC_NOW,
        entries=[
            SplitEntry(
                split_number=1,
                entry_date=UTC_NOW.date(),
                quantity=Decimal("10"),
                entry_price=Decimal("35000"),
                idempotency_key="k1",
            )
        ],
    )


def _decision(asset: Asset, *, ts: datetime = UTC_NOW, action: str = "buy_split_1") -> Decision:
    return Decision(
        timestamp=ts,
        asset=asset,
        action=action,
        reasoning={"current_price": "35000"},
        resulting_order_id="bid-1",
    )


def _snapshot(d: date) -> PortfolioSnapshot:
    return PortfolioSnapshot.build(
        snapshot_date=d,
        snapshot_at=UTC_NOW,
        initial_capital=Money(amount=Decimal("4000000"), currency=Currency.KRW),
        cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
        valuations=[],
    )


# ---------------------------------------------------------------------------
# Individual repos
# ---------------------------------------------------------------------------
class TestInMemoryPositionRepo:
    def test_save_and_get(self):
        repo = InMemoryPositionRepo()
        a = _asset()
        repo.save(_position(a))
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.asset == a

    def test_get_returns_none_when_missing(self):
        repo = InMemoryPositionRepo()
        assert repo.get("KRX:000000") is None

    def test_save_upserts_by_fqn(self):
        repo = InMemoryPositionRepo()
        a = _asset()
        repo.save(_position(a))
        # Re-save with same fqn — replaces
        repo.save(Position.empty(a))
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.quantity == Decimal(0)

    def test_list_all_sorted_by_fqn(self):
        repo = InMemoryPositionRepo()
        repo.save(Position.empty(_asset(code="105190")))
        repo.save(Position.empty(_asset(code="069500")))
        result = repo.list_all()
        assert [p.asset.fqn for p in result] == [
            "KRX:069500",
            "KRX:105190",
        ]

    def test_delete_returns_true_when_present(self):
        repo = InMemoryPositionRepo()
        a = _asset()
        repo.save(Position.empty(a))
        assert repo.delete(a.fqn) is True
        assert repo.get(a.fqn) is None

    def test_delete_returns_false_when_missing(self):
        repo = InMemoryPositionRepo()
        assert repo.delete("KRX:999999") is False


class TestInMemoryOrderRepo:
    def test_save_and_get(self):
        repo = InMemoryOrderRepo()
        repo.save(_order())
        assert repo.get_by_idempotency_key("k1") == _order()

    def test_duplicate_key_raises_value_error(self):
        repo = InMemoryOrderRepo()
        repo.save(_order())
        with pytest.raises(ValueError, match="Duplicate"):
            repo.save(_order())

    def test_list_pending_filters(self):
        repo = InMemoryOrderRepo()
        repo.save(_order(idempotency_key="filled", status=OrderStatus.FILLED))
        repo.save(_order(idempotency_key="pending", status=OrderStatus.PENDING))
        repo.save(
            _order(
                idempotency_key="partial",
                status=OrderStatus.PARTIALLY_FILLED,
            )
        )
        repo.save(
            _order(idempotency_key="rejected", status=OrderStatus.REJECTED)
        )
        keys = {o.idempotency_key for o in repo.list_pending()}
        assert keys == {"pending", "partial"}

    def test_list_by_date_filters(self):
        repo = InMemoryOrderRepo()
        from datetime import timedelta

        today = UTC_NOW
        yesterday = UTC_NOW - timedelta(days=1)
        repo.save(_order(idempotency_key="t1", submitted_at=today))
        repo.save(_order(idempotency_key="t2", submitted_at=today))
        repo.save(_order(idempotency_key="y1", submitted_at=yesterday))
        keys = {o.idempotency_key for o in repo.list_by_date(date(2026, 4, 30))}
        assert keys == {"t1", "t2"}


class TestInMemoryDecisionRepo:
    def test_save_and_query(self):
        repo = InMemoryDecisionRepo()
        a = _asset()
        repo.save(_decision(a))
        result = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert len(result) == 1

    def test_list_by_date_range_filters_and_sorts(self):
        repo = InMemoryDecisionRepo()
        a = _asset()
        repo.save(_decision(a, ts=datetime(2026, 4, 30, 16, 0, 0, tzinfo=UTC)))
        repo.save(_decision(a, ts=datetime(2026, 4, 28, 6, 0, 0, tzinfo=UTC)))
        repo.save(_decision(a, ts=datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)))
        result = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert [d.timestamp for d in result] == [
            datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC),
            datetime(2026, 4, 30, 16, 0, 0, tzinfo=UTC),
        ]

    def test_get_last_for_asset_returns_most_recent(self):
        repo = InMemoryDecisionRepo()
        a = _asset(code="069500")
        b = _asset(code="105190")
        repo.save(_decision(a, ts=datetime(2026, 4, 28, 6, 0, 0, tzinfo=UTC)))
        repo.save(_decision(a, ts=datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)))
        repo.save(_decision(b, ts=datetime(2026, 4, 29, 6, 0, 0, tzinfo=UTC)))
        last = repo.get_last_for_asset(a.fqn)
        assert last is not None
        assert last.timestamp == datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)

    def test_get_last_returns_none_when_no_decisions(self):
        repo = InMemoryDecisionRepo()
        assert repo.get_last_for_asset("KRX:000000") is None


class TestInMemoryPortfolioSnapshotRepo:
    def test_save_and_get_by_date(self):
        repo = InMemoryPortfolioSnapshotRepo()
        snap = _snapshot(date(2026, 4, 30))
        repo.save(snap)
        loaded = repo.get_by_date(date(2026, 4, 30))
        assert loaded == snap

    def test_save_upserts_by_date(self):
        repo = InMemoryPortfolioSnapshotRepo()
        repo.save(_snapshot(date(2026, 4, 30)))
        # Same date upsert (different instance acceptable)
        repo.save(_snapshot(date(2026, 4, 30)))
        result = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert len(result) == 1

    def test_get_returns_none_for_unknown_date(self):
        repo = InMemoryPortfolioSnapshotRepo()
        assert repo.get_by_date(date(2026, 1, 1)) is None

    def test_list_by_date_range_filters_and_sorts(self):
        repo = InMemoryPortfolioSnapshotRepo()
        for d in (date(2026, 4, 30), date(2026, 4, 27), date(2026, 4, 29)):
            repo.save(_snapshot(d))
        result = repo.list_by_date_range(date(2026, 4, 28), date(2026, 4, 30))
        assert [s.snapshot_date for s in result] == [
            date(2026, 4, 29),
            date(2026, 4, 30),
        ]


# ---------------------------------------------------------------------------
# UnitOfWork
# ---------------------------------------------------------------------------
class TestInMemoryUnitOfWork:
    def test_exposes_four_repos(self):
        uow = InMemoryUnitOfWork()
        assert isinstance(uow.positions, InMemoryPositionRepo)
        assert isinstance(uow.orders, InMemoryOrderRepo)
        assert isinstance(uow.decisions, InMemoryDecisionRepo)
        assert isinstance(uow.snapshots, InMemoryPortfolioSnapshotRepo)

    def test_writes_persist_without_commit(self):
        # Per ADR §8.9: in-memory variant does NOT simulate rollback.
        a = _asset()
        with InMemoryUnitOfWork() as uow:
            uow.orders.save(_order())
            uow.positions.save(_position(a))
            # No commit() — but writes are durable on the in-memory dicts.
            assert uow.orders.get_by_idempotency_key("k1") is not None
            assert uow.positions.get(a.fqn) is not None

    def test_commit_is_noop(self):
        uow = InMemoryUnitOfWork()
        # Calling commit() must not raise; the value is unchanged.
        uow.orders.save(_order())
        uow.commit()
        assert uow.orders.get_by_idempotency_key("k1") is not None

    def test_rollback_is_noop_does_not_undo_writes(self):
        # Documented behaviour: rollback is a no-op in the in-memory variant.
        uow = InMemoryUnitOfWork()
        uow.orders.save(_order())
        uow.rollback()
        assert uow.orders.get_by_idempotency_key("k1") is not None

    def test_exception_inside_block_does_not_undo_writes(self):
        # In-memory variant intentionally does NOT roll back on exception
        # (Phase 0 backtest determinism). Live trading uses SqliteUoW.
        uow = InMemoryUnitOfWork()
        with pytest.raises(RuntimeError, match="boom"):  # noqa: SIM117
            with uow:
                uow.orders.save(_order())
                raise RuntimeError("boom")
        assert uow.orders.get_by_idempotency_key("k1") is not None
