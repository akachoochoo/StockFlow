"""Phase 0.11.b — Deflated Sharpe Ratio (Bailey & López de Prado 2014).

ADR 0008 §1.6 D6 (PRIMARY metric) + §1.11 박제. DSR ≥ 1.0 = 5% significance
수준 (random strategy 통과 가능한 SR > 0 보다 엄격).

Decimal-only (CLAUDE.md §2.1). stdlib only — `math.erf` + `math.sqrt` +
`math.log` 만 사용 (CLAUDE.md §0 → numpy/scipy 추가 금지).

Reference:
    Bailey, D. H., & López de Prado, M. (2014). "The Deflated Sharpe Ratio:
    Correcting for Selection Bias, Backtest Overfitting, and Non-Normality."
    Journal of Portfolio Management, 40(5), 94-107.

Formula (paper Eq. 9 + 10):
    SR_observed = mean(returns) / std(returns)
    SR_variance = (1 - skew*SR + (kurt-1)/4 * SR^2) / (N - 1)
    SR_star = sqrt(SR_variance) * (
        (1 - gamma) * Z^(-1)(1 - 1/N_trials)
        + gamma * Z^(-1)(1 - 1/(N_trials * e))
    )
    DSR = (SR_observed - SR_star - threshold) / sqrt(SR_variance)

    where gamma = Euler-Mascheroni constant ≈ 0.5772156649015329.

Note: SR_observed 는 per-period (non-annualized). 호출자가 annualization
보정 (예: SR * sqrt(252)) 필요 시 returns 자체를 annualized 로 입력하거나
output DSR 을 동일 scale 로 해석. 본 함수는 Bailey 2014 raw formula 만 박제.

Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

import math
from decimal import Decimal


# Euler-Mascheroni constant (paper §2 변수 γ). 16 digit precision 충분
# (Decimal SR_variance ~ 1e-4 oracle 의 1e-12 buffer).
_EULER_MASCHERONI = Decimal("0.5772156649015329")

# math.e (자연로그 밑) — Decimal fixed (float→str→Decimal 전파 회피).
_E = Decimal("2.718281828459045")


def _compute_dsr(
    returns: list[Decimal],
    *,
    n_trials: int,
    threshold_sharpe: Decimal = Decimal("0"),
) -> Decimal:
    """Deflated Sharpe Ratio 계산.

    Args:
        returns: per-period return list (Decimal). Length >= 2 의무.
        n_trials: 탐색한 parameter set 수 (multiple testing correction).
        threshold_sharpe: SR_threshold (default 0 = random strategy 대비).

    Returns:
        DSR (Decimal). DSR ≥ 1.0 시 5% significance 수준.

    Raises:
        ValueError: returns 길이 < 2, n_trials < 1, or std(returns) == 0
            (zero variance — Sharpe undefined).
    """
    if len(returns) < 2:
        raise ValueError(f"returns length must be >= 2, got {len(returns)}")
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")

    n = Decimal(len(returns))
    mean_r = sum(returns, Decimal("0")) / n

    # Variance (population denominator N, paper convention).
    sq_dev = [(r - mean_r) ** 2 for r in returns]
    variance = sum(sq_dev, Decimal("0")) / n
    if variance <= Decimal("0"):
        raise ValueError("zero variance — Sharpe ratio undefined")

    std_r = _decimal_sqrt(variance)
    sharpe = mean_r / std_r

    # Higher moments (population convention — denominator N).
    cube_dev = [(r - mean_r) ** 3 for r in returns]
    quad_dev = [(r - mean_r) ** 4 for r in returns]
    m3 = sum(cube_dev, Decimal("0")) / n
    m4 = sum(quad_dev, Decimal("0")) / n
    # Skewness γ_1 = m_3 / σ^3. Kurtosis γ_2 = m_4 / σ^4 (non-excess; paper
    # Eq.9 uses raw 4th-moment ratio).
    skew = m3 / (std_r ** 3)
    kurt = m4 / (variance ** 2)

    # SR variance (paper Eq.9): (1 - γ1*SR + (γ2-1)/4 * SR^2) / (N - 1).
    sr_var_numer = (
        Decimal("1")
        - skew * sharpe
        + (kurt - Decimal("1")) / Decimal("4") * (sharpe ** 2)
    )
    sr_var = sr_var_numer / (n - Decimal("1"))
    if sr_var <= Decimal("0"):
        raise ValueError(
            f"SR variance non-positive ({sr_var}) — formula assumption violated"
        )
    sr_std = _decimal_sqrt(sr_var)

    # SR_star (paper Eq.10).
    # Edge case: n_trials == 1 → Z^(-1)(1 - 1/1) = Z^(-1)(0) = -∞. Multiple
    # testing 자체가 무의미 (single trial), so SR_star = 0 (no penalty).
    # Paper 정신: Bailey 2014 Eq.10 formula 는 N_trials >= 2 가정.
    n_trials_dec = Decimal(n_trials)
    if n_trials == 1:
        sr_star = Decimal("0")
    else:
        z1 = _normal_cdf_inv(Decimal("1") - Decimal("1") / n_trials_dec)
        z2 = _normal_cdf_inv(
            Decimal("1") - Decimal("1") / (n_trials_dec * _E)
        )
        sr_star = sr_std * (
            (Decimal("1") - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2
        )

    return (sharpe - sr_star - threshold_sharpe) / sr_std


def _decimal_sqrt(x: Decimal) -> Decimal:
    """Decimal sqrt — `Decimal.sqrt` context 의존이지만 default precision 28
    digit 으로 1e-12 정밀도 충분.

    Negative input 은 호출자가 사전 검증 (variance > 0 등).
    """
    if x < Decimal("0"):
        raise ValueError(f"sqrt of negative: {x}")
    return x.sqrt()


def _normal_cdf_inv(p: Decimal) -> Decimal:
    """Standard normal inverse CDF (Z^(-1)(p)) — Acklam approximation.

    Reference: P. J. Acklam, "An algorithm for computing the inverse normal
    cumulative distribution function" (2003).
    Maximum relative error: 1.15e-9 over p in (0, 1) — DSR 1e-4 tolerance 충분.

    Args:
        p: cumulative probability in (0, 1) exclusive.

    Returns:
        Z value (Decimal).

    Raises:
        ValueError: p outside (0, 1).
    """
    if not (Decimal("0") < p < Decimal("1")):
        raise ValueError(f"p must be in (0, 1), got {p}")

    # Acklam coefficients (high-precision rationals from his paper).
    a1 = Decimal("-39.6968302866538")
    a2 = Decimal("220.946098424521")
    a3 = Decimal("-275.928510446969")
    a4 = Decimal("138.357751867269")
    a5 = Decimal("-30.6647980661472")
    a6 = Decimal("2.50662827745924")
    b1 = Decimal("-54.4760987982241")
    b2 = Decimal("161.585836858041")
    b3 = Decimal("-155.698979859887")
    b4 = Decimal("66.8013118877197")
    b5 = Decimal("-13.2806815528857")
    c1 = Decimal("-0.00778489400243029")
    c2 = Decimal("-0.322396458041136")
    c3 = Decimal("-2.40075827716184")
    c4 = Decimal("-2.54973253934373")
    c5 = Decimal("4.37466414146497")
    c6 = Decimal("2.93816398269878")
    d1 = Decimal("0.00778469570904146")
    d2 = Decimal("0.32246712907004")
    d3 = Decimal("2.445134137143")
    d4 = Decimal("3.75440866190742")

    p_low = Decimal("0.02425")
    p_high = Decimal("1") - p_low

    if p < p_low:
        # Lower tail — rational approximation.
        # q = sqrt(-2 ln(p))
        q = _decimal_sqrt(Decimal("-2") * _decimal_ln(p))
        z = (
            ((((c1 * q + c2) * q + c3) * q + c4) * q + c5) * q + c6
        ) / ((((d1 * q + d2) * q + d3) * q + d4) * q + Decimal("1"))
        return z
    elif p <= p_high:
        # Central region — rational approximation.
        q = p - Decimal("0.5")
        r = q * q
        z = (
            (((((a1 * r + a2) * r + a3) * r + a4) * r + a5) * r + a6) * q
        ) / (((((b1 * r + b2) * r + b3) * r + b4) * r + b5) * r + Decimal("1"))
        return z
    else:
        # Upper tail — mirror lower.
        q = _decimal_sqrt(Decimal("-2") * _decimal_ln(Decimal("1") - p))
        z = -(
            ((((c1 * q + c2) * q + c3) * q + c4) * q + c5) * q + c6
        ) / ((((d1 * q + d2) * q + d3) * q + d4) * q + Decimal("1"))
        return z


def _decimal_ln(x: Decimal) -> Decimal:
    """Decimal natural logarithm.

    `Decimal.ln()` (Python 3.x context method) 사용 — stdlib only.
    """
    if x <= Decimal("0"):
        raise ValueError(f"ln of non-positive: {x}")
    return x.ln()


__all__: list[str] = []
