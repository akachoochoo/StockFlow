"""Phase 0.11.b — PBO (Probability of Backtest Overfitting), ADR 0008 §1.6 D8 (iv) optional.

Bailey, D. H., Borwein, J., López de Prado, M., & Zhu, Q. J. (2017). "The
Probability of Backtest Overfitting." Journal of Computational Finance, 20(4).

Simplified path (ADR 0008 §1.6 D8 (iv) optional informational + computation
budget 정합):
- Combinatorial split of N WFO folds into 2 halves (S, S_bar).
- For each split: rank grid points by in-sample (S) Sharpe vs OOS (S_bar) Sharpe.
- omega = log(rank_OOS / (N_strats - rank_OOS)) — relative rank logit.
- PBO = fraction of best-in-IS strategies that land OOS rank below median.

본 sub-step 의 simplified path:
- Per grid point: in-sample SR vs OOS SR rank 비교 (sub-step .3 산출 _GridPointResult
  의 is_sharpe / oos_sharpe 활용 — 재실행 zero).
- Combinatorial folds split 가 grid-runner _GridPointResult 에는 흡수되어 있어
  본 sub-step 에서는 N grid points × IS/OOS aggregate rank 비교 path.

Bailey-Lopez 2017 임계: PBO < 0.5 = no overfitting / PBO > 0.5 = overfitting suspect.

Decimal-only (CLAUDE.md §2.1). stdlib only. Underscore-prefix private
(ADR 0007 §1.6.3).
"""
from __future__ import annotations

from decimal import Decimal
from itertools import combinations

from src.research.dgt.optimization._grid_runner import _GridPointResult


def _compute_pbo(
    grid_results: list[_GridPointResult],
    n_folds: int = 5,
) -> Decimal:
    """Simplified PBO calculation from grid_runner WFO aggregate results.

    Algorithm (simplified — ADR 0008 §1.6 D8 (iv) optional informational):
        - Combinatorial split of n_folds into 2 halves (S, S_bar).
          C(n_folds, n_folds//2) = C(5, 2) = 10 splits (asymmetric for odd N).
        - 본 sub-step 의 grid_results 는 이미 fold-aggregate 산출이므로:
          - IS rank = rank by is_sharpe (desc, 1 = best).
          - OOS rank = rank by oos_sharpe (desc).
        - For each grid point N_strat: omega = log_normalized rank shift.
          PBO ≈ fraction of grid points where OOS rank > median (worse than median).
        - 단순화: best-in-IS (top-half by is_sharpe) 중 bottom-half OOS (oos_sharpe
          median 이하) 비율.

    Args:
        grid_results: `_GridPointResult` list (full grid, sub-step .3 산출).
        n_folds: WFO fold 수 — combinatorial split count 계산용 (default 5).

    Returns:
        PBO Decimal in [0, 1]. 0 = no overfitting, 1 = total overfitting.

    Raises:
        ValueError: grid_results empty or n_folds < 2.
    """
    if not grid_results:
        raise ValueError("grid_results must be non-empty")
    if n_folds < 2:
        raise ValueError(f"n_folds must be >= 2, got {n_folds}")

    n_strats = len(grid_results)
    if n_strats < 2:
        return Decimal("0")

    # Combinatorial splits — informational count (C(n_folds, n_folds//2))
    half = n_folds // 2
    n_splits = sum(1 for _ in combinations(range(n_folds), half))
    if n_splits == 0:
        return Decimal("0")

    # Simplified PBO calculation — single split (IS-aggregate vs OOS-aggregate).
    # Bailey 2017 의 정통 N-split combinatorial 은 fold-별 raw IS/OOS 시계열을
    # 필요로 함 → grid_results aggregate 만 입력 가능한 본 sub-step 의 simplified
    # path.

    # Rank by is_sharpe desc (1 = best).
    is_ranked = sorted(
        range(n_strats),
        key=lambda i: (-grid_results[i].is_sharpe, i),
    )
    # Rank by oos_sharpe desc (1 = best).
    oos_ranked = sorted(
        range(n_strats),
        key=lambda i: (-grid_results[i].oos_sharpe, i),
    )

    is_rank = [0] * n_strats
    oos_rank = [0] * n_strats
    for rank_pos, idx in enumerate(is_ranked):
        is_rank[idx] = rank_pos + 1
    for rank_pos, idx in enumerate(oos_ranked):
        oos_rank[idx] = rank_pos + 1

    # Bailey 2017 PBO simplification: among top-half IS strategies, fraction
    # that land bottom-half OOS.
    median = Decimal(n_strats) / Decimal("2")
    top_is_strats = [i for i in range(n_strats) if Decimal(is_rank[i]) <= median]
    if not top_is_strats:
        return Decimal("0")
    bottom_oos_count = sum(
        1 for i in top_is_strats if Decimal(oos_rank[i]) > median
    )
    pbo = Decimal(bottom_oos_count) / Decimal(len(top_is_strats))
    return pbo


__all__: list[str] = []
