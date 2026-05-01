"""Tests for DailySnapshotBuilder — end-of-day valuation + snapshot persistence."""
from __future__ import annotations

import random
from datetime import UTC, date, datetime, time
from decimal import Decimal

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.adapters.mock.market_data import MockMarketData
from src.application.snapshot_builder import DailySnapshotBuilder
from src.domain.constants import KST
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    Money,
    OrderRequest,
    OrderSide,
    OrderType,
)

TODAY = date(2026, 4, 30)


def _utc_after_close(d: date) -> datetime:
    """UTC datetime corresponding to KST 16:00 on `d` (after KRX close)."""
    return datetime.combine(d, time(16, 0), tzinfo=KST).astimezone(UTC)


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


def _bar(asset: Asset, d: date, close: str) -> OHLCV:
    return OHLCV(
        asset=asset,
        trade_date=d,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1000000"),
    )


def _initial_capital() -> Money:
    return Money(amount=Decimal("4000000"), currency=Currency.KRW)


class TestDailySnapshotBuilderHappyPath:
    def test_no_positions_snapshot_is_cash_only(self):
        # Empty Repository + cash = initial — total_value should equal cash.
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        market_data = MockMarketData(ohlcv_by_asset={asset: bars})
        shared_uow = InMemoryUnitOfWork()
        builder = DailySnapshotBuilder(
            broker=broker,
            market_data=market_data,
            uow_factory=lambda: shared_uow,
            clock=lambda: clock_at,
            initial_capital=_initial_capital(),
        )
        snap = builder.build_and_save(TODAY)
        assert snap.snapshot_date == TODAY
        assert snap.cash.amount == Decimal("4000000")
        assert snap.valuations == []
        assert snap.total_market_value.amount == Decimal("0")
        assert snap.total_value.amount == Decimal("4000000")
        assert snap.total_return_pct == Decimal("0")

    def test_single_position_round_trip_via_market_price(self):
        # One filled position with current price > avg — positive PnL.
        asset = _asset()
        bars = [
            _bar(asset, date(2026, 4, 28), "35000"),
            _bar(asset, date(2026, 4, 29), "36000"),
        ]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        # Place an order to seed position via broker
        broker.place_order(
            OrderRequest(
                idempotency_key="seed-1",
                asset=asset,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                target_price=Decimal("35000"),
            )
        )
        market_data = MockMarketData(ohlcv_by_asset={asset: bars})
        shared_uow = InMemoryUnitOfWork()
        # Snapshot needs the position in the repo. Save it from broker state.
        position = broker.get_positions()[0]
        with shared_uow as uow:
            uow.positions.save(position)
            uow.commit()

        builder = DailySnapshotBuilder(
            broker=broker,
            market_data=market_data,
            uow_factory=lambda: shared_uow,
            clock=lambda: clock_at,
            initial_capital=_initial_capital(),
        )
        snap = builder.build_and_save(TODAY)
        assert len(snap.valuations) == 1
        v = snap.valuations[0]
        # current price (4/29 close at 36000) → market_value 360000
        assert v.market_price == Decimal("36000")
        assert v.market_value.amount == Decimal("360000")
        # cash after buy = 100,000,000 - 350,000 = 99,650,000
        assert snap.cash.amount == Decimal("99650000")
        assert snap.total_value.amount == Decimal("100010000")  # 99650000 + 360000

    def test_multiple_positions_aggregated(self):
        a = _asset(code="069500")
        b = _asset(code="105190")
        bars_a = [_bar(a, date(2026, 4, 29), "36000")]
        bars_b = [_bar(b, date(2026, 4, 29), "22000")]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW),
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        # Seed two positions
        broker.place_order(
            OrderRequest(
                idempotency_key="seed-a",
                asset=a,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                target_price=Decimal("35000"),
            )
        )
        broker.place_order(
            OrderRequest(
                idempotency_key="seed-b",
                asset=b,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("5"),
                target_price=Decimal("20000"),
            )
        )
        market_data = MockMarketData(ohlcv_by_asset={a: bars_a, b: bars_b})
        shared_uow = InMemoryUnitOfWork()
        with shared_uow as uow:
            for p in broker.get_positions():
                uow.positions.save(p)
            uow.commit()

        builder = DailySnapshotBuilder(
            broker=broker,
            market_data=market_data,
            uow_factory=lambda: shared_uow,
            clock=lambda: clock_at,
            initial_capital=_initial_capital(),
        )
        snap = builder.build_and_save(TODAY)
        assert len(snap.valuations) == 2
        assert snap.total_market_value.amount == Decimal("470000")  # 360000 + 110000
        assert snap.total_cost_basis.amount == Decimal("450000")  # 350000 + 100000
        assert snap.total_unrealized_pnl.amount == Decimal("20000")


class TestDailySnapshotBuilderPersistence:
    def test_snapshot_saved_via_uow_visible_after(self):
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        shared_uow = InMemoryUnitOfWork()
        builder = DailySnapshotBuilder(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            uow_factory=lambda: shared_uow,
            clock=lambda: clock_at,
            initial_capital=_initial_capital(),
        )
        builder.build_and_save(TODAY)
        # Snapshot retrievable from the same UoW state
        loaded = shared_uow.snapshots.get_by_date(TODAY)
        assert loaded is not None
        assert loaded.snapshot_date == TODAY

    def test_build_again_same_day_overwrites_via_upsert(self):
        # InMemorySnapshotRepo.save upserts by snapshot_date; second build
        # replaces the prior one (matches SqlitePortfolioSnapshotRepo
        # INSERT OR REPLACE semantics).
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        shared_uow = InMemoryUnitOfWork()
        builder = DailySnapshotBuilder(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            uow_factory=lambda: shared_uow,
            clock=lambda: clock_at,
            initial_capital=_initial_capital(),
        )
        builder.build_and_save(TODAY)
        builder.build_and_save(TODAY)
        snaps = shared_uow.snapshots.list_by_date_range(TODAY, TODAY)
        assert len(snaps) == 1


class TestDailySnapshotBuilderEdgeCases:
    def test_zero_quantity_position_skipped(self):
        # An "empty" position (quantity == 0) must not appear in valuations
        # (PositionValuation.from_position rejects qty <= 0; builder filters).
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        shared_uow = InMemoryUnitOfWork()
        with shared_uow as uow:
            from src.domain.models import Position

            uow.positions.save(Position.empty(asset))
            uow.commit()

        builder = DailySnapshotBuilder(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            uow_factory=lambda: shared_uow,
            clock=lambda: clock_at,
            initial_capital=_initial_capital(),
        )
        snap = builder.build_and_save(TODAY)
        assert snap.valuations == []
        assert snap.total_market_value.amount == Decimal("0")

    def test_initial_capital_carried_verbatim(self):
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        custom_initial = Money(
            amount=Decimal("10000000"), currency=Currency.KRW
        )
        builder = DailySnapshotBuilder(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            uow_factory=lambda: InMemoryUnitOfWork(),
            clock=lambda: clock_at,
            initial_capital=custom_initial,
        )
        snap = builder.build_and_save(TODAY)
        assert snap.initial_capital.amount == Decimal("10000000")
        # total_return_pct uses initial_capital as denominator
        assert snap.total_return_pct == (
            (snap.total_value.amount - Decimal("10000000"))
            / Decimal("10000000")
            * Decimal("100")
        )

    def test_multiple_dates_persist_independently(self):
        asset = _asset()
        bars = [
            _bar(asset, date(2026, 4, 28), "35000"),
            _bar(asset, date(2026, 4, 29), "35000"),
        ]
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("4000000"), currency=Currency.KRW),
            ),
            clock=lambda: _utc_after_close(TODAY),
            rng=random.Random(42),
        )
        shared_uow = InMemoryUnitOfWork()
        market_data = MockMarketData(ohlcv_by_asset={asset: bars})

        d1 = date(2026, 4, 28)
        d2 = date(2026, 4, 29)
        # Build for two consecutive days; each lands in its own row.
        builder1 = DailySnapshotBuilder(
            broker=broker,
            market_data=market_data,
            uow_factory=lambda: shared_uow,
            clock=lambda: _utc_after_close(d1),
            initial_capital=_initial_capital(),
        )
        builder1.build_and_save(d1)
        builder2 = DailySnapshotBuilder(
            broker=broker,
            market_data=market_data,
            uow_factory=lambda: shared_uow,
            clock=lambda: _utc_after_close(d2),
            initial_capital=_initial_capital(),
        )
        builder2.build_and_save(d2)
        snaps = shared_uow.snapshots.list_by_date_range(d1, d2)
        assert [s.snapshot_date for s in snaps] == [d1, d2]
