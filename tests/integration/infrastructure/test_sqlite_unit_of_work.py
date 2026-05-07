"""Tests for SqliteUnitOfWork — transactional behavior + repo wiring."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Decision,
    Exchange,
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    SkipReason,
    SplitEntry,
    SplitSlot,
)
from src.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)


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


def _order(idempotency_key: str = "k1") -> Order:
    return Order(
        idempotency_key=idempotency_key,
        asset=_asset(),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        target_price=Decimal("35000"),
        status=OrderStatus.FILLED,
        broker_order_id="bid-1",
        filled_quantity=Decimal("10"),
        filled_price=Decimal("35000"),
        submitted_at=UTC_NOW,
        filled_at=UTC_NOW,
    )


def _position(asset: Asset) -> Position:
    entry = SplitEntry(
        split_number=1,
        entry_date=UTC_NOW.date(),
        quantity=Decimal("10"),
        entry_price=Decimal("35000"),
        idempotency_key="k1",
    )
    slots = [SplitSlot.filled(entry=entry)]
    slots.extend(SplitSlot.empty(slot_number=i) for i in range(2, 8))
    return Position(
        asset=asset,
        quantity=Decimal("10"),
        avg_price=Decimal("35000"),
        split_level=1,
        last_buy_at=UTC_NOW,
        slots=slots,
    )


def _decision(asset: Asset) -> Decision:
    # Phase 0.5: skip-shaped Decision (sells/buy empty, skip_reason set).
    return Decision(
        timestamp=UTC_NOW,
        asset=asset,
        skip_reason=SkipReason.STRATEGY_NO_BUY,
        reasoning={"current_price": "35000"},
    )


class TestSqliteUnitOfWorkCommit:
    def test_commit_persists_writes(self, conn):
        a = _asset()
        with SqliteUnitOfWork(conn) as uow:
            uow.orders.save(_order())
            uow.positions.save(_position(a))
            uow.decisions.save(_decision(a))
            uow.commit()

        # Re-open a fresh UoW and verify the writes are visible.
        with SqliteUnitOfWork(conn) as uow:
            assert uow.orders.get_by_idempotency_key("k1") is not None
            assert uow.positions.get(a.fqn) is not None
            assert uow.decisions.get_last_for_asset(a.fqn) is not None

    def test_no_commit_rolls_back_on_exit(self, conn):
        a = _asset()
        with SqliteUnitOfWork(conn) as uow:
            uow.orders.save(_order())
            # No commit() — context exit must rollback.

        with SqliteUnitOfWork(conn) as uow:
            assert uow.orders.get_by_idempotency_key("k1") is None
            assert uow.positions.get(a.fqn) is None

    def test_exception_inside_block_rolls_back(self, conn):
        a = _asset()
        with pytest.raises(RuntimeError, match="boom"), SqliteUnitOfWork(conn) as uow:
            uow.orders.save(_order())
            uow.positions.save(_position(a))
            raise RuntimeError("boom")  # before commit

        with SqliteUnitOfWork(conn) as uow:
            assert uow.orders.get_by_idempotency_key("k1") is None
            assert uow.positions.get(a.fqn) is None

    def test_explicit_rollback_discards_writes(self, conn):
        with SqliteUnitOfWork(conn) as uow:
            uow.orders.save(_order())
            uow.rollback()
            # After rollback, in-flight is gone but UoW remains usable.
            assert uow.orders.get_by_idempotency_key("k1") is None

    def test_commit_then_re_enter_works(self, conn):
        # After a successful commit and exit, a new UoW should still observe
        # the committed state and be able to start its own transaction.
        with SqliteUnitOfWork(conn) as uow:
            uow.orders.save(_order(idempotency_key="first"))
            uow.commit()
        with SqliteUnitOfWork(conn) as uow:
            assert uow.orders.get_by_idempotency_key("first") is not None
            uow.orders.save(_order(idempotency_key="second"))
            uow.commit()
        with SqliteUnitOfWork(conn) as uow:
            assert uow.orders.get_by_idempotency_key("first") is not None
            assert uow.orders.get_by_idempotency_key("second") is not None


class TestSqliteUnitOfWorkAtomicity:
    def test_partial_save_then_failure_rolls_back_all(self, conn):
        # Save order + decision, then raise; both must be discarded.
        a = _asset()
        with pytest.raises(ValueError, match="simulated"), SqliteUnitOfWork(conn) as uow:
            uow.orders.save(_order(idempotency_key="atomic"))
            uow.decisions.save(_decision(a))
            raise ValueError("simulated post-decision error")

        with SqliteUnitOfWork(conn) as uow:
            assert uow.orders.get_by_idempotency_key("atomic") is None
            assert uow.decisions.get_last_for_asset(a.fqn) is None

    def test_save_then_repository_error_rolls_back_prior_writes(self, conn):
        # Insert order successfully, then attempt duplicate insert (raises
        # IntegrityError); the first insert should be discarded too.
        import sqlite3

        with (
            pytest.raises(sqlite3.IntegrityError),
            SqliteUnitOfWork(conn) as uow,
        ):
            uow.orders.save(_order(idempotency_key="first-insert"))
            uow.orders.save(_order(idempotency_key="first-insert"))
            # IntegrityError fires here; never reach commit()

        with SqliteUnitOfWork(conn) as uow:
            assert uow.orders.get_by_idempotency_key("first-insert") is None


class TestSqliteUnitOfWorkRepoWiring:
    def test_exposes_four_repositories(self, conn):
        from src.infrastructure.repositories.sqlite_decision_repo import (
            SqliteDecisionRepo,
        )
        from src.infrastructure.repositories.sqlite_order_repo import (
            SqliteOrderRepo,
        )
        from src.infrastructure.repositories.sqlite_portfolio_snapshot_repo import (
            SqlitePortfolioSnapshotRepo,
        )
        from src.infrastructure.repositories.sqlite_position_repo import (
            SqlitePositionRepo,
        )

        uow = SqliteUnitOfWork(conn)
        assert isinstance(uow.positions, SqlitePositionRepo)
        assert isinstance(uow.orders, SqliteOrderRepo)
        assert isinstance(uow.decisions, SqliteDecisionRepo)
        assert isinstance(uow.snapshots, SqlitePortfolioSnapshotRepo)

    def test_factory_pattern_yields_fresh_uow_each_call(self, conn):
        # The "uow_factory" closure pattern that the orchestrator uses.
        def uow_factory() -> SqliteUnitOfWork:
            return SqliteUnitOfWork(conn)

        with uow_factory() as uow1:
            uow1.orders.save(_order(idempotency_key="a"))
            uow1.commit()
        with uow_factory() as uow2:
            assert uow2.orders.get_by_idempotency_key("a") is not None
            uow2.orders.save(_order(idempotency_key="b"))
            uow2.commit()
        with uow_factory() as uow3:
            assert uow3.orders.get_by_idempotency_key("a") is not None
            assert uow3.orders.get_by_idempotency_key("b") is not None
