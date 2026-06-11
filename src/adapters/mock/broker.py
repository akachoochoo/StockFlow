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
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.exceptions import BrokerConnectionError
from src.domain.fills import apply_buy_fill, apply_sell_fill
from src.domain.models import (
    Balance,
    BrokerHolding,
    GridHolding,
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
        # ADR 0022 §12 D20: 동일한 차단이 grid 주문에도 적용 (D18 XOR 가
        # split/grid 양립 불가 보장 → partial fill 정책 단일). KIS live 의
        # 실제 partial fill = PARTIALLY_FILLED 상태로 PendingSettler 가
        # 다음 cron 에서 terminal 확인 + reconciliation 흡수 (`reconciler.py:150-170`).
        if simulate_partial_fill_rate != 0.0:
            raise ValueError(
                "simulate_partial_fill_rate must be 0.0 in Phase 0.5 "
                "(partial fills are blocked, ADR 0002 §3.2.1 + ADR 0022 §12 D20). "
                f"Got {simulate_partial_fill_rate}."
            )
        if not 1 <= max_split_count <= 7:
            raise ValueError(
                f"max_split_count must be in [1, 7], got {max_split_count}"
            )

        self._balance: Balance = initial_balance
        self._positions: dict[str, Position] = {}
        # ADR 0022 §12 D19 — DGT grid holdings (slot 우회). split Position 과
        # 분리; 같은 asset 에 동시 holding 금지 (apply 단계 가드).
        self._grid_holdings: dict[str, GridHolding] = {}
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
        # ADR 0022 §12 D19: combines split Position 과 grid GridHolding —
        # 두 dict 은 mutual exclusion (같은 asset_fqn 에 동시 존재 불가, apply
        # 단계 가드).
        split_holdings = [
            BrokerHolding(
                asset_code=p.asset.code,
                quantity=p.quantity,
                avg_price=p.avg_price,
            )
            for p in self._positions.values()
            if p.quantity > 0
        ]
        grid_holdings = [
            BrokerHolding(
                asset_code=h.asset.code,
                quantity=h.quantity,
                avg_price=h.avg_price,
            )
            for h in self._grid_holdings.values()
            if h.quantity > 0
        ]
        return split_holdings + grid_holdings

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
        # ADR 0022 §12 D19 — grid 분기: grid_level_idx 가 set 이면 slot 우회 경로.
        # OrderRequest XOR (D18) 가 slot/grid 양립 불가 보장 → 안전하게 분기.
        if request.grid_level_idx is not None:
            if request.side is OrderSide.BUY:
                cost = result.filled_quantity * result.filled_price
                self._debit_cash(cost)
                self._apply_grid_buy_fill(
                    request.asset,
                    result.filled_quantity,
                    result.filled_price,
                    result.filled_at,
                )
            else:  # SELL
                proceeds = result.filled_quantity * result.filled_price
                self._credit_cash(proceeds)
                self._apply_grid_sell_fill(
                    request.asset,
                    result.filled_quantity,
                )
            return
        # Split path (slot-based, 기존 경로 0변경).
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
    # ADR 0022 §12 D19 — Grid fill paths (slot 우회)
    # ------------------------------------------------------------------
    def _apply_grid_buy_fill(
        self,
        asset: Asset,
        filled_qty: Decimal,
        filled_price: Decimal,
        now: datetime,
    ) -> None:
        """Apply a fully-filled grid BUY into the grid-holdings ledger.

        slot 미사용. weighted avg_price = (기존 cost_basis + new cost) / new qty.
        같은 asset 에 split Position 이 이미 있으면 거부 (mutual exclusion).
        """
        if asset.fqn in self._positions and self._positions[asset.fqn].quantity > 0:
            raise BrokerConnectionError(
                f"grid BUY on {asset.fqn} but split Position with qty>0 exists "
                "— mutual exclusion (ADR 0022 §12 D19)"
            )
        existing = self._grid_holdings.get(asset.fqn)
        if existing is None:
            self._grid_holdings[asset.fqn] = GridHolding(
                asset=asset,
                quantity=filled_qty,
                avg_price=filled_price,
                cost_basis=filled_qty * filled_price,
                last_buy_at=now,
            )
            return
        new_qty = existing.quantity + filled_qty
        new_cost = existing.cost_basis + (filled_qty * filled_price)
        new_avg = new_cost / new_qty
        self._grid_holdings[asset.fqn] = replace(
            existing,
            quantity=new_qty,
            avg_price=new_avg,
            cost_basis=new_cost,
            last_buy_at=now,
        )

    def _apply_grid_sell_fill(
        self,
        asset: Asset,
        filled_qty: Decimal,
    ) -> None:
        """Apply a fully-filled grid SELL — decrement quantity, keep avg_price.

        부분 매도 시: avg_price 유지 (FIFO 가정 아님 — average cost),
        cost_basis = quantity * avg_price 비례 감소. quantity 가 0 이 되면
        holding 삭제 (mutual exclusion 다시 열림).
        같은 asset 에 split Position 이 있으면 거부.
        """
        if asset.fqn in self._positions and self._positions[asset.fqn].quantity > 0:
            raise BrokerConnectionError(
                f"grid SELL on {asset.fqn} but split Position with qty>0 exists "
                "— mutual exclusion (ADR 0022 §12 D19)"
            )
        existing = self._grid_holdings.get(asset.fqn)
        if existing is None or existing.quantity < filled_qty:
            existing_qty = existing.quantity if existing else Decimal(0)
            raise BrokerConnectionError(
                f"grid SELL {filled_qty} on {asset.fqn} exceeds holding qty "
                f"{existing_qty}"
            )
        new_qty = existing.quantity - filled_qty
        if new_qty == 0:
            del self._grid_holdings[asset.fqn]
            return
        # average cost: avg_price 유지, cost_basis 는 새 qty * 같은 avg.
        new_cost = new_qty * existing.avg_price
        self._grid_holdings[asset.fqn] = replace(
            existing,
            quantity=new_qty,
            cost_basis=new_cost,
        )

    def get_grid_holding(self, asset_fqn: str) -> GridHolding | None:
        """Return the current grid holding for ``asset_fqn`` (or None).

        ADR 0022 §12 D19. dry-run/paper composition 에서 GridRunner 가 다음
        결정 평가 전 보유량을 조회.
        """
        return self._grid_holdings.get(asset_fqn)

    def set_grid_holding(self, holding: GridHolding) -> None:
        """Inject a grid holding (state restoration on cron resume).

        ADR §10.3 / §10.7 paper trading composition 정합 — set_position 와
        대칭. 기존 split Position 있으면 거부 (mutual exclusion).
        """
        if (
            holding.asset.fqn in self._positions
            and self._positions[holding.asset.fqn].quantity > 0
        ):
            raise BrokerConnectionError(
                f"set_grid_holding({holding.asset.fqn}) but split Position with "
                "qty>0 exists — mutual exclusion (ADR 0022 §12 D19)"
            )
        self._grid_holdings[holding.asset.fqn] = holding

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
