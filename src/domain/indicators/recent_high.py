"""Recent-high indicator (ADR 0004 §2.2.1 slot 5 — Phase 0.8.1 simplified).

Phase 0.8.1 simplification: max of trailing-window closes (not the OHLC
high field). Park Young-ok's "지지로 전환" pattern is left for Phase
0.8.x refinement (ADR §2.7) — the simple N-day max is the documented
intent.

Caller passes closes already aligned to ``[..., as_of - 1]`` (look-ahead
bias is the caller's responsibility — same convention as
``calculate_sma``). Returns ``None`` when fewer than ``window`` closes
are available, signalling the slot as not evaluable rather than raising.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal


def find_recent_high(closes: list[Decimal], window: int) -> Decimal | None:
    """Maximum close over the trailing ``window`` bars.

    Returns ``None`` when ``len(closes) < window`` — the caller treats
    slot 5 as not evaluable (no trigger fired).
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    if len(closes) < window:
        return None
    return max(closes[-window:])
