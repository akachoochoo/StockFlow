"""InMemoryUnitOfWork — Phase 0 backtest persistence (no-op transactions).

Per ADR §8.9, the in-memory variant is intentionally simpler than the SQLite
one: ``commit()`` and ``rollback()`` are **no-ops** and writes through the
repositories take effect immediately. Backtest determinism + low cost trump
the complexity of simulating transactional rollback in a single-process
single-thread runner.

Phase 1+ live trading uses ``SqliteUnitOfWork`` for real ACID guarantees.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.models import OrderStatus

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal
    from types import TracebackType

    from src.domain.models import (
        Decision,
        Order,
        PortfolioSnapshot,
        Position,
    )
    from src.ports.repositories import (
        DecisionRepoPort,
        OrderRepoPort,
        PortfolioSnapshotRepoPort,
        PositionRepoPort,
    )
    from src.ports.unit_of_work import UnitOfWorkPort

_TERMINAL_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED}
)


class InMemoryPositionRepo:
    """PositionRepoPort backed by a dict keyed on asset.fqn."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def get(self, asset_fqn: str) -> Position | None:
        return self._positions.get(asset_fqn)

    def save(self, position: Position) -> None:
        self._positions[position.asset.fqn] = position

    def list_all(self) -> list[Position]:
        # Sorted by fqn for deterministic order across runs.
        return [self._positions[k] for k in sorted(self._positions)]

    def delete(self, asset_fqn: str) -> bool:
        if asset_fqn in self._positions:
            del self._positions[asset_fqn]
            return True
        return False


class InMemoryOrderRepo:
    """OrderRepoPort backed by a dict keyed on idempotency_key.

    Duplicate inserts raise ValueError, mirroring the IntegrityError the
    SqliteOrderRepo would surface.
    """

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def save(self, order: Order) -> None:
        if order.idempotency_key in self._orders:
            raise ValueError(
                f"Duplicate idempotency_key: {order.idempotency_key}"
            )
        self._orders[order.idempotency_key] = order

    def get_by_idempotency_key(self, key: str) -> Order | None:
        return self._orders.get(key)

    def find_by_broker_order_id(self, broker_order_id: str) -> Order | None:
        for o in self._orders.values():
            if o.broker_order_id == broker_order_id:
                return o
        return None

    def update_status(
        self,
        idempotency_key: str,
        new_status: OrderStatus,
        *,
        filled_quantity: Decimal,
        filled_price: Decimal | None,
        filled_at: datetime | None,
        broker_order_id: str | None = None,
        broker_org_no: str | None = None,
    ) -> None:
        if new_status not in _TERMINAL_STATUSES:
            raise ValueError(
                f"update_status accepts terminal statuses only "
                f"(FILLED / CANCELED / EXPIRED), got {new_status.value}"
            )
        existing = self._orders.get(idempotency_key)
        if existing is None:
            raise ValueError(
                f"update_status: no order with idempotency_key={idempotency_key}"
            )
        # COALESCE semantics: None preserves the existing broker_* values.
        self._orders[idempotency_key] = existing.model_copy(
            update={
                "status": new_status,
                "filled_quantity": filled_quantity,
                "filled_price": filled_price,
                "filled_at": filled_at,
                "broker_order_id": (
                    broker_order_id
                    if broker_order_id is not None
                    else existing.broker_order_id
                ),
                "broker_org_no": (
                    broker_org_no
                    if broker_org_no is not None
                    else existing.broker_org_no
                ),
            }
        )

    def list_pending(self) -> list[Order]:
        pending_states = (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED)
        return sorted(
            (o for o in self._orders.values() if o.status in pending_states),
            key=lambda o: o.submitted_at,
        )

    def list_by_date(self, d: date) -> list[Order]:
        return sorted(
            (o for o in self._orders.values() if o.submitted_at.date() == d),
            key=lambda o: o.submitted_at,
        )


class InMemoryDecisionRepo:
    """DecisionRepoPort backed by an append-only list."""

    def __init__(self) -> None:
        self._decisions: list[Decision] = []

    def save(self, decision: Decision) -> None:
        self._decisions.append(decision)

    def list_by_date_range(self, start: date, end: date) -> list[Decision]:
        return sorted(
            (d for d in self._decisions if start <= d.timestamp.date() <= end),
            key=lambda d: d.timestamp,
        )

    def get_last_for_asset(self, asset_fqn: str) -> Decision | None:
        matching = [d for d in self._decisions if d.asset.fqn == asset_fqn]
        if not matching:
            return None
        return max(matching, key=lambda d: d.timestamp)


class InMemoryPortfolioSnapshotRepo:
    """PortfolioSnapshotRepoPort backed by a dict keyed on snapshot_date."""

    def __init__(self) -> None:
        self._snapshots: dict[date, PortfolioSnapshot] = {}

    def save(self, snapshot: PortfolioSnapshot) -> None:
        self._snapshots[snapshot.snapshot_date] = snapshot

    def get_by_date(self, d: date) -> PortfolioSnapshot | None:
        return self._snapshots.get(d)

    def list_by_date_range(
        self, start: date, end: date
    ) -> list[PortfolioSnapshot]:
        return sorted(
            (
                s
                for s in self._snapshots.values()
                if start <= s.snapshot_date <= end
            ),
            key=lambda s: s.snapshot_date,
        )

    def get_last(self) -> PortfolioSnapshot | None:
        if not self._snapshots:
            return None
        latest_date = max(self._snapshots)
        return self._snapshots[latest_date]


class InMemoryUnitOfWork:
    """UnitOfWorkPort over four in-memory repositories.

    Per ADR §8.9: ``commit()`` and ``rollback()`` are no-ops; writes via the
    exposed repositories are immediately visible. Phase 0 backtest contract.
    """

    def __init__(self) -> None:
        # Annotated as the Port types so this class structurally conforms to
        # UnitOfWorkPort (mypy treats attribute Protocol types as invariant).
        self.positions: PositionRepoPort = InMemoryPositionRepo()
        self.orders: OrderRepoPort = InMemoryOrderRepo()
        self.decisions: DecisionRepoPort = InMemoryDecisionRepo()
        self.snapshots: PortfolioSnapshotRepoPort = InMemoryPortfolioSnapshotRepo()

    def __enter__(self) -> UnitOfWorkPort:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # No-op: writes already took effect on the in-memory dicts.
        pass

    def commit(self) -> None:
        """No-op (writes are immediate). Kept for Port conformance."""

    def rollback(self) -> None:
        """No-op. Phase 0 backtest does NOT simulate transactional rollback."""
