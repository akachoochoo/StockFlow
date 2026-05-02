"""SQLite implementation of PortfolioSnapshotRepoPort.

Per ADR §8.4 / §8.6, snapshots are upserted by snapshot_date (one per day).
`valuations` is stored as a JSON string (TypeAdapter-encoded list of
PositionValuation); each Money field is split into ``*_amount`` (TEXT,
Decimal) + ``*_currency`` (TEXT).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from src.domain.models import (
    Currency,
    Money,
    PortfolioSnapshot,
    PositionValuation,
)

if TYPE_CHECKING:
    import sqlite3


# TypeAdapter handles JSON round-trip of nested enums (Currency, AssetClass,
# Exchange) correctly even under the strict=True ValueObject config. A naive
# json.dumps + model_validate path fails because enum strings are rejected
# by strict Python validation.
_VALUATIONS_ADAPTER = TypeAdapter(list[PositionValuation])


class SqlitePortfolioSnapshotRepo:
    """PortfolioSnapshotRepoPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, snapshot: PortfolioSnapshot) -> None:
        valuations_json = _VALUATIONS_ADAPTER.dump_json(
            snapshot.valuations
        ).decode()
        created_at = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO portfolio_snapshots ("
            "snapshot_date, snapshot_at, "
            "initial_capital_amount, initial_capital_currency, "
            "cash_amount, cash_currency, valuations_json, "
            "total_market_value_amount, total_market_value_currency, "
            "total_value_amount, total_value_currency, "
            "total_cost_basis_amount, total_cost_basis_currency, "
            "total_unrealized_pnl_amount, total_unrealized_pnl_currency, "
            "created_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.snapshot_date.isoformat(),
                snapshot.snapshot_at.isoformat(),
                str(snapshot.initial_capital.amount),
                snapshot.initial_capital.currency.value,
                str(snapshot.cash.amount),
                snapshot.cash.currency.value,
                valuations_json,
                str(snapshot.total_market_value.amount),
                snapshot.total_market_value.currency.value,
                str(snapshot.total_value.amount),
                snapshot.total_value.currency.value,
                str(snapshot.total_cost_basis.amount),
                snapshot.total_cost_basis.currency.value,
                str(snapshot.total_unrealized_pnl.amount),
                snapshot.total_unrealized_pnl.currency.value,
                created_at,
            ),
        )

    def get_by_date(self, d: date) -> PortfolioSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE snapshot_date = ?",
            (d.isoformat(),),
        ).fetchone()
        if row is None:
            return None
        return self._build_snapshot(row)

    def list_by_date_range(
        self, start: date, end: date
    ) -> list[PortfolioSnapshot]:
        rows = self._conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE snapshot_date "
            "BETWEEN ? AND ? ORDER BY snapshot_date",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._build_snapshot(r) for r in rows]

    def get_last(self) -> PortfolioSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM portfolio_snapshots "
            "ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._build_snapshot(row)

    @staticmethod
    def _build_snapshot(row: sqlite3.Row) -> PortfolioSnapshot:
        valuations = _VALUATIONS_ADAPTER.validate_json(row["valuations_json"])
        return PortfolioSnapshot(
            snapshot_date=date.fromisoformat(row["snapshot_date"]),
            snapshot_at=datetime.fromisoformat(row["snapshot_at"]),
            initial_capital=Money(
                amount=Decimal(row["initial_capital_amount"]),
                currency=Currency(row["initial_capital_currency"]),
            ),
            cash=Money(
                amount=Decimal(row["cash_amount"]),
                currency=Currency(row["cash_currency"]),
            ),
            valuations=valuations,
            total_market_value=Money(
                amount=Decimal(row["total_market_value_amount"]),
                currency=Currency(row["total_market_value_currency"]),
            ),
            total_value=Money(
                amount=Decimal(row["total_value_amount"]),
                currency=Currency(row["total_value_currency"]),
            ),
            total_cost_basis=Money(
                amount=Decimal(row["total_cost_basis_amount"]),
                currency=Currency(row["total_cost_basis_currency"]),
            ),
            total_unrealized_pnl=Money(
                amount=Decimal(row["total_unrealized_pnl_amount"]),
                currency=Currency(row["total_unrealized_pnl_currency"]),
            ),
        )
