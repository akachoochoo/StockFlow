"""PriceDropStrategy — gradual buy on price drops (세븐 스플릿).

Phase 0 algorithm summary:

    1. Circuit breaker HALT or EMERGENCY  → skip
    2. position is None or quantity == 0  → 1st split buy
    3. position.split_level >= max_split  → skip (max reached)
    4. drop from avg_price >= threshold   → next split buy
    5. otherwise                          → skip (drop insufficient)
    6. CAUTION signal level               → spend amount halved
    7. quantity rounds below lot_size     → skip
    8. cash < required                    → skip (insufficient balance)

Domain rules (CLAUDE.md §1.1, §3.2): no external imports, no datetime.now(),
all time/price values are injected as parameters. The strategy emits BUY only
in Phase 0; SELL is reserved for future phases (CLAUDE.md §14, OrderSide doc).
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from pydantic import Field, model_validator

from src.domain.models import (
    DomainModel,
    Money,
    SignalLevel,
)

if TYPE_CHECKING:
    from datetime import date

    from src.domain.models import (
        Balance,
        CircuitBreakerSignal,
        Position,
        Price,
    )


# When the circuit breaker is at CAUTION level, halve the spend amount per
# the design doc §3.4 ("CAUTION — reduce new entries, typically 50%").
_CAUTION_REDUCTION_FACTOR: Final = Decimal("0.5")


class SplitStrategyConfig(DomainModel):
    """Configuration for PriceDropStrategy.

    Phase 0: per_split_amount is set directly (no auto-allocation). Phase 1+
    may add `capital_allocation` with auto-divide logic; that requires Port
    interface revision and is out of Phase 0 scope.

    `max_loss_pct` is reserved for Phase 1+ position-loss limits; ignored in
    Phase 0 (CLAUDE.md §11.4).
    """

    drop_threshold_pct: Decimal = Field(gt=Decimal(0))
    max_split_count: int = Field(ge=1, le=7)
    per_split_amount: Money
    max_loss_pct: Decimal | None = None


class StrategyEvaluation(DomainModel):
    """Outcome of PriceDropStrategy.evaluate().

    When `should_buy=True`, `target_quantity` and `target_price` are set, and
    `reason` is a label like "buy_split_2". When `should_buy=False`, both
    target fields are None and `reason` is a "skip:..." label. `reasoning`
    holds every input the strategy used, for replay/debug (CLAUDE.md §8.1).
    """

    should_buy: bool
    reason: str = Field(min_length=1, max_length=100)
    target_quantity: Decimal | None
    target_price: Decimal | None
    reasoning: dict[str, str]

    @model_validator(mode="after")
    def _check_consistency(self) -> StrategyEvaluation:
        if self.should_buy:
            if self.target_quantity is None or self.target_price is None:
                raise ValueError(
                    "should_buy=True requires target_quantity and target_price"
                )
        else:
            if self.target_quantity is not None or self.target_price is not None:
                raise ValueError(
                    "should_buy=False requires target_quantity and target_price to be None"
                )
        return self


class PriceDropStrategy:
    """Gradual buy on price drops (세븐 스플릿).

    The strategy is stateless; all state is in the injected `position` and
    `signal`. This makes it trivial to share between backtest and live trading
    (CLAUDE.md §7.4).
    """

    def evaluate(
        self,
        *,
        position: Position | None,
        current_price: Price,
        balance: Balance,
        config: SplitStrategyConfig,
        today: date,
        signal: CircuitBreakerSignal,
    ) -> StrategyEvaluation:
        """Decide whether to place a buy order at `today`.

        Raises:
            ValueError: caller passed inconsistent inputs (asset/currency
                mismatch). These are programming errors, not market conditions.
        """
        asset = current_price.asset

        # ------------------------------------------------------------------
        # Preconditions — caller must pass consistent inputs.
        # ------------------------------------------------------------------
        if position is not None and position.asset != asset:
            raise ValueError(
                f"position.asset ({position.asset.fqn}) != "
                f"current_price.asset ({asset.fqn})"
            )
        if signal.asset_class != asset.asset_class:
            raise ValueError(
                f"signal.asset_class ({signal.asset_class.value}) != "
                f"asset.asset_class ({asset.asset_class.value})"
            )
        if config.per_split_amount.currency != asset.currency:
            raise ValueError(
                f"config.per_split_amount.currency "
                f"({config.per_split_amount.currency.value}) != "
                f"asset.currency ({asset.currency.value})"
            )
        if balance.cash.currency != asset.currency:
            raise ValueError(
                f"balance.cash.currency ({balance.cash.currency.value}) != "
                f"asset.currency ({asset.currency.value})"
            )

        # Build base reasoning context every branch will extend.
        reasoning_base: dict[str, str] = {
            "today": today.isoformat(),
            "asset": asset.fqn,
            "current_price": str(current_price.value),
            "signal_level": signal.level.value,
            "signal_source": signal.source.value,
            "drop_threshold_pct": str(config.drop_threshold_pct),
            "max_split_count": str(config.max_split_count),
            "per_split_amount": str(config.per_split_amount.amount),
            "available_cash": str(balance.cash.amount),
        }

        # ------------------------------------------------------------------
        # 1. Circuit breaker HALT/EMERGENCY → skip
        # ------------------------------------------------------------------
        if signal.level in (SignalLevel.HALT, SignalLevel.EMERGENCY):
            return StrategyEvaluation(
                should_buy=False,
                reason=f"skip:circuit_breaker_{signal.level.value.lower()}",
                target_quantity=None,
                target_price=None,
                reasoning=reasoning_base,
            )

        # ------------------------------------------------------------------
        # 2. Determine the target split level.
        # ------------------------------------------------------------------
        is_empty_position = position is None or position.quantity == 0
        prev_avg_price: Decimal | None = None
        drop_pct: Decimal | None = None

        if is_empty_position:
            next_split_level = 1
        else:
            assert position is not None  # narrow for mypy; quantity>0 implies not None
            # 3. max split reached
            if position.split_level >= config.max_split_count:
                reasoning = {
                    **reasoning_base,
                    "current_split_level": str(position.split_level),
                }
                return StrategyEvaluation(
                    should_buy=False,
                    reason="skip:max_split_reached",
                    target_quantity=None,
                    target_price=None,
                    reasoning=reasoning,
                )
            next_split_level = position.split_level + 1
            prev_avg_price = position.avg_price
            # 4. drop from avg_price
            drop_pct = (
                (prev_avg_price - current_price.value) / prev_avg_price * Decimal(100)
            )
            if drop_pct < config.drop_threshold_pct:
                reasoning = {
                    **reasoning_base,
                    "current_split_level": str(position.split_level),
                    "avg_price": str(prev_avg_price),
                    "drop_pct": str(drop_pct),
                }
                return StrategyEvaluation(
                    should_buy=False,
                    reason="skip:drop_insufficient",
                    target_quantity=None,
                    target_price=None,
                    reasoning=reasoning,
                )

        # ------------------------------------------------------------------
        # 5. We want to buy. Compute spend, quantity, cost.
        # ------------------------------------------------------------------
        target_price = current_price.value
        spend_amount = config.per_split_amount.amount
        if signal.level is SignalLevel.CAUTION:
            spend_amount = spend_amount * _CAUTION_REDUCTION_FACTOR

        raw_qty = spend_amount / target_price
        lot_size = asset.lot_size
        target_quantity = (raw_qty // lot_size) * lot_size

        # 7. quantity rounds below lot_size
        if target_quantity <= 0:
            reasoning = {
                **reasoning_base,
                "raw_qty": str(raw_qty),
                "lot_size": str(lot_size),
                "spend_amount": str(spend_amount),
            }
            return StrategyEvaluation(
                should_buy=False,
                reason="skip:quantity_below_lot_size",
                target_quantity=None,
                target_price=None,
                reasoning=reasoning,
            )

        actual_cost = target_quantity * target_price

        # 8. insufficient balance
        if balance.cash.amount < actual_cost:
            reasoning = {
                **reasoning_base,
                "target_quantity": str(target_quantity),
                "target_price": str(target_price),
                "actual_cost": str(actual_cost),
            }
            return StrategyEvaluation(
                should_buy=False,
                reason="skip:insufficient_balance",
                target_quantity=None,
                target_price=None,
                reasoning=reasoning,
            )

        # ------------------------------------------------------------------
        # Buy.
        # ------------------------------------------------------------------
        reasoning = {
            **reasoning_base,
            "next_split_level": str(next_split_level),
            "target_quantity": str(target_quantity),
            "target_price": str(target_price),
            "actual_cost": str(actual_cost),
            "spend_amount": str(spend_amount),
        }
        if prev_avg_price is not None:
            reasoning["avg_price"] = str(prev_avg_price)
        if drop_pct is not None:
            reasoning["drop_pct"] = str(drop_pct)
        if signal.level is SignalLevel.CAUTION:
            reasoning["caution_reduction_applied"] = "True"

        return StrategyEvaluation(
            should_buy=True,
            reason=f"buy_split_{next_split_level}",
            target_quantity=target_quantity,
            target_price=target_price,
            reasoning=reasoning,
        )
