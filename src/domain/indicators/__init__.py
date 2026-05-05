"""Domain indicators (Phase 0.8 — ADR 0004 §2.3).

Pure functions on ``list[Decimal]`` of closes. No external dependency
beyond the standard library + Decimal (CLAUDE.md §1.1).

Phase 0.8.1 surface (slots 1~5):
    - calculate_sma — slots 2 (MA5), 3 (MA10), 4 (MA20)
    - find_recent_high — slot 5 (recent_high(60))

Phase 0.8.2 will add bollinger / rsi (slots 6~7) — see ADR 0004 §2.3.2.
"""
from __future__ import annotations

from src.domain.indicators.moving_average import calculate_sma
from src.domain.indicators.recent_high import find_recent_high

__all__ = ["calculate_sma", "find_recent_high"]
