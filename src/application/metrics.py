"""Backtest / paper-trading performance metrics.

Pure functions over `list[PortfolioSnapshot]` → `Decimal`. No I/O, no time
queries, no external dependencies beyond stdlib `decimal`. Per ADR §9.5,
keeping these pure lets the same calculations run against backtest snapshots,
paper-trading snapshots, and live-trading snapshots without modification.

Phase 0 conventions:
- All ratio-style metrics (CAGR, MDD) are returned in **percent units** to
  match `PortfolioSnapshot.total_return_pct` (e.g. ``Decimal("10")`` = 10%).
  MDD is returned as a non-positive Decimal.
- Sharpe and Calmar are dimensionless ratios.
- Phase 0 simplifications: ``risk_free_rate=0``, ``trading_days_per_year=252``.
- Empty / single-snapshot inputs return ``Decimal(0)`` rather than raising,
  so a freshly started backtest with no trading days is reportable.

All math uses :class:`decimal.Decimal` (CLAUDE.md §2) — never ``float``. The
``ln()`` / ``exp()`` / ``sqrt()`` Decimal methods give 28-digit precision by
default, more than enough for backtest reporting.
"""
from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.models import PortfolioSnapshot


_HUNDRED = Decimal(100)
_ZERO = Decimal(0)
_ONE = Decimal(1)


def _sorted_values(snapshots: list[PortfolioSnapshot]) -> list[Decimal]:
    """Extract total_value.amount in chronological order.

    Snapshots arrive from a Repository which already sorts by date, but we
    re-sort defensively so callers can pass arbitrary lists.
    """
    return [
        s.total_value.amount
        for s in sorted(snapshots, key=lambda s: s.snapshot_date)
    ]


def _daily_returns(values: list[Decimal]) -> list[Decimal]:
    """Per-step simple returns (v[i] - v[i-1]) / v[i-1].

    Returns an empty list when there are fewer than two values. Steps where
    the previous value is non-positive are skipped (a zero portfolio cannot
    produce a meaningful return); in Phase 0 this never happens because
    initial_capital > 0 invariant guarantees positivity at t=0.
    """
    out: list[Decimal] = []
    for prev, curr in pairwise(values):
        if prev <= 0:
            continue
        out.append((curr - prev) / prev)
    return out


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return _ZERO
    return sum(values, _ZERO) / Decimal(len(values))


def _sample_stdev(values: list[Decimal]) -> Decimal:
    """Sample standard deviation (n-1 denominator). 0 for n<2."""
    n = len(values)
    if n < 2:
        return _ZERO
    mean = _mean(values)
    variance = sum(((v - mean) ** 2 for v in values), _ZERO) / Decimal(n - 1)
    return variance.sqrt()


def cagr(
    snapshots: list[PortfolioSnapshot],
    *,
    trading_days_per_year: int = 252,
) -> Decimal:
    """Compound Annual Growth Rate, in percent.

    Formula: ``(final_value / initial_value) ** (1 / years) - 1``,
    where ``years = (n_snapshots - 1) / trading_days_per_year``.

    Returns 0 for fewer than two snapshots, non-positive initial value, or
    non-positive final/initial ratio (degenerate portfolio).
    """
    if trading_days_per_year <= 0:
        raise ValueError(
            f"trading_days_per_year must be > 0, got {trading_days_per_year}"
        )
    values = _sorted_values(snapshots)
    if len(values) < 2:
        return _ZERO
    initial = values[0]
    final = values[-1]
    if initial <= 0:
        return _ZERO
    ratio = final / initial
    if ratio <= 0:
        return _ZERO
    n_steps = Decimal(len(values) - 1)
    years = n_steps / Decimal(trading_days_per_year)
    if years <= 0:
        return _ZERO
    # ratio^(1/years) = exp(ln(ratio) / years); Decimal.ln/exp give 28-digit
    # precision which is far more than backtest reports need.
    annualized = (ratio.ln() / years).exp() - _ONE
    return annualized * _HUNDRED


def max_drawdown(snapshots: list[PortfolioSnapshot]) -> Decimal:
    """Maximum drawdown over the snapshot series, in percent (≤ 0).

    Drawdown at time t = (value[t] - running_peak[t]) / running_peak[t].
    MDD is the minimum (most-negative) drawdown observed. Returns 0 for
    empty/single snapshot input or a strictly monotone-up series.
    """
    values = _sorted_values(snapshots)
    if len(values) < 2:
        return _ZERO
    peak = values[0]
    worst = _ZERO
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < worst:
                worst = dd
    return worst * _HUNDRED


def has_nonzero_return_variance(
    snapshots: list[PortfolioSnapshot],
    *,
    risk_free_rate: Decimal = _ZERO,
    trading_days_per_year: int = 252,
) -> bool:
    """Whether ``snapshots`` can yield a defined Sharpe (sample stdev > 0).

    Phase 0.10.bb (ADR 0006 §18.C). Mirrors ``sharpe_ratio`` 의 degeneracy
    guard (n<2 OR σ==0 → Decimal(0)) at the predicate layer so callers
    can distinguish "metric unavailable" (return None) from "zero return"
    (return Decimal(0)). 동일 σ 계산 (DRY).

    Returns:
        True iff the snapshots produce at least 2 daily returns with
        positive sample stdev. Otherwise False.
    """
    returns = _daily_returns(_sorted_values(snapshots))
    if len(returns) < 2:
        return False
    daily_rf = risk_free_rate / Decimal(trading_days_per_year)
    excess = [r - daily_rf for r in returns]
    return _sample_stdev(excess) > 0


def sharpe_ratio(
    snapshots: list[PortfolioSnapshot],
    *,
    risk_free_rate: Decimal = _ZERO,
    trading_days_per_year: int = 252,
) -> Decimal:
    """Annualized Sharpe ratio (dimensionless).

    ``risk_free_rate`` is the **annualized** rate as a fraction (Phase 0
    default 0). The daily risk-free rate is ``risk_free_rate /
    trading_days_per_year`` — a linear approximation that matches Phase 0
    simplification (ADR §9.5).

    Returns 0 when there are not enough returns to estimate stdev or when
    stdev is exactly 0 (a constant series has no risk-adjusted edge to
    report).
    """
    if trading_days_per_year <= 0:
        raise ValueError(
            f"trading_days_per_year must be > 0, got {trading_days_per_year}"
        )
    returns = _daily_returns(_sorted_values(snapshots))
    if len(returns) < 2:
        return _ZERO
    daily_rf = risk_free_rate / Decimal(trading_days_per_year)
    excess = [r - daily_rf for r in returns]
    sigma = _sample_stdev(excess)
    if sigma == 0:
        return _ZERO
    mean_excess = _mean(excess)
    return mean_excess / sigma * Decimal(trading_days_per_year).sqrt()


def calmar_ratio(
    snapshots: list[PortfolioSnapshot],
    *,
    trading_days_per_year: int = 252,
) -> Decimal:
    """Calmar ratio = CAGR / |MDD| (dimensionless).

    Both CAGR and MDD are in percent units, so dividing yields a clean
    ratio. Returns 0 when MDD is 0 (no drawdown ⇒ undefined; we choose 0
    rather than +∞ so reports never carry sentinel infinities).
    """
    mdd = max_drawdown(snapshots)
    if mdd == 0:
        return _ZERO
    return cagr(
        snapshots, trading_days_per_year=trading_days_per_year
    ) / abs(mdd)
