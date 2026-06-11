"""DailyOrchestrator — daily trading decision flow + atomic persistence.

CLAUDE.md §1.2 (DI): all external systems are injected as Ports. Phase 0
wiring uses Mock adapters; Phase 1+ swaps in real adapters with zero changes
here.

Per ADR 0001 §8.5 (corrects §6.1) the orchestrator persists its outcome
through an injected ``uow_factory``. Decision computation is purely
in-memory; a single UnitOfWork commit at the end covers Orders + Position +
Decision in one atomic transaction. Auto-rollback on any exception ensures
partial saves never persist (CLAUDE.md §10.3).

Phase 0.5 (ADR 0002 §5.3 + §5.9): sells-then-buys cascade. A single
evaluation may emit 0..N SellActionRecords and 0..1 BuyActionRecord. The
SELL loop runs first; on the first broker error the loop aborts and the
BUY step is skipped (ADR §5.9.4). Successful sells passed their slot
numbers to the BUY strategy via ``excluded_slot_numbers`` so Decision
Invariant 3 (``buy_slot ∉ sell_slots``) is structurally guaranteed.

Idempotency keys (ADR §5.9.1):
    SELL: ``{asset.fqn}:{date}:sell:{slot_number}``
    BUY:  ``{asset.fqn}:{date}:buy:{slot_number}``

Signal level (ADR §5.9.2): ``HALT`` / ``EMERGENCY`` block both sells and
buys. ``CAUTION`` halves the BUY quantity but lets SELL through at full
size. Phase 0.5 ships NullSignal so this is mostly latent.

CLAUDE.md §6 exception policy:
- DomainError       -> caught; recorded as skip Decision, continue next day
- ExternalSystemError -> caught; recorded as skip Decision, continue next day
- IntegrityError    -> propagated (system halt is the caller's responsibility)

Reconciliation (CLAUDE.md §11.2) is the CLI/runner's responsibility before
calling run_for_date(). The orchestrator trusts that DB and broker state
agree at entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from src.domain.exceptions import (
    BrokerConnectionError,
    BrokerOrderError,
    DataIntegrityError,
    ExternalSystemError,
    MarketDataUnavailableError,
)
from src.domain.models import (
    BuyActionRecord,
    Decision,
    Order,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    SellActionRecord,
    SignalLevel,
    SkipReason,
)
from src.domain.order_keys import build_order_key
from src.domain.strategies.support_level import SupportLevelStrategy

# ADR 0004 §5.5.2 — calendar buffer for SupportLevelStrategy lookback.
# Phase 0.8.1: 60 trading days (slot 5 recent_high(60)) -> ~100 calendar days
# under ~1.6x factor. Hardcoded for Phase 0.8.1; yaml 인자화는 Phase 0.9+.
_SUPPORT_LEVEL_LOOKBACK_DAYS: Final = 100

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime

    from src.domain.models import (
        Balance,
        CircuitBreakerSignal,
        Position,
        Price,
    )
    from src.domain.strategies.profit_target import SellDecision
    from src.ports.broker import BrokerPort
    from src.ports.market_data import MarketDataPort
    from src.ports.signals import SignalPort
    from src.ports.unit_of_work import UnitOfWorkPort
    from src.use_cases.asset_context import AssetContext


_CAUTION_REDUCTION: Final = Decimal("0.5")


# Skip reasons whose specificity outranks the §5.6 retrospective categories
# (ALL_SLOTS_FILLED_NO_PROFIT / ALL_SLOTS_EMPTY_NO_TRIGGER). When the buy
# strategy emits one of these, the orchestrator preserves it.
_SPECIFIC_SKIP_REASONS: Final[frozenset[SkipReason]] = frozenset({
    SkipReason.MARKET_CLOSED,
    SkipReason.CIRCUIT_BREAKER_HALT,
    SkipReason.MARKET_DATA_UNAVAILABLE,
    SkipReason.MAX_SPLIT_PER_DAY_REACHED,
    SkipReason.QUANTITY_TOO_SMALL,
    SkipReason.INSUFFICIENT_BALANCE,
    SkipReason.BROKER_REJECTED,
    SkipReason.BROKER_TIMEOUT,
    SkipReason.DATA_INTEGRITY_ISSUE,
    SkipReason.INSUFFICIENT_HISTORICAL_DATA,
    SkipReason.ALL_EMPTY_SLOTS_EXCLUDED_BY_SAME_DAY_SELL,
})


__all__ = ["DailyOrchestrator", "SkipReason"]


@dataclass(frozen=True)
class _Outcome:
    """Internal result of one orchestrator run before persistence.

    `decision` is always set. `orders` is 0..N — every OrderResult we
    received from the broker (including REJECTED records, kept for audit).
    `updated_position` is set only when broker state actually changed (any
    FILLED sell or buy).
    """

    decision: Decision
    orders: list[Order] = field(default_factory=list)
    updated_position: Position | None = None


@dataclass(frozen=True)
class _SellLoopOutcome:
    """Result of the SELL loop (ADR §5.9.4)."""

    sell_actions: list[SellActionRecord]
    sell_orders: list[Order]
    # When the loop aborted: (skip_reason, error_str, slot_number).
    # ``skip_reason`` is BROKER_REJECTED or BROKER_TIMEOUT; only consulted
    # when ``sell_actions`` is empty (Invariant 1: skip ⇔ both empty).
    abort: tuple[SkipReason, str, int] | None


class DailyOrchestrator:
    """One-day trading decision orchestrator with atomic persistence.

    Phase 0.7.1.c: accepts ``list[AssetContext]`` — one context per asset.
    Phase 0.7.1.c guarantees at least one context; callers at 0.7.1.c always
    pass a single-element list. 0.7.1.d-g will extend to N assets.

    Each evaluation follows ADR §5.3: signal/data/state → SELL loop →
    refresh → BUY — independently per asset in declaration order (ADR 0003
    §5.1). A single UoW commit covers one asset's Orders + Position +
    Decision (ADR 0003 §8.4 — cross-asset atomicity intentionally not
    provided at 0.7.1.c).
    """

    def __init__(
        self,
        *,
        broker: BrokerPort,
        market_data: MarketDataPort,
        signal: SignalPort,
        asset_contexts: list[AssetContext],
        clock: Callable[[], datetime],
        uow_factory: Callable[[], UnitOfWorkPort],
    ) -> None:
        if not asset_contexts:
            raise ValueError("asset_contexts must contain at least one AssetContext")
        self._broker = broker
        self._market_data = market_data
        self._signal = signal
        # Defensive copy — frozen list assumption (ADR 0003 §8.2).
        self._asset_contexts: list[AssetContext] = list(asset_contexts)
        self._clock = clock
        self._uow_factory = uow_factory

    def run_for_date(self, today: date) -> list[Decision]:
        """Evaluate and persist each asset in declaration order.

        Returns one Decision per AssetContext (len == len(asset_contexts)).
        IntegrityError from any asset propagates immediately and halts
        processing of subsequent assets (ADR 0003 §8.4).
        DomainError / ExternalSystemError are caught per-asset so one
        asset's skip does not affect others.
        """
        decisions: list[Decision] = []
        for ctx in self._asset_contexts:
            outcome = self._compute_outcome_for_ctx(ctx, today)
            self._persist(outcome)
            decisions.append(outcome.decision)
        return decisions

    # ------------------------------------------------------------------
    # Persistence (one transaction per call)
    # ------------------------------------------------------------------
    def _persist(self, outcome: _Outcome) -> None:
        with self._uow_factory() as uow:
            for o in outcome.orders:
                uow.orders.save(o)
            if outcome.updated_position is not None:
                uow.positions.save(outcome.updated_position)
            uow.decisions.save(outcome.decision)
            uow.commit()

    # ------------------------------------------------------------------
    # Decision computation
    # ------------------------------------------------------------------
    def _compute_outcome_for_ctx(self, ctx: AssetContext, today: date) -> _Outcome:
        as_of = self._clock()

        # 1. Signal first (HALT/EMERGENCY blocks both sells and buys per
        #    ADR §5.9.2).
        try:
            signal = self._signal.collect(ctx.asset.asset_class, as_of)
        except ExternalSystemError as e:
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.MARKET_DATA_UNAVAILABLE,
                    {"error": str(e), "stage": "signal_collect"},
                    ctx=ctx,
                )
            )

        if signal.level in (SignalLevel.HALT, SignalLevel.EMERGENCY):
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.CIRCUIT_BREAKER_HALT,
                    self._signal_info(signal),
                    ctx=ctx,
                )
            )

        # 2. Market data
        try:
            current_price = self._market_data.get_price(ctx.asset, as_of)
        except DataIntegrityError as e:
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.DATA_INTEGRITY_ISSUE,
                    {**self._signal_info(signal), "error": str(e), "stage": "get_price"},
                    ctx=ctx,
                )
            )
        except MarketDataUnavailableError as e:
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.MARKET_DATA_UNAVAILABLE,
                    {**self._signal_info(signal), "error": str(e), "stage": "get_price"},
                    ctx=ctx,
                )
            )

        # 3. Account state
        try:
            balance = self._broker.get_balance()
            positions = self._broker.get_positions()
        except ExternalSystemError as e:
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.BROKER_TIMEOUT,
                    {**self._signal_info(signal), "error": str(e), "stage": "account_state"},
                    ctx=ctx,
                )
            )

        position = next(
            (p for p in positions if p.asset == ctx.asset), None
        )

        # 4. SELL loop (ADR §5.3 step 2 + §5.9.4 abort handling)
        sell_outcome = self._run_sell_loop(
            ctx=ctx, position=position, current_price=current_price, today=today,
        )

        # 5. If the SELL loop aborted with no successful sells, short-circuit
        #    the buy step and skip with the broker reason. If some sells
        #    succeeded before the abort, fall through (Invariant 1 forbids
        #    skip_reason set with non-empty sell_actions — abort detail
        #    moves into reasoning).
        if sell_outcome.abort is not None and not sell_outcome.sell_actions:
            abort_reason, abort_err, abort_slot = sell_outcome.abort
            return _Outcome(
                decision=self._build_skip_decision(
                    as_of,
                    skip_reason=abort_reason,
                    reasoning={
                        **self._base_reasoning(ctx, today, current_price, balance, signal),
                        "stage": "sell_loop",
                        "sell_loop_aborted_at_slot": str(abort_slot),
                        "sell_loop_error": abort_err,
                    },
                    ctx=ctx,
                ),
                orders=list(sell_outcome.sell_orders),
            )

        # 6. Refresh balance/position if any sell filled (ADR §5.3 — sells
        #    feed cash + slot state into the buy decision).
        if sell_outcome.sell_actions:
            try:
                balance = self._broker.get_balance()
                positions = self._broker.get_positions()
            except ExternalSystemError as e:
                # Sells already filled broker-side; record them and skip buy.
                return _Outcome(
                    decision=self._build_decision_with_sells_and_no_buy(
                        ctx=ctx,
                        as_of=as_of,
                        today=today,
                        current_price=current_price,
                        balance=balance,
                        signal=signal,
                        sell_actions=sell_outcome.sell_actions,
                        sell_abort=sell_outcome.abort,
                        buy_skip_reason=SkipReason.BROKER_TIMEOUT,
                        extra_reasoning={
                            "stage": "post_sell_account_state",
                            "error": str(e),
                        },
                    ),
                    orders=list(sell_outcome.sell_orders),
                    updated_position=self._fetch_updated_position(ctx),
                )
            position = next(
                (p for p in positions if p.asset == ctx.asset), None
            )

        # 7. BUY evaluation + execution
        excluded = {sa.slot_number for sa in sell_outcome.sell_actions}
        # ADR 0004 §5.5: SupportLevelStrategy needs ohlcv_history (slot 2~5
        # indicators); PriceDropStrategy 시그니처는 변경 zero (회귀 invariant).
        if isinstance(ctx.strategy, SupportLevelStrategy):
            lookback_start = today - timedelta(days=_SUPPORT_LEVEL_LOOKBACK_DAYS)
            ohlcv_history = self._market_data.get_ohlcv(
                ctx.asset, lookback_start, today - timedelta(days=1)
            )
            evaluation = ctx.strategy.evaluate(
                position=position,
                current_price=current_price,
                balance=balance,
                config=ctx.config,
                today=today,
                ohlcv_history=ohlcv_history,
                excluded_slot_numbers=excluded if excluded else None,
            )
        else:
            evaluation = ctx.strategy.evaluate(
                position=position,
                current_price=current_price,
                balance=balance,
                config=ctx.config,
                today=today,
                excluded_slot_numbers=excluded if excluded else None,
            )

        if evaluation.skip_reason is not None:
            return self._handle_no_buy(
                ctx=ctx,
                as_of=as_of,
                today=today,
                current_price=current_price,
                balance=balance,
                signal=signal,
                position=position,
                sell_outcome=sell_outcome,
                buy_skip_reason=evaluation.skip_reason,
                buy_reasoning=evaluation.reasoning,
            )

        assert evaluation.buy is not None  # invariant: skip XOR buy
        intent = evaluation.buy

        # Adjust BUY quantity per signal level (ADR §5.9.2 — SELL is full).
        adjusted_qty = self._adjust_quantity(
            signal.level, intent.target_quantity, ctx.asset.lot_size
        )
        if adjusted_qty <= 0:
            return self._handle_no_buy(
                ctx=ctx,
                as_of=as_of,
                today=today,
                current_price=current_price,
                balance=balance,
                signal=signal,
                position=position,
                sell_outcome=sell_outcome,
                buy_skip_reason=SkipReason.QUANTITY_TOO_SMALL,
                buy_reasoning={
                    **evaluation.reasoning,
                    "pre_adjust_quantity": str(intent.target_quantity),
                    "adjusted_quantity": str(adjusted_qty),
                },
            )

        # Place BUY order. ADR §5.9.3: pass the strategy's chosen slot so
        # the broker fills exactly that slot (otherwise its "smallest EMPTY"
        # default would clash with a same-day-emptied slot).
        buy_idem_key = self._buy_idempotency_key(ctx, today, intent.slot_number)
        request = OrderRequest(
            idempotency_key=buy_idem_key,
            asset=ctx.asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=adjusted_qty,
            target_price=intent.target_price,
            slot_number=intent.slot_number,
        )

        try:
            order_result = self._broker.place_order(request)
        except BrokerConnectionError as e:
            recovered = self._try_recover_order(buy_idem_key)
            if recovered is None:
                # Persist a PENDING record so that the broker's dedup check
                # (broker.py: PENDING+no-ODNO → StateMismatchError) blocks a
                # same-day re-POST that could create a duplicate live order.
                # The PendingSettler will flag this as lost if it stays PENDING
                # into the next session (CLAUDE.md §4.3).
                pending_result = OrderResult(
                    idempotency_key=buy_idem_key,
                    asset=request.asset,
                    broker_order_id=None,
                    status=OrderStatus.PENDING,
                    filled_quantity=Decimal(0),
                    filled_price=None,
                    submitted_at=as_of,
                    filled_at=None,
                )
                pending_order = Order.from_request_result(request, pending_result)
                return self._handle_no_buy_with_order(
                    ctx=ctx,
                    as_of=as_of,
                    today=today,
                    current_price=current_price,
                    balance=balance,
                    signal=signal,
                    position=position,
                    sell_outcome=sell_outcome,
                    buy_skip_reason=SkipReason.BROKER_TIMEOUT,
                    buy_reasoning={
                        **evaluation.reasoning,
                        "pre_adjust_quantity": str(intent.target_quantity),
                        "adjusted_quantity": str(adjusted_qty),
                        "idempotency_key": buy_idem_key,
                        "error": str(e),
                    },
                    extra_orders=[pending_order],
                )
            order_result = recovered
        except BrokerOrderError as e:
            return self._handle_no_buy(
                ctx=ctx,
                as_of=as_of,
                today=today,
                current_price=current_price,
                balance=balance,
                signal=signal,
                position=position,
                sell_outcome=sell_outcome,
                buy_skip_reason=SkipReason.BROKER_REJECTED,
                buy_reasoning={
                    **evaluation.reasoning,
                    "pre_adjust_quantity": str(intent.target_quantity),
                    "adjusted_quantity": str(adjusted_qty),
                    "idempotency_key": buy_idem_key,
                    "error": str(e),
                },
            )

        # 8. We have a BUY OrderResult — assemble Decision.
        prior_split_level = (
            position.split_level if position is not None else 0
        )
        buy_order = Order.from_request_result(request, order_result)
        all_orders = [*sell_outcome.sell_orders, buy_order]

        if order_result.status is OrderStatus.FILLED:
            assert order_result.filled_price is not None
            buy_action = BuyActionRecord(
                slot_number=intent.slot_number,
                split_level_after=prior_split_level + 1,
                filled_quantity=order_result.filled_quantity,
                filled_price=order_result.filled_price,
                target_price=intent.target_price,
                idempotency_key=buy_idem_key,
                order_id=order_result.broker_order_id,
                reasoning=intent.reasoning,
            )
            decision = self._build_full_decision(
                ctx=ctx,
                as_of=as_of,
                today=today,
                current_price=current_price,
                balance=balance,
                signal=signal,
                sell_actions=sell_outcome.sell_actions,
                buy_action=buy_action,
                buy_order_result=order_result,
                pre_adjust_quantity=intent.target_quantity,
                adjusted_quantity=adjusted_qty,
                buy_idem_key=buy_idem_key,
                buy_intent_reasoning=evaluation.reasoning,
                sell_abort=sell_outcome.abort,
            )
            return _Outcome(
                decision=decision,
                orders=all_orders,
                updated_position=self._fetch_updated_position(ctx),
            )

        # Non-FILLED BUY (REJECTED / PENDING / CANCELED / EXPIRED / UNKNOWN)
        skip_reason = (
            SkipReason.BROKER_REJECTED
            if order_result.status is OrderStatus.REJECTED
            else SkipReason.BROKER_TIMEOUT
        )
        # Non-FILLED BUY may still have left broker state untouched (REJECTED)
        # but the order record matters for audit, so include in orders list.
        return self._handle_no_buy_with_order(
            ctx=ctx,
            as_of=as_of,
            today=today,
            current_price=current_price,
            balance=balance,
            signal=signal,
            position=position,
            sell_outcome=sell_outcome,
            buy_skip_reason=skip_reason,
            buy_reasoning={
                **evaluation.reasoning,
                "pre_adjust_quantity": str(intent.target_quantity),
                "adjusted_quantity": str(adjusted_qty),
                "idempotency_key": buy_idem_key,
                "broker_order_id": order_result.broker_order_id or "",
                "order_status": order_result.status.value,
                "filled_quantity": str(order_result.filled_quantity),
                "filled_price": (
                    str(order_result.filled_price)
                    if order_result.filled_price is not None
                    else ""
                ),
            },
            extra_orders=[buy_order],
        )

    # ------------------------------------------------------------------
    # SELL loop
    # ------------------------------------------------------------------
    def _run_sell_loop(
        self,
        *,
        ctx: AssetContext,
        position: Position | None,
        current_price: Price,
        today: date,
    ) -> _SellLoopOutcome:
        """Evaluate sell triggers and execute each one.

        Aborts on the first broker error per ADR §5.9.4: previously
        successful sells are kept; the buy step is later short-circuited
        by the caller.
        """
        if position is None or position.split_level == 0:
            return _SellLoopOutcome(
                sell_actions=[], sell_orders=[], abort=None,
            )

        sell_decisions: list[SellDecision] = ctx.sell_strategy.evaluate(
            position=position,
            current_price=current_price,
            config=ctx.sell_config,
            as_of=today,
        )
        if not sell_decisions:
            return _SellLoopOutcome(
                sell_actions=[], sell_orders=[], abort=None,
            )

        sell_actions: list[SellActionRecord] = []
        sell_orders: list[Order] = []
        for sd in sell_decisions:
            slot = position.get_slot(sd.slot_number)
            assert slot is not None and slot.entry is not None  # FILLED invariant
            sell_idem_key = self._sell_idempotency_key(ctx, today, sd.slot_number)
            request = OrderRequest(
                idempotency_key=sell_idem_key,
                asset=ctx.asset,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=slot.entry.quantity,
                target_price=sd.expected_price,
                slot_number=sd.slot_number,
            )

            try:
                result = self._broker.place_order(request)
            except BrokerConnectionError as e:
                # Same rationale as BUY timeout: persist PENDING so that
                # same-day re-POST is blocked at broker dedup (CLAUDE.md §4.3).
                pending_sell_result = OrderResult(
                    idempotency_key=sell_idem_key,
                    asset=request.asset,
                    broker_order_id=None,
                    status=OrderStatus.PENDING,
                    filled_quantity=Decimal(0),
                    filled_price=None,
                    submitted_at=self._clock(),
                    filled_at=None,
                )
                pending_sell_order = Order.from_request_result(
                    request, pending_sell_result
                )
                return _SellLoopOutcome(
                    sell_actions=sell_actions,
                    sell_orders=[*sell_orders, pending_sell_order],
                    abort=(SkipReason.BROKER_TIMEOUT, str(e), sd.slot_number),
                )
            except BrokerOrderError as e:
                return _SellLoopOutcome(
                    sell_actions=sell_actions,
                    sell_orders=sell_orders,
                    abort=(SkipReason.BROKER_REJECTED, str(e), sd.slot_number),
                )

            sell_orders.append(Order.from_request_result(request, result))

            if result.status is OrderStatus.FILLED:
                assert result.filled_price is not None
                entry_price = slot.entry.entry_price
                profit_pct = (
                    (result.filled_price - entry_price)
                    / entry_price
                    * Decimal(100)
                )
                sell_actions.append(SellActionRecord(
                    slot_number=sd.slot_number,
                    filled_quantity=result.filled_quantity,
                    filled_price=result.filled_price,
                    profit_pct=profit_pct,
                    idempotency_key=sell_idem_key,
                    order_id=result.broker_order_id,
                    reasoning=sd.reasoning,
                ))
                continue

            # Non-FILLED SELL aborts the loop (ADR §5.9.4).
            abort_reason = (
                SkipReason.BROKER_REJECTED
                if result.status is OrderStatus.REJECTED
                else SkipReason.BROKER_TIMEOUT
            )
            return _SellLoopOutcome(
                sell_actions=sell_actions,
                sell_orders=sell_orders,
                abort=(
                    abort_reason,
                    f"broker returned {result.status.value}",
                    sd.slot_number,
                ),
            )

        return _SellLoopOutcome(
            sell_actions=sell_actions, sell_orders=sell_orders, abort=None,
        )

    # ------------------------------------------------------------------
    # Decision composition helpers
    # ------------------------------------------------------------------
    def _handle_no_buy(
        self,
        *,
        ctx: AssetContext,
        as_of: datetime,
        today: date,
        current_price: Price,
        balance: Balance,
        signal: CircuitBreakerSignal,
        position: Position | None,
        sell_outcome: _SellLoopOutcome,
        buy_skip_reason: SkipReason,
        buy_reasoning: dict[str, str],
    ) -> _Outcome:
        """Buy step skipped (no order even attempted). No new order to
        persist beyond the SELL orders already queued.
        """
        return self._handle_no_buy_with_order(
            ctx=ctx,
            as_of=as_of,
            today=today,
            current_price=current_price,
            balance=balance,
            signal=signal,
            position=position,
            sell_outcome=sell_outcome,
            buy_skip_reason=buy_skip_reason,
            buy_reasoning=buy_reasoning,
            extra_orders=[],
        )

    def _handle_no_buy_with_order(
        self,
        *,
        ctx: AssetContext,
        as_of: datetime,
        today: date,
        current_price: Price,
        balance: Balance,
        signal: CircuitBreakerSignal,
        position: Position | None,
        sell_outcome: _SellLoopOutcome,
        buy_skip_reason: SkipReason,
        buy_reasoning: dict[str, str],
        extra_orders: list[Order],
    ) -> _Outcome:
        """Build the no-buy outcome, including any non-FILLED buy order
        record (REJECTED/UNKNOWN) that should still persist for audit.
        """
        if sell_outcome.sell_actions:
            decision = self._build_decision_with_sells_and_no_buy(
                ctx=ctx,
                as_of=as_of,
                today=today,
                current_price=current_price,
                balance=balance,
                signal=signal,
                sell_actions=sell_outcome.sell_actions,
                sell_abort=sell_outcome.abort,
                buy_skip_reason=buy_skip_reason,
                extra_reasoning=buy_reasoning,
            )
            return _Outcome(
                decision=decision,
                orders=[*sell_outcome.sell_orders, *extra_orders],
                updated_position=self._fetch_updated_position(ctx),
            )

        skip_reason = self._classify_no_action_skip_reason(
            ctx=ctx,
            position=position,
            sell_decisions_evaluated=True,
            buy_skip_reason=buy_skip_reason,
        )
        decision = self._build_skip_decision(
            as_of,
            skip_reason=skip_reason,
            reasoning={
                **self._base_reasoning(ctx, today, current_price, balance, signal),
                **buy_reasoning,
                "buy_skip_reason_emitted": buy_skip_reason.value,
            },
            ctx=ctx,
        )
        # No sells succeeded → no broker state mutation, no position to refresh.
        return _Outcome(
            decision=decision,
            orders=[*sell_outcome.sell_orders, *extra_orders],
            updated_position=None,
        )

    def _build_decision_with_sells_and_no_buy(
        self,
        *,
        ctx: AssetContext,
        as_of: datetime,
        today: date,
        current_price: Price,
        balance: Balance,
        signal: CircuitBreakerSignal,
        sell_actions: list[SellActionRecord],
        sell_abort: tuple[SkipReason, str, int] | None,
        buy_skip_reason: SkipReason,
        extra_reasoning: dict[str, str],
    ) -> Decision:
        """Decision row when sells succeeded but buy was skipped (Invariant 1
        forbids skip_reason set; abort/buy-skip detail goes into reasoning).
        """
        reasoning: dict[str, str] = {
            **self._base_reasoning(ctx, today, current_price, balance, signal),
            **extra_reasoning,
            "buy_skip_reason_emitted": buy_skip_reason.value,
        }
        if sell_abort is not None:
            abort_reason, abort_err, abort_slot = sell_abort
            reasoning["sell_loop_aborted_at_slot"] = str(abort_slot)
            reasoning["sell_loop_error"] = abort_err
            reasoning["sell_loop_abort_reason"] = abort_reason.value
        return Decision(
            timestamp=as_of,
            asset=ctx.asset,
            sell_actions=sell_actions,
            buy_action=None,
            skip_reason=None,
            reasoning=reasoning,
        )

    def _build_full_decision(
        self,
        *,
        ctx: AssetContext,
        as_of: datetime,
        today: date,
        current_price: Price,
        balance: Balance,
        signal: CircuitBreakerSignal,
        sell_actions: list[SellActionRecord],
        buy_action: BuyActionRecord,
        buy_order_result: OrderResult,
        pre_adjust_quantity: Decimal,
        adjusted_quantity: Decimal,
        buy_idem_key: str,
        buy_intent_reasoning: dict[str, str],
        sell_abort: tuple[SkipReason, str, int] | None,
    ) -> Decision:
        reasoning: dict[str, str] = {
            **self._base_reasoning(ctx, today, current_price, balance, signal),
            **buy_intent_reasoning,
            "pre_adjust_quantity": str(pre_adjust_quantity),
            "adjusted_quantity": str(adjusted_quantity),
            "idempotency_key": buy_idem_key,
            "broker_order_id": buy_order_result.broker_order_id or "",
            "order_status": buy_order_result.status.value,
            "filled_quantity": str(buy_order_result.filled_quantity),
            "filled_price": (
                str(buy_order_result.filled_price)
                if buy_order_result.filled_price is not None
                else ""
            ),
        }
        if sell_abort is not None:
            # Cannot reach here in practice — abort short-circuits before
            # buy. Defensive: capture the abort detail if it ever does.
            abort_reason, abort_err, abort_slot = sell_abort
            reasoning["sell_loop_aborted_at_slot"] = str(abort_slot)
            reasoning["sell_loop_error"] = abort_err
            reasoning["sell_loop_abort_reason"] = abort_reason.value
        return Decision(
            timestamp=as_of,
            asset=ctx.asset,
            sell_actions=sell_actions,
            buy_action=buy_action,
            skip_reason=None,
            reasoning=reasoning,
        )

    def _classify_no_action_skip_reason(
        self,
        *,
        ctx: AssetContext,
        position: Position | None,
        sell_decisions_evaluated: bool,
        buy_skip_reason: SkipReason,
    ) -> SkipReason:
        """Apply ADR §5.6 priority for "no action taken" Decisions.

        Order:
            1. Specific skip reasons (broker errors, data issues, balance,
               quantity, max-per-day, historical-data, excluded-by-sell)
               always win.
            2. Position with all FILLED slots + no sells → ALL_SLOTS_FILLED_NO_PROFIT
            3. Position with all EMPTY slots (or no position) + no buy →
               ALL_SLOTS_EMPTY_NO_TRIGGER
            4. Mixed state + STRATEGY_NO_BUY → keep STRATEGY_NO_BUY.
        """
        del sell_decisions_evaluated  # currently always True; reserved for
                                      # future "skipped sell evaluation" branch
        if buy_skip_reason in _SPECIFIC_SKIP_REASONS:
            return buy_skip_reason

        if position is not None:
            # "All FILLED" is bounded by ``config.max_split_count`` rather
            # than ``position.max_split_count``. The Position carries 7
            # slots (Phase 0.5 fixed slot count), but the strategy may be
            # configured with fewer (e.g. max_split_count=3 caps growth at
            # 3 even though slots 4..7 stay EMPTY).
            all_filled = position.split_level >= ctx.config.max_split_count
            all_empty = position.split_level == 0
        else:
            all_filled = False
            all_empty = True  # no position == effectively all empty

        if all_filled:
            return SkipReason.ALL_SLOTS_FILLED_NO_PROFIT
        if all_empty:
            return SkipReason.ALL_SLOTS_EMPTY_NO_TRIGGER
        return buy_skip_reason  # mixed + STRATEGY_NO_BUY → keep

    def _base_reasoning(
        self,
        ctx: AssetContext,
        today: date,
        current_price: Price,
        balance: Balance,
        signal: CircuitBreakerSignal,
    ) -> dict[str, str]:
        """Reasoning common to every Decision row in the post-account-state
        flow (CLAUDE.md §8.1)."""
        return {
            "today": today.isoformat(),
            "asset": ctx.asset.fqn,
            "current_price": str(current_price.value),
            "balance_cash": str(balance.cash.amount),
            "drop_threshold_pct": str(ctx.config.drop_threshold_pct),
            "max_split_count": str(ctx.config.max_split_count),
            "profit_target_pct": str(ctx.sell_config.profit_target_pct),
            "max_sells_per_day": str(ctx.sell_config.max_sells_per_day),
            **self._signal_info(signal),
        }

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def _buy_idempotency_key(self, ctx: AssetContext, today: date, slot_number: int) -> str:
        """ADR §5.9.1 — slot-aware idempotency key for BUY.

        Delegates to :func:`src.domain.order_keys.build_order_key` (Phase 1.1
        Stage 8-2 single source of truth — byte-identical to the historical
        format, so existing keys are unchanged; ``PendingSettler`` recovers the
        slot via the matching parser).
        """
        return build_order_key(
            asset_fqn=ctx.asset.fqn,
            date_iso=today.isoformat(),
            side=OrderSide.BUY,
            slot_number=slot_number,
        )

    def _sell_idempotency_key(self, ctx: AssetContext, today: date, slot_number: int) -> str:
        """ADR §5.9.1 — slot-aware idempotency key for SELL. See
        :meth:`_buy_idempotency_key` (shared :func:`build_order_key`)."""
        return build_order_key(
            asset_fqn=ctx.asset.fqn,
            date_iso=today.isoformat(),
            side=OrderSide.SELL,
            slot_number=slot_number,
        )

    def _signal_info(self, signal: CircuitBreakerSignal) -> dict[str, str]:
        return {
            "signal_level": signal.level.value,
            "signal_source": signal.source.value,
            "signal_evaluated_at": signal.evaluated_at.isoformat(),
        }

    def _adjust_quantity(
        self, level: SignalLevel, quantity: Decimal, lot_size: Decimal,
    ) -> Decimal:
        """Apply circuit-breaker-level BUY quantity adjustment (ADR §5.9.2).

        - NORMAL: pass through
        - CAUTION: halve, floor to lot_size
        - HALT/EMERGENCY: 0 (defense; caller short-circuits earlier)
        """
        if level == SignalLevel.NORMAL:
            return quantity
        if level == SignalLevel.CAUTION:
            halved = quantity * _CAUTION_REDUCTION
            return (halved // lot_size) * lot_size
        return Decimal(0)

    def _try_recover_order(self, idempotency_key: str) -> OrderResult | None:
        """Recovery path after a BrokerConnectionError on place_order."""
        try:
            return self._broker.get_order_status(idempotency_key)
        except ExternalSystemError:
            return None

    def _fetch_updated_position(self, ctx: AssetContext) -> Position | None:
        """Fetch the post-fill Position from the broker. None if absent."""
        positions = self._broker.get_positions()
        return next((p for p in positions if p.asset == ctx.asset), None)

    def _skip(
        self,
        today: date,
        as_of: datetime,
        reason: SkipReason,
        extra_reasoning: dict[str, str],
        *,
        ctx: AssetContext,
    ) -> Decision:
        reasoning = {
            "today": today.isoformat(),
            "asset": ctx.asset.fqn,
            **extra_reasoning,
        }
        return self._build_skip_decision(
            as_of,
            skip_reason=reason,
            reasoning=reasoning,
            ctx=ctx,
        )

    def _build_skip_decision(
        self,
        as_of: datetime,
        *,
        skip_reason: SkipReason,
        reasoning: dict[str, str],
        ctx: AssetContext,
    ) -> Decision:
        return Decision(
            timestamp=as_of,
            asset=ctx.asset,
            sell_actions=[],
            buy_action=None,
            skip_reason=skip_reason,
            reasoning=reasoning,
        )
