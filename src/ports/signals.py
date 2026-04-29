"""Circuit breaker signal port.

Phase 0 uses NullSignal which always returns level=NORMAL, source=NULL.
Phase 2 introduces rule-based and AI-based signals (design doc §3.4).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.models import AssetClass, CircuitBreakerSignal


class SignalPort(Protocol):
    """Circuit breaker signal source for a given asset class.

    Implementations encapsulate the Collect → Evaluate pipeline (design doc
    §3.4) and return a single CircuitBreakerSignal per call. The orchestrator
    uses the signal's `level` to decide whether to proceed, throttle, or
    halt new entries (and, for EMERGENCY, reduce positions).

    `as_of` is required for the same time-injection reason as MarketDataPort
    (CLAUDE.md §3.2).
    """

    def collect(
        self, asset_class: AssetClass, as_of: datetime
    ) -> CircuitBreakerSignal:
        """Evaluate the circuit breaker for `asset_class` at `as_of` (UTC)."""
        ...
