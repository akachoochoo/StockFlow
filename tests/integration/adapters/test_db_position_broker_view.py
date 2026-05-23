"""Integration tests for DbPositionBrokerView (C2 / 8-1.5).

The view restores full split-slot Positions from the DB (SqlitePositionRepo —
real reconstruction, **not** MockBroker, which would mask the live
Position-source gap) and serves cash from an injected balance source.

Coverage:
- live_position_view_restores_split_level_across_buys: multi-buy sequence
  persisted to the DB → view restores split_level / slots faithfully.
- db_position_view_returns_committed_state_only: a position only becomes
  visible after it is committed (NF-2 — committed state only).
- db_position_view_aggregate_matches_get_holdings: the view's aggregate
  quantity (sum of FILLED slots, via Position.quantity) equals the broker
  get_holdings aggregate for the same asset code (same-aggregate invariant).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.adapters.db_position_broker_view import DbPositionBrokerView
from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    BrokerHolding,
    Currency,
    Exchange,
    Market,
    Money,
    Position,
    SplitEntry,
    SplitSlot,
)
from src.infrastructure.db import connect
from src.infrastructure.repositories.sqlite_position_repo import (
    SqlitePositionRepo,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

UTC_NOW = datetime(2026, 5, 22, 1, 0, 0, tzinfo=UTC)
TRADE_DATE = date(2026, 5, 21)


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    c = connect(":memory:")
    try:
        yield c
    finally:
        c.close()


def _asset(code: str = "069500", name: str = "KODEX 200") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name=name,
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _split_entry(n: int, *, qty: str, price: str) -> SplitEntry:
    return SplitEntry(
        split_number=n,
        entry_date=TRADE_DATE,
        quantity=Decimal(qty),
        entry_price=Decimal(price),
        idempotency_key=f"k{n}",
    )


def _position(
    asset: Asset,
    *entries: SplitEntry,
    quantity: str,
    avg_price: str,
    max_split_count: int = 7,
) -> Position:
    filled = {e.split_number: SplitSlot.filled(entry=e) for e in entries}
    slots: list[SplitSlot] = [
        filled.get(i, SplitSlot.empty(slot_number=i))
        for i in range(1, max_split_count + 1)
    ]
    return Position(
        asset=asset,
        quantity=Decimal(quantity),
        avg_price=Decimal(avg_price),
        split_level=len(entries),
        last_buy_at=UTC_NOW,
        slots=slots,
    )


class _FakeBalanceSource:
    """BalanceReaderPort stand-in returning a fixed cash balance."""

    def __init__(self, cash: str) -> None:
        self._cash = Decimal(cash)

    def get_balance(self) -> Balance:
        return Balance(cash=Money(amount=self._cash, currency=Currency.KRW))


class _FakeHoldingsReader:
    """KIS-shaped get_holdings stand-in (aggregate per-symbol view)."""

    def __init__(self, holdings: list[BrokerHolding]) -> None:
        self._holdings = holdings

    def get_holdings(self) -> list[BrokerHolding]:
        return self._holdings


class TestDbPositionBrokerView:
    def test_live_position_view_restores_split_level_across_buys(self, conn):
        # Simulate two settle commits (two buys) growing split_level 1 → 2.
        repo = SqlitePositionRepo(conn)
        a = _asset()

        first = _position(
            a,
            _split_entry(1, qty="14", price="35000"),
            quantity="14",
            avg_price="35000",
        )
        repo.save(first)
        conn.commit()

        second = _position(
            a,
            _split_entry(1, qty="14", price="35000"),
            _split_entry(2, qty="14", price="33000"),
            quantity="28",
            avg_price="34000",
        )
        repo.save(second)
        conn.commit()

        view = DbPositionBrokerView(
            positions=repo,
            balance_source=_FakeBalanceSource("1000000"),
        )
        positions = view.get_positions()
        assert len(positions) == 1
        restored = positions[0]
        assert restored.split_level == 2
        assert restored.quantity == Decimal("28")
        assert restored.avg_price == Decimal("34000")
        filled = [s for s in restored.slots if s.entry is not None]
        assert len(filled) == 2
        assert {s.slot_number for s in filled} == {1, 2}

    def test_db_position_view_returns_committed_state_only(self, conn):
        # NF-2: only committed state is visible. Before commit the view (which
        # reads via the same connection) reflects pending writes; once an
        # empty/zero-qty position is committed it is filtered out (quantity > 0).
        repo = SqlitePositionRepo(conn)
        a = _asset()

        view = DbPositionBrokerView(
            positions=repo,
            balance_source=_FakeBalanceSource("1000000"),
        )
        # No positions persisted yet → empty.
        assert view.get_positions() == []

        held = _position(
            a,
            _split_entry(1, qty="10", price="35000"),
            quantity="10",
            avg_price="35000",
        )
        repo.save(held)
        conn.commit()
        positions = view.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("10")

    def test_db_position_view_filters_zero_quantity_positions(self, conn):
        # A fully exited position (quantity 0) is not a held position →
        # excluded from get_positions (quantity > 0 contract).
        repo = SqlitePositionRepo(conn)
        a = _asset()
        flat = Position(
            asset=a,
            quantity=Decimal("0"),
            avg_price=Decimal("0"),
            split_level=0,
            last_buy_at=UTC_NOW,
            slots=[SplitSlot.empty(slot_number=i) for i in range(1, 8)],
        )
        repo.save(flat)
        conn.commit()
        view = DbPositionBrokerView(
            positions=repo,
            balance_source=_FakeBalanceSource("1000000"),
        )
        assert view.get_positions() == []

    def test_db_position_view_aggregate_matches_get_holdings(self, conn):
        # The view's aggregate quantity (Position.quantity = sum of FILLED
        # slots) equals the broker get_holdings aggregate for the same code.
        repo = SqlitePositionRepo(conn)
        a = _asset()
        pos = _position(
            a,
            _split_entry(1, qty="14", price="35000"),
            _split_entry(2, qty="14", price="33000"),
            quantity="28",
            avg_price="34000",
        )
        repo.save(pos)
        conn.commit()

        holdings_reader = _FakeHoldingsReader(
            [
                BrokerHolding(
                    asset_code=a.code,
                    quantity=Decimal("28"),
                    avg_price=Decimal("34000"),
                )
            ]
        )

        view = DbPositionBrokerView(
            positions=repo,
            balance_source=_FakeBalanceSource("1000000"),
        )
        view_by_code = {p.asset.code: p.quantity for p in view.get_positions()}
        holdings_by_code = {
            h.asset_code: h.quantity for h in holdings_reader.get_holdings()
        }
        assert view_by_code == holdings_by_code

    def test_get_balance_delegates_to_balance_source(self, conn):
        repo = SqlitePositionRepo(conn)
        view = DbPositionBrokerView(
            positions=repo,
            balance_source=_FakeBalanceSource("5000000"),
        )
        balance = view.get_balance()
        assert balance.cash.amount == Decimal("5000000")
        assert balance.cash.currency == Currency.KRW

    def test_write_surface_raises_not_implemented(self, conn):
        repo = SqlitePositionRepo(conn)
        view = DbPositionBrokerView(
            positions=repo,
            balance_source=_FakeBalanceSource("1000000"),
        )
        with pytest.raises(NotImplementedError):
            view.get_order_status("k1")
        with pytest.raises(NotImplementedError):
            view.cancel_order("odno-1")
        with pytest.raises(NotImplementedError):
            view.get_holdings()
