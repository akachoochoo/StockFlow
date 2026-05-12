"""Phase 0.11.b — Walk-Forward Optimization splitter (ADR 0008 §1.8).

K-fold WFO with purge gap. Bar 인덱스 기반 (int), deterministic ordering
(D12 reproducibility). Statistical power: 각 fold train_bars >=
min_cycle_bars * 3 (3 complete cycles per fold, Architect 권고).

Edge case: n_bars < min_cycle_bars * 5 → ValueError (fold 1 개 미만으로
WFO 의 multi-fold 평균 정신 위반).

Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

from decimal import Decimal


def _wfo_split(
    n_bars: int,
    *,
    n_folds: int = 5,
    train_ratio: Decimal = Decimal("0.8"),
    purge_gap: int = 5,
    min_cycle_bars: int = 60,
) -> list[tuple[range, range]]:
    """Walk-forward fold split.

    Args:
        n_bars: 전체 bar 수 (>= min_cycle_bars * 5).
        n_folds: fold 수 (default 5, ADR 0008 D2).
        train_ratio: train / (train + test) 비율 (default 0.8 = 80% train).
        purge_gap: train_end 와 test_start 사이 buffer bars (default 5,
            ADR 0008 D8 가드레일 — leakage 방지).
        min_cycle_bars: 1 cycle 의 최소 bar 수 (default 60, ~3 month
            grid trading cycle 가정). train_bars >= min_cycle_bars * 3
            보장.

    Returns:
        list of (train_indices, test_indices) tuples. Each = `range` object
        (deterministic, hashable, ordered).

    Raises:
        ValueError: n_folds < 1, train_ratio outside (0, 1), purge_gap < 0,
            min_cycle_bars < 1, or n_bars < min_cycle_bars * 5 (insufficient
            statistical power).

    Algorithm (Architect 권고 — 3 cycles per fold):
        - fold_size = n_bars / n_folds
        - train_bars = fold_size * train_ratio (floored to int)
        - test_bars = fold_size - train_bars - purge_gap
        - fold_i: train = [i*fold_size, i*fold_size + train_bars),
                  test  = [train_end + purge_gap, (i+1)*fold_size)
    """
    if n_folds < 1:
        raise ValueError(f"n_folds must be >= 1, got {n_folds}")
    if not (Decimal("0") < train_ratio < Decimal("1")):
        raise ValueError(f"train_ratio must be in (0, 1), got {train_ratio}")
    if purge_gap < 0:
        raise ValueError(f"purge_gap must be >= 0, got {purge_gap}")
    if min_cycle_bars < 1:
        raise ValueError(f"min_cycle_bars must be >= 1, got {min_cycle_bars}")

    # Statistical power guard: 5 folds * 1 cycle min = 5 cycles total
    if n_bars < min_cycle_bars * 5:
        raise ValueError(
            f"n_bars ({n_bars}) < min_cycle_bars * 5 ({min_cycle_bars * 5}) — "
            f"insufficient statistical power for WFO"
        )

    fold_size = n_bars // n_folds
    train_bars = int(Decimal(fold_size) * train_ratio)
    test_bars = fold_size - train_bars - purge_gap

    if train_bars < min_cycle_bars * 3:
        raise ValueError(
            f"train_bars ({train_bars}) < min_cycle_bars * 3 "
            f"({min_cycle_bars * 3}) — increase n_bars or reduce n_folds"
        )
    if test_bars < 1:
        raise ValueError(
            f"test_bars ({test_bars}) < 1 — reduce purge_gap or train_ratio"
        )

    splits: list[tuple[range, range]] = []
    for i in range(n_folds):
        train_start = i * fold_size
        train_end = train_start + train_bars
        test_start = train_end + purge_gap
        test_end = test_start + test_bars
        splits.append((range(train_start, train_end), range(test_start, test_end)))
    return splits
