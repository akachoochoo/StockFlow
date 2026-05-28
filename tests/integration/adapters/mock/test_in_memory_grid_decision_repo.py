"""Tests for InMemoryGridDecisionRepo (ADR 0022 §12 D22).

In-memory parity 검증 — Phase 0 backtest 가 sqlite 없이 GridDecision 영속을
시뮬레이션. 동일 contract (save/list_for_date/list_by_date_range).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.adapters.mock.in_memory_unit_of_work import (
    InMemoryGridDecisionRepo,
    InMemoryUnitOfWork,
)
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    OrderSide,
)
from src.domain.strategies.grid import GridDecision


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
    quantity: Decimal = Decimal("10"),
) -> GridDecision:
    return GridDecision(
        side=side,
        level_index=level_index,
        level_price=Decimal("30007.5"),
        rounded_price=Decimal("30005"),
        quantity=quantity,
        reasoning={"trigger": "level_cross"},
    )


def test_save_then_list_round_trip() -> None:
    repo = InMemoryGridDecisionRepo()
    asset = _asset()
    ts = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)
    repo.save(asset=asset, timestamp=ts, decision=_gd())
    got = repo.list_for_date(asset.fqn, ts.date())
    assert len(got) == 1 and got[0].level_index == 3


def test_multiple_per_day_preserves_count_and_order() -> None:
    repo = InMemoryGridDecisionRepo()
    asset = _asset()
    base = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)
    # 삽입 = 역순 (10s, 2s, 5s)
    repo.save(asset=asset, timestamp=base.replace(second=10), decision=_gd(level_index=5))
    repo.save(asset=asset, timestamp=base.replace(second=2), decision=_gd(level_index=1))
    repo.save(asset=asset, timestamp=base.replace(second=5), decision=_gd(level_index=3))
    got = repo.list_for_date(asset.fqn, base.date())
    assert [d.level_index for d in got] == [1, 3, 5]


def test_isolation_by_asset_and_date() -> None:
    repo = InMemoryGridDecisionRepo()
    a1, a2 = _asset("069500"), _asset("005930")
    d1 = datetime(2026, 5, 27, 6, tzinfo=UTC)
    d2 = datetime(2026, 5, 28, 6, tzinfo=UTC)
    repo.save(asset=a1, timestamp=d1, decision=_gd(level_index=1))
    repo.save(asset=a2, timestamp=d2, decision=_gd(level_index=2))
    assert repo.list_for_date(a1.fqn, d1.date())[0].level_index == 1
    assert repo.list_for_date(a1.fqn, d2.date()) == []
    assert repo.list_for_date(a2.fqn, d1.date()) == []


def test_list_by_date_range_inclusive() -> None:
    repo = InMemoryGridDecisionRepo()
    asset = _asset()
    for d in [date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28)]:
        repo.save(
            asset=asset,
            timestamp=datetime(d.year, d.month, d.day, 6, tzinfo=UTC),
            decision=_gd(level_index=d.day),
        )
    got = repo.list_by_date_range(asset.fqn, date(2026, 5, 27), date(2026, 5, 28))
    assert [g.level_index for g in got] == [27, 28]


def test_uow_exposes_grid_decisions_attribute() -> None:
    """InMemoryUnitOfWork 가 grid_decisions Port attribute 노출."""
    uow = InMemoryUnitOfWork()
    asset = _asset()
    ts = datetime(2026, 5, 28, 6, tzinfo=UTC)
    with uow:
        uow.grid_decisions.save(asset=asset, timestamp=ts, decision=_gd())
        uow.commit()
    assert len(uow.grid_decisions.list_for_date(asset.fqn, ts.date())) == 1
