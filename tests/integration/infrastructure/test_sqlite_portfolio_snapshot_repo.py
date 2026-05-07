"""Tests for SqlitePortfolioSnapshotRepo (round-trip + upsert + filters)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
    PortfolioSnapshot,
    PositionValuation,
)
from src.infrastructure.repositories.sqlite_portfolio_snapshot_repo import (
    SqlitePortfolioSnapshotRepo,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)


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


def _val(
    asset: Asset, qty: str = "10", avg: str = "35000", market: str = "36000"
) -> PositionValuation:
    q = Decimal(qty)
    a = Decimal(avg)
    m = Decimal(market)
    return PositionValuation(
        asset=asset,
        quantity=q,
        avg_price=a,
        market_price=m,
        market_value=Money(amount=q * m, currency=Currency.KRW),
        unrealized_pnl=Money(
            amount=(m - a) * q, currency=Currency.KRW
        ),
        split_level=1,
    )


def _snapshot(
    *,
    snapshot_date: date = date(2026, 4, 30),
    cash_amount: str = "3640000",
    valuations: list[PositionValuation] | None = None,
) -> PortfolioSnapshot:
    return PortfolioSnapshot.build(
        snapshot_date=snapshot_date,
        snapshot_at=UTC_NOW,
        initial_capital=Money(amount=Decimal("4000000"), currency=Currency.KRW),
        cash=Money(amount=Decimal(cash_amount), currency=Currency.KRW),
        valuations=valuations if valuations is not None else [_val(_asset())],
    )


class TestSqlitePortfolioSnapshotRepoRoundTrip:
    def test_save_then_get_returns_equal_snapshot(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        original = _snapshot()
        repo.save(original)
        loaded = repo.get_by_date(date(2026, 4, 30))
        assert loaded == original

    def test_get_returns_none_for_unknown_date(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        assert repo.get_by_date(date(2026, 1, 1)) is None

    def test_empty_valuations_round_trip(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        snap = _snapshot(cash_amount="4000000", valuations=[])
        repo.save(snap)
        loaded = repo.get_by_date(date(2026, 4, 30))
        assert loaded == snap
        assert loaded.valuations == []
        assert loaded.total_market_value.amount == Decimal("0")
        assert loaded.total_value.amount == Decimal("4000000")

    def test_multiple_valuations_round_trip(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        a = _asset(code="069500")
        b = _asset(code="105190")
        snap = _snapshot(
            cash_amount="3530000",
            valuations=[
                _val(a, qty="10", avg="35000", market="36000"),
                _val(b, qty="5", avg="20000", market="22000"),
            ],
        )
        repo.save(snap)
        loaded = repo.get_by_date(date(2026, 4, 30))
        assert loaded == snap
        assert len(loaded.valuations) == 2
        assert {v.asset.fqn for v in loaded.valuations} == {
            "KRX:069500",
            "KRX:105190",
        }


class TestSqlitePortfolioSnapshotRepoUpsert:
    def test_save_replaces_existing_date(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        first = _snapshot()
        repo.save(first)
        # Second save with different cash → upsert by snapshot_date
        second = _snapshot(cash_amount="3700000")
        repo.save(second)
        loaded = repo.get_by_date(date(2026, 4, 30))
        assert loaded is not None
        assert loaded.cash.amount == Decimal("3700000")
        # Only one row remains
        rows = conn.execute(
            "SELECT COUNT(*) FROM portfolio_snapshots"
        ).fetchone()
        assert rows[0] == 1


class TestSqlitePortfolioSnapshotRepoListByDateRange:
    def test_list_by_date_range_filters(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        for d in (date(2026, 4, 27), date(2026, 4, 28), date(2026, 4, 29), date(2026, 4, 30)):
            repo.save(_snapshot(snapshot_date=d, valuations=[]))
        result = repo.list_by_date_range(date(2026, 4, 28), date(2026, 4, 29))
        assert [s.snapshot_date for s in result] == [
            date(2026, 4, 28),
            date(2026, 4, 29),
        ]

    def test_list_by_date_range_ordered_ascending(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        repo.save(_snapshot(snapshot_date=date(2026, 4, 30), valuations=[]))
        repo.save(_snapshot(snapshot_date=date(2026, 4, 28), valuations=[]))
        repo.save(_snapshot(snapshot_date=date(2026, 4, 29), valuations=[]))
        result = repo.list_by_date_range(date(2026, 4, 28), date(2026, 4, 30))
        assert [s.snapshot_date for s in result] == [
            date(2026, 4, 28),
            date(2026, 4, 29),
            date(2026, 4, 30),
        ]

    def test_list_by_date_range_empty_when_no_match(self, conn):
        repo = SqlitePortfolioSnapshotRepo(conn)
        repo.save(_snapshot(valuations=[]))
        assert repo.list_by_date_range(date(2026, 5, 1), date(2026, 5, 31)) == []
