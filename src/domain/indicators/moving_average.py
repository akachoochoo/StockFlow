"""Moving-average indicator (ADR 0004 §2.3 / §2.4).

Phase 0.8.1 ships SMA only — slots 2 (MA5), 3 (MA10), 4 (MA20).
Phase 0.8.2 will reuse the same function for slot 6 (MA60).

Caller passes a list of closes already aligned to ``[..., as_of - 1]``
(look-ahead bias is the caller's responsibility — same convention as
``MovingAverageReentry`` in ``src.domain.strategies.reentry``). Returns
``None`` when fewer than ``window`` closes are available, signalling the
slot as not evaluable rather than raising.
"""
from __future__ import annotations

from decimal import Decimal


def calculate_sma(closes: list[Decimal], window: int) -> Decimal | None:
    """Simple moving average over the trailing ``window`` closes.

    Returns ``None`` when ``len(closes) < window`` — the caller treats
    the corresponding slot as not evaluable (no trigger fired).
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    if len(closes) < window:
        return None
    recent = closes[-window:]
    return sum(recent, Decimal(0)) / Decimal(window)
