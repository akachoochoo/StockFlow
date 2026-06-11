"""Tests for MockBroker grid fill paths (ADR 0022 §12 D19).

slot 우회 경로 검증 — grid_level_idx 가 set 인 OrderRequest 가 split Position
이 아닌 _grid_holdings 에 적용되는지, weighted avg / partial sell / mutual
exclusion / state 주입 등이 정확한지.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.adapters.mock.broker import MockBroker
from src.domain.exceptions import BrokerConnectionError
from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    GridHolding,
    Market,
    Money,
    OrderRequest,
    OrderSide,
    OrderType,
    Position,
    SplitSlot,
)

UTC_NOW = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)


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


def _balance(amount: str = "10000000") -> Balance:
    return Balance(cash=Money(amount=Decimal(amount), currency=Currency.KRW))


def _broker() -> MockBroker:
    return MockBroker(initial_balance=_balance(), clock=lambda: UTC_NOW)


def _grid_buy(
    asset: Asset,
    *,
    level: int,
    qty: str,
    price: str,
    key_suffix: str = "",
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=f"{asset.fqn}:2026-05-28:buy:grid:{level}{key_suffix}",
        asset=asset,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        target_price=Decimal(price),
        grid_level_idx=level,
    )


def _grid_sell(
    asset: Asset,
    *,
    level: int,
    qty: str,
    price: str,
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=f"{asset.fqn}:2026-05-28:sell:grid:{level}",
        asset=asset,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        target_price=Decimal(price),
        grid_level_idx=level,
    )


class TestGridBuy:
    def test_first_buy_creates_holding(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="10", price="30000"))
        h = broker.get_grid_holding(asset.fqn)
        assert h is not None
        assert h.quantity == Decimal("10")
        assert h.avg_price == Decimal("30000")
        assert h.cost_basis == Decimal("300000")
        assert h.last_buy_at == UTC_NOW

    def test_cash_debited_on_buy(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="10", price="30000"))
        assert broker.get_balance().cash.amount == Decimal("9700000")

    def test_second_buy_weighted_avg(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="10", price="30000"))
        broker.place_order(_grid_buy(asset, level=2, qty="10", price="29700"))
        h = broker.get_grid_holding(asset.fqn)
        # (10*30000 + 10*29700) / 20 = 29850
        assert h.quantity == Decimal("20")
        assert h.avg_price == Decimal("29850")

    def test_split_position_not_created(self) -> None:
        """Grid BUY 는 split Position 을 만들지 않음."""
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="10", price="30000"))
        assert broker.get_positions() == []


class TestGridSell:
    def test_partial_sell_keeps_avg_price(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="20", price="30000"))
        broker.place_order(_grid_sell(asset, level=4, qty="8", price="30300"))
        h = broker.get_grid_holding(asset.fqn)
        assert h.quantity == Decimal("12")
        assert h.avg_price == Decimal("30000")  # 유지

    def test_full_sell_removes_holding(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="10", price="30000"))
        broker.place_order(_grid_sell(asset, level=4, qty="10", price="30300"))
        assert broker.get_grid_holding(asset.fqn) is None

    def test_oversell_raises(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="10", price="30000"))
        with pytest.raises(BrokerConnectionError, match="exceeds holding"):
            broker.place_order(_grid_sell(asset, level=4, qty="11", price="30300"))

    def test_sell_without_holding_raises(self) -> None:
        broker = _broker()
        asset = _asset()
        with pytest.raises(BrokerConnectionError, match="exceeds holding"):
            broker.place_order(_grid_sell(asset, level=4, qty="1", price="30000"))

    def test_cash_credited_on_sell(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(_grid_buy(asset, level=3, qty="10", price="30000"))
        broker.place_order(_grid_sell(asset, level=4, qty="10", price="30300"))
        # 1억 - 300k + 303k = 10003000
        assert broker.get_balance().cash.amount == Decimal("10003000")


class TestGetHoldingsAggregated:
    def test_includes_grid_holdings(self) -> None:
        broker = _broker()
        a = _asset("069500")
        broker.place_order(_grid_buy(a, level=3, qty="10", price="30000"))
        holdings = broker.get_holdings()
        assert len(holdings) == 1
        assert holdings[0].asset_code == "069500"
        assert holdings[0].quantity == Decimal("10")
        assert holdings[0].avg_price == Decimal("30000")

    def test_empty_after_full_sell(self) -> None:
        broker = _broker()
        a = _asset()
        broker.place_order(_grid_buy(a, level=3, qty="10", price="30000"))
        broker.place_order(_grid_sell(a, level=4, qty="10", price="30300"))
        assert broker.get_holdings() == []


class TestMutualExclusion:
    def test_grid_buy_rejected_when_split_position_exists(self) -> None:
        """같은 asset 에 split Position 이 qty>0 → grid BUY 거부."""
        broker = _broker()
        asset = _asset()
        # split BUY 먼저
        broker.place_order(
            OrderRequest(
                idempotency_key=f"{asset.fqn}:2026-05-28:buy:1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                target_price=Decimal("30000"),
                slot_number=1,
            )
        )
        with pytest.raises(BrokerConnectionError, match="mutual exclusion"):
            broker.place_order(_grid_buy(asset, level=3, qty="5", price="29000"))

    def test_set_grid_holding_rejected_when_split_position_exists(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(
            OrderRequest(
                idempotency_key=f"{asset.fqn}:2026-05-28:buy:1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                target_price=Decimal("30000"),
                slot_number=1,
            )
        )
        with pytest.raises(BrokerConnectionError, match="mutual exclusion"):
            broker.set_grid_holding(
                GridHolding(
                    asset=asset,
                    quantity=Decimal("5"),
                    avg_price=Decimal("29000"),
                    cost_basis=Decimal("145000"),
                    last_buy_at=UTC_NOW,
                )
            )


class TestStateInjection:
    def test_set_grid_holding_restores_state(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.set_grid_holding(
            GridHolding(
                asset=asset,
                quantity=Decimal("10"),
                avg_price=Decimal("30000"),
                cost_basis=Decimal("300000"),
                last_buy_at=UTC_NOW,
            )
        )
        h = broker.get_grid_holding(asset.fqn)
        assert h.quantity == Decimal("10")
        # 이후 BUY 가 누적 weighted avg
        broker.place_order(_grid_buy(asset, level=4, qty="10", price="29700"))
        h2 = broker.get_grid_holding(asset.fqn)
        assert h2.quantity == Decimal("20")
        assert h2.avg_price == Decimal("29850")


class TestSplitRegression:
    """기존 split 경로 회귀 zero — D19 grid 분기 가 영향 없음."""

    def test_split_buy_then_sell_unchanged(self) -> None:
        broker = _broker()
        asset = _asset()
        broker.place_order(
            OrderRequest(
                idempotency_key=f"{asset.fqn}:2026-05-28:buy:1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                target_price=Decimal("30000"),
                slot_number=1,
            )
        )
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("10")
        # grid 미사용 — _grid_holdings 비어있음
        assert broker.get_grid_holding(asset.fqn) is None
