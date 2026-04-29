"""MockBroker — in-memory broker for backtesting and Phase 0 paper trading.

Design highlights:

- Outcomes are decided by three independent probability rates (timeout /
  rejection / partial fill); when none fire the order fills in full.
- All randomness goes through the injected ``random.Random`` so tests with
  the same seed produce identical sequences.
- ``clock`` is a callable returning UTC datetime — same time-injection
  pattern as MarketDataPort (CLAUDE.md §3.2).
- Orders are stored by ``idempotency_key``. Repeating ``place_order`` with
  the same key returns the prior result without re-executing
  (CLAUDE.md §4.1).
- Position state and cash balance are mutated automatically on FILLED /
  PARTIALLY_FILLED orders. ``split_level`` increments only on FILLED
  (CLAUDE.md §4.4).
- Timeout simulation: ``BrokerConnectionError`` is raised but the order is
  still recorded as FILLED internally so ``get_order_status`` can locate it
  (CLAUDE.md §4.3).
"""
from __future__ import annotations

import random
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.exceptions import BrokerConnectionError
from src.domain.models import (
    Balance,
    Money,
    Order,
    OrderResult,
    OrderStatus,
    Position,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from src.domain.models import Asset, OrderRequest


class MockBroker:
    """In-memory broker implementing BrokerPort for Phase 0."""

    def __init__(
        self,
        *,
        initial_balance: Balance,
        clock: Callable[[], datetime],
        rng: random.Random | None = None,
        simulate_timeout_rate: float = 0.0,
        simulate_rejection_rate: float = 0.0,
        simulate_partial_fill_rate: float = 0.0,
    ) -> None:
        for name, rate in (
            ("simulate_timeout_rate", simulate_timeout_rate),
            ("simulate_rejection_rate", simulate_rejection_rate),
            ("simulate_partial_fill_rate", simulate_partial_fill_rate),
        ):
            if not (0.0 <= rate <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0], got {rate}")

        self._balance: Balance = initial_balance
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._next_broker_order_id: int = 1
        self._clock = clock
        self._rng: random.Random = rng if rng is not None else random.Random()
        self._timeout_rate = simulate_timeout_rate
        self._rejection_rate = simulate_rejection_rate
        self._partial_fill_rate = simulate_partial_fill_rate

    # ------------------------------------------------------------------
    # BrokerPort
    # ------------------------------------------------------------------
    def get_balance(self) -> Balance:
        return self._balance

    def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity > 0]

    def place_order(self, request: OrderRequest) -> OrderResult:
        # Idempotency: same key returns the prior result without re-execution
        existing = self._orders.get(request.idempotency_key)
        if existing is not None:
            return self._order_to_result(existing)

        now = self._clock()
        broker_order_id = f"mock-{self._next_broker_order_id}"
        self._next_broker_order_id += 1

        # 1. Timeout: order is recorded as FILLED but caller sees connection error.
        if self._rng.random() < self._timeout_rate:
            result = self._build_filled_result(request, broker_order_id, now)
            self._record_order(request, result)
            self._update_state_on_fill(request, result)
            raise BrokerConnectionError(
                f"timeout simulating broker delay; order {broker_order_id} was placed"
            )

        # 2. Rejection: no state change beyond the rejection record.
        if self._rng.random() < self._rejection_rate:
            result = OrderResult(
                idempotency_key=request.idempotency_key,
                asset=request.asset,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=now,
                filled_at=None,
            )
            self._record_order(request, result)
            return result

        # 3. Partial fill: only when achievable; else fall through to FILLED.
        if self._rng.random() < self._partial_fill_rate:
            partial_qty = self._compute_partial_quantity(request)
            if 0 < partial_qty < request.quantity:
                result = OrderResult(
                    idempotency_key=request.idempotency_key,
                    asset=request.asset,
                    broker_order_id=broker_order_id,
                    status=OrderStatus.PARTIALLY_FILLED,
                    filled_quantity=partial_qty,
                    filled_price=request.target_price,
                    submitted_at=now,
                    filled_at=now,
                )
                self._record_order(request, result)
                self._update_state_on_fill(request, result)
                return result

        # 4. Default: FILLED.
        result = self._build_filled_result(request, broker_order_id, now)
        self._record_order(request, result)
        self._update_state_on_fill(request, result)
        return result

    def get_order_status(self, idempotency_key: str) -> OrderResult | None:
        order = self._orders.get(idempotency_key)
        if order is None:
            return None
        return self._order_to_result(order)

    def cancel_order(self, broker_order_id: str) -> bool:
        # Phase 0: orders are immediate; nothing pending to cancel.
        # Returning False is the truthful answer rather than a fake-success.
        del broker_order_id  # used to silence unused-arg lint
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_filled_result(
        self,
        request: OrderRequest,
        broker_order_id: str,
        now: datetime,
    ) -> OrderResult:
        return OrderResult(
            idempotency_key=request.idempotency_key,
            asset=request.asset,
            broker_order_id=broker_order_id,
            status=OrderStatus.FILLED,
            filled_quantity=request.quantity,
            filled_price=request.target_price,
            submitted_at=now,
            filled_at=now,
        )

    def _compute_partial_quantity(self, request: OrderRequest) -> Decimal:
        """Return a partial fill quantity (lot-aligned, < request.quantity).

        Phase 0 simulates partials at exactly half the requested quantity,
        rounded down to the asset's lot_size. Returns 0 if the result is not
        smaller than the requested quantity (i.e. partial impossible).
        """
        lot = request.asset.lot_size
        half = (request.quantity / Decimal(2) // lot) * lot
        if half <= 0 or half >= request.quantity:
            return Decimal(0)
        return half

    def _record_order(self, request: OrderRequest, result: OrderResult) -> None:
        self._orders[request.idempotency_key] = Order.from_request_result(
            request, result
        )

    def _order_to_result(self, order: Order) -> OrderResult:
        return OrderResult(
            idempotency_key=order.idempotency_key,
            asset=order.asset,
            broker_order_id=order.broker_order_id,
            status=order.status,
            filled_quantity=order.filled_quantity,
            filled_price=order.filled_price,
            submitted_at=order.submitted_at,
            filled_at=order.filled_at,
        )

    def _update_state_on_fill(
        self, request: OrderRequest, result: OrderResult
    ) -> None:
        # Caller responsibility: only invoke for FILLED / PARTIALLY_FILLED
        # results (filled_quantity > 0). Order invariants then guarantee
        # filled_price and filled_at are non-None.
        assert result.filled_price is not None
        assert result.filled_at is not None
        cost = result.filled_quantity * result.filled_price
        self._debit_cash(cost)
        self._update_position(
            request.asset,
            result.filled_quantity,
            result.filled_price,
            result.filled_at,
            full_fill=(result.status == OrderStatus.FILLED),
        )

    def _debit_cash(self, amount: Decimal) -> None:
        new_amount = self._balance.cash.amount - amount
        if new_amount < 0:
            raise BrokerConnectionError(
                f"insufficient cash to debit {amount} from "
                f"{self._balance.cash.amount}"
            )
        self._balance = Balance(
            cash=Money(amount=new_amount, currency=self._balance.cash.currency)
        )

    def _update_position(
        self,
        asset: Asset,
        filled_qty: Decimal,
        filled_price: Decimal,
        now: datetime,
        *,
        full_fill: bool,
    ) -> None:
        existing = self._positions.get(asset.fqn)
        if existing is None or existing.quantity == 0:
            new_qty = filled_qty
            new_avg = filled_price
            new_split = 1 if full_fill else 0
        else:
            new_qty = existing.quantity + filled_qty
            total_cost = (
                existing.quantity * existing.avg_price + filled_qty * filled_price
            )
            new_avg = total_cost / new_qty
            new_split = (
                existing.split_level + 1 if full_fill else existing.split_level
            )

        self._positions[asset.fqn] = Position(
            asset=asset,
            quantity=new_qty,
            avg_price=new_avg,
            split_level=new_split,
            last_buy_at=now,
        )

    # ------------------------------------------------------------------
    # Test inspection helpers
    # ------------------------------------------------------------------
    def all_orders(self) -> list[Order]:
        """Return a copy of all recorded orders for test inspection."""
        return list(self._orders.values())
