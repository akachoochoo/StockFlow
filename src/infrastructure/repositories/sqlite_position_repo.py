"""SQLite implementation of PositionRepoPort.

Per ADR §8.1 / §8.3, persists Position + its SplitEntry rows. The Asset is
stored denormalised as asset_json on each row so the point-in-time snapshot
survives later asset metadata changes. `save` upserts by asset.fqn and
replaces split_entries via DELETE+INSERT (cascade-friendly).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.models import Asset, Position, SplitEntry

if TYPE_CHECKING:
    import sqlite3


class SqlitePositionRepo:
    """PositionRepoPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, asset_fqn: str) -> Position | None:
        row = self._conn.execute(
            "SELECT id, asset_json, quantity, avg_price, split_level, "
            "last_buy_at FROM positions WHERE asset_fqn = ?",
            (asset_fqn,),
        ).fetchone()
        if row is None:
            return None
        entry_rows = self._conn.execute(
            "SELECT split_number, entry_date, quantity, entry_price, "
            "idempotency_key FROM split_entries WHERE position_id = ? "
            "ORDER BY split_number",
            (row["id"],),
        ).fetchall()
        return self._build_position(row, entry_rows)

    def save(self, position: Position) -> None:
        from datetime import datetime as _dt

        # updated_at is current wall-clock UTC. Phase 0 uses real time here
        # because Position only persists state, not a decision moment;
        # callers requiring deterministic timestamps should override at
        # higher levels.
        updated_at = _dt.now(UTC).isoformat()

        asset_json = position.asset.model_dump_json()
        last_buy_at = (
            position.last_buy_at.isoformat()
            if position.last_buy_at is not None
            else None
        )
        # Upsert by asset_fqn
        existing = self._conn.execute(
            "SELECT id FROM positions WHERE asset_fqn = ?",
            (position.asset.fqn,),
        ).fetchone()
        if existing is None:
            cursor = self._conn.execute(
                "INSERT INTO positions (asset_fqn, asset_json, quantity, "
                "avg_price, split_level, last_buy_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    position.asset.fqn,
                    asset_json,
                    str(position.quantity),
                    str(position.avg_price),
                    position.split_level,
                    last_buy_at,
                    updated_at,
                ),
            )
            position_id = cursor.lastrowid
        else:
            position_id = existing["id"]
            # Per ADR §8.3, asset_json is point-in-time and is NOT overwritten.
            self._conn.execute(
                "UPDATE positions SET quantity = ?, avg_price = ?, "
                "split_level = ?, last_buy_at = ?, updated_at = ? WHERE id = ?",
                (
                    str(position.quantity),
                    str(position.avg_price),
                    position.split_level,
                    last_buy_at,
                    updated_at,
                    position_id,
                ),
            )
            # Replace split_entries: delete old, insert new
            self._conn.execute(
                "DELETE FROM split_entries WHERE position_id = ?",
                (position_id,),
            )

        for entry in position.entries:
            self._conn.execute(
                "INSERT INTO split_entries (position_id, split_number, "
                "entry_date, quantity, entry_price, idempotency_key) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    position_id,
                    entry.split_number,
                    entry.entry_date.isoformat(),
                    str(entry.quantity),
                    str(entry.entry_price),
                    entry.idempotency_key,
                ),
            )

    def list_all(self) -> list[Position]:
        rows = self._conn.execute(
            "SELECT id, asset_json, quantity, avg_price, split_level, "
            "last_buy_at FROM positions ORDER BY asset_fqn"
        ).fetchall()
        result: list[Position] = []
        for row in rows:
            entry_rows = self._conn.execute(
                "SELECT split_number, entry_date, quantity, entry_price, "
                "idempotency_key FROM split_entries WHERE position_id = ? "
                "ORDER BY split_number",
                (row["id"],),
            ).fetchall()
            result.append(self._build_position(row, entry_rows))
        return result

    def delete(self, asset_fqn: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM positions WHERE asset_fqn = ?", (asset_fqn,)
        )
        return cursor.rowcount > 0

    @staticmethod
    def _build_position(row: sqlite3.Row, entry_rows: list[sqlite3.Row]) -> Position:
        asset = Asset.model_validate_json(row["asset_json"])
        last_buy_at = (
            datetime.fromisoformat(row["last_buy_at"])
            if row["last_buy_at"] is not None
            else None
        )
        from datetime import date as _date
        entries = [
            SplitEntry(
                split_number=er["split_number"],
                entry_date=_date.fromisoformat(er["entry_date"]),
                quantity=Decimal(er["quantity"]),
                entry_price=Decimal(er["entry_price"]),
                idempotency_key=er["idempotency_key"],
            )
            for er in entry_rows
        ]
        return Position(
            asset=asset,
            quantity=Decimal(row["quantity"]),
            avg_price=Decimal(row["avg_price"]),
            split_level=row["split_level"],
            last_buy_at=last_buy_at,
            entries=entries,
        )
