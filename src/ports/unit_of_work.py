"""UnitOfWork port — transactional boundary across all four repositories.

Per ADR §8.2 / §8.5 the UoW owns the transaction; Repository methods do
not. Use Cases use the UoW context-manager, then call `commit()` to make
changes durable. **Auto-rollback** on context exit without commit is the
safe default — partial saves never persist.

Phase 0 implementations:
- ``SqliteUnitOfWork`` (src/infrastructure/sqlite_unit_of_work.py): real
  sqlite3 transaction wrapping.
- ``InMemoryUnitOfWork`` (src/adapters/mock/in_memory_unit_of_work.py):
  in-process no-op; backtest determinism without DB cost.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from types import TracebackType

    from src.ports.repositories import (
        DecisionRepoPort,
        GridDecisionRepoPort,
        GridStateRepoPort,
        OrderRepoPort,
        PortfolioSnapshotRepoPort,
        PositionRepoPort,
    )


class UnitOfWorkPort(Protocol):
    """Transactional boundary spanning the four repositories.

    Usage:
        with uow_factory() as uow:
            uow.orders.save(order)
            uow.positions.save(position)
            uow.decisions.save(decision)
            uow.commit()
        # context exit triggers rollback only if commit() wasn't called

    Repositories are exposed as attributes; their implementations must
    share the underlying connection / state with this UoW so that the
    transaction encompasses their writes.
    """

    positions: PositionRepoPort
    orders: OrderRepoPort
    decisions: DecisionRepoPort
    grid_decisions: GridDecisionRepoPort  # ADR 0022 §12 D22
    grid_states: GridStateRepoPort  # ADR 0022 §12 follow-up (cron 간 영속)
    snapshots: PortfolioSnapshotRepoPort

    def __enter__(self) -> UnitOfWorkPort:
        """Begin a transaction (or its in-memory analogue)."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """End the unit. Triggers rollback if commit() wasn't called."""
        ...

    def commit(self) -> None:
        """Make the writes durable. Subsequent ``__exit__`` is a no-op."""
        ...

    def rollback(self) -> None:
        """Discard all writes since enter. Idempotent."""
        ...
