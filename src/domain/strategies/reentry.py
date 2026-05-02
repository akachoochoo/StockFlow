"""Reentry price strategies (Phase 0.5 / ADR 0002 §4).

Two policies + a factory. The trigger price an EMPTY slot uses to qualify
for re-entry is computed here; the caller (PriceDropStrategy) compares
``current_price`` against the result.

Policy D-2 (MovingAverageReentry):
    anchor = mean(close for last N trading-day bars before as_of)
    trigger = anchor * (1 - drop_threshold_pct/100)
    Returns ``None`` when fewer than ``window`` historical bars are
    available — caller treats the slot as not evaluable.

Policy F (HybridTimeBasedReentry):
    Within cooldown_days of slot's last_exit_date:
        trigger = last_exit_price * (1 - drop_threshold_pct/100)
    Beyond cooldown:
        Same formula (Phase 0.5 keeps last_exit anchor for orthogonal
        comparison vs D-2; Phase 1+ may delegate to D-2 after cooldown).

Both policies return ``current_price`` unchanged when the slot has no
exit history (ADR §4.7 first-buy bypass) — caller fires immediately at
market.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from src.domain.models import Position, SplitSlot
    from src.ports.market_data import MarketDataPort
    from src.ports.reentry_strategy import ReentryPriceStrategyPort


@dataclass(frozen=True)
class MovingAverageReentry:
    """Policy D-2 — N-day moving-average anchored trigger.

    Phase 0.5 ships SMA only; ``ma_type="ema"`` reserved for Phase 1+.
    Look-ahead bias is prevented by fetching ``[as_of - buffer, as_of)``
    (end exclusive) so the as_of bar's close never enters the MA — see
    ADR §4.10.
    """

    market_data: MarketDataPort
    window: int = 20
    ma_type: str = "sma"

    def __post_init__(self) -> None:
        if not 1 <= self.window <= 500:
            raise ValueError(
                f"window must be in [1, 500], got {self.window}"
            )
        if self.ma_type != "sma":
            raise ValueError(
                f"ma_type {self.ma_type!r} not supported; "
                "Phase 0.5 only ships SMA"
            )

    def get_trigger_price(
        self,
        *,
        slot: SplitSlot,
        position: Position,
        current_price: Decimal,
        drop_threshold_pct: Decimal,
        as_of: date,
    ) -> Decimal | None:
        # First-buy bypass (ADR §4.7 narrowed): only when nothing has ever
        # been bought (split_level == 0). All EMPTY slots get this bypass
        # in that case so the strategy's slot-priority loop fires slot 1.
        if position.split_level == 0:
            return current_price
        # Note: slot.last_exit_date is irrelevant here — the SMA-based
        # anchor doesn't depend on slot history. Subsequent splits and
        # post-sell re-entries share the same SMA-derived trigger.

        # Calendar buffer (ADR §4.10): max(int(window*1.6) + 10, 30).
        buffer_days = max(int(self.window * 1.6) + 10, 30)
        start = as_of - timedelta(days=buffer_days)

        # Fetch bars in [start, as_of - 1 day] — as_of bar excluded
        # (look-ahead prevention). get_ohlcv is inclusive on both ends,
        # so subtract 1 day from the upper bound.
        bars = self.market_data.get_ohlcv(
            position.asset, start, as_of - timedelta(days=1)
        )
        if len(bars) < self.window:
            return None

        recent = bars[-self.window :]
        sma = sum((b.close for b in recent), Decimal(0)) / Decimal(self.window)
        return sma * (1 - drop_threshold_pct / Decimal(100))


@dataclass(frozen=True)
class HybridTimeBasedReentry:
    """Policy F — last_exit anchored within cooldown.

    ``cooldown_days`` is inclusive of day 0 (matches ADR §4.6 — same-day
    re-entry uses the conservative anchor). Beyond cooldown, Phase 0.5
    keeps the last_exit anchor for orthogonal comparison vs D-2.

    Fresh-slot fallback (ADR §4.3 / §4.7 5차): for an EMPTY slot in a
    non-empty position whose ``last_exit_*`` is None (never been bought),
    F uses ``position.avg_price`` as the anchor — Phase 0 D behaviour.
    """

    cooldown_days: int = 60

    def __post_init__(self) -> None:
        if not 0 <= self.cooldown_days <= 365:
            raise ValueError(
                f"cooldown_days must be in [0, 365], got {self.cooldown_days}"
            )

    def get_trigger_price(
        self,
        *,
        slot: SplitSlot,
        position: Position,
        current_price: Decimal,
        drop_threshold_pct: Decimal,
        as_of: date,
    ) -> Decimal | None:
        # First-buy bypass (ADR §4.7 narrowed): only when nothing has ever
        # been bought (split_level == 0). Subsequent splits go through
        # one of the two anchor branches below.
        if position.split_level == 0:
            return current_price
        # Slot has exit history → cooldown rule (Phase 0.5 keeps the
        # last_exit anchor regardless of cooldown elapsed; see §4.3).
        if slot.last_exit_date is not None and slot.last_exit_price is not None:
            return slot.last_exit_price * (1 - drop_threshold_pct / Decimal(100))
        # Fresh slot in non-empty position → Phase 0 D fallback (avg_price).
        return position.avg_price * (1 - drop_threshold_pct / Decimal(100))


def create_reentry_strategy(
    name: str,
    *,
    market_data: MarketDataPort | None = None,
    **params: object,
) -> ReentryPriceStrategyPort:
    """Factory dispatch by policy name (ADR §4.9).

    YAML loader's single entry point. Unknown name → ``ValueError``;
    missing required dependency → ``ValueError``.
    """
    if name == "moving_average":
        if market_data is None:
            raise ValueError(
                "moving_average policy requires market_data dependency"
            )
        window = params.get("window", 20)
        ma_type = params.get("ma_type", "sma")
        if not isinstance(window, int):
            raise ValueError(
                f"moving_average requires int window, got {window!r}"
            )
        if not isinstance(ma_type, str):
            raise ValueError(
                f"moving_average requires str ma_type, got {ma_type!r}"
            )
        return MovingAverageReentry(
            market_data=market_data, window=window, ma_type=ma_type
        )
    if name == "hybrid":
        cooldown = params.get("cooldown_days", 60)
        if not isinstance(cooldown, int):
            raise ValueError(
                f"hybrid policy requires int cooldown_days, got {cooldown!r}"
            )
        return HybridTimeBasedReentry(cooldown_days=cooldown)
    raise ValueError(
        f"unknown reentry strategy {name!r}; "
        "expected 'moving_average' or 'hybrid'"
    )
