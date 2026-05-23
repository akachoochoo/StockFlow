"""DGT grid math — geometric levels + adaptive k (Phase 1.x, ADR 0022 G1).

`src/research/dgt/formulas.py:grid_levels_table1` + `paper_adaptive_runner`
``_adaptive_k`` (use_trend 제외 — D3 invalidated, 최적 구성 미사용) 의 inner
ring **충실 포팅** (research → domain 승격, ADR 0022 D6). 순수 Decimal, 외부
import zero, 시계 의존 zero. research 버전과의 출력 동치는 테스트로 잠근다.

DGT 논문: Chen/Chen/Jang 2025 (arXiv:2506.11921), Table 1 geometric spacing.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from src.domain.indicators.volatility import (
    average_daily_range,
    average_true_range,
)

if TYPE_CHECKING:
    from src.domain.models import OHLCV


def grid_levels(
    n: int,
    reference_price: Decimal,
    k: Decimal,
    levels_above: int,
) -> list[Decimal]:
    """Geometric grid levels (n+1 prices, ascending).

    level_i = reference_price * (1 + k)^i, i in range(-(n-levels_above),
    levels_above + 1). research ``grid_levels_table1`` 와 동일.

    Raises:
        ValueError: n <= 0, levels_above ∉ [0, n], reference_price <= 0, k <= 0.
    """
    if n <= 0:
        raise ValueError(f"n must be > 0, got {n}")
    if not (0 <= levels_above <= n):
        raise ValueError(f"levels_above must be in [0, {n}], got {levels_above}")
    if reference_price <= 0:
        raise ValueError(f"reference_price must be > 0, got {reference_price}")
    if k <= 0:
        raise ValueError(f"k must be > 0, got {k}")

    levels_below = n - levels_above
    factor = Decimal(1) + k
    return [
        reference_price * (factor**i)
        for i in range(-levels_below, levels_above + 1)
    ]


def adaptive_k(
    bars: list[OHLCV],
    end_idx: int,
    close: Decimal,
    *,
    period: int,
    multiplier: Decimal,
    k_min: Decimal,
    k_max: Decimal,
    fallback_k: Decimal,
    measure: Literal["atr", "adr"] = "adr",
) -> Decimal:
    """Volatility-adaptive grid spacing k = clamp(vol_pct * multiplier, kmin, kmax).

    vol_pct = (ATR|ADR)(period) / close. 변동성↑ → k 넓음(거래 감소), 변동성↓ →
    k 좁음(횡보 수확). 변동성 0 또는 close ≤ 0 시 ``fallback_k`` (research
    ``_adaptive_k`` 의 ``config.k_ratio`` fallback 대응). use_trend(D3) 제외.
    """
    vol = (
        average_daily_range(bars, period, end_idx)
        if measure == "adr"
        else average_true_range(bars, period, end_idx)
    )
    if vol <= 0 or close <= 0:
        return fallback_k
    k = (vol / close) * multiplier
    return max(k_min, min(k_max, k))
