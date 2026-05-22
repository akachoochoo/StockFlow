"""Tests for src.infrastructure.db — connection factory + schema bootstrap."""
from __future__ import annotations

import sqlite3

from src.infrastructure.db import bootstrap_schema, connect

_EXPECTED_TABLES = (
    "positions",
    "split_slots",
    "orders",
    "decisions",
    "portfolio_snapshots",
)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


class TestConnect:
    def test_in_memory_creates_all_tables(self):
        conn = connect(":memory:")
        try:
            tables = _table_names(conn)
            for name in _EXPECTED_TABLES:
                assert name in tables
        finally:
            conn.close()

    def test_file_path_creates_all_tables(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = connect(db_path)
        try:
            tables = _table_names(conn)
            for name in _EXPECTED_TABLES:
                assert name in tables
        finally:
            conn.close()
        assert db_path.exists()

    def test_string_path_accepted(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = connect(db_path)
        try:
            assert _table_names(conn) >= set(_EXPECTED_TABLES)
        finally:
            conn.close()

    def test_foreign_keys_enabled(self):
        conn = connect(":memory:")
        try:
            row = conn.execute("PRAGMA foreign_keys").fetchone()
            assert row[0] == 1
        finally:
            conn.close()

    def test_row_factory_returns_mapping(self):
        conn = connect(":memory:")
        try:
            conn.execute(
                "INSERT INTO orders (idempotency_key, asset_fqn, asset_json, "
                "side, order_type, quantity, target_price, status, "
                "filled_quantity, submitted_at) VALUES "
                "('k1', 'KRX:069500', '{}', 'BUY', 'LIMIT', '10', '35000', "
                "'FILLED', '10', '2026-04-30T06:00:00+00:00')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM orders WHERE idempotency_key = 'k1'"
            ).fetchone()
            # sqlite3.Row supports both index and key access
            assert row["idempotency_key"] == "k1"
            assert row["asset_fqn"] == "KRX:069500"
        finally:
            conn.close()


class TestOrdersCostFieldsSchema:
    """ADR 0019 — fresh DB orders table carries cost/routing columns."""

    def test_orders_schema_has_tax_commission_broker_org_no(self):
        conn = connect(":memory:")
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(orders)").fetchall()
            }
            assert "tax" in cols
            assert "commission" in cols
            assert "broker_org_no" in cols
        finally:
            conn.close()


class TestBootstrapSchema:
    def test_idempotent(self):
        conn = sqlite3.connect(":memory:")
        try:
            bootstrap_schema(conn)
            tables_first = _table_names(conn)
            # Calling again should not raise and tables stay the same.
            bootstrap_schema(conn)
            tables_second = _table_names(conn)
            assert tables_first == tables_second
            for name in _EXPECTED_TABLES:
                assert name in tables_first
        finally:
            conn.close()

    def test_split_slots_cascade_delete(self):
        # Verify FK cascade works: deleting a position removes its split_slots.
        conn = connect(":memory:")
        try:
            cursor = conn.execute(
                "INSERT INTO positions (asset_fqn, asset_json, quantity, "
                "avg_price, split_level, last_buy_at, updated_at) VALUES "
                "('KRX:069500', '{}', '10', '35000', 1, "
                "'2026-04-30T06:00:00+00:00', '2026-04-30T06:00:00+00:00')"
            )
            position_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO split_slots (position_id, slot_number, state, "
                "entry_date, entry_quantity, entry_price, "
                "entry_idempotency_key) VALUES "
                "(?, 1, 'FILLED', '2026-04-30', '10', '35000', 'k1')",
                (position_id,),
            )
            conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) FROM split_slots"
            ).fetchone()[0] == 1
            conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
            conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) FROM split_slots"
            ).fetchone()[0] == 0
        finally:
            conn.close()

    def test_orders_idempotency_key_unique(self):
        conn = connect(":memory:")
        try:
            conn.execute(
                "INSERT INTO orders (idempotency_key, asset_fqn, asset_json, "
                "side, order_type, quantity, target_price, status, "
                "filled_quantity, submitted_at) VALUES "
                "('dup', 'KRX:069500', '{}', 'BUY', 'LIMIT', '10', '35000', "
                "'FILLED', '10', '2026-04-30T06:00:00+00:00')"
            )
            conn.commit()
            try:
                conn.execute(
                    "INSERT INTO orders (idempotency_key, asset_fqn, "
                    "asset_json, side, order_type, quantity, target_price, "
                    "status, filled_quantity, submitted_at) VALUES "
                    "('dup', 'KRX:069500', '{}', 'BUY', 'LIMIT', '10', "
                    "'35000', 'FILLED', '10', '2026-04-30T06:00:00+00:00')"
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass  # expected
            else:
                raise AssertionError("Duplicate idempotency_key should raise")
        finally:
            conn.close()

    def test_portfolio_snapshots_date_unique(self):
        conn = connect(":memory:")
        try:
            insert = (
                "INSERT INTO portfolio_snapshots ("
                "snapshot_date, snapshot_at, "
                "initial_capital_amount, initial_capital_currency, "
                "cash_amount, cash_currency, valuations_json, "
                "total_market_value_amount, total_market_value_currency, "
                "total_value_amount, total_value_currency, "
                "total_cost_basis_amount, total_cost_basis_currency, "
                "total_unrealized_pnl_amount, total_unrealized_pnl_currency, "
                "created_at) VALUES ("
                "'2026-04-30', '2026-04-30T06:00:00+00:00', "
                "'4000000', 'KRW', '4000000', 'KRW', '[]', "
                "'0', 'KRW', '4000000', 'KRW', '0', 'KRW', '0', 'KRW', "
                "'2026-04-30T06:00:00+00:00')"
            )
            conn.execute(insert)
            conn.commit()
            try:
                conn.execute(insert)
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Duplicate snapshot_date should raise")
        finally:
            conn.close()
