"""DailyOrchestrator — daily trading decision flow.

CLAUDE.md §1.2 (DI): all external systems are injected as Ports. Phase 0
wiring uses Mock adapters; Phase 1+ swaps in real adapters with zero changes
here.

CLAUDE.md §6 exception policy:
- DomainError      -> caught; recorded as skip Decision, continue next day
- ExternalSystemError -> caught; recorded as skip Decision, continue next day
- IntegrityError   -> propagated (system halt is the caller's responsibility)

Reconciliation (CLAUDE.md §11.2) is the CLI/runner's responsibility before
calling run_for_date(). The orchestrator trusts that DB and broker state
agree at entry. See docs/decisions/0001-phase-0-decisions.md.
"""
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from src.domain.exceptions import (
    BrokerConnectionError,
    BrokerOrderError,
    DataIntegrityError,
    ExternalSystemError,
    MarketDataUnavailableError,
)
from src.domain.models import (
    Decision,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalLevel,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime

    from src.domain.models import (
        Asset,
        CircuitBreakerSignal,
        OrderResult,
    )
    from src.domain.strategies.price_drop import (
        PriceDropStrategy,
        SplitStrategyConfig,
        StrategyEvaluation,
    )
    from src.ports.broker import BrokerPort
    from src.ports.market_data import MarketDataPort
    from src.ports.signals import SignalPort


_CAUTION_REDUCTION: Final = Decimal("0.5")


class SkipReason(StrEnum):
    """Skip reasons used in Decision.action.

    Strategy returns granular reasons (e.g. "skip:max_split_reached"); the
    orchestrator maps those to SkipReason values for the persisted Decision
    while preserving the strategy-side string in reasoning["strategy_reason"].
    """

    MARKET_CLOSED = "market_closed"
    CIRCUIT_BREAKER_HALT = "circuit_breaker_halt"
    MARKET_DATA_UNAVAILABLE = "market_data_unavailable"
    STRATEGY_NO_BUY = "strategy_no_buy"
    QUANTITY_TOO_SMALL = "quantity_too_small"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    BROKER_REJECTED = "broker_rejected"
    BROKER_TIMEOUT = "broker_timeout"
    DATA_INTEGRITY_ISSUE = "data_integrity_issue"


# Map strategy-side skip reason strings to orchestrator SkipReason values.
# Anything not listed defaults to STRATEGY_NO_BUY (granular detail kept in
# reasoning["strategy_reason"]).
_STRATEGY_REASON_MAP: Final[dict[str, SkipReason]] = {
    "skip:max_split_reached": SkipReason.STRATEGY_NO_BUY,
    "skip:drop_insufficient": SkipReason.STRATEGY_NO_BUY,
    "skip:quantity_below_lot_size": SkipReason.QUANTITY_TOO_SMALL,
    "skip:insufficient_balance": SkipReason.INSUFFICIENT_BALANCE,
}


class DailyOrchestrator:
    """One-day trading decision orchestrator."""

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
    ) -> None:
        self._broker = broker
        self._market_data = market_data
        self._signal = signal
        self._strategy = strategy
        self._config = config
        self._asset = asset
        self._clock = clock

    def run_for_date(self, today: date) -> Decision:
        """Run the daily decision flow for `today`.

        IntegrityError-class exceptions propagate; everything else maps to a
        skip Decision so the system can record and continue.
        """
        as_of = self._clock()

        # 1. Signal first (HALT/EMERGENCY short-circuits everything else)
        try:
            signal = self._signal.collect(self._asset.asset_class, as_of)
        except ExternalSystemError as e:
            return self._skip(
                today, as_of,
                SkipReason.MARKET_DATA_UNAVAILABLE,
                {"error": str(e), "stage": "signal_collect"},
            )

        if signal.level in (SignalLevel.HALT, SignalLevel.EMERGENCY):
            return self._skip(
                today, as_of,
                SkipReason.CIRCUIT_BREAKER_HALT,
                self._signal_info(signal),
            )

        # 2. Market data
        try:
            current_price = self._market_data.get_price(self._asset, as_of)
        except DataIntegrityError as e:
            return self._skip(
                today, as_of,
                SkipReason.DATA_INTEGRITY_ISSUE,
                {**self._signal_info(signal), "error": str(e), "stage": "get_price"},
            )
        except MarketDataUnavailableError as e:
            return self._skip(
                today, as_of,
                SkipReason.MARKET_DATA_UNAVAILABLE,
                {**self._signal_info(signal), "error": str(e), "stage": "get_price"},
            )

        # 3. Account state
        try:
            balance = self._broker.get_balance()
            positions = self._broker.get_positions()
        except ExternalSystemError as e:
            return self._skip(
                today, as_of,
                SkipReason.BROKER_TIMEOUT,
                {**self._signal_info(signal), "error": str(e), "stage": "account_state"},
            )

        position = next(
            (p for p in positions if p.asset == self._asset), None
        )

        # 4. Strategy
        evaluation = self._strategy.evaluate(
            position=position,
            current_price=current_price,
            balance=balance,
            config=self._config,
            today=today,
        )

        if not evaluation.should_buy:
            skip_reason = _STRATEGY_REASON_MAP.get(
                evaluation.reason, SkipReason.STRATEGY_NO_BUY
            )
            return self._build_decision(
                as_of,
                action=f"skip:{skip_reason.value}",
                reasoning={
                    **evaluation.reasoning,
                    **self._signal_info(signal),
                    "strategy_reason": evaluation.reason,
                },
                resulting_order_id=None,
            )

        # mypy narrowing: should_buy=True implies these are non-None
        assert evaluation.target_quantity is not None
        assert evaluation.target_price is not None

        # 5. Adjust quantity per signal level (CAUTION halves; HALT/EMERGENCY
        #    already short-circuited above)
        adjusted_qty = self._adjust_quantity(
            signal.level, evaluation.target_quantity, self._asset.lot_size
        )
        if adjusted_qty <= 0:
            return self._build_decision(
                as_of,
                action=f"skip:{SkipReason.QUANTITY_TOO_SMALL.value}",
                reasoning={
                    **evaluation.reasoning,
                    **self._signal_info(signal),
                    "strategy_reason": evaluation.reason,
                    "pre_adjust_quantity": str(evaluation.target_quantity),
                    "adjusted_quantity": str(adjusted_qty),
                },
                resulting_order_id=None,
            )

        # 6. Place order with idempotency + recovery on timeout
        idempotency_key = self._make_idempotency_key(today)
        request = OrderRequest(
            idempotency_key=idempotency_key,
            asset=self._asset,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=adjusted_qty,
            target_price=evaluation.target_price,
        )

        try:
            order_result = self._broker.place_order(request)
        except BrokerConnectionError as e:
            recovered = self._try_recover_order(idempotency_key)
            if recovered is None:
                return self._build_decision(
                    as_of,
                    action=f"skip:{SkipReason.BROKER_TIMEOUT.value}",
                    reasoning={
                        **evaluation.reasoning,
                        **self._signal_info(signal),
                        "strategy_reason": evaluation.reason,
                        "idempotency_key": idempotency_key,
                        "error": str(e),
                    },
                    resulting_order_id=None,
                )
            order_result = recovered
        except BrokerOrderError as e:
            return self._build_decision(
                as_of,
                action=f"skip:{SkipReason.BROKER_REJECTED.value}",
                reasoning={
                    **evaluation.reasoning,
                    **self._signal_info(signal),
                    "strategy_reason": evaluation.reason,
                    "idempotency_key": idempotency_key,
                    "error": str(e),
                },
                resulting_order_id=None,
            )

        # 7. Build Decision from order result
        return self._decision_from_result(
            as_of,
            evaluation,
            signal,
            order_result,
            pre_adjust_quantity=evaluation.target_quantity,
            adjusted_quantity=adjusted_qty,
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

    def _decision_from_result(
        self,
        as_of: datetime,
        evaluation: StrategyEvaluation,
        signal: CircuitBreakerSignal,
        result: OrderResult,
        *,
        pre_adjust_quantity: Decimal,
        adjusted_quantity: Decimal,
    ) -> Decision:
        next_split_level = evaluation.reasoning.get("next_split_level", "?")
        base_reasoning = {
            **evaluation.reasoning,
            **self._signal_info(signal),
            "strategy_reason": evaluation.reason,
            "pre_adjust_quantity": str(pre_adjust_quantity),
            "adjusted_quantity": str(adjusted_quantity),
            "broker_order_id": result.broker_order_id or "",
            "order_status": result.status.value,
            "filled_quantity": str(result.filled_quantity),
            "filled_price": (
                str(result.filled_price) if result.filled_price is not None else ""
            ),
        }

        if result.status == OrderStatus.FILLED:
            return self._build_decision(
                as_of,
                action=f"buy_split_{next_split_level}",
                reasoning=base_reasoning,
                resulting_order_id=result.broker_order_id,
            )
        if result.status == OrderStatus.PARTIALLY_FILLED:
            return self._build_decision(
                as_of,
                action=f"buy_split_{next_split_level}_partial",
                reasoning=base_reasoning,
                resulting_order_id=result.broker_order_id,
            )
        if result.status == OrderStatus.REJECTED:
            return self._build_decision(
                as_of,
                action=f"skip:{SkipReason.BROKER_REJECTED.value}",
                reasoning=base_reasoning,
                resulting_order_id=result.broker_order_id,
            )
        # PENDING / CANCELED / EXPIRED / UNKNOWN → broker-timeout class
        return self._build_decision(
            as_of,
            action=f"skip:{SkipReason.BROKER_TIMEOUT.value}",
            reasoning=base_reasoning,
            resulting_order_id=result.broker_order_id,
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
        return self._build_decision(
            as_of,
            action=f"skip:{reason.value}",
            reasoning=reasoning,
            resulting_order_id=None,
        )

    def _build_decision(
        self,
        as_of: datetime,
        *,
        action: str,
        reasoning: dict[str, str],
        resulting_order_id: str | None,
    ) -> Decision:
        return Decision(
            timestamp=as_of,
            asset=self._asset,
            action=action,
            reasoning=reasoning,
            resulting_order_id=resulting_order_id,
        )
