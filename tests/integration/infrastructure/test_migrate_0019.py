"""Tests for scripts/migrate_0019_add_order_cost_fields.py (ADR 0019).

Covers: old-schema DB migration round-trip, idempotent re-run, file-restore
rollback, and backup artifact creation. Uses tmp_path (real files because the
migration backs up / restores files on disk).
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

# Import the migration script module by path (scripts/ is not a package).
_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "migrate_0019_add_order_cost_fields.py"
)
_spec = importlib.util.spec_from_file_location("migrate_0019", _SCRIPT)
assert _spec is not None and _spec.loader is not None
migrate_0019 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate_0019)


# Old (pre-ADR-0019) orders schema — the 13-column Phase 0 layout WITHOUT
# tax / commission / broker_org_no.
_OLD_ORDERS_DDL = """
CREATE TABLE orders (
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
"""

_INSERT_ROW = (
    "INSERT INTO orders (idempotency_key, asset_fqn, asset_json, side, "
    "order_type, quantity, target_price, status, filled_quantity, "
    "submitted_at) VALUES ('k1', 'KRX:069500', '{}', 'BUY', 'LIMIT', '10', "
    "'35000', 'FILLED', '10', '2026-04-30T06:00:00+00:00')"
)


def _make_old_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_OLD_ORDERS_DDL)
        conn.execute(_INSERT_ROW)
        conn.commit()
    finally:
        conn.close()


def _orders_columns(path: Path) -> set[str]:
    conn = sqlite3.connect(str(path))
    try:
        return {
            row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }
    finally:
        conn.close()


def test_migration_0019_roundtrip_and_rollback(tmp_path):
    db_path = tmp_path / "trading.db"
    _make_old_db(db_path)
    assert "tax" not in _orders_columns(db_path)

    # Migrate: 3 columns added, existing row preserved (NULL cost fields).
    rc = migrate_0019.migrate(db_path)
    assert rc == 0
    cols = _orders_columns(db_path)
    assert {"tax", "commission", "broker_org_no"} <= cols
    # Capture the original (old-schema) backup made by the first migration
    # before any later run can create additional backups.
    original_backups = sorted(tmp_path.glob("trading.db.bak.*"))
    assert len(original_backups) == 1
    original_backup = original_backups[0]
    assert "tax" not in _orders_columns(original_backup)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE idempotency_key = 'k1'"
        ).fetchone()
        assert row is not None
        assert row["quantity"] == "10"  # existing data preserved
        assert row["tax"] is None  # new column NULL for old rows
        assert row["commission"] is None
        assert row["broker_org_no"] is None
    finally:
        conn.close()

    # Idempotent: re-running is harmless and still succeeds.
    rc2 = migrate_0019.migrate(db_path)
    assert rc2 == 0
    assert {"tax", "commission", "broker_org_no"} <= _orders_columns(db_path)

    # Rollback: restore the original backup (file restore -> 3 columns gone).
    rc3 = migrate_0019.rollback(db_path, original_backup)
    assert rc3 == 0
    assert "tax" not in _orders_columns(db_path)
    # Original row still present after rollback.
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_migration_backup_artifact_present(tmp_path):
    db_path = tmp_path / "trading.db"
    _make_old_db(db_path)
    rc = migrate_0019.migrate(db_path)
    assert rc == 0
    backups = list(tmp_path.glob("trading.db.bak.*"))
    assert len(backups) == 1
    # Backup is a valid SQLite DB with the OLD schema (no new columns).
    assert "tax" not in _orders_columns(backups[0])


def test_migration_missing_db_fails(tmp_path):
    missing = tmp_path / "does-not-exist.db"
    rc = migrate_0019.migrate(missing)
    assert rc == 1


def test_rollback_missing_backup_fails(tmp_path):
    db_path = tmp_path / "trading.db"
    _make_old_db(db_path)
    rc = migrate_0019.rollback(db_path, tmp_path / "no-such-backup")
    assert rc == 1
