"""StopLossPolicy — position-loss breach detection (Phase 1.1 Stage 6).

ADR 0012 D2(b'): when a position's price-only loss reaches ``-max_loss_pct``,
the system MUST (1) block further buys for that asset and (2) recommend a
manual sell review via Telegram. It MUST NEVER auto-sell (CLAUDE.md §11.4 —
Phase 0 기준 자동 손절 안 함). This policy is a *pure* breach detector: it
reports whether the threshold was crossed and the current loss percent; the
caller decides what to do with that signal.

``max_loss_pct`` is a positive magnitude in percent units: e.g. ``Decimal("20")``
means a -20 % drawdown triggers a breach. ADR 0012 D2(b') default = 20.

Domain rules (CLAUDE.md §1.1, §3.2): no external imports (stdlib + pydantic
only), no datetime.now() / date.today() — breach is purely a function of the
*current price vs the position's average price*, with no clock dependency.
All money/price values are Decimal (§2.1/§2.3); I/O is zero.

This class is a stand-alone policy — it is NOT wired into the orchestrator or
any runner. Orchestrator/runner integration (buy block + Telegram review
recommendation + manual-sell flow) is Stage 8.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import field_validator

from src.domain.models import ValueObject, _to_decimal

if TYPE_CHECKING:
    from src.domain.models import Position


class StopLossDecision(ValueObject):
    """Outcome of a StopLossPolicy evaluation (ADR 0012 D2(b')).

    Fields:
    - breached : True when ``loss_pct <= -max_loss_pct`` (threshold crossed).
    - loss_pct : the position's price-only return percent vs avg_price. A loss
                 is negative (e.g. ``Decimal("-21")`` = -21 %). Excludes
                 fees/taxes. Zero when there is no position.
    """

    breached: bool
    loss_pct: Decimal

    @field_validator("loss_pct", mode="before")
    @classmethod
    def _coerce_loss_pct(cls, v: object) -> Decimal:
        return _to_decimal(v)


class StopLossPolicy:
    """Stateless price-vs-avg-price loss breach detector (ADR 0012 D2(b')).

    ``evaluate`` returns a :class:`StopLossDecision`. When ``breached`` is True,
    the caller must (1) block further buys for the asset and (2) recommend a
    manual sell review (Telegram). This policy NEVER auto-sells (CLAUDE.md
    §11.4 — 자동 손절 금지). ``max_loss_pct`` is injected from config (ADR 0012
    D2(b') default 20). Orchestrator/runner wiring is Stage 8.
    """

    def evaluate(
        self,
        *,
        position: Position,
        current_price: Decimal,
        max_loss_pct: Decimal,
    ) -> StopLossDecision:
        """Detect whether ``position`` has breached the loss limit.

        Args:
            position: the current holding. No position (quantity <= 0 or
                avg_price <= 0) → not breached, loss_pct = 0.
            current_price: the spot price (Decimal). Caller is responsible for
                passing a trusted, validated price.
            max_loss_pct: positive magnitude in percent (e.g. Decimal("20") for
                a -20 % stop-loss trigger).

        Returns:
            StopLossDecision with ``loss_pct`` = price-only return percent and
            ``breached`` = (loss_pct <= -max_loss_pct). Exactly -max_loss_pct
            counts as a breach (``<=``).
        """
        if position.quantity <= 0 or position.avg_price <= 0:
            return StopLossDecision(breached=False, loss_pct=Decimal(0))

        loss_pct = (
            (current_price - position.avg_price)
            / position.avg_price
            * Decimal(100)
        )
        breached = loss_pct <= -max_loss_pct
        return StopLossDecision(breached=breached, loss_pct=loss_pct)
