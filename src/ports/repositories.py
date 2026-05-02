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
    from datetime import date

    from src.domain.models import (
        Decision,
        Order,
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
    """Order persistence (orders table). Orders are immutable in Phase 0."""

    def save(self, order: Order) -> None:
        """Insert by idempotency_key. Duplicate inserts are caller errors."""
        ...

    def get_by_idempotency_key(self, key: str) -> Order | None:
        """Return the Order for `key`, or None if absent."""
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
