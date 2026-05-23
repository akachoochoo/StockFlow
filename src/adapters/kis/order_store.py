"""KISOrderStore adapter — durable idempotency_key ↔ ODNO ↔ org_no lookup.

KIS supports **no client-side idempotency key** (ADR 0020 §4), so the durable
mapping ``idempotency_key ↔ broker_order_id ↔ broker_org_no`` lives in our own
order store. ``KISBroker.place_order`` consults it for dedup; ``cancel_order``
consults it to resolve the routing org_no for a given broker_order_id.

This adapter wraps :class:`~src.ports.repositories.OrderRepoPort` (a port,
injected via DI) and converts the persisted :class:`~src.domain.models.Order`
to the :class:`~src.domain.models.OrderResult` the
:class:`~src.adapters.kis.broker.KISOrderStore` Protocol returns. It lives in
the adapter ring (not use_cases) so that a use case never imports the
infrastructure repository directly (CLAUDE.md §1.1 dependency rule).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.models import OrderResult

if TYPE_CHECKING:
    from src.domain.models import Order
    from src.ports.repositories import OrderRepoPort


class SqliteKISOrderStore:
    """KISOrderStore Protocol over an injected :class:`OrderRepoPort`.

    Structurally satisfies ``src.adapters.kis.broker.KISOrderStore`` (both
    methods return ``OrderResult | None``); no explicit subclassing — duck
    typing per the Protocol.
    """

    def __init__(self, *, orders: OrderRepoPort) -> None:
        self._orders = orders

    def find_by_idempotency_key(self, key: str) -> OrderResult | None:
        order = self._orders.get_by_idempotency_key(key)
        if order is None:
            return None
        return self._to_result(order)

    def find_by_broker_order_id(
        self, broker_order_id: str
    ) -> OrderResult | None:
        order = self._orders.find_by_broker_order_id(broker_order_id)
        if order is None:
            return None
        return self._to_result(order)

    @staticmethod
    def _to_result(order: Order) -> OrderResult:
        return OrderResult(
            idempotency_key=order.idempotency_key,
            asset=order.asset,
            broker_order_id=order.broker_order_id,
            status=order.status,
            filled_quantity=order.filled_quantity,
            filled_price=order.filled_price,
            submitted_at=order.submitted_at,
            filled_at=order.filled_at,
            tax=order.tax,
            commission=order.commission,
            broker_org_no=order.broker_org_no,
        )
