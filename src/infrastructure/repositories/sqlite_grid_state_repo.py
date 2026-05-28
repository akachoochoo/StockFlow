"""SQLite implementation of GridStateRepoPort (ADR 0022 §12 follow-up).

Per-asset 1 행 upsert. ``grid_levels`` 는 JSON array of Decimal strings (정수
보존). cooldown_remaining/avg_cost/last_sell_price 는 단순 TEXT(Decimal) /
INT.

Schema (`src/infrastructure/db.py` ``grid_states``):
    asset_fqn PK, reference_price, grid_levels_json,
    cooldown_remaining, last_sell_price, avg_cost, updated_at.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.strategies.grid import GridRuntimeState, GridState

if TYPE_CHECKING:
    import sqlite3


class SqliteGridStateRepo:
    """GridStateRepoPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, asset_fqn: str) -> GridRuntimeState | None:
        row = self._conn.execute(
            "SELECT * FROM grid_states WHERE asset_fqn = ?",
            (asset_fqn,),
        ).fetchone()
        if row is None:
            return None
        return self._build_state(row)

    def save(
        self,
        *,
        asset_fqn: str,
        state: GridRuntimeState,
        updated_at: datetime,
    ) -> None:
        levels_json = json.dumps([str(lvl) for lvl in state.grid_state.grid_levels])
        # INSERT OR REPLACE = upsert (asset_fqn PK conflict → replace).
        self._conn.execute(
            "INSERT OR REPLACE INTO grid_states ("
            "asset_fqn, reference_price, grid_levels_json, "
            "cooldown_remaining, last_sell_price, avg_cost, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                asset_fqn,
                str(state.grid_state.reference_price),
                levels_json,
                state.cooldown_remaining,
                str(state.last_sell_price),
                str(state.avg_cost),
                updated_at.isoformat(),
            ),
        )

    def delete(self, asset_fqn: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM grid_states WHERE asset_fqn = ?",
            (asset_fqn,),
        )
        return cur.rowcount > 0

    @staticmethod
    def _build_state(row: sqlite3.Row) -> GridRuntimeState:
        levels = tuple(
            Decimal(s) for s in json.loads(row["grid_levels_json"])
        )
        grid_state = GridState(
            reference_price=Decimal(row["reference_price"]),
            grid_levels=levels,
        )
        return GridRuntimeState(
            grid_state=grid_state,
            cooldown_remaining=int(row["cooldown_remaining"]),
            last_sell_price=Decimal(row["last_sell_price"]),
            avg_cost=Decimal(row["avg_cost"]),
        )
