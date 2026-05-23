"""Unit tests for src.adapters.kis.order_store — SqliteKISOrderStore.

The adapter wraps an injected ``OrderRepoPort`` and converts the persisted
:class:`Order` to the :class:`OrderResult` the KISOrderStore Protocol returns.
Uses a fake in-memory OrderRepoPort — zero DB, zero network.

Coverage (function names carry ``kis_order_store`` for the gate selector):
- find_by_idempotency_key: Order → OrderResult conversion (all carried
  fields) + None when unknown.
- find_by_broker_order_id: Order → OrderResult conversion + None when unknown.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.adapters.kis.order_store import SqliteKISOrderStore
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Order,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)

UTC_NOW = datetime(2026, 5, 22, 1, 0, 0, tzinfo=UTC)
UTC_LATER = datetime(2026, 5, 22, 6, 0, 0, tzinfo=UTC)


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
    broker_order_id: str | None = "odno-1",
    status: OrderStatus = OrderStatus.FILLED,
    filled_quantity: str = "10",
    filled_price: str | None = "35000",
    tax: str | None = "52.5",
    commission: str | None = "17.5",
    broker_org_no: str | None = "00950",
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
        submitted_at=UTC_NOW,
        filled_at=UTC_LATER if status == OrderStatus.FILLED else None,
        tax=Decimal(tax) if tax is not None else None,
        commission=Decimal(commission) if commission is not None else None,
        broker_org_no=broker_org_no,
    )


class _FakeOrderRepo:
    """In-memory OrderRepoPort stand-in for the order_store adapter."""

    def __init__(self, orders: list[Order] | None = None) -> None:
        self._by_key = {o.idempotency_key: o for o in (orders or [])}

    def get_by_idempotency_key(self, key: str) -> Order | None:
        return self._by_key.get(key)

    def find_by_broker_order_id(self, broker_order_id: str) -> Order | None:
        for o in self._by_key.values():
            if o.broker_order_id == broker_order_id:
                return o
        return None


class TestKISOrderStoreFindByIdempotencyKey:
    def test_kis_order_store_find_by_idempotency_key_converts_to_result(self):
        order = _order()
        store = SqliteKISOrderStore(orders=_FakeOrderRepo([order]))
        result = store.find_by_idempotency_key("k1")
        assert isinstance(result, OrderResult)
        assert result.idempotency_key == "k1"
        assert result.asset == order.asset
        assert result.broker_order_id == "odno-1"
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == Decimal("10")
        assert result.filled_price == Decimal("35000")
        assert result.submitted_at == UTC_NOW
        assert result.filled_at == UTC_LATER
        assert result.tax == Decimal("52.5")
        assert result.commission == Decimal("17.5")
        assert result.broker_org_no == "00950"

    def test_kis_order_store_find_by_idempotency_key_none_when_unknown(self):
        store = SqliteKISOrderStore(orders=_FakeOrderRepo([_order()]))
        assert store.find_by_idempotency_key("unknown") is None


class TestKISOrderStoreFindByBrokerOrderId:
    def test_kis_order_store_find_by_broker_order_id_converts_to_result(self):
        order = _order(broker_order_id="odno-7")
        store = SqliteKISOrderStore(orders=_FakeOrderRepo([order]))
        result = store.find_by_broker_order_id("odno-7")
        assert isinstance(result, OrderResult)
        assert result.idempotency_key == "k1"
        assert result.broker_order_id == "odno-7"
        assert result.broker_org_no == "00950"

    def test_kis_order_store_find_by_broker_order_id_none_when_unknown(self):
        store = SqliteKISOrderStore(orders=_FakeOrderRepo([_order()]))
        assert store.find_by_broker_order_id("odno-missing") is None

    def test_kis_order_store_pending_order_converts_with_nulls(self):
        # PENDING order: filled_at None, filled_price None, costs provisional.
        pending = _order(
            status=OrderStatus.PENDING,
            filled_quantity="0",
            filled_price=None,
            tax=None,
            commission=None,
        )
        store = SqliteKISOrderStore(orders=_FakeOrderRepo([pending]))
        result = store.find_by_idempotency_key("k1")
        assert result is not None
        assert result.status == OrderStatus.PENDING
        assert result.filled_quantity == Decimal("0")
        assert result.filled_price is None
        assert result.filled_at is None
        assert result.tax is None
        assert result.commission is None
