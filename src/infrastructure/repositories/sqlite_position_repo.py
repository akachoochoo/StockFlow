"""SQLite implementation of PositionRepoPort.

Per ADR §8.1 / §8.3 + ADR 0002 §3.2 / §3.3, persists Position + its
SplitSlot rows. The Asset is stored denormalised as ``asset_json`` on the
positions row so the point-in-time snapshot survives later asset metadata
changes. ``save`` upserts by ``asset.fqn`` and replaces split_slots via
DELETE+INSERT (cascade-friendly).

Phase 0.5 schema (see ``db._SCHEMA_STATEMENTS``): each slot row carries
``state`` (EMPTY/FILLED), the optional ``entry_*`` columns when FILLED,
and the optional ``last_exit_*`` columns regardless of state — the
HybridTimeBasedReentry policy needs the latter to compute reentry
trigger prices.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.models import (
    Asset,
    Position,
    SlotState,
    SplitEntry,
    SplitSlot,
)

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
        slot_rows = self._conn.execute(
            "SELECT slot_number, state, entry_date, entry_quantity, "
            "entry_price, entry_idempotency_key, last_exit_price, "
            "last_exit_date FROM split_slots WHERE position_id = ? "
            "ORDER BY slot_number",
            (row["id"],),
        ).fetchall()
        return self._build_position(row, slot_rows)

    def save(self, position: Position) -> None:
        # updated_at is current wall-clock UTC. Phase 0 uses real time here
        # because Position only persists state, not a decision moment;
        # callers requiring deterministic timestamps should override at
        # higher levels.
        updated_at = datetime.now(UTC).isoformat()

        asset_json = position.asset.model_dump_json()
        last_buy_at = (
            position.last_buy_at.isoformat()
            if position.last_buy_at is not None
            else None
        )
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
            # Replace split_slots: delete old, insert new
            self._conn.execute(
                "DELETE FROM split_slots WHERE position_id = ?",
                (position_id,),
            )

        for slot in position.slots:
            entry = slot.entry
            self._conn.execute(
                "INSERT INTO split_slots (position_id, slot_number, state, "
                "entry_date, entry_quantity, entry_price, "
                "entry_idempotency_key, last_exit_price, last_exit_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    position_id,
                    slot.slot_number,
                    slot.state.value,
                    entry.entry_date.isoformat() if entry is not None else None,
                    str(entry.quantity) if entry is not None else None,
                    str(entry.entry_price) if entry is not None else None,
                    entry.idempotency_key if entry is not None else None,
                    str(slot.last_exit_price)
                    if slot.last_exit_price is not None
                    else None,
                    slot.last_exit_date.isoformat()
                    if slot.last_exit_date is not None
                    else None,
                ),
            )

    def list_all(self) -> list[Position]:
        rows = self._conn.execute(
            "SELECT id, asset_json, quantity, avg_price, split_level, "
            "last_buy_at FROM positions ORDER BY asset_fqn"
        ).fetchall()
        result: list[Position] = []
        for row in rows:
            slot_rows = self._conn.execute(
                "SELECT slot_number, state, entry_date, entry_quantity, "
                "entry_price, entry_idempotency_key, last_exit_price, "
                "last_exit_date FROM split_slots WHERE position_id = ? "
                "ORDER BY slot_number",
                (row["id"],),
            ).fetchall()
            result.append(self._build_position(row, slot_rows))
        return result

    def delete(self, asset_fqn: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM positions WHERE asset_fqn = ?", (asset_fqn,)
        )
        return cursor.rowcount > 0

    @staticmethod
    def _build_position(
        row: sqlite3.Row, slot_rows: list[sqlite3.Row]
    ) -> Position:
        asset = Asset.model_validate_json(row["asset_json"])
        last_buy_at = (
            datetime.fromisoformat(row["last_buy_at"])
            if row["last_buy_at"] is not None
            else None
        )
        slots = [
            SqlitePositionRepo._row_to_slot(sr) for sr in slot_rows
        ]
        return Position(
            asset=asset,
            quantity=Decimal(row["quantity"]),
            avg_price=Decimal(row["avg_price"]),
            split_level=row["split_level"],
            last_buy_at=last_buy_at,
            slots=slots,
        )

    @staticmethod
    def _row_to_slot(sr: sqlite3.Row) -> SplitSlot:
        state = SlotState(sr["state"])
        entry: SplitEntry | None = None
        if state is SlotState.FILLED:
            entry = SplitEntry(
                split_number=sr["slot_number"],
                entry_date=date.fromisoformat(sr["entry_date"]),
                quantity=Decimal(sr["entry_quantity"]),
                entry_price=Decimal(sr["entry_price"]),
                idempotency_key=sr["entry_idempotency_key"],
            )
        last_exit_price = (
            Decimal(sr["last_exit_price"])
            if sr["last_exit_price"] is not None
            else None
        )
        last_exit_date = (
            date.fromisoformat(sr["last_exit_date"])
            if sr["last_exit_date"] is not None
            else None
        )
        return SplitSlot(
            slot_number=sr["slot_number"],
            state=state,
            entry=entry,
            last_exit_price=last_exit_price,
            last_exit_date=last_exit_date,
        )
