"""SQLite connection factory and schema bootstrap.

Phase 0 keeps things simple per ADR §8.4 / §8.5 and the global decision in
ADR §1 (no Alembic). Connecting to a path runs ``CREATE TABLE IF NOT EXISTS``
for every schema object so the file is ready to use after a single call.

PRAGMA settings:
- ``foreign_keys = ON`` — required for the split_slots cascade to work
  (sqlite3 disables FKs by default).

All Decimal values are stored as TEXT, all datetimes as ISO 8601 UTC TEXT,
all dates as YYYY-MM-DD TEXT, and Money values as separate amount/currency
columns. See ADR §8.4 for the rationale and the full DDL.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema (ADR §8.4)
# ---------------------------------------------------------------------------
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_fqn TEXT NOT NULL UNIQUE,
        asset_json TEXT NOT NULL,
        quantity TEXT NOT NULL,
        avg_price TEXT NOT NULL,
        split_level INTEGER NOT NULL,
        last_buy_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_positions_asset_fqn ON positions(asset_fqn)",
    """
    CREATE TABLE IF NOT EXISTS split_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
        slot_number INTEGER NOT NULL,
        state TEXT NOT NULL,                     -- EMPTY | FILLED
        entry_date TEXT,                         -- nullable when EMPTY
        entry_quantity TEXT,
        entry_price TEXT,
        entry_idempotency_key TEXT,
        last_exit_price TEXT,                    -- nullable
        last_exit_date TEXT,                     -- nullable
        UNIQUE (position_id, slot_number)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_split_slots_position ON split_slots(position_id)",
    """
    CREATE TABLE IF NOT EXISTS orders (
        idempotency_key TEXT PRIMARY KEY,
        asset_fqn TEXT NOT NULL,
        asset_json TEXT NOT NULL,
        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        quantity TEXT NOT NULL,
        target_price TEXT NOT NULL,
        status TEXT NOT NULL,
        broker_order_id TEXT,
        filled_quantity TEXT NOT NULL,
        filled_price TEXT,
        submitted_at TEXT NOT NULL,
        filled_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_orders_submitted_at ON orders(submitted_at)",
    "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)",
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        asset_fqn TEXT NOT NULL,
        asset_json TEXT NOT NULL,
        action TEXT NOT NULL,
        reasoning TEXT NOT NULL,
        resulting_order_id TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_asset_fqn ON decisions(asset_fqn)",
    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_date TEXT NOT NULL UNIQUE,
        snapshot_at TEXT NOT NULL,
        initial_capital_amount TEXT NOT NULL,
        initial_capital_currency TEXT NOT NULL,
        cash_amount TEXT NOT NULL,
        cash_currency TEXT NOT NULL,
        valuations_json TEXT NOT NULL,
        total_market_value_amount TEXT NOT NULL,
        total_market_value_currency TEXT NOT NULL,
        total_value_amount TEXT NOT NULL,
        total_value_currency TEXT NOT NULL,
        total_cost_basis_amount TEXT NOT NULL,
        total_cost_basis_currency TEXT NOT NULL,
        total_unrealized_pnl_amount TEXT NOT NULL,
        total_unrealized_pnl_currency TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a sqlite3 connection and bootstrap the Phase 0 schema.

    `path` may be ``":memory:"``, a string filesystem path, or a ``Path``.
    The connection is configured with ``foreign_keys = ON`` and a row
    factory that yields ``sqlite3.Row`` (mapping access). Repository
    adapters use the row mapping directly without their own row factories.

    Returns the connection. The caller owns its lifecycle and should close
    it (or use ``with conn:`` patterns for transaction blocks).
    """
    conn = sqlite3.connect(str(path) if isinstance(path, Path) else path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    bootstrap_schema(conn)
    return conn


def bootstrap_schema(conn: sqlite3.Connection) -> None:
    """Run ``CREATE TABLE IF NOT EXISTS`` for every Phase 0 schema object.

    Idempotent — safe to call multiple times. Commits each DDL so a failed
    later statement leaves the database in a consistent state.
    """
    for stmt in _SCHEMA_STATEMENTS:
        conn.execute(stmt)
    conn.commit()
