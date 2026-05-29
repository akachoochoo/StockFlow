"""Tests for SqliteGridDecisionRepo (ADR 0022 §12 D22 — round-trip + filters)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    OrderSide,
)
from src.domain.strategies.grid import GridDecision
from src.infrastructure.repositories.sqlite_grid_decision_repo import (
    SqliteGridDecisionRepo,
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


def _gd(
    *,
    side: OrderSide = OrderSide.BUY,
    level_index: int = 3,
    level_price: Decimal = Decimal("30007.5"),
    rounded_price: Decimal = Decimal("30005"),
    quantity: Decimal = Decimal("10"),
    reasoning: dict[str, str] | None = None,
) -> GridDecision:
    return GridDecision(
        side=side,
        level_index=level_index,
        level_price=level_price,
        rounded_price=rounded_price,
        quantity=quantity,
        reasoning=reasoning or {"trigger": "level_cross"},
    )


class TestRoundTrip:
    def test_save_then_list_returns_equal(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        ts = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)
        decision = _gd(reasoning={"atr": "150", "trigger": "cross"})
        repo.save(asset=asset, timestamp=ts, decision=decision)

        got = repo.list_for_date(asset.fqn, ts.date())
        assert len(got) == 1
        d = got[0]
        assert d.side == OrderSide.BUY
        assert d.level_index == 3
        assert d.level_price == Decimal("30007.5")
        assert d.rounded_price == Decimal("30005")
        assert d.quantity == Decimal("10")
        assert d.reasoning == {"atr": "150", "trigger": "cross"}

    def test_decimal_precision_preserved(self, conn) -> None:
        """Decimal 정확 보존 (string 저장, 부동소수점 오차 zero)."""
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        ts = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)
        precise = Decimal("30007.123456789")
        repo.save(
            asset=asset,
            timestamp=ts,
            decision=_gd(level_price=precise, rounded_price=Decimal("30005")),
        )
        got = repo.list_for_date(asset.fqn, ts.date())
        assert got[0].level_price == precise


class TestMultipleDecisionsPerDay:
    """DGT 가 하루 동일 asset 에 다수 trade 가능 — 모두 보존."""

    def test_multiple_rows_for_same_day_asset(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        base = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)
        for i, side in enumerate([OrderSide.BUY, OrderSide.SELL, OrderSide.BUY]):
            repo.save(
                asset=asset,
                timestamp=base.replace(second=i),
                decision=_gd(side=side, level_index=i),
            )
        got = repo.list_for_date(asset.fqn, base.date())
        assert len(got) == 3
        assert [d.side for d in got] == [
            OrderSide.BUY,
            OrderSide.SELL,
            OrderSide.BUY,
        ]
        assert [d.level_index for d in got] == [0, 1, 2]

    def test_timestamp_order_preserved(self, conn) -> None:
        """list_for_date 는 timestamp asc 정렬."""
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        base = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)
        # 삽입 순서 = 역순
        repo.save(asset=asset, timestamp=base.replace(second=10), decision=_gd(level_index=5))
        repo.save(asset=asset, timestamp=base.replace(second=2), decision=_gd(level_index=1))
        repo.save(asset=asset, timestamp=base.replace(second=5), decision=_gd(level_index=3))
        got = repo.list_for_date(asset.fqn, base.date())
        assert [d.level_index for d in got] == [1, 3, 5]


class TestDateAndAssetFilters:
    def test_list_for_date_isolates_by_asset(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        a1 = _asset("069500")
        a2 = _asset("005930")
        ts = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)
        repo.save(asset=a1, timestamp=ts, decision=_gd(level_index=1))
        repo.save(asset=a2, timestamp=ts, decision=_gd(level_index=2))
        assert len(repo.list_for_date(a1.fqn, ts.date())) == 1
        assert len(repo.list_for_date(a2.fqn, ts.date())) == 1
        assert repo.list_for_date(a1.fqn, ts.date())[0].level_index == 1

    def test_list_for_date_isolates_by_date(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        d1 = datetime(2026, 5, 27, 6, 0, tzinfo=UTC)
        d2 = datetime(2026, 5, 28, 6, 0, tzinfo=UTC)
        repo.save(asset=asset, timestamp=d1, decision=_gd(level_index=1))
        repo.save(asset=asset, timestamp=d2, decision=_gd(level_index=2))
        assert len(repo.list_for_date(asset.fqn, date(2026, 5, 27))) == 1
        assert repo.list_for_date(asset.fqn, date(2026, 5, 27))[0].level_index == 1

    def test_list_by_date_range_inclusive(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        for d in [date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28)]:
            repo.save(
                asset=asset,
                timestamp=datetime(d.year, d.month, d.day, 6, tzinfo=UTC),
                decision=_gd(level_index=d.day),
            )
        # 범위 = [27, 28] → 2개
        got = repo.list_by_date_range(asset.fqn, date(2026, 5, 27), date(2026, 5, 28))
        assert [g.level_index for g in got] == [27, 28]

    def test_empty_when_no_match(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        assert repo.list_for_date("KRX:000000", date(2026, 5, 28)) == []
        assert repo.list_by_date_range("KRX:000000", date(2026, 1, 1), date(2026, 12, 31)) == []


class TestListNetQuantities:
    """ADR 0022 §13 D26 — Reconciliation grid 인식의 토대."""

    def test_empty_when_no_decisions(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        assert repo.list_net_quantities() == {}

    def test_single_buy(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        ts = datetime(2026, 5, 28, 6, tzinfo=UTC)
        repo.save(asset=asset, timestamp=ts, decision=_gd(quantity=Decimal("10")))
        assert repo.list_net_quantities() == {asset.fqn: Decimal("10")}

    def test_net_after_buy_sell(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        base = datetime(2026, 5, 28, 6, tzinfo=UTC)
        repo.save(asset=asset, timestamp=base, decision=_gd(side=OrderSide.BUY, quantity=Decimal("15")))
        repo.save(asset=asset, timestamp=base.replace(minute=1), decision=_gd(side=OrderSide.SELL, quantity=Decimal("3")))
        assert repo.list_net_quantities() == {asset.fqn: Decimal("12")}

    def test_zero_net_excluded(self, conn) -> None:
        """qty 0 (BUY 동량 SELL) 자산은 결과에서 제외."""
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        base = datetime(2026, 5, 28, 6, tzinfo=UTC)
        repo.save(asset=asset, timestamp=base, decision=_gd(side=OrderSide.BUY, quantity=Decimal("20")))
        repo.save(asset=asset, timestamp=base.replace(minute=1), decision=_gd(side=OrderSide.SELL, quantity=Decimal("20")))
        assert repo.list_net_quantities() == {}

    def test_multiple_assets_independent(self, conn) -> None:
        repo = SqliteGridDecisionRepo(conn)
        a1 = _asset("095660")
        a2 = _asset("069500")
        ts = datetime(2026, 5, 28, 6, tzinfo=UTC)
        repo.save(asset=a1, timestamp=ts, decision=_gd(quantity=Decimal("10")))
        repo.save(asset=a2, timestamp=ts, decision=_gd(quantity=Decimal("25")))
        repo.save(asset=a2, timestamp=ts.replace(minute=1), decision=_gd(side=OrderSide.SELL, quantity=Decimal("5")))
        assert repo.list_net_quantities() == {
            a1.fqn: Decimal("10"),
            a2.fqn: Decimal("20"),
        }

    def test_decimal_precision_preserved(self, conn) -> None:
        """sqlite SUM/CAST 회피 → Decimal 정확 합산."""
        repo = SqliteGridDecisionRepo(conn)
        asset = _asset()
        ts = datetime(2026, 5, 28, 6, tzinfo=UTC)
        # 정수 주식이지만 Decimal 합산 정확성 검증.
        for i, qty in enumerate(["7", "13", "11"]):
            repo.save(
                asset=asset, timestamp=ts.replace(minute=i),
                decision=_gd(quantity=Decimal(qty)),
            )
        assert repo.list_net_quantities() == {asset.fqn: Decimal("31")}
