"""Tests for SqliteDecisionRepo (round-trip + filters)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Decision,
    Exchange,
)
from src.infrastructure.repositories.sqlite_decision_repo import (
    SqliteDecisionRepo,
)


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


def _decision(
    *,
    timestamp: datetime,
    asset: Asset | None = None,
    action: str = "buy_split_1",
    reasoning: dict[str, str] | None = None,
    resulting_order_id: str | None = "bid-1",
) -> Decision:
    return Decision(
        timestamp=timestamp,
        asset=asset or _asset(),
        action=action,
        reasoning=reasoning or {"current_price": "35000"},
        resulting_order_id=resulting_order_id,
    )


class TestSqliteDecisionRepoRoundTrip:
    def test_save_then_query_returns_equal(self, conn):
        repo = SqliteDecisionRepo(conn)
        ts = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        original = _decision(
            timestamp=ts,
            reasoning={
                "current_price": "35000",
                "drop_pct": "8.5",
                "today_buys": "0",
            },
        )
        repo.save(original)
        loaded = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert len(loaded) == 1
        assert loaded[0] == original

    def test_skip_decision_with_no_order_id(self, conn):
        repo = SqliteDecisionRepo(conn)
        ts = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        original = _decision(
            timestamp=ts,
            action="skip:strategy_no_buy",
            reasoning={"strategy_reason": "skip:max_split_reached"},
            resulting_order_id=None,
        )
        repo.save(original)
        loaded = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert loaded[0].resulting_order_id is None

    def test_reasoning_round_trip_preserves_keys(self, conn):
        repo = SqliteDecisionRepo(conn)
        ts = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        reasoning = {
            "key_z": "z",
            "key_a": "a",
            "key_m": "m",
            "key_with_special_chars": "value with \"quotes\" and \\backslash",
        }
        original = _decision(timestamp=ts, reasoning=reasoning)
        repo.save(original)
        loaded = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))[0]
        assert loaded.reasoning == reasoning


class TestSqliteDecisionRepoFilters:
    def test_list_by_date_range_filters(self, conn):
        repo = SqliteDecisionRepo(conn)
        repo.save(_decision(timestamp=datetime(2026, 4, 28, 6, 0, 0, tzinfo=UTC)))
        repo.save(_decision(timestamp=datetime(2026, 4, 29, 6, 0, 0, tzinfo=UTC)))
        repo.save(_decision(timestamp=datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)))
        repo.save(_decision(timestamp=datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)))
        result = repo.list_by_date_range(date(2026, 4, 29), date(2026, 4, 30))
        assert len(result) == 2

    def test_list_by_date_range_orders_ascending(self, conn):
        repo = SqliteDecisionRepo(conn)
        late = datetime(2026, 4, 30, 16, 0, 0, tzinfo=UTC)
        early = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        repo.save(_decision(timestamp=late))
        repo.save(_decision(timestamp=early))
        result = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert [d.timestamp for d in result] == [early, late]

    def test_list_by_date_range_empty(self, conn):
        repo = SqliteDecisionRepo(conn)
        assert repo.list_by_date_range(date(2026, 4, 1), date(2026, 4, 30)) == []

    def test_get_last_for_asset_returns_most_recent(self, conn):
        repo = SqliteDecisionRepo(conn)
        a = _asset(code="069500")
        b = _asset(code="105190")
        repo.save(_decision(timestamp=datetime(2026, 4, 28, 6, 0, 0, tzinfo=UTC), asset=a))
        repo.save(_decision(timestamp=datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC), asset=a))
        repo.save(_decision(timestamp=datetime(2026, 4, 29, 6, 0, 0, tzinfo=UTC), asset=b))
        last = repo.get_last_for_asset(a.fqn)
        assert last is not None
        assert last.timestamp == datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)

    def test_get_last_for_asset_returns_none_when_no_decisions(self, conn):
        repo = SqliteDecisionRepo(conn)
        assert repo.get_last_for_asset("KRX:000000") is None
