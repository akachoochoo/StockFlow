"""NullSignal — Phase 0 SignalPort that always returns NORMAL.

This adapter exists so that PriceDropStrategy + DailyOrchestrator can be
wired identically across Phase 0 (no circuit breaker) and Phase 2 (full
circuit breaker). Replacing this adapter with a real one in Phase 2 requires
zero changes to the orchestrator or strategy.
"""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from src.domain.models import CircuitBreakerSignal, SignalLevel, SignalSource

if TYPE_CHECKING:
    from datetime import datetime

    from src.domain.models import AssetClass


# Phase 0 NullSignal validity window. Long enough that a single daily
# evaluation never expires within a session; short enough that staleness
# would still surface if accidentally reused over many days.
_VALIDITY_WINDOW = timedelta(days=1)


class NullSignal:
    """Always-NORMAL SignalPort implementation for Phase 0."""

    def collect(
        self, asset_class: AssetClass, as_of: datetime
    ) -> CircuitBreakerSignal:
        return CircuitBreakerSignal(
            level=SignalLevel.NORMAL,
            source=SignalSource.NULL,
            asset_class=asset_class,
            evaluated_at=as_of,
            triggered_by=[],
            reasoning={},
            valid_until=as_of + _VALIDITY_WINDOW,
        )
