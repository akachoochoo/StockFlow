"""SqliteUnitOfWork — transactional boundary over a sqlite3.Connection.

Per ADR §8.2, the UoW owns the BEGIN / COMMIT / ROLLBACK while Repository
methods stay scoped to single-statement work. Auto-rollback on context exit
without an explicit commit is the safe default — partial writes never persist.

sqlite3 driver semantics:
- ``isolation_level = ""`` (default) auto-BEGINs a transaction on the first
  DML statement after the previous commit/rollback. The UoW's ``__exit__``
  rolls back any in-flight transaction when commit() wasn't called.

Phase 0 single-process single-thread: one ``sqlite3.Connection`` is reused
across UoW instances. The ``uow_factory`` closure provided to use cases
captures this connection and yields a fresh UoW per invocation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.infrastructure.repositories.sqlite_decision_repo import (
    SqliteDecisionRepo,
)
from src.infrastructure.repositories.sqlite_order_repo import SqliteOrderRepo
from src.infrastructure.repositories.sqlite_portfolio_snapshot_repo import (
    SqlitePortfolioSnapshotRepo,
)
from src.infrastructure.repositories.sqlite_position_repo import (
    SqlitePositionRepo,
)

if TYPE_CHECKING:
    import sqlite3
    from types import TracebackType


class SqliteUnitOfWork:
    """UnitOfWorkPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._committed = False
        self.positions = SqlitePositionRepo(conn)
        self.orders = SqliteOrderRepo(conn)
        self.decisions = SqliteDecisionRepo(conn)
        self.snapshots = SqlitePortfolioSnapshotRepo(conn)

    def __enter__(self) -> SqliteUnitOfWork:
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._committed:
            self._conn.rollback()

    def commit(self) -> None:
        """Commit the in-flight transaction. Subsequent ``__exit__`` is no-op."""
        self._conn.commit()
        self._committed = True

    def rollback(self) -> None:
        """Discard any in-flight changes. Idempotent."""
        self._conn.rollback()
        self._committed = False
