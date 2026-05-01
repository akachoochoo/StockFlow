"""SQLite implementation of OrderRepoPort.

Per ADR §8.1 / §8.3, persists Order rows with denormalised asset_json.
Orders are immutable in Phase 0 — duplicate inserts on the same
idempotency_key surface as sqlite3.IntegrityError (caller responsibility).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.models import (
    Asset,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)

if TYPE_CHECKING:
    import sqlite3


class SqliteOrderRepo:
    """OrderRepoPort over a sqlite3.Connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, order: Order) -> None:
        self._conn.execute(
            "INSERT INTO orders (idempotency_key, asset_fqn, asset_json, "
            "side, order_type, quantity, target_price, status, "
            "broker_order_id, filled_quantity, filled_price, submitted_at, "
            "filled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.idempotency_key,
                order.asset.fqn,
                order.asset.model_dump_json(),
                order.side.value,
                order.order_type.value,
                str(order.quantity),
                str(order.target_price),
                order.status.value,
                order.broker_order_id,
                str(order.filled_quantity),
                str(order.filled_price) if order.filled_price is not None else None,
                order.submitted_at.isoformat(),
                order.filled_at.isoformat() if order.filled_at is not None else None,
            ),
        )

    def get_by_idempotency_key(self, key: str) -> Order | None:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return self._build_order(row)

    def list_pending(self) -> list[Order]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE status IN (?, ?) ORDER BY submitted_at",
            (OrderStatus.PENDING.value, OrderStatus.PARTIALLY_FILLED.value),
        ).fetchall()
        return [self._build_order(r) for r in rows]

    def list_by_date(self, d: date) -> list[Order]:
        # submitted_at is ISO 8601 UTC; the date prefix matches calendar date.
        prefix = d.isoformat()
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE substr(submitted_at, 1, 10) = ? "
            "ORDER BY submitted_at",
            (prefix,),
        ).fetchall()
        return [self._build_order(r) for r in rows]

    @staticmethod
    def _build_order(row: sqlite3.Row) -> Order:
        return Order(
            idempotency_key=row["idempotency_key"],
            asset=Asset.model_validate_json(row["asset_json"]),
            side=OrderSide(row["side"]),
            order_type=OrderType(row["order_type"]),
            quantity=Decimal(row["quantity"]),
            target_price=Decimal(row["target_price"]),
            status=OrderStatus(row["status"]),
            broker_order_id=row["broker_order_id"],
            filled_quantity=Decimal(row["filled_quantity"]),
            filled_price=(
                Decimal(row["filled_price"])
                if row["filled_price"] is not None
                else None
            ),
            submitted_at=datetime.fromisoformat(row["submitted_at"]),
            filled_at=(
                datetime.fromisoformat(row["filled_at"])
                if row["filled_at"] is not None
                else None
            ),
        )
