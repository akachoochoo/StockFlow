"""Capital-tier rollback artifact (Phase 1.1 Stage 8-8 / ADR 0012 D19).

During staged capital expansion (200→300→500만, D10/D12), a no-incident
*violation* (an operational / integrity incident — NOT a P&L loss, ADR 0020 §4)
triggers a **rollback to the previous tier** (D19 (a)): e.g. a violation while
at 300 reverts to 200; the operator then runs 5 more no-incident business days
before re-attempting 300. Cumulative rollbacks reaching ``max_rollbacks`` (D19
default 3) — or a violation at the 200 floor (nowhere lower to go) — **ends
Phase 1.1** (회고 commit + Phase 1.2 진입 결정 라운드).

This module is a *pure* planner + log schema: :func:`plan_capital_rollback`
computes the next tier (or termination) and returns a :class:`RollbackLogEntry`
the operator records. It does **not** itself mutate config or place/cancel
orders — capital change is a human action (D10 / D19, every expansion AND every
rollback is operator-explicit). Clock is injected (CLAUDE.md §3.2).

Ring 2 (cli); imports the CapitalTier of the arming gate (live_gate) only.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.cli.live_gate import CapitalTier

# Ascending tier ladder (D10 staged-expansion order).
_TIER_LADDER: tuple[CapitalTier, ...] = (
    CapitalTier.TIER_200,
    CapitalTier.TIER_300,
    CapitalTier.TIER_500,
)

DEFAULT_MAX_ROLLBACKS = 3  # ADR 0012 D19 — cumulative ≥ 3 → Phase 1.1 종료.


def previous_tier(tier: CapitalTier) -> CapitalTier | None:
    """The tier one step below ``tier`` on the ladder, or None at the floor."""
    index = _TIER_LADDER.index(tier)
    return _TIER_LADDER[index - 1] if index > 0 else None


@dataclass(frozen=True)
class RollbackLogEntry:
    """An auditable record of one capital-tier rollback decision (D19).

    ``phase_terminated`` is True when this violation ends Phase 1.1 — either the
    cumulative rollback count reached ``max_rollbacks`` or the violation
    occurred at the 200 floor (no lower tier). When terminated, ``to_tier``
    equals ``from_tier`` (no productive rollback; the phase ends instead).
    """

    occurred_at: str  # ISO-8601 UTC timestamp (injected)
    from_tier: str  # CapitalTier.name at the time of the violation
    to_tier: str  # the tier to revert to (== from_tier when terminated)
    reason: str  # the no-incident violation reason (operational / integrity)
    cumulative_rollbacks: int  # including this one
    phase_terminated: bool

    def to_dict(self) -> dict[str, str | int | bool]:
        """Serialise to the rollback-log schema (JSON-ready: str/int/bool)."""
        return {
            "occurred_at": self.occurred_at,
            "from_tier": self.from_tier,
            "to_tier": self.to_tier,
            "reason": self.reason,
            "cumulative_rollbacks": self.cumulative_rollbacks,
            "phase_terminated": self.phase_terminated,
        }


def plan_capital_rollback(
    *,
    current_tier: CapitalTier,
    prior_rollback_count: int,
    reason: str,
    occurred_at: str,
    max_rollbacks: int = DEFAULT_MAX_ROLLBACKS,
) -> RollbackLogEntry:
    """Plan the rollback for a no-incident violation at ``current_tier``.

    Returns the :class:`RollbackLogEntry` to record. ``prior_rollback_count``
    is the number of rollbacks BEFORE this one; the entry's
    ``cumulative_rollbacks`` includes this violation. Termination (Phase 1.1
    종료) occurs when the cumulative count reaches ``max_rollbacks`` OR the
    violation is at the 200 floor (no lower tier); otherwise the tier reverts
    one step down the ladder.
    """
    if prior_rollback_count < 0:
        raise ValueError(
            f"prior_rollback_count must be >= 0, got {prior_rollback_count}"
        )
    cumulative = prior_rollback_count + 1
    prev = previous_tier(current_tier)
    terminated = cumulative >= max_rollbacks or prev is None
    to_tier = current_tier if (terminated or prev is None) else prev
    return RollbackLogEntry(
        occurred_at=occurred_at,
        from_tier=current_tier.name,
        to_tier=to_tier.name,
        reason=reason,
        cumulative_rollbacks=cumulative,
        phase_terminated=terminated,
    )


__all__ = [
    "DEFAULT_MAX_ROLLBACKS",
    "RollbackLogEntry",
    "plan_capital_rollback",
    "previous_tier",
]
