"""DailyOrchestrator — daily trading decision flow + atomic persistence.

CLAUDE.md §1.2 (DI): all external systems are injected as Ports. Phase 0
wiring uses Mock adapters; Phase 1+ swaps in real adapters with zero changes
here.

Per ADR §8.5 (corrects §6.1) the orchestrator persists its outcome through
an injected ``uow_factory``. Decision computation is purely in-memory; a
single UnitOfWork commit at the end covers Order + Position + Decision in
one atomic transaction. Auto-rollback on any exception ensures partial
saves never persist (CLAUDE.md §10.3).

CLAUDE.md §6 exception policy:
- DomainError       -> caught; recorded as skip Decision, continue next day
- ExternalSystemError -> caught; recorded as skip Decision, continue next day
- IntegrityError    -> propagated (system halt is the caller's responsibility)

Reconciliation (CLAUDE.md §11.2) is the CLI/runner's responsibility before
calling run_for_date(). The orchestrator trusts that DB and broker state
agree at entry. See docs/decisions/0001-phase-0-decisions.md.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    OrderSide,
    OrderStatus,
    OrderType,
    SignalLevel,
    SkipReason,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime

    from src.domain.models import (
        Asset,
        CircuitBreakerSignal,
        OrderResult,
        Position,
    )
    from src.domain.strategies.price_drop import (
        BuyDecision,
        PriceDropStrategy,
        SplitStrategyConfig,
    )
    from src.ports.broker import BrokerPort
    from src.ports.market_data import MarketDataPort
    from src.ports.signals import SignalPort
    from src.ports.unit_of_work import UnitOfWorkPort


_CAUTION_REDUCTION: Final = Decimal("0.5")


# SkipReason now lives in src.domain.models (ADR 0002 §5.6 — Phase 0.5
# extends with NO_ACTION_TAKEN / ALL_SLOTS_EMPTY_NO_TRIGGER /
# ALL_SLOTS_FILLED_NO_PROFIT for retrospective analysis). Re-exported here
# for backward-compat with any caller that did
# ``from src.use_cases.daily_orchestrator import SkipReason``.
__all__ = ["DailyOrchestrator", "SkipReason"]


# Phase 0.5 (ADR 0002 §4.11): PriceDropStrategy emits SkipReason directly
# via BuyEvaluationResult.skip_reason. The Phase 0 string→enum mapping
# (_STRATEGY_REASON_MAP) is no longer needed.


@dataclass(frozen=True)
class _Outcome:
    """Internal result of one orchestrator run before persistence.

    `decision` is always set. `order` is set whenever we obtained a real
    OrderResult (any status — REJECTED orders are still worth persisting
    for audit). `updated_position` is set only when broker state actually
    changed (FILLED — partial fills blocked in Phase 0.5 / ADR 0002 §3.2.1).
    """

    decision: Decision
    order: Order | None = None
    updated_position: Position | None = None


class DailyOrchestrator:
    """One-day trading decision orchestrator with atomic persistence."""

    def __init__(
        self,
        *,
        broker: BrokerPort,
        market_data: MarketDataPort,
        signal: SignalPort,
        strategy: PriceDropStrategy,
        config: SplitStrategyConfig,
        asset: Asset,
        clock: Callable[[], datetime],
        uow_factory: Callable[[], UnitOfWorkPort],
    ) -> None:
        self._broker = broker
        self._market_data = market_data
        self._signal = signal
        self._strategy = strategy
        self._config = config
        self._asset = asset
        self._clock = clock
        self._uow_factory = uow_factory

    def run_for_date(self, today: date) -> Decision:
        """Run the daily decision flow for `today`.

        Computes the outcome (Decision + optional Order + optional updated
        Position) without touching persistence, then commits all of it
        through one UnitOfWork. IntegrityError propagates; everything else
        becomes a skip Decision so the system can record and continue.
        """
        outcome = self._compute_outcome(today)
        self._persist(outcome)
        return outcome.decision

    # ------------------------------------------------------------------
    # Persistence (one transaction per call)
    # ------------------------------------------------------------------
    def _persist(self, outcome: _Outcome) -> None:
        with self._uow_factory() as uow:
            if outcome.order is not None:
                uow.orders.save(outcome.order)
            if outcome.updated_position is not None:
                uow.positions.save(outcome.updated_position)
            uow.decisions.save(outcome.decision)
            uow.commit()

    # ------------------------------------------------------------------
    # Decision computation
    # ------------------------------------------------------------------
    def _compute_outcome(self, today: date) -> _Outcome:
        as_of = self._clock()

        # 1. Signal first (HALT/EMERGENCY short-circuits everything else)
        try:
            signal = self._signal.collect(self._asset.asset_class, as_of)
        except ExternalSystemError as e:
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.MARKET_DATA_UNAVAILABLE,
                    {"error": str(e), "stage": "signal_collect"},
                )
            )

        if signal.level in (SignalLevel.HALT, SignalLevel.EMERGENCY):
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.CIRCUIT_BREAKER_HALT,
                    self._signal_info(signal),
                )
            )

        # 2. Market data
        try:
            current_price = self._market_data.get_price(self._asset, as_of)
        except DataIntegrityError as e:
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.DATA_INTEGRITY_ISSUE,
                    {**self._signal_info(signal), "error": str(e), "stage": "get_price"},
                )
            )
        except MarketDataUnavailableError as e:
            return _Outcome(
                decision=self._skip(
                    today, as_of,
                    SkipReason.MARKET_DATA_UNAVAILABLE,
                    {**self._signal_info(signal), "error": str(e), "stage": "get_price"},
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
                )
            )

        position = next(
            (p for p in positions if p.asset == self._asset), None
        )

        # Phase 0.5 (ADR 0002 §3.2.1) blocks partial fills end-to-end, so
        # the Phase 0 "pending_partial" warning fragment is no longer
        # surfaced — the slot model has no pending-partial concept.

        # 4. Strategy → BuyEvaluationResult (ADR 0002 §4.11)
        evaluation = self._strategy.evaluate(
            position=position,
            current_price=current_price,
            balance=balance,
            config=self._config,
            today=today,
        )

        if evaluation.skip_reason is not None:
            return _Outcome(
                decision=self._build_skip_decision(
                    as_of,
                    skip_reason=evaluation.skip_reason,
                    reasoning={
                        **evaluation.reasoning,
                        **self._signal_info(signal),
                    },
                )
            )

        assert evaluation.buy is not None  # invariant: skip XOR buy
        intent = evaluation.buy

        # 5. Adjust quantity per signal level (CAUTION halves; HALT/EMERGENCY
        #    already short-circuited above)
        adjusted_qty = self._adjust_quantity(
            signal.level, intent.target_quantity, self._asset.lot_size
        )
        if adjusted_qty <= 0:
            return _Outcome(
                decision=self._build_skip_decision(
                    as_of,
                    skip_reason=SkipReason.QUANTITY_TOO_SMALL,
                    reasoning={
                        **evaluation.reasoning,
                        **self._signal_info(signal),
                        "pre_adjust_quantity": str(intent.target_quantity),
                        "adjusted_quantity": str(adjusted_qty),
                    },
                )
            )

        # 6. Place order with idempotency + recovery on timeout
        idempotency_key = self._make_idempotency_key(today)
        request = OrderRequest(
            idempotency_key=idempotency_key,
            asset=self._asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=adjusted_qty,
            target_price=intent.target_price,
        )

        try:
            order_result = self._broker.place_order(request)
        except BrokerConnectionError as e:
            recovered = self._try_recover_order(idempotency_key)
            if recovered is None:
                return _Outcome(
                    decision=self._build_skip_decision(
                        as_of,
                        skip_reason=SkipReason.BROKER_TIMEOUT,
                        reasoning={
                            **evaluation.reasoning,
                            **self._signal_info(signal),
                            "idempotency_key": idempotency_key,
                            "error": str(e),
                        },
                    )
                )
            order_result = recovered
        except BrokerOrderError as e:
            return _Outcome(
                decision=self._build_skip_decision(
                    as_of,
                    skip_reason=SkipReason.BROKER_REJECTED,
                    reasoning={
                        **evaluation.reasoning,
                        **self._signal_info(signal),
                        "idempotency_key": idempotency_key,
                        "error": str(e),
                    },
                )
            )

        # 7. We have an OrderResult — build Decision, Order record, and
        #    optionally fetch the updated Position to persist.
        prior_split_level = position.split_level if position is not None else 0
        decision = self._decision_from_result(
            as_of,
            evaluation_reasoning=evaluation.reasoning,
            intent=intent,
            signal=signal,
            result=order_result,
            pre_adjust_quantity=intent.target_quantity,
            adjusted_quantity=adjusted_qty,
            idempotency_key=idempotency_key,
            prior_split_level=prior_split_level,
        )
        order = Order.from_request_result(request, order_result)
        updated_position = None
        if order_result.status is OrderStatus.FILLED:
            # Phase 0.5: only FILLED reaches here (partial fills blocked).
            updated_position = self._fetch_updated_position()
        return _Outcome(
            decision=decision,
            order=order,
            updated_position=updated_position,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _make_idempotency_key(self, today: date) -> str:
        """Deterministic key per (asset, day). Phase 0 = one buy attempt/day."""
        return f"{self._asset.fqn}:{today.isoformat()}"

    def _signal_info(self, signal: CircuitBreakerSignal) -> dict[str, str]:
        return {
            "signal_level": signal.level.value,
            "signal_source": signal.source.value,
            "signal_evaluated_at": signal.evaluated_at.isoformat(),
        }

    def _adjust_quantity(
        self, level: SignalLevel, quantity: Decimal, lot_size: Decimal,
    ) -> Decimal:
        """Apply circuit-breaker-level quantity adjustment.

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

    def _fetch_updated_position(self) -> Position | None:
        """Fetch the post-fill Position from the broker. None if absent."""
        positions = self._broker.get_positions()
        return next((p for p in positions if p.asset == self._asset), None)

    def _decision_from_result(
        self,
        as_of: datetime,
        *,
        evaluation_reasoning: dict[str, str],
        intent: BuyDecision,
        signal: CircuitBreakerSignal,
        result: OrderResult,
        pre_adjust_quantity: Decimal,
        adjusted_quantity: Decimal,
        idempotency_key: str,
        prior_split_level: int,
    ) -> Decision:
        base_reasoning = {
            **evaluation_reasoning,
            **self._signal_info(signal),
            "pre_adjust_quantity": str(pre_adjust_quantity),
            "adjusted_quantity": str(adjusted_quantity),
            "broker_order_id": result.broker_order_id or "",
            "order_status": result.status.value,
            "filled_quantity": str(result.filled_quantity),
            "filled_price": (
                str(result.filled_price) if result.filled_price is not None else ""
            ),
        }

        if result.status is OrderStatus.FILLED:
            assert result.filled_price is not None
            buy_action = BuyActionRecord(
                slot_number=intent.slot_number,
                split_level_after=prior_split_level + 1,
                filled_quantity=result.filled_quantity,
                filled_price=result.filled_price,
                target_price=intent.target_price,
                idempotency_key=idempotency_key,
                order_id=result.broker_order_id,
                reasoning=intent.reasoning,
            )
            return self._build_buy_decision(
                as_of,
                buy_action=buy_action,
                reasoning=base_reasoning,
            )
        if result.status is OrderStatus.REJECTED:
            return self._build_skip_decision(
                as_of,
                skip_reason=SkipReason.BROKER_REJECTED,
                reasoning=base_reasoning,
            )
        # PENDING / CANCELED / EXPIRED / UNKNOWN → broker-timeout class
        return self._build_skip_decision(
            as_of,
            skip_reason=SkipReason.BROKER_TIMEOUT,
            reasoning=base_reasoning,
        )

    def _skip(
        self,
        today: date,
        as_of: datetime,
        reason: SkipReason,
        extra_reasoning: dict[str, str],
    ) -> Decision:
        reasoning = {
            "today": today.isoformat(),
            "asset": self._asset.fqn,
            **extra_reasoning,
        }
        return self._build_skip_decision(
            as_of,
            skip_reason=reason,
            reasoning=reasoning,
        )

    def _build_skip_decision(
        self,
        as_of: datetime,
        *,
        skip_reason: SkipReason,
        reasoning: dict[str, str],
    ) -> Decision:
        return Decision(
            timestamp=as_of,
            asset=self._asset,
            sell_actions=[],
            buy_action=None,
            skip_reason=skip_reason,
            reasoning=reasoning,
        )

    def _build_buy_decision(
        self,
        as_of: datetime,
        *,
        buy_action: BuyActionRecord,
        reasoning: dict[str, str],
    ) -> Decision:
        return Decision(
            timestamp=as_of,
            asset=self._asset,
            sell_actions=[],
            buy_action=buy_action,
            skip_reason=None,
            reasoning=reasoning,
        )
