"""Tests for SqliteDecisionRepo (round-trip + filters)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.models import (
    Asset,
    AssetClass,
    BuyActionRecord,
    Currency,
    Decision,
    Exchange,
    Market,
    SellActionRecord,
    SkipReason,
)
from src.infrastructure.repositories.sqlite_decision_repo import (
    SqliteDecisionRepo,
)


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


def _buy_decision(
    *,
    timestamp: datetime,
    asset: Asset | None = None,
    slot_number: int = 1,
    reasoning: dict[str, str] | None = None,
) -> Decision:
    return Decision(
        timestamp=timestamp,
        asset=asset or _asset(),
        buy_action=BuyActionRecord(
            slot_number=slot_number,
            split_level_after=slot_number,
            filled_quantity=Decimal("10"),
            filled_price=Decimal("35000"),
            target_price=Decimal("35000"),
            idempotency_key=f"buy-{timestamp.isoformat()}",
            order_id="bid-1",
            reasoning={"strategy_reason": "buy_split_1"},
        ),
        reasoning=reasoning or {"current_price": "35000"},
    )


def _skip_decision(
    *,
    timestamp: datetime,
    asset: Asset | None = None,
    skip_reason: SkipReason = SkipReason.STRATEGY_NO_BUY,
    reasoning: dict[str, str] | None = None,
) -> Decision:
    return Decision(
        timestamp=timestamp,
        asset=asset or _asset(),
        skip_reason=skip_reason,
        reasoning=reasoning or {"strategy_reason": "skip:max_split_reached"},
    )


class TestSqliteDecisionRepoRoundTrip:
    def test_save_then_query_returns_equal(self, conn):
        repo = SqliteDecisionRepo(conn)
        ts = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        original = _buy_decision(
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

    def test_skip_decision_round_trip(self, conn):
        repo = SqliteDecisionRepo(conn)
        ts = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        original = _skip_decision(
            timestamp=ts,
            skip_reason=SkipReason.ALL_SLOTS_FILLED_NO_PROFIT,
            reasoning={"strategy_reason": "skip:no_profit_target_met"},
        )
        repo.save(original)
        loaded = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert loaded[0] == original
        assert loaded[0].skip_reason is SkipReason.ALL_SLOTS_FILLED_NO_PROFIT
        assert loaded[0].sell_actions == []
        assert loaded[0].buy_action is None

    def test_sells_and_buy_round_trip(self, conn):
        repo = SqliteDecisionRepo(conn)
        ts = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        original = Decision(
            timestamp=ts,
            asset=_asset(),
            sell_actions=[
                SellActionRecord(
                    slot_number=2,
                    filled_quantity=Decimal("10"),
                    filled_price=Decimal("38500"),
                    profit_pct=Decimal("10"),
                    idempotency_key="sell-1",
                    order_id="ord-s2",
                    reasoning={"trigger": "profit_target"},
                ),
            ],
            buy_action=BuyActionRecord(
                slot_number=3,
                split_level_after=2,
                filled_quantity=Decimal("12"),
                filled_price=Decimal("32000"),
                target_price=Decimal("32500"),
                idempotency_key="buy-1",
                order_id="ord-b3",
                reasoning={"strategy_reason": "buy_split_3"},
            ),
            reasoning={"current_price": "32500"},
        )
        repo.save(original)
        loaded = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))[0]
        assert loaded == original

    def test_reasoning_round_trip_preserves_keys(self, conn):
        repo = SqliteDecisionRepo(conn)
        ts = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        reasoning = {
            "key_z": "z",
            "key_a": "a",
            "key_m": "m",
            "key_with_special_chars": "value with \"quotes\" and \\backslash",
        }
        original = _buy_decision(timestamp=ts, reasoning=reasoning)
        repo.save(original)
        loaded = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))[0]
        assert loaded.reasoning == reasoning


class TestSqliteDecisionRepoFilters:
    def test_list_by_date_range_filters(self, conn):
        repo = SqliteDecisionRepo(conn)
        repo.save(_buy_decision(timestamp=datetime(2026, 4, 28, 6, 0, 0, tzinfo=UTC)))
        repo.save(_buy_decision(timestamp=datetime(2026, 4, 29, 6, 0, 0, tzinfo=UTC)))
        repo.save(_buy_decision(timestamp=datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)))
        repo.save(_buy_decision(timestamp=datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)))
        result = repo.list_by_date_range(date(2026, 4, 29), date(2026, 4, 30))
        assert len(result) == 2

    def test_list_by_date_range_orders_ascending(self, conn):
        repo = SqliteDecisionRepo(conn)
        late = datetime(2026, 4, 30, 16, 0, 0, tzinfo=UTC)
        early = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
        repo.save(_buy_decision(timestamp=late))
        repo.save(_buy_decision(timestamp=early))
        result = repo.list_by_date_range(date(2026, 4, 30), date(2026, 4, 30))
        assert [d.timestamp for d in result] == [early, late]

    def test_list_by_date_range_empty(self, conn):
        repo = SqliteDecisionRepo(conn)
        assert repo.list_by_date_range(date(2026, 4, 1), date(2026, 4, 30)) == []

    def test_get_last_for_asset_returns_most_recent(self, conn):
        repo = SqliteDecisionRepo(conn)
        a = _asset(code="069500")
        b = _asset(code="105190")
        repo.save(_buy_decision(timestamp=datetime(2026, 4, 28, 6, 0, 0, tzinfo=UTC), asset=a))
        repo.save(_buy_decision(timestamp=datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC), asset=a))
        repo.save(_buy_decision(timestamp=datetime(2026, 4, 29, 6, 0, 0, tzinfo=UTC), asset=b))
        last = repo.get_last_for_asset(a.fqn)
        assert last is not None
        assert last.timestamp == datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)

    def test_get_last_for_asset_returns_none_when_no_decisions(self, conn):
        repo = SqliteDecisionRepo(conn)
        assert repo.get_last_for_asset("KRX:000000") is None
