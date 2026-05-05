"""SupportLevelStrategy — gradual buy on support-level breach (Phase 0.8).

ADR 0004 §1 (paradigm comparison) / §2 (slot mapping) / §3 (SupportSlot) /
§4 (signature decisions). Phase 0.8.1 ships slots 1~5; Phase 0.8.2 adds
slots 6~7 (separate sub-step).

Algorithm (ADR 0004 §4.6):

    1. Validate caller-supplied inputs (asset / currency consistency).
    2. max_split_per_day guard (PriceDropStrategy 동일).
    3. max_split_count guard (split_level >= max_split_count → skip).
    4. Determine candidate EMPTY slot_numbers (apply excluded set).
    5. Slot 1 first-buy bypass — fires when (position is None OR
       split_level == 0) AND slot 1 is candidate.
    6. Slots 2~5 indicator-based evaluation (Phase 0.8.1):
         2 → MA5     (current < MA5 → trigger)
         3 → MA10
         4 → MA20    (생명선)
         5 → recent_high(60)
       "이탈" = strict less than (ADR §2.2.3). equal-case 트리거 안 함.
    7. Skip reasons: INSUFFICIENT_HISTORICAL_DATA (window 부족) /
       ALL_SLOTS_EMPTY_NO_TRIGGER (data 충분 but 미트리거) / etc.
    8. Build BuyDecision (intent) — target_price floored to tick_size,
       quantity floored to lot_size, balance check.

Domain rules (CLAUDE.md §1.1, §3.2): no external imports, no
``datetime.now()``. ``ohlcv_history`` is injected — caller (BacktestRunner
/ DailyOrchestrator) is responsible for look-ahead bias prevention
(history must be ``[..., today - 1]`` close-only inclusive).

No reentry policy injection (ADR §4.3 β-2 채택). Slot trigger = indicator
condition; cooldown 무 (Phase 0.8.1 simplification — Phase 0.8.x may
revisit). PriceDropStrategy 의 회귀 invariant 보존: 본 strategy 는
BuyDecision / BuyEvaluationResult / SplitStrategyConfig 재사용.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from src.domain.indicators import calculate_sma, find_recent_high
from src.domain.models import OHLCV, SkipReason, SupportSlot
from src.domain.strategies.price_drop import (
    BuyDecision,
    BuyEvaluationResult,
    SplitStrategyConfig,
)

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from src.domain.models import Balance, Position, Price


# Phase 0.8.1 slot -> indicator mapping (ADR 0004 §2.2.1 / §2.4.1).
# Hardcoded windows (decision §2.4 = option gamma). Phase 0.8.2 will extend
# the mapping with slots 6 (MA60) and 7 (BB-or-RSI) — see ADR §2.2.2.
_MA_WINDOWS: dict[int, int] = {2: 5, 3: 10, 4: 20}
_RECENT_HIGH_WINDOW: int = 60


class SupportLevelStrategy:
    """Buy on support-level breach (Phase 0.8 / ADR 0004 §1.2 / §2).

    Stateless. No reentry policy (ADR §4.3 β-2) — slot trigger is the
    slot's own indicator condition. Composition root injects nothing
    beyond the strategy instance itself.
    """

    def evaluate(
        self,
        *,
        position: Position | None,
        current_price: Price,
        balance: Balance,
        config: SplitStrategyConfig,
        today: date,
        ohlcv_history: list[OHLCV],
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
            "max_split_count": str(config.max_split_count),
            "per_split_amount": str(config.per_split_amount.amount),
            "available_cash": str(balance.cash.amount),
            "ohlcv_history_len": str(len(ohlcv_history)),
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
        # 2. max_split_count guard — strategy enforces config cap on
        #    FILLED count (Position.slots length may exceed config).
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
        # 3. Determine candidate EMPTY slot_numbers.
        # ------------------------------------------------------------------
        if position is None:
            candidate_slot_numbers = list(range(1, config.max_split_count + 1))
        else:
            # ADR 0004 §1.3 (B-1): SupportLevelStrategy operates on
            # Positions with SupportSlots. Narrow union for type correctness.
            empty_support_slots = cast(
                "list[SupportSlot]", position.empty_slots
            )
            candidate_slot_numbers = [
                s.slot_number for s in empty_support_slots
            ]
        excluded = excluded_slot_numbers or set()
        candidate_slot_numbers = [
            n for n in candidate_slot_numbers if n not in excluded
        ]

        if not candidate_slot_numbers:
            # Either max_split reached (handled above) or every empty
            # slot was excluded by same-day sell.
            if excluded:
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
            return BuyEvaluationResult(
                buy=None,
                skip_reason=SkipReason.STRATEGY_NO_BUY,
                reasoning={
                    **reasoning_base,
                    "reason": "no_candidate_slots",
                },
            )

        # ------------------------------------------------------------------
        # 4. Slot 1 first-buy bypass (ADR §2.2.1 + §4.3.4).
        #    Fires when (position is None OR split_level == 0) AND
        #    slot 1 is in candidates. Otherwise fall through to slot 2~5.
        # ------------------------------------------------------------------
        is_first_buy_eligible = (
            position is None or position.split_level == 0
        ) and 1 in candidate_slot_numbers

        target_slot_number: int | None = None
        target_indicator_value: Decimal | None = None
        none_count = 0
        evaluated_count = 0

        if is_first_buy_eligible:
            target_slot_number = 1
            # Slot 1 has no indicator — symbolic trigger = current_price.
            target_indicator_value = current_price.value
        else:
            # ------------------------------------------------------------------
            # 5. Slots 2~5 indicator evaluation (Phase 0.8.1).
            #    Strict less than ("이탈" semantics, ADR §2.2.3).
            # ------------------------------------------------------------------
            closes = [bar.close for bar in ohlcv_history]
            triggers: list[tuple[int, Decimal]] = []
            for slot_number in sorted(candidate_slot_numbers):
                if slot_number == 1:
                    # split_level > 0 — slot 1 not eligible (ADR §2.2.1
                    # first-buy 전용). Skip without counting.
                    continue
                indicator_value = self._evaluate_slot_indicator(
                    slot_number, closes
                )
                if indicator_value is None:
                    # Either insufficient data OR slot beyond Phase 0.8.1
                    # mapping (e.g., slot 6/7 — only active in Phase 0.8.2).
                    if slot_number in _MA_WINDOWS or slot_number == 5:
                        # Phase 0.8.1 slot — None means insufficient data.
                        evaluated_count += 1
                        none_count += 1
                    continue
                evaluated_count += 1
                if current_price.value < indicator_value:
                    triggers.append((slot_number, indicator_value))

            if not triggers:
                if evaluated_count == 0:
                    # No Phase 0.8.1 slots in candidates (e.g., only slot
                    # 6 / 7 candidates — shouldn't happen in 0.8.1).
                    skip_reason = SkipReason.STRATEGY_NO_BUY
                elif none_count == evaluated_count:
                    skip_reason = SkipReason.INSUFFICIENT_HISTORICAL_DATA
                else:
                    skip_reason = SkipReason.ALL_SLOTS_EMPTY_NO_TRIGGER
                return BuyEvaluationResult(
                    buy=None,
                    skip_reason=skip_reason,
                    reasoning={
                        **reasoning_base,
                        "candidate_slot_numbers": ",".join(
                            str(n) for n in sorted(candidate_slot_numbers)
                        ),
                        "evaluated_count": str(evaluated_count),
                        "none_count": str(none_count),
                    },
                )

            # Smallest slot_number wins (ADR §2.2.4).
            target_slot_number, target_indicator_value = min(
                triggers, key=lambda t: t[0]
            )

        assert target_slot_number is not None
        assert target_indicator_value is not None

        # ------------------------------------------------------------------
        # 6. Compute order quantity / price (lot + tick aligned).
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
                    "target_slot_number": str(target_slot_number),
                    "trigger_indicator": str(target_indicator_value),
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
                    "target_slot_number": str(target_slot_number),
                    "target_quantity": str(target_quantity),
                    "target_price": str(target_price),
                    "actual_cost": str(actual_cost),
                },
            )

        # ------------------------------------------------------------------
        # 7. Buy intent. ``trigger_indicator`` records the indicator value
        #    that triggered (or current_price for slot 1 first-buy) for
        #    later retrospective analysis (CLAUDE.md §8.1).
        # ------------------------------------------------------------------
        slot_label = _slot_label(target_slot_number)
        buy_reasoning = {
            "slot_label": slot_label,
            "trigger_indicator": str(target_indicator_value),
            "current_price": str(current_price.value),
            "target_quantity": str(target_quantity),
            "target_price": str(target_price),
            "actual_cost": str(actual_cost),
        }

        return BuyEvaluationResult(
            buy=BuyDecision(
                slot_number=target_slot_number,
                target_quantity=target_quantity,
                target_price=target_price,
                reasoning=buy_reasoning,
            ),
            skip_reason=None,
            reasoning={
                **reasoning_base,
                "target_slot_number": str(target_slot_number),
                "trigger_indicator": str(target_indicator_value),
                "slot_label": slot_label,
            },
        )

    @staticmethod
    def _evaluate_slot_indicator(
        slot_number: int, closes: list[Decimal]
    ) -> Decimal | None:
        """Phase 0.8.1 slot mapping (ADR §2.2.1). Returns None when window
        insufficient OR slot is beyond 0.8.1 (slots 6/7 reserved for 0.8.2).
        """
        ma_window = _MA_WINDOWS.get(slot_number)
        if ma_window is not None:
            return calculate_sma(closes, ma_window)
        if slot_number == 5:
            return find_recent_high(closes, _RECENT_HIGH_WINDOW)
        return None


def _slot_label(slot_number: int) -> str:
    """Phase 0.8.1 slot label (ADR §2.2.1). Used for Decision.reasoning."""
    if slot_number == 1:
        return "first_buy"
    if slot_number in _MA_WINDOWS:
        return f"MA{_MA_WINDOWS[slot_number]}"
    if slot_number == 5:
        return f"recent_high({_RECENT_HIGH_WINDOW})"
    return f"slot_{slot_number}"
