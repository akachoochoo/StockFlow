"""Phase 0.11.b sub-step .4 — `_perturbation` tests (AC1~AC8).

ADR 0008 §1.6 D8 (iii) + D11 (c) oracle 박제. Best parameter ±10% 27-point
WFO perturbation 측정.

Decimal-only (CLAUDE.md §2.1). stdlib only.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import OHLCV, Asset
from src.research.dgt.optimization._grid_runner import _GridPointResult
from src.research.dgt.optimization._perturbation import (
    _PerturbationResult,
    _build_perturbation_grid,
    _run_perturbation,
)
from src.research.dgt.runner import _DGTConfig


_SMOKE_BAR_COUNT = 1500
_BEST_CONFIG = _DGTConfig(
    grid_count=11,
    grid_spacing_pct=Decimal("3"),
    levels_above=1,
)


def _synthesize_bars(asset: Asset, n: int = _SMOKE_BAR_COUNT) -> list[OHLCV]:
    """N bars 합성 — sinusoidal-like price (grid trigger 확보, _grid_runner 정합)."""
    bars: list[OHLCV] = []
    base_date = date(2020, 1, 2)
    base_price = Decimal("25000")
    for i in range(n):
        delta = Decimal("750") if (i // 20) % 2 == 0 else Decimal("-750")
        if i > 0:
            base_price += delta if i % 5 == 0 else Decimal("50")
        if base_price < Decimal("15000"):
            base_price = Decimal("15000")
        if base_price > Decimal("35000"):
            base_price = Decimal("35000")
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base_date + timedelta(days=i),
                open=base_price,
                high=base_price + Decimal("100"),
                low=base_price - Decimal("100"),
                close=base_price,
                volume=Decimal("1000"),
            )
        )
    return bars


class TestAC1Generate27Points:
    """3 × 3 × 3 = 27 perturbation grid (m < n 필터 후 검증)."""

    def test_perturbation_grid_size_n11_k3_m1(self) -> None:
        grid = _build_perturbation_grid(_BEST_CONFIG)
        # n=11 → [10, 11, 12]; k=3 → [2.7, 3.0, 3.3]; m=1 → [0, 1, 2]
        # m < n 항상 만족 (max m = 2 < 10) → filter 후 27.
        assert len(grid) == 27


class TestAC2DeltaDefault10Pct:
    """±10% 변동 정확성."""

    def test_n_values_pm_10pct(self) -> None:
        grid = _build_perturbation_grid(_BEST_CONFIG)
        n_set = sorted({int(point["n"]) for point in grid})
        assert n_set == [10, 11, 12]

    def test_k_values_pm_10pct(self) -> None:
        grid = _build_perturbation_grid(_BEST_CONFIG)
        k_set = sorted({point["k"] for point in grid})
        assert k_set == [Decimal("2.7"), Decimal("3.0"), Decimal("3.3")]

    def test_m_values_pm_1(self) -> None:
        grid = _build_perturbation_grid(_BEST_CONFIG)
        m_set = sorted({int(point["m"]) for point in grid})
        assert m_set == [0, 1, 2]


class TestAC3WorstSharpeMin:
    """`worst_oos_sharpe == min(results.oos_sharpe)`."""

    def test_worst_equals_min(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
        sharpes = [r.oos_sharpe for r in result.perturbation_results]
        assert result.worst_oos_sharpe == min(sharpes)


class TestAC4D11CThreshold:
    """`passes_d11_c` = `worst_oos_sharpe > 0.3` 임계 (ADR 0008 D11 (c))."""

    def test_passes_when_above_threshold(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
        if result.worst_oos_sharpe > Decimal("0.3"):
            assert result.passes_d11_c is True
        else:
            assert result.passes_d11_c is False


class TestAC5Determinism:
    """2회 호출 동일 결과 (D12 reproducibility)."""

    def test_two_runs_byte_identical(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        r1 = _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
        r2 = _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
        assert len(r1.perturbation_results) == len(r2.perturbation_results)
        for p1, p2 in zip(r1.perturbation_results, r2.perturbation_results):
            assert p1 == p2
        assert r1.worst_oos_sharpe == r2.worst_oos_sharpe
        assert r1.mean_oos_sharpe == r2.mean_oos_sharpe
        assert r1.passes_d11_c == r2.passes_d11_c


class TestAC6BestConfigPreserved:
    """Input best_config == output best_config (불변)."""

    def test_best_config_unchanged(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
        assert result.best_config == _BEST_CONFIG
        assert result.best_config.grid_count == 11
        assert result.best_config.grid_spacing_pct == Decimal("3")
        assert result.best_config.levels_above == 1


class TestAC7DecimalInvariant:
    """모든 결과 = Decimal (CLAUDE.md §2.1)."""

    def test_all_decimals(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
        assert isinstance(result.worst_oos_sharpe, Decimal)
        assert isinstance(result.mean_oos_sharpe, Decimal)
        assert isinstance(result.delta_pct, Decimal)
        for p in result.perturbation_results:
            assert isinstance(p, _GridPointResult)
            assert isinstance(p.oos_sharpe, Decimal)
            assert isinstance(p.config_k_pct, Decimal)


class TestAC8MeanComputation:
    """mean_oos_sharpe = sum(oos_sharpe) / count."""

    def test_mean_arithmetic(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500)
        result = _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
        sharpes = [r.oos_sharpe for r in result.perturbation_results]
        expected_mean = sum(sharpes, Decimal("0")) / Decimal(len(sharpes))
        assert result.mean_oos_sharpe == expected_mean


class TestAC9EmptyBarsRaises:
    """Bars 부족 시 ValueError."""

    def test_empty_bars_raises(self, kr_etf_069500: Asset) -> None:
        with pytest.raises(ValueError):
            _run_perturbation([], kr_etf_069500, _BEST_CONFIG)

    def test_too_short_bars_raises(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=100)
        with pytest.raises(ValueError):
            _run_perturbation(bars, kr_etf_069500, _BEST_CONFIG)
