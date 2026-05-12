"""Phase 0.11.b — Deflated Sharpe Ratio tests (AC1~AC10).

ADR 0008 §1.11 oracle 박제. Bailey & López de Prado 2014 formula.
stdlib only — `math.erf` 기반 Acklam normal CDF inverse.

Decimal precision tolerance: 0.001 (Acklam 1.15e-9 보다 충분히 relaxed,
DSR formula 자체의 propagation 고려).
"""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from src.research.dgt.optimization._dsr import (
    _compute_dsr,
    _normal_cdf_inv,
)


_TOL = Decimal("0.001")


class TestAC1NormalCDFInverse:
    def test_z_0_975_approx_1_96(self) -> None:
        z = _normal_cdf_inv(Decimal("0.975"))
        assert abs(z - Decimal("1.95996398")) < _TOL

    def test_z_0_5_zero(self) -> None:
        z = _normal_cdf_inv(Decimal("0.5"))
        assert abs(z - Decimal("0")) < _TOL

    def test_z_0_025_neg_1_96(self) -> None:
        z = _normal_cdf_inv(Decimal("0.025"))
        assert abs(z - Decimal("-1.95996398")) < _TOL

    def test_z_0_999_tail(self) -> None:
        # Standard normal 0.999 quantile ≈ 3.0902
        z = _normal_cdf_inv(Decimal("0.999"))
        assert abs(z - Decimal("3.0902")) < _TOL

    def test_z_invalid_bounds(self) -> None:
        with pytest.raises(ValueError, match="p must be in"):
            _normal_cdf_inv(Decimal("0"))
        with pytest.raises(ValueError, match="p must be in"):
            _normal_cdf_inv(Decimal("1"))


class TestAC2DSRZeroVarianceReturns:
    def test_zero_variance_raises(self) -> None:
        returns = [Decimal("0.01")] * 100
        with pytest.raises(ValueError, match="zero variance"):
            _compute_dsr(returns, n_trials=10)

    def test_length_below_2_raises(self) -> None:
        with pytest.raises(ValueError, match="returns length must be >= 2"):
            _compute_dsr([Decimal("0.01")], n_trials=10)

    def test_n_trials_below_1_raises(self) -> None:
        returns = [Decimal("0.01"), Decimal("-0.01"), Decimal("0.005")]
        with pytest.raises(ValueError, match="n_trials must be >= 1"):
            _compute_dsr(returns, n_trials=0)


class TestAC3DSRRandomReturns:
    def test_random_returns_finite(self) -> None:
        random.seed(42)
        returns = [Decimal(str(random.gauss(0.001, 0.02))) for _ in range(252)]
        dsr = _compute_dsr(returns, n_trials=100)
        assert isinstance(dsr, Decimal)
        # finite + sane bound — random near-zero SR should give DSR near 0 to -2
        assert dsr > Decimal("-10")
        assert dsr < Decimal("10")


class TestAC4DSRLowTrials:
    def test_n_trials_1_no_penalty(self) -> None:
        # n_trials=1 → sr_star = 0 (no multiple testing correction)
        # → DSR = SR_observed / sr_std (no penalty)
        random.seed(42)
        returns = [Decimal(str(random.gauss(0.001, 0.02))) for _ in range(252)]
        dsr_1 = _compute_dsr(returns, n_trials=1)
        dsr_100 = _compute_dsr(returns, n_trials=100)
        # No penalty version must dominate penalized version
        assert dsr_1 > dsr_100


class TestAC5DSRHighTrials:
    def test_n_trials_large_penalty(self) -> None:
        random.seed(42)
        returns = [Decimal(str(random.gauss(0.001, 0.02))) for _ in range(252)]
        dsr_100 = _compute_dsr(returns, n_trials=100)
        dsr_10000 = _compute_dsr(returns, n_trials=10000)
        # SR_star grows with n_trials → DSR decreases
        assert dsr_10000 < dsr_100


class TestAC6DSRMonotonic:
    def test_threshold_increase_decreases_dsr(self) -> None:
        random.seed(42)
        returns = [Decimal(str(random.gauss(0.001, 0.02))) for _ in range(252)]
        dsr_0 = _compute_dsr(returns, n_trials=100, threshold_sharpe=Decimal("0"))
        dsr_05 = _compute_dsr(returns, n_trials=100, threshold_sharpe=Decimal("0.5"))
        assert dsr_05 < dsr_0


class TestAC7DSRBailey2014Reference:
    """Strong positive signal → DSR > 1.0 (5% significance).

    Bailey 2014 §2.3: DSR > 1.0 = approximate 5% significance under
    null hypothesis of zero true Sharpe.
    """

    def test_strong_signal_passes_significance(self) -> None:
        random.seed(7)
        # mean=0.01, std=0.02 → SR ≈ 0.5 per period (strong signal)
        returns = [Decimal(str(random.gauss(0.01, 0.02))) for _ in range(252)]
        dsr = _compute_dsr(returns, n_trials=100)
        # Strong signal must clear 5% significance threshold
        assert dsr > Decimal("1.0")

    def test_weak_signal_fails_significance(self) -> None:
        random.seed(11)
        # mean ≈ 0 — random walk, should fail significance
        returns = [Decimal(str(random.gauss(0.0, 0.02))) for _ in range(252)]
        dsr = _compute_dsr(returns, n_trials=100)
        assert dsr < Decimal("1.0")


class TestAC8DSRDecimalPrecision:
    def test_decimal_input_returns_decimal(self) -> None:
        returns = [
            Decimal("0.01"),
            Decimal("-0.005"),
            Decimal("0.012"),
            Decimal("-0.003"),
            Decimal("0.008"),
            Decimal("-0.002"),
            Decimal("0.006"),
            Decimal("0.004"),
            Decimal("-0.001"),
            Decimal("0.009"),
        ]
        dsr = _compute_dsr(returns, n_trials=10)
        assert isinstance(dsr, Decimal)

    def test_no_float_conversion_in_pipeline(self) -> None:
        # Source-level no-float discipline (CLAUDE.md §2.1)
        import inspect

        from src.research.dgt.optimization import _dsr as module

        src = inspect.getsource(module)
        # float() construction 금지. math.erf/sqrt/log 등 stdlib float
        # math 함수는 사용 OK (Acklam approximation 은 Decimal 만 거침)
        assert "float(" not in src, "float() 사용 금지 (CLAUDE.md §2.1)"


class TestAC9DSRSkewKurt:
    def test_skewed_returns_finite(self) -> None:
        # Asymmetric returns (skew != 0). Lognormal-like distribution.
        random.seed(99)
        returns = [
            Decimal(str(random.lognormvariate(0.001, 0.02) - 1))
            for _ in range(252)
        ]
        dsr = _compute_dsr(returns, n_trials=100)
        # Should yield finite Decimal; skewness is folded into SR variance
        assert isinstance(dsr, Decimal)
        assert dsr > Decimal("-100")
        assert dsr < Decimal("100")


class TestAC10DSRMonotonicTrials:
    def test_monotonic_decreasing_with_trials(self) -> None:
        random.seed(42)
        returns = [Decimal(str(random.gauss(0.001, 0.02))) for _ in range(252)]
        dsr_2 = _compute_dsr(returns, n_trials=2)
        dsr_10 = _compute_dsr(returns, n_trials=10)
        dsr_100 = _compute_dsr(returns, n_trials=100)
        dsr_1000 = _compute_dsr(returns, n_trials=1000)
        # Monotonic decrease (multiple testing penalty grows)
        assert dsr_2 > dsr_10 > dsr_100 > dsr_1000
