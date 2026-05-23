"""Live-trading arming gate (Phase 1.1 Stage 8-3 / M4 — codifiable D16).

The single function ``assert_armed_for_live`` is the last guard before any
real-money order leaves the runner. It is a strict AND-gate over the **five
machine-checkable per-run conditions** (ADR 0012 §4 Pre-mortem scenario 2 /
roadmap Stage 8): if any one fails, it raises and the runner places no orders.

    (1) the persistent halt sentinel is absent,
    (2) the system clock is NTP-synced (D16 (vi)),
    (3) today's reconciliation matched — supplied as the *in-process*
        ``ReconciliationResult.matched`` (NOT inferred from a file / sentinel,
        so a stale recon can never silently arm),
    (4) the intended capital tier is within the human-authorized cap, and
    (5) a human arming token is present — a CLI ``--arm-live <tier>`` AND an
        environment double-confirm, so a stray flag alone cannot arm.

The *manual* D16 entry-audit conditions (i)~(v) — ADR §1 박제 commits, sub-step
completion, paper-trading no-incident days, the D6 entry gate — are NOT checked
here: they are one-time pre-entry evidence (commit hashes + paper logs) audited
at Stage 8-7, not per-run state. This function codifies only what a machine can
re-verify on every run (M4).

Real orders stay structurally blocked until the runner (Stage 8-5) calls this
and it returns without raising — discipline is enforced by *structure*, not
convention (Principle #1). Ring 2 (cli); imports domain exceptions + the
reconciliation result type (inward) only.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from src.domain.exceptions import ClockSkewError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.use_cases.reconciliation import ReconciliationResult

# Environment double-confirm for live arming. Must be set (to the armed tier's
# name) IN ADDITION to the CLI --arm-live flag — a flag alone cannot arm.
ARM_LIVE_ENV = "TRADING_ARM_LIVE"


class CapitalTier(Enum):
    """Phase 1.1 staged capital tiers (ADR 0012 D10 / D12 — 200→300→500만원).

    Value is the tier ceiling in KRW (Decimal, CLAUDE.md §2). Staged expansion
    is gated by per-tier no-incident operation (G2.1~G2.3) and every expansion
    is a human decision (D10 / D19).
    """

    TIER_200 = Decimal("2000000")
    TIER_300 = Decimal("3000000")
    TIER_500 = Decimal("5000000")

    @property
    def krw(self) -> Decimal:
        """The tier ceiling in KRW."""
        return self.value


class LiveArmingError(RuntimeError):
    """Live arming refused — a per-run arming condition is unmet.

    The runner must NOT place live orders. Not caught anywhere in the live
    path → the process stops before any money moves (ADR 0012 §4 scenario 2 /
    Principle #4).
    """


@dataclass(frozen=True)
class LiveArmingToken:
    """A human's live-trading authorization.

    Built from the CLI ``--arm-live <tier>`` flag plus the ``TRADING_ARM_LIVE``
    environment double-confirm. ``env_confirmed`` is True only when the env var
    was present AND matched the CLI tier — both halves must agree, so neither a
    stray flag nor a stray env var can arm on its own.
    """

    tier_cap: CapitalTier
    env_confirmed: bool


def capital_tier_from_str(value: str) -> CapitalTier:
    """Map a CLI tier string ('200'/'300'/'500') to a :class:`CapitalTier`."""
    mapping = {
        "200": CapitalTier.TIER_200,
        "300": CapitalTier.TIER_300,
        "500": CapitalTier.TIER_500,
    }
    try:
        return mapping[value]
    except KeyError:
        raise LiveArmingError(
            f"unknown capital tier {value!r}; expected one of {sorted(mapping)}"
        ) from None


def build_arming_token(
    cli_tier: CapitalTier | None,
    *,
    env: Mapping[str, str],
) -> LiveArmingToken | None:
    """Construct the arming token from the CLI flag + environment double-confirm.

    Returns None when ``--arm-live`` was not passed (the safe default — not
    armed). Otherwise returns a token whose ``env_confirmed`` reflects whether
    ``TRADING_ARM_LIVE`` is present and equals the CLI tier's name (e.g.
    ``TIER_200``). The actual cap/confirm check happens in
    :func:`assert_armed_for_live`.
    """
    if cli_tier is None:
        return None
    raw = env.get(ARM_LIVE_ENV)
    env_confirmed = raw is not None and raw.strip() == cli_tier.name
    return LiveArmingToken(tier_cap=cli_tier, env_confirmed=env_confirmed)


def assert_armed_for_live(
    *,
    intended_tier: CapitalTier,
    token: LiveArmingToken | None,
    recon: ReconciliationResult,
    halt_active: bool,
    ntp_synced: bool,
) -> None:
    """Raise unless ALL five per-run arming conditions hold (strict AND-gate).

    Raises :class:`ClockSkewError` when the clock is not NTP-synced (an
    IntegrityError) and :class:`LiveArmingError` for every other unmet
    condition. Returns None when fully armed. Side-effect free — every input is
    threaded in (especially ``recon``, the in-process reconciliation result),
    so the decision is reproducible and never depends on ambient filesystem
    state.
    """
    # (1) Persistent halt sentinel must be absent.
    if halt_active:
        raise LiveArmingError(
            "halt sentinel is active — refusing to arm live trading "
            "(clear it with `trading resume` after human review)"
        )

    # (2) Clock must be NTP-synced (D16 (vi)). ClockSkewError → IntegrityError.
    if not ntp_synced:
        raise ClockSkewError(
            "clock not verified NTP-synced — refusing to arm live trading "
            "(fail-closed, CLAUDE.md §3.3)"
        )

    # (3) Today's reconciliation matched — the in-process result, not a file.
    if not recon.matched:
        raise LiveArmingError(
            "today's reconciliation did not match — refusing to arm "
            "(DB positions vs broker holdings mismatch; CLAUDE.md §11.2)"
        )

    # (4)+(5) Human arming token present and the intended tier within its cap.
    if token is None or not token.env_confirmed:
        raise LiveArmingError(
            "human arming token absent — refusing to arm "
            f"(need --arm-live <tier> AND {ARM_LIVE_ENV}=<tier> matching)"
        )
    if intended_tier.krw > token.tier_cap.krw:
        raise LiveArmingError(
            f"intended capital tier {intended_tier.name} "
            f"({intended_tier.krw} KRW) exceeds the armed cap "
            f"{token.tier_cap.name} ({token.tier_cap.krw} KRW) — refusing to arm"
        )


__all__ = [
    "ARM_LIVE_ENV",
    "CapitalTier",
    "LiveArmingError",
    "LiveArmingToken",
    "assert_armed_for_live",
    "build_arming_token",
    "capital_tier_from_str",
]
