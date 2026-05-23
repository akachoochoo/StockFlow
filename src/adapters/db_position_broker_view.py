"""DbPositionBrokerView — live Position source backed by the DB (C2 / 8-1.5).

KIS ``get_positions`` is **structurally absent** (``inquire-balance output1[]``
reports a per-symbol *aggregate* only — code + total quantity + average price —
with no split-slot structure; the broker does not model splits). The
orchestrator, however, reads full split-slot :class:`~src.domain.models.Position`
via ``self._broker.get_positions()`` (daily_orchestrator.py:257, 304, 922).

This adapter is a BrokerPort-shaped *view* the live composition injects in the
``self._broker`` slot (collaborator substitution — the KIS broker does not
attach to the orchestrator directly): it **restores** the full split-slot
Position from the DB (:class:`~src.ports.repositories.PositionRepoPort`, which
wraps the existing ``SqlitePositionRepo._build_position`` full-split
reconstruction — no new reconstruction logic), and serves cash from an injected
balance source (KIS real balance).

NF-2 — **commit 된 상태만 read**: the view reflects only committed DB state. It
never infers uncommitted / in-flight fills. In the live (PENDING-async) model a
fill becomes visible only *after* the next cron's settle phase commits it; the
orchestrator's FILLED in-flight branches (daily_orchestrator.py:493 buy / :704
sell) are effectively dead in live trading.

Aggregate invariant — the view's aggregate quantity (sum of FILLED slots, via
``Position.quantity``) equals the reconciliation ``get_holdings`` aggregate
quantity for the same asset code. This is a *same-aggregate* invariant, not a
*same-reconstruction* one: reconciliation compares aggregate quantities only and
does not rebuild split structure (reconciler.py).

Scope (8-1.5): only ``get_positions`` (DB) and ``get_balance`` (balance source)
are live. The write surface (``place_order`` / ``get_order_status`` /
``cancel_order``) and ``get_holdings`` raise ``NotImplementedError`` — wiring
the write delegation to the KIS broker is the live-composition concern (Stage
8-4), out of scope here. No runner calls this view yet (실주문 zero).
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from src.domain.models import (
        Balance,
        OrderRequest,
        OrderResult,
        Position,
    )
    from src.ports.broker import BalanceReaderPort
    from src.ports.repositories import PositionRepoPort


class DbPositionBrokerView:
    """BrokerPort-shaped Position source: positions from DB, cash from KIS."""

    def __init__(
        self,
        *,
        positions: PositionRepoPort,
        balance_source: BalanceReaderPort,
    ) -> None:
        self._positions = positions
        self._balance_source = balance_source

    def get_positions(self) -> list[Position]:
        """Return non-empty holdings (quantity > 0) restored from the DB.

        Wraps ``PositionRepoPort.list_all`` (which restores full split-slot
        structure via the existing ``_build_position``) and filters to held
        positions, matching the ``BrokerPort.get_positions`` contract
        (quantity > 0). NF-2: committed DB state only.
        """
        return [p for p in self._positions.list_all() if p.quantity > Decimal(0)]

    def get_balance(self) -> Balance:
        """Return current available cash via the injected balance source (KIS)."""
        return self._balance_source.get_balance()

    # ------------------------------------------------------------------
    # Write surface + aggregate holdings — not this view's responsibility.
    # Wiring write delegation to the KIS broker is the Stage 8-4 live
    # composition concern. These stubs keep the view BrokerPort-shaped while
    # making the deferred wiring explicit (no silent no-op).
    # ------------------------------------------------------------------
    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError(
            "DbPositionBrokerView serves get_positions / get_balance only; "
            "place_order is wired to the KIS broker at the live composition "
            "(Stage 8-4)"
        )

    def get_order_status(self, idempotency_key: str) -> OrderResult | None:
        raise NotImplementedError(
            "DbPositionBrokerView serves get_positions / get_balance only; "
            "get_order_status is wired to the KIS broker at the live "
            "composition (Stage 8-4)"
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        raise NotImplementedError(
            "DbPositionBrokerView serves get_positions / get_balance only; "
            "cancel_order is wired to the KIS broker at the live composition "
            "(Stage 8-4)"
        )

    def get_holdings(self) -> NoReturn:
        raise NotImplementedError(
            "DbPositionBrokerView serves get_positions / get_balance only; "
            "reconciliation reads get_holdings from the KIS broker directly"
        )
