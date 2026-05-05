"""PriceDropStrategy — gradual buy on price drops (세븐 스플릿).

Phase 0.5 algorithm (ADR 0002 §4.4 / §4.7 / §4.8):

    1. Validate caller-supplied inputs (asset / currency consistency).
    2. max_split_per_day guard (CLAUDE.md §4.4 / ADR 0001 §7.11).
    3. If position has any FILLED slot AND all slots are FILLED → skip.
    4. For each EMPTY slot (or synthesized slot 1 when position is None),
       compute the slot's trigger price via the injected
       ``ReentryPriceStrategyPort``.
       - First-buy / no-history slots return ``current_price`` (auto match).
       - Slots whose trigger is ``None`` (data insufficient) are excluded.
    5. Pick the smallest ``slot_number`` whose trigger ≥ current_price
       (i.e. ``current_price <= trigger``).
    6. If no slot qualifies, skip with a precise SkipReason
       (NO_ACTION_TAKEN / INSUFFICIENT_HISTORICAL_DATA / max_split_reached).
    7. Build a ``BuyDecision`` (intent) with target_price floored to
       tick_size and quantity floored to lot_size; verify cash balance.

Domain rules (CLAUDE.md §1.1, §3.2): no external imports, no datetime.now(),
all time/price values are injected as parameters. The strategy emits BUY
intents only — orchestrator wires SELL via ``ProfitTargetSell`` separately.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from pydantic import Field, model_validator

from src.domain.models import (
    DomainModel,
    Money,
    SkipReason,
    SplitSlot,
    ValueObject,
)

if TYPE_CHECKING:
    from datetime import date

    from src.domain.models import Asset, Balance, Position, Price
    from src.ports.reentry_strategy import ReentryPriceStrategyPort


class SplitStrategyConfig(DomainModel):
    """Configuration for PriceDropStrategy.

    Phase 0: per_split_amount is set directly (no auto-allocation). Phase 1+
    may add `capital_allocation` with auto-divide logic; that requires Port
    interface revision and is out of Phase 0 scope.

    `max_loss_pct` is reserved for Phase 1+ position-loss limits; ignored in
    Phase 0 (CLAUDE.md §11.4).

    `max_split_per_day` (ADR 0001 §7.11) caps the number of FULL fills
    allowed on one calendar day. Default 1 makes the Phase 0 implicit
    "one buy per day" rule explicit. Counted against FILLED slots whose
    `entry.entry_date == today`.
    """

    drop_threshold_pct: Decimal = Field(gt=Decimal(0))
    max_split_count: int = Field(ge=1, le=7)
    per_split_amount: Money
    max_loss_pct: Decimal | None = None
    max_split_per_day: int = Field(default=1, ge=1)


class BuyDecision(ValueObject):
    """Strategy-side BUY intent (ADR 0002 §4.11).

    `target_quantity` and `target_price` are pre-fill projections. The
    orchestrator may further reduce quantity per circuit-breaker
    (CAUTION) before submitting the OrderRequest. Once the broker fills
    the order, the orchestrator composes a ``BuyActionRecord`` from this
    intent + ``OrderResult`` for the persisted Decision.
    """

    slot_number: int = Field(ge=1, le=7)
    target_quantity: Decimal = Field(gt=Decimal(0))
    target_price: Decimal = Field(gt=Decimal(0))
    reasoning: dict[str, str]


class BuyEvaluationResult(DomainModel):
    """PriceDropStrategy.evaluate output (ADR 0002 §4.11).

    Mutually exclusive: either ``buy`` is set (intent to buy) OR
    ``skip_reason`` is set (no buy this evaluation). The top-level
    ``reasoning`` dict carries the strategy-wide context (current_price,
    drop_threshold, etc.); per-buy details live in ``buy.reasoning``.
    """

    buy: BuyDecision | None = None
    skip_reason: SkipReason | None = None
    reasoning: dict[str, str]

    @model_validator(mode="after")
    def _check_xor(self) -> BuyEvaluationResult:
        has_buy = self.buy is not None
        has_skip = self.skip_reason is not None
        if has_buy == has_skip:
            raise ValueError(
                "BuyEvaluationResult requires exactly one of "
                "buy / skip_reason; got "
                f"(buy={'set' if has_buy else 'None'}, "
                f"skip_reason={'set' if has_skip else 'None'})"
            )
        return self


class PriceDropStrategy:
    """Gradual buy on price drops (세븐 스플릿).

    Stateless: all state is in the injected `position`. The reentry
    price policy is also injected — Phase 0.5 ships D-2 (MA) and F
    (cooldown) implementations; composition root chooses one. No default
    is provided to avoid biasing the D-2 vs F backtest comparison
    (ADR 0002 §4.4).
    """

    def __init__(self, reentry: ReentryPriceStrategyPort) -> None:
        self._reentry = reentry

    def evaluate(
        self,
        *,
        position: Position | None,
        current_price: Price,
        balance: Balance,
        config: SplitStrategyConfig,
        today: date,
        excluded_slot_numbers: set[int] | None = None,
    ) -> BuyEvaluationResult:
        asset = current_price.asset

        # ------------------------------------------------------------------
        # Preconditions — caller must pass consistent inputs.
        # ------------------------------------------------------------------
        if position is not None and position.asset != asset:
            raise ValueError(
                f"position.asset ({position.asset.fqn}) != "
                f"current_price.asset ({asset.fqn})"
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

        reasoning_base: dict[str, str] = {
            "today": today.isoformat(),
            "asset": asset.fqn,
            "current_price": str(current_price.value),
            "drop_threshold_pct": str(config.drop_threshold_pct),
            "max_split_count": str(config.max_split_count),
            "per_split_amount": str(config.per_split_amount.amount),
            "available_cash": str(balance.cash.amount),
        }

        # ------------------------------------------------------------------
        # 1. max_split_per_day guard — count today's FILLED slots.
        # ------------------------------------------------------------------
        today_buys = (
            sum(
                1
                for s in position.filled_slots
                if s.entry is not None and s.entry.entry_date == today
            )
            if position is not None
            else 0
        )
        if today_buys >= config.max_split_per_day:
            return BuyEvaluationResult(
                buy=None,
                skip_reason=SkipReason.MAX_SPLIT_PER_DAY_REACHED,
                reasoning={
                    **reasoning_base,
                    "today_buys": str(today_buys),
                    "max_split_per_day": str(config.max_split_per_day),
                },
            )

        # ------------------------------------------------------------------
        # 2. config.max_split_count guard. Position.slots length may exceed
        #    config.max_split_count (broker uses its own slot count). The
        #    strategy enforces the config cap on FILLED count.
        # ------------------------------------------------------------------
        if position is not None and position.split_level >= config.max_split_count:
            return BuyEvaluationResult(
                buy=None,
                skip_reason=SkipReason.STRATEGY_NO_BUY,
                reasoning={
                    **reasoning_base,
                    "current_split_level": str(position.split_level),
                    "max_split_reached": "True",
                },
            )

        # ------------------------------------------------------------------
        # 3. Determine candidate EMPTY slots.
        #    - position is None → synthesize EMPTY slots 1..max_split_count
        #      with no exit history (first-buy bypass via §4.7).
        #    - position exists, all FILLED → skip (max_split_reached).
        # ------------------------------------------------------------------
        if position is None:
            candidate_slots = [
                SplitSlot.empty(slot_number=i)
                for i in range(1, config.max_split_count + 1)
            ]
            effective_position = _synthetic_empty_position(asset, config.max_split_count)
        else:
            # Position.slots is homogeneous per asset (ADR 0004 §1.3 B-1).
            # PriceDropStrategy is dispatched only for buy_strategy=price_drop
            # → Position carries SplitSlots. Narrow union for downstream
            # ReentryPriceStrategyPort which takes ``slot: SplitSlot``.
            candidate_slots = cast("list[SplitSlot]", position.empty_slots)
            if not candidate_slots:
                return BuyEvaluationResult(
                    buy=None,
                    skip_reason=SkipReason.STRATEGY_NO_BUY,
                    reasoning={
                        **reasoning_base,
                        "current_split_level": str(position.split_level),
                        "max_split_reached": "True",
                    },
                )
            effective_position = position

        # ADR 0002 §5.9.3: orchestrator passes the slots it just sold this
        # evaluation; we exclude them so the resulting BuyDecision cannot
        # collide with any SellActionRecord (Decision Invariant 3).
        excluded = excluded_slot_numbers or set()
        if excluded:
            candidate_slots = [
                s for s in candidate_slots if s.slot_number not in excluded
            ]
            if not candidate_slots:
                return BuyEvaluationResult(
                    buy=None,
                    skip_reason=SkipReason.ALL_EMPTY_SLOTS_EXCLUDED_BY_SAME_DAY_SELL,
                    reasoning={
                        **reasoning_base,
                        "excluded_slot_numbers": ",".join(
                            str(n) for n in sorted(excluded)
                        ),
                    },
                )

        # ------------------------------------------------------------------
        # 3. Compute trigger per slot via injected ReentryPriceStrategy.
        #    Track slots that qualified (current_price <= trigger) vs
        #    slots whose trigger was None (insufficient data).
        # ------------------------------------------------------------------
        qualified: list[tuple[SplitSlot, Decimal]] = []
        none_count = 0
        for slot in candidate_slots:
            trigger = self._reentry.get_trigger_price(
                slot=slot,
                position=effective_position,
                current_price=current_price.value,
                drop_threshold_pct=config.drop_threshold_pct,
                as_of=today,
            )
            if trigger is None:
                none_count += 1
                continue
            if current_price.value <= trigger:
                qualified.append((slot, trigger))

        if not qualified:
            # Distinguish "all slots insufficient data" from "all slots
            # data fine but none qualified" for retrospective analysis.
            if none_count == len(candidate_slots):
                skip_reason = SkipReason.INSUFFICIENT_HISTORICAL_DATA
            else:
                skip_reason = SkipReason.STRATEGY_NO_BUY
            return BuyEvaluationResult(
                buy=None,
                skip_reason=skip_reason,
                reasoning={
                    **reasoning_base,
                    "candidate_empty_slots": str(len(candidate_slots)),
                    "none_count": str(none_count),
                },
            )

        # Smallest slot_number wins — already sorted in iteration order.
        target_slot, target_trigger = qualified[0]

        # ------------------------------------------------------------------
        # 4. Compute order quantity / price (lot + tick aligned).
        # ------------------------------------------------------------------
        target_price = asset.round_to_tick(current_price.value)
        spend_amount = config.per_split_amount.amount
        raw_qty = spend_amount / target_price
        lot_size = asset.lot_size
        target_quantity = (raw_qty // lot_size) * lot_size

        if target_quantity <= 0:
            return BuyEvaluationResult(
                buy=None,
                skip_reason=SkipReason.QUANTITY_TOO_SMALL,
                reasoning={
                    **reasoning_base,
                    "target_slot_number": str(target_slot.slot_number),
                    "trigger_price": str(target_trigger),
                    "raw_qty": str(raw_qty),
                    "lot_size": str(lot_size),
                },
            )

        actual_cost = target_quantity * target_price
        if balance.cash.amount < actual_cost:
            return BuyEvaluationResult(
                buy=None,
                skip_reason=SkipReason.INSUFFICIENT_BALANCE,
                reasoning={
                    **reasoning_base,
                    "target_slot_number": str(target_slot.slot_number),
                    "target_quantity": str(target_quantity),
                    "target_price": str(target_price),
                    "actual_cost": str(actual_cost),
                },
            )

        # ------------------------------------------------------------------
        # 5. Buy intent.
        # ------------------------------------------------------------------
        buy_reasoning = {
            "trigger_price": str(target_trigger),
            "current_price": str(current_price.value),
            "target_quantity": str(target_quantity),
            "target_price": str(target_price),
            "actual_cost": str(actual_cost),
        }
        if target_slot.last_exit_price is not None:
            buy_reasoning["last_exit_price"] = str(target_slot.last_exit_price)
        if target_slot.last_exit_date is not None:
            buy_reasoning["last_exit_date"] = target_slot.last_exit_date.isoformat()

        return BuyEvaluationResult(
            buy=BuyDecision(
                slot_number=target_slot.slot_number,
                target_quantity=target_quantity,
                target_price=target_price,
                reasoning=buy_reasoning,
            ),
            skip_reason=None,
            reasoning={
                **reasoning_base,
                "target_slot_number": str(target_slot.slot_number),
                "trigger_price": str(target_trigger),
                "qualified_slot_count": str(len(qualified)),
            },
        )


def _synthetic_empty_position(asset: Asset, max_split_count: int) -> Position:
    """Build a placeholder Position with all-EMPTY slots.

    Used to give MovingAverageReentry a Position object when the broker
    has no record yet. The reentry policy reads ``position.asset`` and
    ``position.split_level`` (== 0) — both correct for first-buy bypass.
    """
    from src.domain.models import Position
    return Position.empty(asset, max_split_count=max_split_count)
