"""Phase 0.11.b — DGT grid generator tests (AC1~AC10).

ADR 0008 §1.11 oracle 박제. Decimal-only `k` invariant + m < n constraint.
"""
from __future__ import annotations

from decimal import Decimal

from src.research.dgt.optimization._grid_generator import (
    _filter_valid,
    _generate_grid,
)


# Pre-filter combinatorics: n=5, k=5, m=4 → 100 (3-dim); * re_anchor=4 → 400.
# Post-filter (m < n): m=3 invalid only when n=3 → eliminated 5 (k) * 1 (m=3,n=3)
# 점, so 100 - 5 = 95 (3-dim post-filter), 380 (4-dim post-filter).


class TestAC1Grid3DimCount:
    def test_3dim_grid_post_filter_count(self) -> None:
        grid = _generate_grid()
        # 5 (n) * 5 (k) * 4 (m) = 100 pre-filter; m=3,n=3 invalid → -5
        assert len(grid) == 95


class TestAC2Grid4DimCount:
    def test_4dim_grid_post_filter_count(self) -> None:
        grid = _generate_grid(include_re_anchor=True)
        # 100 * 4 (re_anchor) = 400 pre-filter; m=3,n=3 invalid → -5 * 4 = -20
        assert len(grid) == 380


class TestAC3FilterMGreaterN:
    def test_m_equals_n_removed(self) -> None:
        # m=3 with n=3 (m >= n) MUST be filtered out
        grid = _generate_grid()
        for point in grid:
            assert int(point["m"]) < int(point["n"]), point

    def test_filter_valid_direct(self) -> None:
        raw: list[dict[str, int | Decimal]] = [
            {"n": 3, "k": Decimal("1"), "m": 0},
            {"n": 3, "k": Decimal("1"), "m": 3},  # invalid
            {"n": 5, "k": Decimal("2"), "m": 2},
            {"n": 3, "k": Decimal("1"), "m": 4},  # invalid
        ]
        out = _filter_valid(raw)
        assert len(out) == 2
        assert all(int(p["m"]) < int(p["n"]) for p in out)


class TestAC4Determinism:
    def test_two_calls_identical(self) -> None:
        a = _generate_grid()
        b = _generate_grid()
        assert a == b

    def test_4dim_two_calls_identical(self) -> None:
        a = _generate_grid(include_re_anchor=True)
        b = _generate_grid(include_re_anchor=True)
        assert a == b


class TestAC5SortedKeys:
    def test_3dim_keys_sorted(self) -> None:
        grid = _generate_grid()
        for point in grid:
            keys = list(point.keys())
            assert keys == sorted(keys), keys

    def test_4dim_keys_sorted(self) -> None:
        grid = _generate_grid(include_re_anchor=True)
        for point in grid:
            keys = list(point.keys())
            assert keys == sorted(keys), keys


class TestAC6Boundaries:
    def test_n_values(self) -> None:
        grid = _generate_grid()
        n_values = sorted({int(p["n"]) for p in grid})
        assert n_values == [3, 5, 7, 9, 11]

    def test_k_values(self) -> None:
        grid = _generate_grid()
        k_values = sorted({p["k"] for p in grid})
        assert k_values == [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("5"), Decimal("7")]

    def test_m_values(self) -> None:
        grid = _generate_grid()
        m_values = sorted({int(p["m"]) for p in grid})
        # m=3 only valid when n > 3 → still appears in grid
        assert m_values == [0, 1, 2, 3]

    def test_re_anchor_values(self) -> None:
        grid = _generate_grid(include_re_anchor=True)
        re_values = sorted({int(p["re_anchor_period"]) for p in grid})
        assert re_values == [60, 120, 180, 240]


class TestAC7DecimalK:
    def test_k_is_decimal(self) -> None:
        grid = _generate_grid()
        for point in grid:
            assert isinstance(point["k"], Decimal), point


class TestAC8IntN:
    def test_n_is_int(self) -> None:
        grid = _generate_grid()
        for point in grid:
            assert isinstance(point["n"], int), point
            assert isinstance(point["m"], int), point

    def test_re_anchor_is_int(self) -> None:
        grid = _generate_grid(include_re_anchor=True)
        for point in grid:
            assert isinstance(point["re_anchor_period"], int), point


class TestAC9CartesianProduct:
    def test_each_combination_present_when_valid(self) -> None:
        grid = _generate_grid()
        # (n=5, k=Decimal("3"), m=2) MUST be in grid (5>2)
        assert {"n": 5, "k": Decimal("3"), "m": 2} in grid
        # (n=3, k=Decimal("1"), m=3) MUST be absent (filtered, m>=n)
        assert {"n": 3, "k": Decimal("1"), "m": 3} not in grid


class TestAC10NonEmpty:
    def test_3dim_grid_non_empty(self) -> None:
        assert len(_generate_grid()) > 0

    def test_4dim_grid_non_empty(self) -> None:
        assert len(_generate_grid(include_re_anchor=True)) > 0
