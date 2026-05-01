"""Tests for SqlitePositionRepo (round-trip + cascade + asset_json)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Position,
    SplitEntry,
)
from src.infrastructure.repositories.sqlite_position_repo import (
    SqlitePositionRepo,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
TRADE_DATE = date(2026, 4, 29)


def _asset(code: str = "069500", name: str = "KODEX 200") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name=name,
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


def _split_entry(
    n: int, qty: str = "10", price: str = "35000", key_suffix: str = ""
) -> SplitEntry:
    return SplitEntry(
        split_number=n,
        entry_date=TRADE_DATE,
        quantity=Decimal(qty),
        entry_price=Decimal(price),
        idempotency_key=f"k{n}{key_suffix}",
    )


class TestSqlitePositionRepoRoundTrip:
    def test_save_then_get_returns_equal_position(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        original = Position(
            asset=a,
            quantity=Decimal("28"),
            avg_price=Decimal("35000"),
            split_level=2,
            last_buy_at=UTC_NOW,
            entries=[
                _split_entry(1, qty="14"),
                _split_entry(2, qty="14", price="35000"),
            ],
        )
        repo.save(original)
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.asset == a
        assert loaded.quantity == Decimal("28")
        assert loaded.avg_price == Decimal("35000")
        assert loaded.split_level == 2
        assert loaded.last_buy_at == UTC_NOW
        assert [e.split_number for e in loaded.entries] == [1, 2]
        assert loaded.entries[0].entry_date == TRADE_DATE

    def test_get_returns_none_for_unknown_fqn(self, conn):
        repo = SqlitePositionRepo(conn)
        assert repo.get("KRX:000000") is None

    def test_save_empty_position(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        empty = Position.empty(a)
        repo.save(empty)
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.quantity == Decimal(0)
        assert loaded.entries == []
        assert loaded.last_buy_at is None


class TestSqlitePositionRepoUpsert:
    def test_save_existing_position_replaces_entries(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        # Initial save: split_level 1
        repo.save(
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=UTC_NOW,
                entries=[_split_entry(1, qty="10")],
            )
        )
        # Upsert: split_level 2 (entries replaced wholesale)
        repo.save(
            Position(
                asset=a,
                quantity=Decimal("20"),
                avg_price=Decimal("33000"),
                split_level=2,
                last_buy_at=UTC_NOW,
                entries=[
                    _split_entry(1, qty="10", price="35000"),
                    _split_entry(2, qty="10", price="31000", key_suffix="b"),
                ],
            )
        )
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.split_level == 2
        assert [e.split_number for e in loaded.entries] == [1, 2]
        assert loaded.entries[1].idempotency_key == "k2b"

    def test_asset_json_preserved_on_update(self, conn):
        # ADR §8.3: asset_json is point-in-time. Updates do NOT overwrite it.
        repo = SqlitePositionRepo(conn)
        a_old = _asset(name="KODEX 200")
        repo.save(Position.empty(a_old))
        # Caller now passes a renamed Asset (mimicking metadata change)
        a_new = _asset(name="KODEX 200 (renamed)")
        repo.save(Position.empty(a_new))
        loaded = repo.get(a_old.fqn)
        assert loaded is not None
        # The stored asset is the original — point-in-time integrity intact.
        assert loaded.asset.name == "KODEX 200"


class TestSqlitePositionRepoListAndDelete:
    def test_list_all_returns_every_position(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset(code="069500", name="KODEX 200")
        b = _asset(code="105190", name="KODEX 코스닥")
        repo.save(Position.empty(a))
        repo.save(Position.empty(b))
        positions = repo.list_all()
        fqns = {p.asset.fqn for p in positions}
        assert fqns == {"KRX:069500", "KRX:105190"}

    def test_list_all_empty(self, conn):
        repo = SqlitePositionRepo(conn)
        assert repo.list_all() == []

    def test_delete_returns_true_when_present(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        repo.save(Position.empty(a))
        assert repo.delete(a.fqn) is True
        assert repo.get(a.fqn) is None

    def test_delete_returns_false_when_missing(self, conn):
        repo = SqlitePositionRepo(conn)
        assert repo.delete("KRX:999999") is False

    def test_delete_cascades_split_entries(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        repo.save(
            Position(
                asset=a,
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
                split_level=1,
                last_buy_at=UTC_NOW,
                entries=[_split_entry(1, qty="10")],
            )
        )
        # Sanity: row exists
        count = conn.execute(
            "SELECT COUNT(*) FROM split_entries"
        ).fetchone()[0]
        assert count == 1
        repo.delete(a.fqn)
        count = conn.execute(
            "SELECT COUNT(*) FROM split_entries"
        ).fetchone()[0]
        assert count == 0
