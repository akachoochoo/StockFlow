"""SQLite implementation of DecisionRepoPort.

Per ADR §8.1 / §8.3 + ADR 0002 §5.4.2, decisions are append-only history.
The Phase 0.5 schema persists per-row sell_actions (JSON list), an
optional buy_action (JSON or NULL), and an optional skip_reason. Per-row
reasoning (top-level dict) is stored as JSON via
``json.dumps(sort_keys=True)`` for deterministic output (diffable across
runs). ``idx_decisions_skip_reason`` lets retrospective tooling cheaply
count skip categories such as ``ALL_SLOTS_FILLED_NO_PROFIT`` (the Phase 0
4.7-year dormancy KPI).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from src.domain.models import (
    Asset,
    BuyActionRecord,
    Decision,
    SellActionRecord,
    SkipReason,
)

if TYPE_CHECKING:
    import sqlite3
    from datetime import date


# TypeAdapter handles JSON round-trip of nested ValueObjects with the
# strict=True config (mirrors PortfolioSnapshot.valuations pattern).
_SELL_ACTIONS_ADAPTER = TypeAdapter(list[SellActionRecord])
_BUY_ACTION_ADAPTER = TypeAdapter(BuyActionRecord)


class SqliteDecisionRepo:
    """DecisionRepoPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, decision: Decision) -> None:
        sell_actions_json = _SELL_ACTIONS_ADAPTER.dump_json(
            decision.sell_actions
        ).decode()
        buy_action_json = (
            _BUY_ACTION_ADAPTER.dump_json(decision.buy_action).decode()
            if decision.buy_action is not None
            else None
        )
        skip_reason = (
            decision.skip_reason.value
            if decision.skip_reason is not None
            else None
        )
        self._conn.execute(
            "INSERT INTO decisions (timestamp, asset_fqn, asset_json, "
            "sell_actions_json, buy_action_json, skip_reason, reasoning) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                decision.timestamp.isoformat(),
                decision.asset.fqn,
                decision.asset.model_dump_json(),
                sell_actions_json,
                buy_action_json,
                skip_reason,
                json.dumps(decision.reasoning, sort_keys=True),
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
        sell_actions = _SELL_ACTIONS_ADAPTER.validate_json(
            row["sell_actions_json"]
        )
        buy_action = (
            _BUY_ACTION_ADAPTER.validate_json(row["buy_action_json"])
            if row["buy_action_json"] is not None
            else None
        )
        skip_reason = (
            SkipReason(row["skip_reason"])
            if row["skip_reason"] is not None
            else None
        )
        return Decision(
            timestamp=datetime.fromisoformat(row["timestamp"]),
            asset=Asset.model_validate_json(row["asset_json"]),
            sell_actions=sell_actions,
            buy_action=buy_action,
            skip_reason=skip_reason,
            reasoning=json.loads(row["reasoning"]),
        )
