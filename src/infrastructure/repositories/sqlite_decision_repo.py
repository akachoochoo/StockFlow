"""SQLite implementation of DecisionRepoPort.

Per ADR §8.1 / §8.3, decisions are append-only history. `reasoning` is
stored as JSON via ``json.dumps(sort_keys=True)`` for deterministic output
(diffable across runs).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from src.domain.models import Asset, Decision

if TYPE_CHECKING:
    import sqlite3
    from datetime import date


class SqliteDecisionRepo:
    """DecisionRepoPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, decision: Decision) -> None:
        self._conn.execute(
            "INSERT INTO decisions (timestamp, asset_fqn, asset_json, "
            "action, reasoning, resulting_order_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                decision.timestamp.isoformat(),
                decision.asset.fqn,
                decision.asset.model_dump_json(),
                decision.action,
                json.dumps(decision.reasoning, sort_keys=True),
                decision.resulting_order_id,
            ),
        )

    def list_by_date_range(self, start: date, end: date) -> list[Decision]:
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE substr(timestamp, 1, 10) "
            "BETWEEN ? AND ? ORDER BY timestamp",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._build_decision(r) for r in rows]

    def get_last_for_asset(self, asset_fqn: str) -> Decision | None:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE asset_fqn = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (asset_fqn,),
        ).fetchone()
        if row is None:
            return None
        return self._build_decision(row)

    @staticmethod
    def _build_decision(row: sqlite3.Row) -> Decision:
        return Decision(
            timestamp=datetime.fromisoformat(row["timestamp"]),
            asset=Asset.model_validate_json(row["asset_json"]),
            action=row["action"],
            reasoning=json.loads(row["reasoning"]),
            resulting_order_id=row["resulting_order_id"],
        )
