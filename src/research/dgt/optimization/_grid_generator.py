"""Phase 0.11.b — DGT parameter grid generator (ADR 0008 D4).

3+1 차원 grid (n / k / m + optional re_anchor_period). Decimal-only for `k`
(CLAUDE.md §2.1). `n`, `m`, `re_anchor_period` = int. Cartesian product via
`itertools.product`, deterministic ordering (sorted keys, D12 reproducibility).

Constraint: `m < n` (m=n 은 levels_below=0 으로 단방향 grid — paper Table 1
정합 위반). `_filter_valid` 가 m >= n 쌍 제거.

3-dim default = 5 * 5 * 4 = 100 점 (D10 budget ~100s 충족).
4-dim (re_anchor) = 100 * 4 = 400 점 (optional, D10 초과 → opt-in).

Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

from decimal import Decimal
from itertools import product


# n (grid_count): ADR 0008 §1.6 D4 (i) range 3~15, default 2. 박제 grid = 홀수
# only (대칭 grid, m < n/2 자연스러움).
_GRID_N: tuple[int, ...] = (3, 5, 7, 9, 11)

# k (grid_spacing_pct): ADR 0008 §1.6 D4 (ii) range 1~10%, default 1%. 박제
# grid = 1/2/3/5/7% (10% 은 boundary, 박제 7 까지).
_GRID_K: tuple[Decimal, ...] = (
    Decimal("1"),
    Decimal("2"),
    Decimal("3"),
    Decimal("5"),
    Decimal("7"),
)

# m (levels_above): ADR 0008 §1.6 D4 (iii) range 0~n, default 1. 박제 grid =
# 0/1/2/3 (n=3 최소 정합 — m<n 제약은 _filter_valid 에서 적용).
_GRID_M: tuple[int, ...] = (0, 1, 2, 3)

# re_anchor_period (days): ADR 0008 §1.6 D4 (iv) optional 4th 차원.
_GRID_RE_ANCHOR: tuple[int, ...] = (60, 120, 180, 240)


def _generate_grid(*, include_re_anchor: bool = False) -> list[dict[str, int | Decimal]]:
    """Cartesian product grid 생성.

    Args:
        include_re_anchor: True 시 4 차원 grid (re_anchor_period 포함).

    Returns:
        list of dicts, deterministic order. Each dict 은 sorted keys ordering.
        m >= n 쌍은 `_filter_valid` 로 제거됨.

    Default 3-dim grid size: 5 * 5 * 4 = 20 (before filter), filter 후 m < n
    인 쌍만 유지. 4-dim grid: 20 * 4 = 80 (before filter).

    Note: combined 점수는 (n, k, m) 삼중 product 라서 정확 = 5*5*4 = 100 (3-dim,
    pre-filter), 4-dim = 5*5*4*4 = 400 (pre-filter).
    """
    if include_re_anchor:
        raw: list[dict[str, int | Decimal]] = [
            {"k": k, "m": m, "n": n, "re_anchor_period": re_anchor}
            for n, k, m, re_anchor in product(
                _GRID_N, _GRID_K, _GRID_M, _GRID_RE_ANCHOR
            )
        ]
    else:
        raw = [
            {"k": k, "m": m, "n": n}
            for n, k, m in product(_GRID_N, _GRID_K, _GRID_M)
        ]
    return _filter_valid(raw)


def _filter_valid(
    grid: list[dict[str, int | Decimal]],
) -> list[dict[str, int | Decimal]]:
    """m < n constraint 적용 (m >= n 쌍 제거).

    Paper Table 1 정합 (ADR 0007 §1.0 reference): m == n 시 levels_below = 0
    → 단방향 grid (no sells below). m > n 은 grid_levels_table1 ValueError.
    """
    return [point for point in grid if int(point["m"]) < int(point["n"])]
