"""Tests for InMemoryGridStateRepo + UoW grid_states attribute (ADR 0022 §12).

In-memory parity with SqliteGridStateRepo — Phase 0 backtest 가 sqlite 없이
크론 간 영속을 시뮬레이션.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.adapters.mock.in_memory_unit_of_work import (
    InMemoryGridStateRepo,
    InMemoryUnitOfWork,
)
from src.domain.strategies.grid import GridRuntimeState, GridState

NOW = datetime(2026, 5, 28, 6, 0, 0, tzinfo=UTC)


def _state(
    *,
    cooldown_remaining: int = 0,
    last_sell_price: str = "0",
    avg_cost: str = "0",
) -> GridRuntimeState:
    return GridRuntimeState(
        grid_state=GridState(
            reference_price=Decimal("30000"),
            grid_levels=(
                Decimal("29400"),
                Decimal("29700"),
                Decimal("30000"),
                Decimal("30300"),
                Decimal("30600"),
            ),
        ),
        cooldown_remaining=cooldown_remaining,
        last_sell_price=Decimal(last_sell_price),
        avg_cost=Decimal(avg_cost),
    )


def test_save_and_get_round_trip() -> None:
    repo = InMemoryGridStateRepo()
    s = _state(cooldown_remaining=3, last_sell_price="30605", avg_cost="29850")
    repo.save(asset_fqn="KRX:069500", state=s, updated_at=NOW)
    got = repo.get("KRX:069500")
    assert got == s


def test_save_twice_replaces() -> None:
    repo = InMemoryGridStateRepo()
    repo.save(
        asset_fqn="KRX:069500", state=_state(cooldown_remaining=3), updated_at=NOW
    )
    repo.save(
        asset_fqn="KRX:069500", state=_state(cooldown_remaining=0), updated_at=NOW
    )
    assert repo.get("KRX:069500").cooldown_remaining == 0


def test_get_returns_none_when_absent() -> None:
    repo = InMemoryGridStateRepo()
    assert repo.get("KRX:000000") is None


def test_delete_returns_true_when_present() -> None:
    repo = InMemoryGridStateRepo()
    repo.save(asset_fqn="KRX:069500", state=_state(), updated_at=NOW)
    assert repo.delete("KRX:069500") is True
    assert repo.get("KRX:069500") is None


def test_delete_returns_false_when_absent() -> None:
    repo = InMemoryGridStateRepo()
    assert repo.delete("KRX:000000") is False


def test_uow_exposes_grid_states_attribute() -> None:
    """InMemoryUnitOfWork 가 grid_states Port attribute 노출."""
    uow = InMemoryUnitOfWork()
    with uow:
        uow.grid_states.save(
            asset_fqn="KRX:069500",
            state=_state(cooldown_remaining=5),
            updated_at=NOW,
        )
        uow.commit()
    got = uow.grid_states.get("KRX:069500")
    assert got is not None
    assert got.cooldown_remaining == 5
