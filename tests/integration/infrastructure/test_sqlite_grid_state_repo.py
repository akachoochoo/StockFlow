"""Tests for SqliteGridStateRepo (ADR 0022 §12 follow-up — round-trip + upsert)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.strategies.grid import GridRuntimeState, GridState
from src.infrastructure.repositories.sqlite_grid_state_repo import (
    SqliteGridStateRepo,
)

NOW = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)


def _state(
    *,
    reference_price: str = "30000",
    levels: tuple[str, ...] = ("29400", "29700", "30000", "30300", "30600"),
    cooldown_remaining: int = 0,
    last_sell_price: str = "0",
    avg_cost: str = "0",
) -> GridRuntimeState:
    return GridRuntimeState(
        grid_state=GridState(
            reference_price=Decimal(reference_price),
            grid_levels=tuple(Decimal(s) for s in levels),
        ),
        cooldown_remaining=cooldown_remaining,
        last_sell_price=Decimal(last_sell_price),
        avg_cost=Decimal(avg_cost),
    )


class TestSqliteGridStateRepoRoundTrip:
    def test_save_then_get_returns_equal(self, conn) -> None:
        repo = SqliteGridStateRepo(conn)
        original = _state(
            cooldown_remaining=3,
            last_sell_price="30605",
            avg_cost="29850.5",
        )
        repo.save(asset_fqn="KRX:069500", state=original, updated_at=NOW)
        got = repo.get("KRX:069500")
        assert got is not None
        assert got.cooldown_remaining == 3
        assert got.last_sell_price == Decimal("30605")
        assert got.avg_cost == Decimal("29850.5")
        assert got.grid_state.reference_price == Decimal("30000")
        assert got.grid_state.grid_levels == (
            Decimal("29400"),
            Decimal("29700"),
            Decimal("30000"),
            Decimal("30300"),
            Decimal("30600"),
        )

    def test_decimal_precision_preserved(self, conn) -> None:
        repo = SqliteGridStateRepo(conn)
        precise = "29850.123456789012345678"
        repo.save(
            asset_fqn="KRX:069500",
            state=_state(avg_cost=precise),
            updated_at=NOW,
        )
        got = repo.get("KRX:069500")
        assert got.avg_cost == Decimal(precise)


class TestUpsert:
    def test_save_twice_replaces(self, conn) -> None:
        repo = SqliteGridStateRepo(conn)
        repo.save(
            asset_fqn="KRX:069500",
            state=_state(cooldown_remaining=3),
            updated_at=NOW,
        )
        repo.save(
            asset_fqn="KRX:069500",
            state=_state(cooldown_remaining=0),
            updated_at=NOW,
        )
        got = repo.get("KRX:069500")
        assert got.cooldown_remaining == 0

    def test_multiple_assets_independent(self, conn) -> None:
        repo = SqliteGridStateRepo(conn)
        repo.save(
            asset_fqn="KRX:069500",
            state=_state(cooldown_remaining=3),
            updated_at=NOW,
        )
        repo.save(
            asset_fqn="KRX:005930",
            state=_state(cooldown_remaining=5),
            updated_at=NOW,
        )
        assert repo.get("KRX:069500").cooldown_remaining == 3
        assert repo.get("KRX:005930").cooldown_remaining == 5


class TestGetEmpty:
    def test_get_returns_none_when_absent(self, conn) -> None:
        repo = SqliteGridStateRepo(conn)
        assert repo.get("KRX:000000") is None


class TestDelete:
    def test_delete_removes_row(self, conn) -> None:
        repo = SqliteGridStateRepo(conn)
        repo.save(asset_fqn="KRX:069500", state=_state(), updated_at=NOW)
        deleted = repo.delete("KRX:069500")
        assert deleted is True
        assert repo.get("KRX:069500") is None

    def test_delete_absent_returns_false(self, conn) -> None:
        repo = SqliteGridStateRepo(conn)
        assert repo.delete("KRX:000000") is False
