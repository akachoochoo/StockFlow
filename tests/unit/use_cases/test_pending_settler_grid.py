"""Unit tests for PendingSettler grid settle branch (ADR 0022 §12 D21).

Verifies that 6-segment grid idempotency keys dispatch to the slot-free
``_settle_grid_filled`` path, persist GridDecision via uow.grid_decisions,
transition the order to FILLED, and leave the existing split settle paths
untouched.

Fakes only — zero real network / DB.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    Market,
    Money,
    Order,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.use_cases.pending_settler import PendingSettler

DAY = date(2026, 5, 22)
TODAY = date(2026, 5, 23)


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


def _utc(d: date, hour: int = 6) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=UTC)


def _grid_pending_order(
    asset: Asset,
    *,
    side: OrderSide,
    level_idx: int,
    qty: str = "10",
    price: str = "30000",
    day: date = DAY,
) -> Order:
    """Build a PENDING grid Order with the 6-segment idempotency key."""
    key = f"{asset.fqn}:{day.isoformat()}:{side.value.lower()}:grid:{level_idx}"
    return Order(
        idempotency_key=key,
        asset=asset,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        target_price=Decimal(price),
        status=OrderStatus.PENDING,
        broker_order_id="mock-1",
        filled_quantity=Decimal(0),
        filled_price=None,
        submitted_at=_utc(day),
        filled_at=None,
    )


def _make_broker(asset: Asset, fills: list[OrderRequest]) -> MockBroker:
    """MockBroker that immediately FILLs the given requests (mirrors what would
    have happened if the broker had been called synchronously)."""
    broker = MockBroker(
        initial_balance=Balance(
            cash=Money(amount=Decimal("10000000"), currency=Currency.KRW)
        ),
        clock=lambda: _utc(DAY),
    )
    for r in fills:
        broker.place_order(r)
    return broker


def _grid_request(
    asset: Asset,
    *,
    side: OrderSide,
    level_idx: int,
    qty: str = "10",
    price: str = "30000",
    day: date = DAY,
) -> OrderRequest:
    key = f"{asset.fqn}:{day.isoformat()}:{side.value.lower()}:grid:{level_idx}"
    return OrderRequest(
        idempotency_key=key,
        asset=asset,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        target_price=Decimal(price),
        grid_level_idx=level_idx,
    )


class TestGridBuySettle:
    def test_grid_buy_settle_persists_decision(self) -> None:
        asset = _asset()
        order = _grid_pending_order(asset, side=OrderSide.BUY, level_idx=3)
        broker = _make_broker(
            asset,
            fills=[_grid_request(asset, side=OrderSide.BUY, level_idx=3)],
        )

        uow = InMemoryUnitOfWork()
        with uow:
            uow.orders.save(order)
            uow.commit()

        settler = PendingSettler(uow_factory=lambda: uow, broker=broker)
        outcome = settler.settle(today=TODAY)

        # GridDecision persisted
        saved = uow.grid_decisions.list_for_date(asset.fqn, DAY)
        assert len(saved) == 1
        assert saved[0].side == OrderSide.BUY
        assert saved[0].level_index == 3
        assert saved[0].quantity == Decimal("10")

        # outcome
        assert len(outcome.settled_grid) == 1
        assert outcome.transitioned_keys == [order.idempotency_key]
        assert outcome.settled_buys == []
        assert outcome.settled_sells == []

        # Order status transitioned to FILLED
        updated = uow.orders.get_by_idempotency_key(order.idempotency_key)
        assert updated.status == OrderStatus.FILLED


class TestGridSellSettle:
    def test_grid_sell_settle_persists_decision(self) -> None:
        asset = _asset()
        # Seed broker with a holding so the SELL request is accepted there.
        buy_req = _grid_request(asset, side=OrderSide.BUY, level_idx=3)
        sell_req = _grid_request(
            asset, side=OrderSide.SELL, level_idx=4, price="30300"
        )
        broker = _make_broker(asset, fills=[buy_req, sell_req])

        sell_order = _grid_pending_order(
            asset, side=OrderSide.SELL, level_idx=4, price="30300"
        )

        uow = InMemoryUnitOfWork()
        with uow:
            uow.orders.save(sell_order)
            uow.commit()

        settler = PendingSettler(uow_factory=lambda: uow, broker=broker)
        outcome = settler.settle(today=TODAY)

        saved = uow.grid_decisions.list_for_date(asset.fqn, DAY)
        assert len(saved) == 1
        assert saved[0].side == OrderSide.SELL
        assert saved[0].level_index == 4
        assert saved[0].quantity == Decimal("10")
        assert outcome.settled_grid[0].side == OrderSide.SELL


class TestSplitRegression:
    """기존 split settle 경로 회귀 zero — grid 분기 추가가 영향 없음 확인."""

    def test_split_key_uses_existing_path_not_grid(self) -> None:
        asset = _asset()
        from src.domain.order_keys import build_order_key

        # split BUY request (slot_number, 5-segment key)
        split_req = OrderRequest(
            idempotency_key=build_order_key(
                asset_fqn=asset.fqn,
                date_iso=DAY.isoformat(),
                side=OrderSide.BUY,
                slot_number=1,
            ),
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            target_price=Decimal("35000"),
            slot_number=1,
        )
        broker = _make_broker(asset, fills=[split_req])

        split_order = Order(
            idempotency_key=split_req.idempotency_key,
            asset=asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            target_price=Decimal("35000"),
            status=OrderStatus.PENDING,
            broker_order_id="mock-1",
            filled_quantity=Decimal(0),
            filled_price=None,
            submitted_at=_utc(DAY),
            filled_at=None,
        )

        uow = InMemoryUnitOfWork()
        with uow:
            uow.orders.save(split_order)
            uow.commit()

        settler = PendingSettler(uow_factory=lambda: uow, broker=broker)
        outcome = settler.settle(today=TODAY)

        # split path 경유 → settled_buys 에 들어가야 함 (grid 가 아님)
        assert len(outcome.settled_buys) == 1
        assert outcome.settled_grid == []
        # Position 도 split 경로로 저장됨
        assert uow.positions.get(asset.fqn) is not None
        # grid_decisions 는 비어있어야 함
        assert uow.grid_decisions.list_for_date(asset.fqn, DAY) == []


class TestKeyFormatDetection:
    def test_grid_key_routes_to_grid_path(self) -> None:
        """6세그먼트 grid 키 → grid settle 경로. 5세그먼트 split 키 → 기존 경로."""
        asset = _asset()
        grid_order = _grid_pending_order(
            asset, side=OrderSide.BUY, level_idx=5
        )
        broker = _make_broker(
            asset,
            fills=[_grid_request(asset, side=OrderSide.BUY, level_idx=5)],
        )

        uow = InMemoryUnitOfWork()
        with uow:
            uow.orders.save(grid_order)
            uow.commit()

        settler = PendingSettler(uow_factory=lambda: uow, broker=broker)
        outcome = settler.settle(today=TODAY)
        assert outcome.settled_grid[0].level_index == 5
        assert outcome.settled_buys == []
