"""PendingSettler — Phase 1.1 Stage 8-2 asynchronous settlement use-case.

KIS confirms fills asynchronously: ``KISBroker.place_order`` returns
``OrderStatus.PENDING`` (the order is *accepted*; the fill is confirmed later).
The ``DailyOrchestrator`` assumes synchronous ``FILLED`` (it only increments
``split_level`` on FILLED), so a live PENDING order is recorded as a
``BROKER_TIMEOUT`` skip and persisted PENDING. ``PendingSettler`` is the
*settle phase* that runs at the start of each daily cron, **before** the
decision phase: it walks ``list_pending()``, asks the broker for each order's
current status, and applies confirmed fills.

Adopted design (ADR 0012 Stage 8 §3 Option B + §8 사람결정, 2026-05-23):

  - **C1 매수 gap = post-settle 비교**: a confirmed FILLED buy applies the
    shared :func:`~src.domain.fills.apply_buy_fill` (``split_level++``) and
    writes a *new corrected* Decision (buy_action filled) — the raw pre-settle
    ``BROKER_TIMEOUT`` skip stays as audit and intentionally diverges from the
    backtest. G2(d) equivalence is evaluated on the corrected (post-settle)
    Decision.
  - **NF-1 매도 = (가) settle-only, orchestrator unchanged**: a confirmed
    FILLED sell applies the shared :func:`~src.domain.fills.apply_sell_fill`
    (slot reversal, ``split_level--``) and reconstructs a SellActionRecord +
    corrected Decision. A live PENDING sell short-circuits that decision day's
    buy (orchestrator behaviour); recovery is the next cron's normal decision
    (NOT auto catch-up — conservative & safe). A visible WARNING event is
    emitted so the one-day buy skip never passes silently.
  - **slot_number recovery = strict idempotency_key parse** (§8(4)): the
    persisted Order carries no ``slot_number`` (only the transient
    OrderRequest did); it is recovered via
    :func:`~src.domain.order_keys.parse_order_key` — a malformed key halts.
  - **gap a / gap b / re-settle idempotency**: a terminal transition
    (FILLED / CANCELED / EXPIRED) is persisted via
    ``OrderRepoPort.update_status`` so the order drops out of ``list_pending``
    and is never re-settled (the apply-fill + status-transition pair is a
    *single UoW*, so a crash before commit leaves the order PENDING and the
    next cron re-settles it exactly once). A non-terminal order that survives
    past its submission day (KIS 지정가 = day-order, §8(6) N=1 business day)
    halts rather than re-settling forever.

Safety: every halt condition raises :class:`StateMismatchError` (an
``IntegrityError`` → not caught → all trading stops, CLAUDE.md §6.1/§11.2). No
auto-correction, no retry, no auto catch-up (CLAUDE.md §11). Each settle is one
UoW committed before the next; a mid-run halt leaves already-committed settles
durable and consistent (M2).

Layering (CLAUDE.md §1.1): imports domain + ports only (UnitOfWorkPort,
OrderStatusReaderPort, NotifierPort level). No adapter / infrastructure import.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.exceptions import StateMismatchError
from src.domain.fills import apply_buy_fill, apply_sell_fill
from src.domain.models import (
    BuyActionRecord,
    Decision,
    OrderSide,
    OrderStatus,
    SellActionRecord,
    SplitSlot,
)
from src.domain.order_keys import parse_order_key
from src.ports.notifications import NotificationLevel

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from src.domain.models import (
        Order,
        OrderResult,
        Position,
        SupportSlot,
    )
    from src.ports.broker import OrderStatusReaderPort
    from src.ports.unit_of_work import UnitOfWorkPort

# Statuses that mean the order is done and must leave list_pending. REJECTED is
# deliberately excluded: a rejection happens at place_order time (never reaches
# PENDING), so seeing it on a previously-accepted order is anomalous → halt.
_TERMINAL_NO_FILL = frozenset({OrderStatus.CANCELED, OrderStatus.EXPIRED})
_NON_TERMINAL = frozenset(
    {OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED}
)


@dataclass(frozen=True)
class SettleEvent:
    """A structured observability event surfaced by a settle run.

    The runner (Stage 8-5) forwards these to the NotifierPort. Kept as a
    first-class return value (not buried in Decision.reasoning) so the daily
    summary makes the event visible (Architect precision 3 / NF-1).
    """

    level: NotificationLevel
    kind: str
    title: str
    body: str


@dataclass
class SettleOutcome:
    """The result of one ``settle()`` run."""

    settled_buys: list[Decision] = field(default_factory=list)
    settled_sells: list[Decision] = field(default_factory=list)
    transitioned_keys: list[str] = field(default_factory=list)
    still_pending_keys: list[str] = field(default_factory=list)
    events: list[SettleEvent] = field(default_factory=list)


class PendingSettler:
    """Settle phase: confirm and apply PENDING fills before the decision phase."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWorkPort],
        broker: OrderStatusReaderPort,
        max_split_count: int = 7,
        slot_model: type[SplitSlot] | type[SupportSlot] = SplitSlot,
        max_pending_age_business_days: int = 1,
    ) -> None:
        self._uow_factory = uow_factory
        self._broker = broker
        self._max_split_count = max_split_count
        self._slot_model = slot_model
        self._max_pending_age_business_days = max_pending_age_business_days

    # ------------------------------------------------------------------
    def settle(self, today: date) -> SettleOutcome:
        """Confirm + apply every pending order's current broker status.

        ``today`` is the cron's trading date (used for the day-order max-age
        check and corrected-Decision context). Raises ``StateMismatchError`` on
        any integrity violation (lost order, drift, stale pending) — already
        committed settles stay durable.
        """
        outcome = SettleOutcome()
        with self._uow_factory() as uow:
            pending = uow.orders.list_pending()
        for order in pending:
            self._settle_one(order, today, outcome)
        return outcome

    # ------------------------------------------------------------------
    def _settle_one(
        self, order: Order, today: date, outcome: SettleOutcome
    ) -> None:
        result = self._broker.get_order_status(order.idempotency_key)
        if result is None:
            # The order is PENDING in our DB but the broker has no record of
            # it — a possible lost order (Pre-mortem scenario 1). Halt; never
            # guess (CLAUDE.md §11.2).
            raise StateMismatchError(
                f"PendingSettler: broker returned no status for "
                f"{order.idempotency_key} which is PENDING in the DB — "
                "possible lost order; halting for human reconciliation"
            )

        status = result.status
        if status is OrderStatus.FILLED:
            self._settle_filled(order, result, today, outcome)
        elif status in _TERMINAL_NO_FILL:
            self._settle_terminal_no_fill(order, result, status, outcome)
        elif status in _NON_TERMINAL:
            self._handle_still_pending(order, status, today, outcome)
        else:
            # REJECTED / UNKNOWN on a previously-accepted order is anomalous.
            raise StateMismatchError(
                f"PendingSettler: order {order.idempotency_key} returned "
                f"unexpected status {status.value} (was PENDING/accepted); "
                "halting for human reconciliation"
            )

    # ------------------------------------------------------------------
    def _settle_filled(
        self,
        order: Order,
        result: OrderResult,
        today: date,
        outcome: SettleOutcome,
    ) -> None:
        parsed = parse_order_key(order.idempotency_key)  # OrderKeyError → halt
        with self._uow_factory() as uow:
            existing = uow.positions.get(order.asset.fqn)

            if parsed.side is OrderSide.BUY:
                # Re-settle idempotency (defensive — single-UoW atomicity
                # normally prevents a re-applied buy from ever being PENDING):
                # if a slot already carries this fill, do NOT apply it again
                # (no second split++); only ensure the terminal transition.
                if existing is not None and _buy_already_applied(
                    existing, order.idempotency_key
                ):
                    self._persist_terminal(uow, order, result, OrderStatus.FILLED)
                    uow.commit()
                    outcome.transitioned_keys.append(order.idempotency_key)
                    return
                decision = self._settle_buy(
                    uow, order, result, parsed.slot_number, existing, today
                )
                outcome.settled_buys.append(decision)
            else:  # SELL
                decision = self._settle_sell(
                    uow, order, result, parsed.slot_number, existing, today
                )
                outcome.settled_sells.append(decision)
                outcome.events.append(_sell_pending_buy_skip_event(order))

            uow.commit()
        outcome.transitioned_keys.append(order.idempotency_key)

    def _settle_buy(
        self,
        uow: UnitOfWorkPort,
        order: Order,
        result: OrderResult,
        slot_number: int,
        existing: Position | None,
        today: date,
    ) -> Decision:
        filled_price = _require_fill_economics(result, order)
        assert result.filled_at is not None  # FILLED invariant (checked above)
        new_position = apply_buy_fill(
            existing=existing,
            asset=order.asset,
            filled_qty=result.filled_quantity,
            filled_price=filled_price,
            now=result.filled_at,
            idempotency_key=order.idempotency_key,
            max_split_count=self._max_split_count,
            slot_model=self._slot_model,
            target_slot_number=slot_number,
        )
        buy_action = BuyActionRecord(
            slot_number=slot_number,
            split_level_after=new_position.split_level,
            filled_quantity=result.filled_quantity,
            filled_price=filled_price,
            target_price=order.target_price,
            idempotency_key=order.idempotency_key,
            order_id=result.broker_order_id,
            reasoning=_settle_reasoning(order, today),
        )
        decision = Decision(
            timestamp=result.filled_at,
            asset=order.asset,
            sell_actions=[],
            buy_action=buy_action,
            skip_reason=None,
            reasoning=_settle_reasoning(order, today),
        )
        uow.positions.save(new_position)
        self._persist_terminal(uow, order, result, OrderStatus.FILLED)
        uow.decisions.save(decision)
        return decision

    def _settle_sell(
        self,
        uow: UnitOfWorkPort,
        order: Order,
        result: OrderResult,
        slot_number: int,
        existing: Position | None,
        today: date,
    ) -> Decision:
        filled_price = _require_fill_economics(result, order)
        assert result.filled_at is not None
        if existing is None:
            raise StateMismatchError(
                f"PendingSettler: SELL {order.idempotency_key} settled FILLED "
                f"but no DB position for {order.asset.fqn} — drift; halting"
            )
        slot = existing.get_slot(slot_number)
        if slot is None or slot.entry is None:
            raise StateMismatchError(
                f"PendingSettler: SELL {order.idempotency_key} targets slot "
                f"{slot_number} on {order.asset.fqn} which is not FILLED in the "
                "DB — drift; halting"
            )
        entry_price = slot.entry.entry_price
        profit_pct = (filled_price - entry_price) / entry_price * Decimal(100)
        new_position = apply_sell_fill(
            existing=existing,
            asset=order.asset,
            slot_number=slot_number,
            filled_qty=result.filled_quantity,
            filled_price=filled_price,
            now=result.filled_at,
        )
        sell_action = SellActionRecord(
            slot_number=slot_number,
            filled_quantity=result.filled_quantity,
            filled_price=filled_price,
            profit_pct=profit_pct,
            idempotency_key=order.idempotency_key,
            order_id=result.broker_order_id,
            reasoning=_settle_reasoning(order, today),
        )
        decision = Decision(
            timestamp=result.filled_at,
            asset=order.asset,
            sell_actions=[sell_action],
            buy_action=None,
            skip_reason=None,
            reasoning=_settle_reasoning(order, today),
        )
        uow.positions.save(new_position)
        self._persist_terminal(uow, order, result, OrderStatus.FILLED)
        uow.decisions.save(decision)
        return decision

    # ------------------------------------------------------------------
    def _settle_terminal_no_fill(
        self,
        order: Order,
        result: OrderResult,
        status: OrderStatus,
        outcome: SettleOutcome,
    ) -> None:
        # A clean cancel/expire (nothing filled) → no split change, no Decision
        # (the raw skip was real). A cancel/expire that carries a non-zero
        # filled quantity means a partial executed at the broker — unaccounted
        # in the DB → drift → halt (CLAUDE.md §4.4 / §11.2).
        if result.filled_quantity > 0:
            raise StateMismatchError(
                f"PendingSettler: order {order.idempotency_key} is "
                f"{status.value} but reports filled_quantity="
                f"{result.filled_quantity} (partial-then-terminal) — "
                "unaccounted broker fill; halting for human reconciliation"
            )
        with self._uow_factory() as uow:
            self._persist_terminal(uow, order, result, status)
            uow.commit()
        outcome.transitioned_keys.append(order.idempotency_key)

    def _handle_still_pending(
        self,
        order: Order,
        status: OrderStatus,
        today: date,
        outcome: SettleOutcome,
    ) -> None:
        # KIS 지정가 = day-order: it must be terminal by the next session. A
        # non-terminal order whose submission day is strictly before today's
        # cron has lingered past its session → exceeds the N=1 business-day
        # max-age (§8(6)) → halt (gap b, no infinite re-settle). An order
        # submitted today (same cron) is allowed to remain pending.
        if order.submitted_at.date() < today:
            raise StateMismatchError(
                f"PendingSettler: order {order.idempotency_key} still "
                f"{status.value} from {order.submitted_at.date().isoformat()} "
                f"at cron {today.isoformat()} — exceeds "
                f"{self._max_pending_age_business_days} business-day max-age "
                "(KIS day-orders expire same session); halting"
            )
        outcome.still_pending_keys.append(order.idempotency_key)
        if status is OrderStatus.PARTIALLY_FILLED:
            outcome.events.append(
                SettleEvent(
                    level=NotificationLevel.WARNING,
                    kind="partial_fill_pending",
                    title="부분 체결 대기 중",
                    body=(
                        f"주문 {order.idempotency_key} 가 PARTIALLY_FILLED 상태로 "
                        "다음 cron 확인 대기 중 (split 미증가, CLAUDE.md §4.4)."
                    ),
                )
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _persist_terminal(
        uow: UnitOfWorkPort,
        order: Order,
        result: OrderResult,
        status: OrderStatus,
    ) -> None:
        uow.orders.update_status(
            order.idempotency_key,
            status,
            filled_quantity=result.filled_quantity,
            filled_price=result.filled_price,
            filled_at=result.filled_at,
            broker_order_id=result.broker_order_id,
            broker_org_no=result.broker_org_no,
        )


# ----------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------
def _buy_already_applied(existing: Position, idempotency_key: str) -> bool:
    """True iff a slot already carries the SplitEntry for ``idempotency_key``."""
    return any(
        s.entry is not None and s.entry.idempotency_key == idempotency_key
        for s in existing.slots
    )


def _require_fill_economics(result: OrderResult, order: Order) -> Decimal:
    """Return the FILLED price, halting if a FILLED result is missing it.

    A FILLED OrderResult must carry filled_price + filled_at (Order's FILLED
    invariant). A FILLED status without them is broker-data corruption → halt.
    """
    if result.filled_price is None or result.filled_at is None:
        raise StateMismatchError(
            f"PendingSettler: order {order.idempotency_key} is FILLED but "
            "missing filled_price/filled_at — broker-data corruption; halting"
        )
    return result.filled_price


def _settle_reasoning(order: Order, today: date) -> dict[str, str]:
    """Context dict for a corrected (post-settle) Decision / action record.

    Excluded from G2(d) equivalence (decision_projection drops reasoning), so
    these values are audit context only — the raw pre-settle skip Decision
    preserves the original strategy reasoning.
    """
    return {
        "settled_from_pending": "true",
        "settle_cron_date": today.isoformat(),
        "idempotency_key": order.idempotency_key,
        "submitted_date": order.submitted_at.date().isoformat(),
    }


def _sell_pending_buy_skip_event(order: Order) -> SettleEvent:
    """NF-1 visibility: a PENDING sell short-circuited that day's buy."""
    return SettleEvent(
        level=NotificationLevel.WARNING,
        kind="sell_pending_buy_skip",
        title="익절일 매수 1회 skip (NF-1)",
        body=(
            f"PENDING 매도 {order.idempotency_key} 가 settle 되었습니다. 해당 "
            "결정일의 매수는 매도 PENDING 으로 short-circuit 되었고, 다음 cron "
            "정상 의사결정으로 회복됩니다 (자동 catch-up 아님 — 보수적·안전, "
            "ADR 0012 §8 NF-1 (가))."
        ),
    )


__all__ = ["PendingSettler", "SettleEvent", "SettleOutcome"]
