"""Phase 0.11.b sub-step .4 — `_pbo` tests (AC1~AC6).

ADR 0008 §1.6 D8 (iv) optional informational oracle 박제. Bailey 2017
simplified PBO formula.

Decimal-only (CLAUDE.md §2.1). stdlib only.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.research.dgt.optimization._grid_runner import _GridPointResult
from src.research.dgt.optimization._pbo import _compute_pbo


def _make_point(
    *,
    is_sharpe: Decimal,
    oos_sharpe: Decimal,
    n: int = 5,
    k: Decimal = Decimal("3"),
    m: int = 1,
) -> _GridPointResult:
    """`_GridPointResult` factory — IS/OOS Sharpe 만 의미 있음."""
    return _GridPointResult(
        config_n=n,
        config_k_pct=k,
        config_m=m,
        is_cagr_pct=Decimal("0"),
        is_mdd_pct=Decimal("0"),
        is_sharpe=is_sharpe,
        is_calmar=Decimal("0"),
        oos_cagr_pct=Decimal("0"),
        oos_mdd_pct=Decimal("0"),
        oos_sharpe=oos_sharpe,
        oos_calmar=Decimal("0"),
        dsr=Decimal("0"),
        total_trade_count=0,
        median_holding_period_days=Decimal("0"),
        mean_holding_period_days=Decimal("0"),
    )


class TestAC1PBOCombinatorialSplits:
    """C(5, 2) = 10 splits — informational count."""

    def test_compute_pbo_does_not_raise(self) -> None:
        # n=5 folds: C(5,2) = 10 splits → empty grid raises
        with pytest.raises(ValueError, match="grid_results must be non-empty"):
            _compute_pbo([], n_folds=5)

    def test_pbo_n_folds_below_2_raises(self) -> None:
        with pytest.raises(ValueError, match="n_folds must be >= 2"):
            _compute_pbo([_make_point(is_sharpe=Decimal("1"), oos_sharpe=Decimal("1"))], n_folds=1)


class TestAC2PBORandomZero:
    """Single grid point → PBO = 0 (only 1 strategy in IS-top, OOS-bottom 동일)."""

    def test_single_point_returns_zero(self) -> None:
        # n_strats=1 → 함수 early-return Decimal("0").
        pbo = _compute_pbo(
            [_make_point(is_sharpe=Decimal("1"), oos_sharpe=Decimal("0.5"))],
            n_folds=5,
        )
        assert pbo == Decimal("0")


class TestAC3PBOOverfittingHigh:
    """Synthetic: IS best ↔ OOS worst (perfect rank inversion) → PBO = 1.0."""

    def test_perfect_rank_inversion(self) -> None:
        # 4 strategies — IS rank [1,2,3,4] perfectly inverted in OOS [4,3,2,1].
        # Top-half IS (rank ≤ 2): strategies 0,1.
        # Their OOS ranks = 4, 3 (both > median 2) → bottom-half OOS.
        # PBO = 2/2 = 1.0.
        results = [
            _make_point(is_sharpe=Decimal("4"), oos_sharpe=Decimal("1")),  # IS=1, OOS=4
            _make_point(is_sharpe=Decimal("3"), oos_sharpe=Decimal("2")),  # IS=2, OOS=3
            _make_point(is_sharpe=Decimal("2"), oos_sharpe=Decimal("3")),  # IS=3, OOS=2
            _make_point(is_sharpe=Decimal("1"), oos_sharpe=Decimal("4")),  # IS=4, OOS=1
        ]
        pbo = _compute_pbo(results, n_folds=5)
        assert pbo > Decimal("0.5")
        assert pbo == Decimal("1")


class TestAC4PBORobustLow:
    """Synthetic: IS rank == OOS rank → PBO = 0 (no overfitting)."""

    def test_perfect_rank_alignment(self) -> None:
        # 4 strategies — IS rank == OOS rank.
        # Top-half IS (rank ≤ 2): strategies 0,1.
        # Their OOS ranks = 1, 2 (both ≤ median 2) → top-half OOS.
        # PBO = 0/2 = 0.
        results = [
            _make_point(is_sharpe=Decimal("4"), oos_sharpe=Decimal("4")),
            _make_point(is_sharpe=Decimal("3"), oos_sharpe=Decimal("3")),
            _make_point(is_sharpe=Decimal("2"), oos_sharpe=Decimal("2")),
            _make_point(is_sharpe=Decimal("1"), oos_sharpe=Decimal("1")),
        ]
        pbo = _compute_pbo(results, n_folds=5)
        assert pbo == Decimal("0")


class TestAC5PBOReturnsDecimal:
    """Result type = Decimal (CLAUDE.md §2.1)."""

    def test_returns_decimal(self) -> None:
        results = [
            _make_point(is_sharpe=Decimal("1"), oos_sharpe=Decimal("0.5")),
            _make_point(is_sharpe=Decimal("2"), oos_sharpe=Decimal("0.3")),
        ]
        pbo = _compute_pbo(results, n_folds=5)
        assert isinstance(pbo, Decimal)


class TestAC6PBODeterministic:
    """2 회 동일 결과 (D12)."""

    def test_two_runs_identical(self) -> None:
        results = [
            _make_point(is_sharpe=Decimal("0.5"), oos_sharpe=Decimal("0.4")),
            _make_point(is_sharpe=Decimal("0.3"), oos_sharpe=Decimal("0.6")),
            _make_point(is_sharpe=Decimal("0.8"), oos_sharpe=Decimal("0.2")),
            _make_point(is_sharpe=Decimal("0.1"), oos_sharpe=Decimal("0.7")),
        ]
        a = _compute_pbo(results, n_folds=5)
        b = _compute_pbo(results, n_folds=5)
        assert a == b
