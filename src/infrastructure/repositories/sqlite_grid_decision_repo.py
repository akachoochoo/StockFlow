"""SQLite implementation of GridDecisionRepoPort (ADR 0022 §12 D22).

Mirror of :mod:`src.infrastructure.repositories.sqlite_decision_repo` but
for DGT grid trades. Split decisions 와 다른 점:

- 하루 같은 asset 에 다수 GridDecision row 가능 (다중 격자 통과).
- ``slot_number`` 없음 — ``level_index`` (0..n).
- ``buy_action`` / ``sell_actions`` / ``skip_reason`` 없음 — 직접 side / level
  / price / quantity 만.

저장 단위: (timestamp, asset, GridDecision). Repo signature 가 metadata 를
명시적으로 받음 (Decision 처럼 wrapper 없이).

Schema (`src/infrastructure/db.py` ``grid_decisions``):
    id, timestamp, asset_fqn, asset_json, side, level_index, level_price,
    rounded_price, quantity, reasoning(JSON)

Indexes: idx_grid_decisions_timestamp, idx_grid_decisions_asset_fqn.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.models import Asset, OrderSide
from src.domain.strategies.grid import GridDecision

if TYPE_CHECKING:
    import sqlite3


class SqliteGridDecisionRepo:
    """GridDecisionRepoPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(
        self,
        *,
        asset: Asset,
        timestamp: datetime,
        decision: GridDecision,
    ) -> None:
        self._conn.execute(
            "INSERT INTO grid_decisions ("
            "timestamp, asset_fqn, asset_json, side, level_index, "
            "level_price, rounded_price, quantity, reasoning"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                timestamp.isoformat(),
                asset.fqn,
                asset.model_dump_json(),
                decision.side.value,
                decision.level_index,
                str(decision.level_price),
                str(decision.rounded_price),
                str(decision.quantity),
                json.dumps(decision.reasoning, sort_keys=True),
            ),
        )

    def list_for_date(
        self, asset_fqn: str, trade_date: date
    ) -> list[GridDecision]:
        rows = self._conn.execute(
            "SELECT * FROM grid_decisions "
            "WHERE asset_fqn = ? AND substr(timestamp, 1, 10) = ? "
            "ORDER BY timestamp ASC",
            (asset_fqn, trade_date.isoformat()),
        ).fetchall()
        return [self._build_decision(r) for r in rows]

    def list_by_date_range(
        self, asset_fqn: str, start: date, end: date
    ) -> list[GridDecision]:
        rows = self._conn.execute(
            "SELECT * FROM grid_decisions "
            "WHERE asset_fqn = ? AND substr(timestamp, 1, 10) BETWEEN ? AND ? "
            "ORDER BY timestamp ASC",
            (asset_fqn, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [self._build_decision(r) for r in rows]

    @staticmethod
    def _build_decision(row: sqlite3.Row) -> GridDecision:
        return GridDecision(
            side=OrderSide(row["side"]),
            level_index=int(row["level_index"]),
            level_price=Decimal(row["level_price"]),
            rounded_price=Decimal(row["rounded_price"]),
            quantity=Decimal(row["quantity"]),
            reasoning=json.loads(row["reasoning"]),
        )
