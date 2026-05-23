"""Repository ports — persistence abstractions per aggregate.

Per ADR §8.1, each aggregate has its own Port. Implementations live in
`src/infrastructure/repositories/` (SQLite) and `src/adapters/mock/` (in
memory). Use Cases hold these via UnitOfWorkPort, never directly.

Per ADR §8.2 these methods are single-SQL-statement scoped — they do NOT
own transaction boundaries. The UnitOfWork wraps multiple repository calls
in one transaction.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from src.domain.models import (
        Decision,
        Order,
        OrderStatus,
        PortfolioSnapshot,
        Position,
    )


class PositionRepoPort(Protocol):
    """Position persistence (positions + split_entries tables).

    `save` performs upsert by `position.asset.fqn` and replaces the
    cascading `split_entries` rows. `get` returns the Position with its
    entries reconstructed; the asset on the returned Position is the
    point-in-time snapshot stored in `asset_json` (ADR §8.3).
    """

    def get(self, asset_fqn: str) -> Position | None:
        """Return the Position for `asset_fqn`, or None if absent."""
        ...

    def save(self, position: Position) -> None:
        """Upsert by asset.fqn. Replaces split_entries via cascade-delete."""
        ...

    def list_all(self) -> list[Position]:
        """Return every persisted Position. Empty list when none."""
        ...

    def delete(self, asset_fqn: str) -> bool:
        """Remove a Position by fqn. Returns True if a row was deleted."""
        ...


class OrderRepoPort(Protocol):
    """Order persistence (orders table).

    Phase 0 immutable; Phase 1.1 async settlement 위해 terminal status
    전이(:meth:`update_status`)만 허용 — settle 은 broker 가 *이미 확정한*
    체결 사실을 *기록* 할 뿐 split_level/avg 를 재계산하지 않는다 (결정론
    보존, ADR 0012 §2.5 / ADR 0019 정신). 이 전이 경로가 없으면 settle 된
    PENDING 주문이 매 cron :meth:`list_pending` 에 재반환되어 반복 split++
    → drift → reconciliation halt 가 구조적으로 불가피하므로, 좁게 한정된
    write 메서드를 additive 로 추가한다.
    """

    def save(self, order: Order) -> None:
        """Insert by idempotency_key. Duplicate inserts are caller errors."""
        ...

    def get_by_idempotency_key(self, key: str) -> Order | None:
        """Return the Order for `key`, or None if absent."""
        ...

    def find_by_broker_order_id(self, broker_order_id: str) -> Order | None:
        """Return the Order for `broker_order_id`, or None if absent.

        Used to resolve the routing org_no (broker_org_no) for a given
        broker_order_id when cancelling — KIS cancel needs both the original
        ODNO and the org_no (KRX_FWDG_ORD_ORGNO).
        """
        ...

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
        """Persist a terminal status transition for an existing order.

        Only terminal statuses (FILLED / CANCELED / EXPIRED) are accepted —
        PARTIALLY_FILLED is rejected because a partial fill must stay in
        :meth:`list_pending` so the next cron re-checks it (its termination
        is handled by a separate max-age halt, not by this method).

        ``broker_order_id`` / ``broker_org_no`` are preserved when passed as
        None (the existing values are not overwritten) so a PENDING→FILLED
        transition does not erase the cancel-routing org_no.

        settle records broker-confirmed facts; it does NOT recompute
        split_level / avg_price (determinism, ADR 0012 §2.5).
        """
        ...

    def list_pending(self) -> list[Order]:
        """Return orders in PENDING / PARTIALLY_FILLED state.

        Used by reconciliation to identify orders awaiting completion.
        """
        ...

    def list_by_date(self, d: date) -> list[Order]:
        """Return orders submitted on the given UTC date."""
        ...


class DecisionRepoPort(Protocol):
    """Decision persistence (decisions table). Decisions are append-only."""

    def save(self, decision: Decision) -> None:
        """Insert a Decision row. Each Decision is immutable history."""
        ...

    def list_by_date_range(self, start: date, end: date) -> list[Decision]:
        """Return decisions whose `timestamp.date()` falls in [start, end]."""
        ...

    def get_last_for_asset(self, asset_fqn: str) -> Decision | None:
        """Return the most recent Decision for `asset_fqn`, or None if none."""
        ...


class PortfolioSnapshotRepoPort(Protocol):
    """Daily portfolio snapshot persistence (portfolio_snapshots table)."""

    def save(self, snapshot: PortfolioSnapshot) -> None:
        """Upsert by snapshot_date (one snapshot per day)."""
        ...

    def get_by_date(self, d: date) -> PortfolioSnapshot | None:
        """Return the snapshot for the given date, or None if absent."""
        ...

    def list_by_date_range(
        self, start: date, end: date
    ) -> list[PortfolioSnapshot]:
        """Return snapshots in [start, end], ordered by snapshot_date asc."""
        ...

    def get_last(self) -> PortfolioSnapshot | None:
        """Return the most-recent snapshot by snapshot_date, or None if empty.

        Used by paper trading composition (ADR §10.3) to restore cash
        between cron invocations: the last snapshot's cash is the
        starting cash for the next day.
        """
        ...
