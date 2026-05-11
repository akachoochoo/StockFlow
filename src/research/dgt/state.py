"""Phase 0.11.a — _DGTGridState (DGT runner 의 grid + accounting state).

ADR 0007 §1.7 Lifecycle + Critic Round 1 Gap #2 흡수: **독립 model**.
src/domain/Balance 재사용 안 함 (inner ring mutation risk 회피 — 회귀 invariant 보존).

CLAUDE.md §2.1 — Decimal-only. Mutable (runner step 마다 갱신).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class _DGTGridState:
    """Grid + cash + holdings state for DGTPrototypeRunner.

    Mutable — runner.run() loop 안에서 cash / holdings / wallet 갱신.
    Underscore-prefix private (ADR 0007 §1.6.3, __all__ = []).
    """

    reference_price: Decimal
    grid_levels: list[Decimal]
    cash: Decimal
    holdings: Decimal
    wallet: Decimal = Decimal("0")
    trades_count: int = 0
