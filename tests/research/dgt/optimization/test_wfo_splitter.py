"""Phase 0.11.b — WFO splitter tests (AC1~AC10).

ADR 0008 §1.11 oracle 박제. Bar 인덱스 기반 + purge gap + 3-cycle statistical
power guard.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.research.dgt.optimization._wfo_splitter import _wfo_split


class TestAC1FoldCount:
    def test_default_n_folds_5(self) -> None:
        splits = _wfo_split(n_bars=1500)
        assert len(splits) == 5

    def test_n_folds_explicit(self) -> None:
        splits = _wfo_split(n_bars=2000, n_folds=4)
        assert len(splits) == 4


class TestAC2PurgeGap:
    def test_purge_gap_default_5(self) -> None:
        splits = _wfo_split(n_bars=1500)
        for train, test in splits:
            # train_end (exclusive) + purge_gap == test_start
            assert test.start - train.stop == 5

    def test_purge_gap_custom(self) -> None:
        splits = _wfo_split(n_bars=2000, purge_gap=10)
        for train, test in splits:
            assert test.start - train.stop == 10


class TestAC3TrainTestSplit:
    def test_default_train_ratio_0_8(self) -> None:
        # n_bars=1500, n_folds=5 → fold_size=300, train=240, test=300-240-5=55
        splits = _wfo_split(n_bars=1500)
        train, test = splits[0]
        assert len(train) == 240
        assert len(test) == 55

    def test_custom_train_ratio(self) -> None:
        # n_bars=2500, n_folds=5 → fold_size=500, train=350 (ratio=0.7), test=500-350-5=145
        splits = _wfo_split(n_bars=2500, train_ratio=Decimal("0.7"))
        train, test = splits[0]
        assert len(train) == 350
        assert len(test) == 145


class TestAC4MinCycle:
    def test_default_min_cycle_3x_guard(self) -> None:
        # min_cycle_bars=60 default → train_bars >= 180
        splits = _wfo_split(n_bars=1500)
        for train, _ in splits:
            assert len(train) >= 180

    def test_custom_min_cycle(self) -> None:
        # min_cycle_bars=30 → train_bars >= 90 (relaxed)
        splits = _wfo_split(n_bars=600, min_cycle_bars=30)
        for train, _ in splits:
            assert len(train) >= 90


class TestAC5EdgeCase:
    def test_insufficient_n_bars_raises(self) -> None:
        # min_cycle_bars=60 → need >= 300 n_bars
        with pytest.raises(ValueError, match="insufficient statistical power"):
            _wfo_split(n_bars=200)

    def test_train_bars_below_3_cycle_raises(self) -> None:
        # n_bars=400 (>= 300 power check) but n_folds=5 → fold_size=80,
        # train_bars=64 < 180 (min_cycle*3) → raises
        with pytest.raises(ValueError, match="min_cycle_bars \\* 3"):
            _wfo_split(n_bars=400)

    def test_invalid_n_folds(self) -> None:
        with pytest.raises(ValueError, match="n_folds must be >= 1"):
            _wfo_split(n_bars=1500, n_folds=0)

    def test_invalid_train_ratio(self) -> None:
        with pytest.raises(ValueError, match="train_ratio must be in"):
            _wfo_split(n_bars=1500, train_ratio=Decimal("0"))
        with pytest.raises(ValueError, match="train_ratio must be in"):
            _wfo_split(n_bars=1500, train_ratio=Decimal("1"))

    def test_invalid_purge_gap(self) -> None:
        with pytest.raises(ValueError, match="purge_gap must be >= 0"):
            _wfo_split(n_bars=1500, purge_gap=-1)


class TestAC6Determinism:
    def test_two_calls_identical(self) -> None:
        a = _wfo_split(n_bars=1500)
        b = _wfo_split(n_bars=1500)
        assert a == b

    def test_two_calls_custom_identical(self) -> None:
        a = _wfo_split(n_bars=2000, n_folds=4, train_ratio=Decimal("0.75"), purge_gap=10)
        b = _wfo_split(n_bars=2000, n_folds=4, train_ratio=Decimal("0.75"), purge_gap=10)
        assert a == b


class TestAC7BoundaryNBars:
    def test_exact_5_fold_split(self) -> None:
        # n_bars=1500, n_folds=5 → exact fold_size=300
        splits = _wfo_split(n_bars=1500)
        fold_starts = [tr.start for tr, _ in splits]
        assert fold_starts == [0, 300, 600, 900, 1200]


class TestAC8NoOverlap:
    def test_train_test_disjoint(self) -> None:
        splits = _wfo_split(n_bars=1500)
        for train, test in splits:
            train_set = set(train)
            test_set = set(test)
            assert train_set.isdisjoint(test_set)

    def test_purge_bars_excluded_from_both(self) -> None:
        splits = _wfo_split(n_bars=1500)
        train, test = splits[0]
        # purge gap bars = [240, 245) = {240, 241, 242, 243, 244}
        purge_bars = set(range(train.stop, test.start))
        assert not any(b in train for b in purge_bars)
        assert not any(b in test for b in purge_bars)


class TestAC9PurgeGap0:
    def test_zero_purge_gap_adjacent(self) -> None:
        splits = _wfo_split(n_bars=1500, purge_gap=0)
        for train, test in splits:
            # train_end == test_start when purge=0
            assert train.stop == test.start


class TestAC10LargeFolds:
    def test_10_folds_uniform(self) -> None:
        # n_bars=3000, n_folds=10 → fold_size=300, train=240
        splits = _wfo_split(n_bars=3000, n_folds=10)
        assert len(splits) == 10
        for train, _ in splits:
            assert len(train) == 240
