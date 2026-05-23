"""Broker port — order execution and account state.

CLAUDE.md §1.3: domain depends only on this Protocol; concrete brokers
(KIS, MockBroker, ...) live in src/adapters/.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.domain.models import (
        Balance,
        BrokerHolding,
        OrderRequest,
        OrderResult,
        Position,
    )


class BalanceReaderPort(Protocol):
    """Read-only cash balance accessor (Interface Segregation).

    The narrow surface a Position-source view depends on — it only ever reads
    the broker's available cash, never positions or orders. A read-subset
    adapter (e.g. ``KISBroker``) satisfies this without pretending to be a
    full ``BrokerPort``. Any full ``BrokerPort`` implementation also satisfies
    it structurally.
    """

    def get_balance(self) -> Balance:
        """Return current available cash balance."""
        ...


class HoldingsReaderPort(Protocol):
    """Read-only broker holdings accessor (Interface Segregation).

    The narrow surface reconciliation depends on — it only ever reads the
    broker's aggregated holdings (CLAUDE.md §11.2), never orders. A partial
    read-subset adapter (e.g. ``KISBroker`` before the Stage 5 write surface
    exists) satisfies this without pretending to be a full ``BrokerPort``.
    Any full ``BrokerPort`` implementation also satisfies it structurally.
    """

    def get_holdings(self) -> list[BrokerHolding]:
        """Return the broker's per-asset aggregated holdings (quantity > 0)."""
        ...


class OrderStatusReaderPort(Protocol):
    """Read-only order-status accessor (Interface Segregation).

    The narrow surface ``PendingSettler`` depends on (Phase 1.1 Stage 8-2): it
    only ever looks up an order's current status via ``get_order_status``, never
    places or cancels orders. A write-capable adapter (e.g. ``KISBroker`` with
    its order store) satisfies this structurally; any full ``BrokerPort`` does
    too.
    """

    def get_order_status(self, idempotency_key: str) -> OrderResult | None:
        """Look up an order by idempotency_key. None if the broker has no order
        for that key (CLAUDE.md §4.3)."""
        ...


class OrderExecutorPort(OrderStatusReaderPort, Protocol):
    """Order write surface (Interface Segregation, Phase 1.1 Stage 8-4).

    The narrow surface ``DbPositionBrokerView`` delegates to for live order
    execution — place / status / cancel, no balance or positions. A
    write-capable ``KISBroker`` (with its order store) satisfies it; the view
    serves positions / balance itself and routes only these writes to the KIS
    broker (collaborator composition). Extends :class:`OrderStatusReaderPort`
    so ``get_order_status`` is part of the same delegated surface.
    """

    def place_order(self, request: OrderRequest) -> OrderResult:
        """Submit an order. Idempotent on ``request.idempotency_key``."""
        ...

    def cancel_order(self, broker_order_id: str) -> bool:
        """Request cancellation. Returns True if accepted."""
        ...


class BrokerPort(Protocol):
    """Order execution and account state.

    Implementations MUST:
    - Be idempotent on `place_order`: a second call with the same
      idempotency_key must NOT create a duplicate order. The original result
      should be returned (or re-fetched). See CLAUDE.md §4.1.
    - Be synchronous. CLAUDE.md §10.1 disallows asyncio in Phase 0.

    Method-level errors are raised via the exception hierarchy in
    src.domain.exceptions:
    - BrokerConnectionError: transport-level failure (e.g. network, timeout)
    - BrokerOrderError: broker rejected the order (validation, balance, etc.)
    """

    def get_balance(self) -> Balance:
        """Return current available cash balance."""
        ...

    def get_positions(self) -> list[Position]:
        """Return non-empty holdings (quantity > 0)."""
        ...

    def get_holdings(self) -> list[BrokerHolding]:
        """Return the broker's per-asset aggregated holdings (quantity > 0).

        Distinct from :meth:`get_positions`: this returns the broker's
        *aggregated* per-symbol view (:class:`~src.domain.models.BrokerHolding`)
        — code + total quantity + average price, with **no split-slot
        structure** (the broker does not model splits). Used by reconciliation
        (CLAUDE.md §11.2) to compare DB Positions against the broker's reported
        holdings; mismatches halt all trading and wait for human intervention.
        """
        ...

    def place_order(self, request: OrderRequest) -> OrderResult:
        """Submit an order. Idempotent on `request.idempotency_key`."""
        ...

    def get_order_status(self, idempotency_key: str) -> OrderResult | None:
        """Look up an order by idempotency_key.

        Returns None if no order with that key exists at the broker. Used after
        a place_order timeout to determine whether the order actually went
        through (CLAUDE.md §4.3).
        """
        ...

    def cancel_order(self, broker_order_id: str) -> bool:
        """Request cancellation. Returns True if accepted (not necessarily
        completed)."""
        ...
