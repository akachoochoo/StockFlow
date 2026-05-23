"""Migration 0019 — add nullable cost/routing columns to the ``orders`` table.

Phase 1.1 Stage 4.5 (ADR 0019 — DB Schema Migration). Adds three nullable
columns to ``orders`` so that write (Stage 5) and the cost cross-check never
consume columns that do not exist:

  - ``tax``           거래세  (provisional None; KIS basic responses carry no
                      per-order tax — ADR 0020 §4)
  - ``commission``    수수료  (provisional None; same reason as tax)
  - ``broker_org_no`` KRX_FWDG_ORD_ORGNO (populated at Stage 5 cancel routing)

Design (CLAUDE.md §1 "no Alembic", ADR 0012 D17 / ADR 0019):
  - **Backup first**: copy the DB file to ``<db>.bak.<UTC timestamp>`` before
    any schema change. If the backup fails, abort (no migration).
  - **Idempotent**: inspect ``PRAGMA table_info(orders)`` and only
    ``ALTER TABLE orders ADD COLUMN`` the columns that are missing. Re-running
    the migration is a no-op.
  - **Verify**: after migration, re-read ``PRAGMA table_info`` and fail if any
    of the three columns is still absent.
  - **Rollback**: ``--rollback <backup>`` restores the backup over the DB path
    (SQLite cannot DROP COLUMN portably, so we restore the file). The current
    DB is first copied to ``<db>.pre-rollback.<UTC timestamp>``.

All status is printed to stdout — no silent failure (CLAUDE.md §6.3).

Usage::

    python scripts/migrate_0019_add_order_cost_fields.py --db path/to/trading.db
    python scripts/migrate_0019_add_order_cost_fields.py --db path/to/trading.db \\
        --rollback path/to/trading.db.bak.20260522T120000Z

Exit codes:
  0 — success (migration applied/idempotent, or rollback restored)
  1 — failure (backup failed, verification failed, missing file, bad args)
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_NEW_COLUMNS: tuple[str, ...] = ("tax", "commission", "broker_org_no")


def _utc_stamp() -> str:
    """Filesystem-safe UTC timestamp, e.g. ``20260522T120000Z`` (CLAUDE.md §3.1)."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names on ``table`` via PRAGMA table_info."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    return {row[1] for row in rows}


def _backup(db_path: Path, *, label: str) -> Path:
    """Copy ``db_path`` to a timestamped sibling. Raise on failure (abort caller).

    Never overwrites an existing backup: if the timestamped name already exists
    (e.g. two runs within the same second), a numeric suffix is appended so a
    prior backup is preserved (real-money safety — CLAUDE.md §11).
    """
    stamp = _utc_stamp()
    backup_path = db_path.with_name(f"{db_path.name}.{label}.{stamp}")
    counter = 1
    while backup_path.exists():
        backup_path = db_path.with_name(f"{db_path.name}.{label}.{stamp}.{counter}")
        counter += 1
    shutil.copy2(db_path, backup_path)
    if not backup_path.exists():
        raise RuntimeError(f"backup not created at {backup_path}")
    print(f"[backup] {db_path} -> {backup_path}")
    return backup_path


def migrate(db_path: Path) -> int:
    """Apply the migration to ``db_path``. Returns a process exit code."""
    if not db_path.exists():
        print(f"[error] DB file not found: {db_path}", file=sys.stderr)
        return 1

    # 1. Backup first — abort the entire migration if the backup fails.
    try:
        _backup(db_path, label="bak")
    except OSError as exc:
        print(f"[error] backup failed, aborting migration: {exc}", file=sys.stderr)
        return 1

    # 2. Idempotent ALTER for missing columns only.
    conn = sqlite3.connect(str(db_path))
    try:
        before = _existing_columns(conn, "orders")
        print(f"[inspect] orders columns before: {sorted(before)}")
        added: list[str] = []
        for col in _NEW_COLUMNS:
            if col in before:
                print(f"[skip] column already present: {col}")
                continue
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col} TEXT")
            added.append(col)
            print(f"[add] ALTER TABLE orders ADD COLUMN {col} TEXT")
        conn.commit()

        # 3. Verify all three columns now exist.
        after = _existing_columns(conn, "orders")
        missing = [c for c in _NEW_COLUMNS if c not in after]
        if missing:
            print(
                f"[error] verification failed, missing columns: {missing}",
                file=sys.stderr,
            )
            return 1
        print(f"[verify] orders has all cost/routing columns: {list(_NEW_COLUMNS)}")
        print(f"[done] migration complete (added: {added or 'none — idempotent'})")
        return 0
    finally:
        conn.close()


def rollback(db_path: Path, backup_path: Path) -> int:
    """Restore ``backup_path`` over ``db_path``. Returns a process exit code.

    SQLite has no portable DROP COLUMN, so rollback is a file restore. The
    current DB is first backed up to ``<db>.pre-rollback.<UTC timestamp>`` so
    the rollback itself is reversible.
    """
    if not backup_path.exists():
        print(f"[error] backup file not found: {backup_path}", file=sys.stderr)
        return 1

    if db_path.exists():
        try:
            _backup(db_path, label="pre-rollback")
        except OSError as exc:
            print(
                f"[error] pre-rollback safety backup failed, aborting: {exc}",
                file=sys.stderr,
            )
            return 1
    else:
        print(f"[warn] current DB missing at {db_path}; restoring backup anyway")

    shutil.copy2(backup_path, db_path)
    print(f"[rollback] restored {backup_path} -> {db_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ADR 0019 — add nullable cost/routing columns to orders.",
    )
    parser.add_argument("--db", required=True, help="path to the SQLite DB file")
    parser.add_argument(
        "--rollback",
        metavar="BACKUP",
        help="restore the given backup file over --db (instead of migrating)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if args.rollback is not None:
        return rollback(db_path, Path(args.rollback))
    return migrate(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
