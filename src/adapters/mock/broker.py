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
from src.domain.fills import apply_buy_fill, apply_sell_fill
from src.domain.models import (
    Balance,
    BrokerHolding,
    Money,
    Order,
    OrderResult,
    OrderSide,
    OrderStatus,
    SplitSlot,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from src.domain.models import Asset, OrderRequest, Position, SupportSlot


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
        max_split_count: int = 7,
        slot_model: type[SplitSlot] | type[SupportSlot] = SplitSlot,
    ) -> None:
        for name, rate in (
            ("simulate_timeout_rate", simulate_timeout_rate),
            ("simulate_rejection_rate", simulate_rejection_rate),
        ):
            if not (0.0 <= rate <= 1.0):
                raise ValueError(f"{name} must be in [0.0, 1.0], got {rate}")
        # ADR 0002 §3.2.1: Phase 0.5 blocks partial fills end-to-end.
        # Parameter kept in the signature so the boundary is loud — Phase 1
        # KIS adapter will reintroduce partial-fill handling with a redesigned
        # slot-aware policy.
        if simulate_partial_fill_rate != 0.0:
            raise ValueError(
                "simulate_partial_fill_rate must be 0.0 in Phase 0.5 "
                "(partial fills are blocked, ADR 0002 §3.2.1). Got "
                f"{simulate_partial_fill_rate}."
            )
        if not 1 <= max_split_count <= 7:
            raise ValueError(
                f"max_split_count must be in [1, 7], got {max_split_count}"
            )

        self._balance: Balance = initial_balance
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._next_broker_order_id: int = 1
        self._clock = clock
        self._rng: random.Random = rng if rng is not None else random.Random()
        self._timeout_rate = simulate_timeout_rate
        self._rejection_rate = simulate_rejection_rate
        self._max_split_count = max_split_count
        # ADR 0004 §5.6: which slot model to use for newly-created Positions.
        # Existing Positions preserve their slot type via ``list(existing.slots)``.
        self._slot_model: type[SplitSlot] | type[SupportSlot] = slot_model

    # ------------------------------------------------------------------
    # BrokerPort
    # ------------------------------------------------------------------
    def get_balance(self) -> Balance:
        return self._balance

    def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity > 0]

    def get_holdings(self) -> list[BrokerHolding]:
        # Mirror of get_positions but as the aggregated BrokerHolding view
        # (code + quantity + avg_price, no split-slot structure) used for
        # reconciliation (CLAUDE.md §11.2). Only non-empty holdings (qty > 0).
        return [
            BrokerHolding(
                asset_code=p.asset.code,
                quantity=p.quantity,
                avg_price=p.avg_price,
            )
            for p in self._positions.values()
            if p.quantity > 0
        ]

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

        # 3. Default: FILLED. Partial fills are blocked in Phase 0.5
        # (constructor enforces simulate_partial_fill_rate == 0.0,
        # ADR 0002 §3.2.1).
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
        # Phase 0.5: only FILLED reaches here (partial fills are blocked
        # at the constructor; ADR 0002 §3.2.1). The assertion guards the
        # invariant — if it fires, the caller broke the contract.
        assert result.status is OrderStatus.FILLED, (
            f"_update_state_on_fill expected FILLED, got {result.status}"
        )
        assert result.filled_price is not None
        assert result.filled_at is not None
        if request.side is OrderSide.BUY:
            cost = result.filled_quantity * result.filled_price
            self._debit_cash(cost)
            self._apply_buy_fill(
                request.asset,
                result.filled_quantity,
                result.filled_price,
                result.filled_at,
                idempotency_key=request.idempotency_key,
                target_slot_number=request.slot_number,
            )
        else:  # SELL
            assert request.slot_number is not None
            proceeds = result.filled_quantity * result.filled_price
            self._credit_cash(proceeds)
            self._apply_sell_fill(
                request.asset,
                slot_number=request.slot_number,
                filled_qty=result.filled_quantity,
                filled_price=result.filled_price,
                now=result.filled_at,
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

    def _credit_cash(self, amount: Decimal) -> None:
        new_amount = self._balance.cash.amount + amount
        self._balance = Balance(
            cash=Money(amount=new_amount, currency=self._balance.cash.currency)
        )

    def _apply_buy_fill(
        self,
        asset: Asset,
        filled_qty: Decimal,
        filled_price: Decimal,
        now: datetime,
        *,
        idempotency_key: str,
        target_slot_number: int | None = None,
    ) -> None:
        """Apply a fully-filled BUY into a target EMPTY slot.

        Delegates the slot transition to the shared pure domain function
        :func:`src.domain.fills.apply_buy_fill` (Phase 1.1 Stage 8-2 / C3
        carve-out) so the live ``PendingSettler`` settle path and this
        synchronous path can never drift. Behaviour is byte-identical to the
        pre-carve-out implementation.
        """
        self._positions[asset.fqn] = apply_buy_fill(
            existing=self._positions.get(asset.fqn),
            asset=asset,
            filled_qty=filled_qty,
            filled_price=filled_price,
            now=now,
            idempotency_key=idempotency_key,
            max_split_count=self._max_split_count,
            slot_model=self._slot_model,
            target_slot_number=target_slot_number,
        )

    def _apply_sell_fill(
        self,
        asset: Asset,
        *,
        slot_number: int,
        filled_qty: Decimal,
        filled_price: Decimal,
        now: datetime,
    ) -> None:
        """Close a single FILLED slot by selling exactly its entry quantity.

        Delegates to the shared pure domain function
        :func:`src.domain.fills.apply_sell_fill` (C3 carve-out, byte-identical
        to the pre-carve-out implementation).
        """
        self._positions[asset.fqn] = apply_sell_fill(
            existing=self._positions.get(asset.fqn),
            asset=asset,
            slot_number=slot_number,
            filled_qty=filled_qty,
            filled_price=filled_price,
            now=now,
        )

    # ------------------------------------------------------------------
    # State injection (ADR §10.3 / §10.7 — paper trading composition)
    # ------------------------------------------------------------------
    def set_position(self, position: Position) -> None:
        """Inject a Position into broker state.

        Used by paper trading composition root to restore positions from
        the SqlitePositionRepo before the day's run. After this call the
        broker treats the position as if it had placed the original
        buy orders itself.
        """
        self._positions[position.asset.fqn] = position

    # ------------------------------------------------------------------
    # Test inspection helpers
    # ------------------------------------------------------------------
    def all_orders(self) -> list[Order]:
        """Return a copy of all recorded orders for test inspection."""
        return list(self._orders.values())
