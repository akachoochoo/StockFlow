"""Tests for SqliteOrderRepo (round-trip + filters)."""
from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.infrastructure.repositories.sqlite_order_repo import SqliteOrderRepo

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
UTC_LATER = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


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


def _order(
    *,
    idempotency_key: str = "k1",
    status: OrderStatus = OrderStatus.FILLED,
    submitted_at: datetime = UTC_NOW,
    filled_at: datetime | None = UTC_LATER,
    filled_quantity: str = "10",
    filled_price: str | None = "35000",
    broker_order_id: str | None = "bid-1",
    tax: str | None = None,
    commission: str | None = None,
    broker_org_no: str | None = None,
) -> Order:
    return Order(
        idempotency_key=idempotency_key,
        asset=_asset(),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        target_price=Decimal("35000"),
        status=status,
        broker_order_id=broker_order_id,
        filled_quantity=Decimal(filled_quantity),
        filled_price=Decimal(filled_price) if filled_price is not None else None,
        submitted_at=submitted_at,
        filled_at=filled_at,
        tax=Decimal(tax) if tax is not None else None,
        commission=Decimal(commission) if commission is not None else None,
        broker_org_no=broker_org_no,
    )


class TestSqliteOrderRepoRoundTrip:
    def test_save_then_get_returns_equal_order(self, conn):
        repo = SqliteOrderRepo(conn)
        original = _order()
        repo.save(original)
        loaded = repo.get_by_idempotency_key("k1")
        assert loaded == original

    def test_get_returns_none_for_unknown_key(self, conn):
        repo = SqliteOrderRepo(conn)
        assert repo.get_by_idempotency_key("nonexistent") is None

    def test_pending_order_round_trip(self, conn):
        repo = SqliteOrderRepo(conn)
        pending = _order(
            status=OrderStatus.PENDING,
            filled_at=None,
            filled_quantity="0",
            filled_price=None,
        )
        repo.save(pending)
        loaded = repo.get_by_idempotency_key("k1")
        assert loaded == pending
        assert loaded.filled_at is None
        assert loaded.filled_price is None

    def test_rejected_order_with_no_broker_id(self, conn):
        repo = SqliteOrderRepo(conn)
        rejected = _order(
            status=OrderStatus.REJECTED,
            broker_order_id=None,
            filled_at=None,
            filled_quantity="0",
            filled_price=None,
        )
        repo.save(rejected)
        loaded = repo.get_by_idempotency_key("k1")
        assert loaded == rejected
        assert loaded.broker_order_id is None

    def test_cost_fields_none_round_trip(self, conn):
        # ADR 0019 — provisional None tax/commission/broker_org_no.
        repo = SqliteOrderRepo(conn)
        original = _order()
        assert original.tax is None
        repo.save(original)
        loaded = repo.get_by_idempotency_key("k1")
        assert loaded == original
        assert loaded.tax is None
        assert loaded.commission is None
        assert loaded.broker_org_no is None

    def test_cost_fields_values_round_trip(self, conn):
        # ADR 0019 — tax/commission/broker_org_no persist and restore.
        repo = SqliteOrderRepo(conn)
        original = _order(
            tax="52.5",
            commission="17.5",
            broker_org_no="00950",
        )
        repo.save(original)
        loaded = repo.get_by_idempotency_key("k1")
        assert loaded == original
        assert loaded.tax == Decimal("52.5")
        assert loaded.commission == Decimal("17.5")
        assert loaded.broker_org_no == "00950"


class TestSqliteOrderRepoFilters:
    def test_list_pending_includes_pending_and_partial(self, conn):
        repo = SqliteOrderRepo(conn)
        repo.save(_order(idempotency_key="filled", status=OrderStatus.FILLED))
        repo.save(
            _order(
                idempotency_key="pending",
                status=OrderStatus.PENDING,
                filled_at=None,
                filled_quantity="0",
                filled_price=None,
            )
        )
        repo.save(
            _order(
                idempotency_key="partial",
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity="5",
            )
        )
        repo.save(
            _order(
                idempotency_key="rejected",
                status=OrderStatus.REJECTED,
                broker_order_id=None,
                filled_at=None,
                filled_quantity="0",
                filled_price=None,
            )
        )
        keys = {o.idempotency_key for o in repo.list_pending()}
        assert keys == {"pending", "partial"}

    def test_list_pending_empty(self, conn):
        repo = SqliteOrderRepo(conn)
        assert repo.list_pending() == []

    def test_list_by_date_filters_by_submitted_date(self, conn):
        repo = SqliteOrderRepo(conn)
        today = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        yesterday = today - timedelta(days=1)
        repo.save(_order(idempotency_key="today1", submitted_at=today))
        repo.save(_order(idempotency_key="today2", submitted_at=today))
        repo.save(_order(idempotency_key="yesterday1", submitted_at=yesterday))
        keys = {o.idempotency_key for o in repo.list_by_date(date(2026, 4, 30))}
        assert keys == {"today1", "today2"}

    def test_list_by_date_empty_when_no_match(self, conn):
        repo = SqliteOrderRepo(conn)
        repo.save(_order())
        assert repo.list_by_date(date(2026, 5, 5)) == []


class TestSqliteOrderRepoIntegrity:
    def test_duplicate_idempotency_key_raises_integrity_error(self, conn):
        repo = SqliteOrderRepo(conn)
        repo.save(_order(idempotency_key="dup"))
        with pytest.raises(sqlite3.IntegrityError):
            repo.save(_order(idempotency_key="dup"))
