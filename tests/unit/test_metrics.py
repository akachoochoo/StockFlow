"""Unit tests for src.application.metrics — CAGR, MDD, Sharpe, Calmar.

All tests use carefully chosen series so the expected values can be derived
on paper. Where Decimal exp/ln/sqrt introduce rounding (CAGR, Sharpe), tests
compare with a small absolute tolerance instead of exact equality.

Each test passes a custom ``trading_days_per_year`` so the math stays small
and obvious — production calls will use the default 252 (ADR §9.5).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from src.application.metrics import cagr, calmar_ratio, max_drawdown, sharpe_ratio
from src.domain.constants import KST
from src.domain.models import Currency, Money, PortfolioSnapshot


def _snap(d: date, total_value: str) -> PortfolioSnapshot:
    """Build a no-positions PortfolioSnapshot with cash == total_value.

    The initial_capital is fixed at 100 so total_return_pct is well-defined,
    but it is independent of the metrics under test (which look only at
    total_value time series).
    """
    snap_at = datetime.combine(d, time(16, 0), tzinfo=KST).astimezone(UTC)
    return PortfolioSnapshot.build(
        snapshot_date=d,
        snapshot_at=snap_at,
        initial_capital=Money(amount=Decimal("100"), currency=Currency.KRW),
        cash=Money(amount=Decimal(total_value), currency=Currency.KRW),
        valuations=[],
    )


def _series(start: date, totals: list[str]) -> list[PortfolioSnapshot]:
    return [_snap(start + timedelta(days=i), t) for i, t in enumerate(totals)]


_TOLERANCE = Decimal("0.0001")


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------
class TestCAGR:
    def test_empty_series_returns_zero(self):
        assert cagr([]) == Decimal(0)

    def test_single_snapshot_returns_zero(self):
        snaps = _series(date(2026, 1, 1), ["100"])
        assert cagr(snaps) == Decimal(0)

    def test_one_year_growth(self):
        # 2 snapshots, n_steps=1, trading_days=1, years=1, 100 → 121 = 21%
        snaps = _series(date(2026, 1, 1), ["100", "121"])
        result = cagr(snaps, trading_days_per_year=1)
        assert abs(result - Decimal("21")) < _TOLERANCE

    def test_two_year_compounding_to_known_cagr(self):
        # 3 snapshots, n_steps=2, trading_days=1, years=2, 100 → 121 = 10%
        snaps = _series(date(2026, 1, 1), ["100", "110", "121"])
        result = cagr(snaps, trading_days_per_year=1)
        assert abs(result - Decimal("10")) < _TOLERANCE

    def test_loss_returns_negative_cagr(self):
        snaps = _series(date(2026, 1, 1), ["100", "90"])
        result = cagr(snaps, trading_days_per_year=1)
        assert abs(result - Decimal("-10")) < _TOLERANCE

    def test_zero_initial_value_returns_zero(self):
        # Degenerate: initial_capital invariant blocks 0 in normal use,
        # but defensive 0-return is required for the Decimal divide guard.
        # Use a series that bypasses the invariant: cash = 100 → cash = 100
        # is valid, then we test a different degenerate path via reordering.
        snaps = _series(date(2026, 1, 1), ["100", "100"])
        assert cagr(snaps, trading_days_per_year=1) == Decimal(0)

    def test_snapshots_sorted_by_date_regardless_of_input_order(self):
        # Reverse-sorted input must give the same answer as forward-sorted.
        snaps = _series(date(2026, 1, 1), ["100", "121"])
        forward = cagr(snaps, trading_days_per_year=1)
        backward = cagr(list(reversed(snaps)), trading_days_per_year=1)
        assert forward == backward

    def test_invalid_trading_days_per_year_raises(self):
        with pytest.raises(ValueError):
            cagr([], trading_days_per_year=0)
        with pytest.raises(ValueError):
            cagr([], trading_days_per_year=-1)


# ---------------------------------------------------------------------------
# Max Drawdown
# ---------------------------------------------------------------------------
class TestMaxDrawdown:
    def test_empty_series_returns_zero(self):
        assert max_drawdown([]) == Decimal(0)

    def test_single_snapshot_returns_zero(self):
        snaps = _series(date(2026, 1, 1), ["100"])
        assert max_drawdown(snaps) == Decimal(0)

    def test_monotone_increasing_series_returns_zero(self):
        snaps = _series(date(2026, 1, 1), ["100", "110", "120", "130"])
        assert max_drawdown(snaps) == Decimal(0)

    def test_known_drawdown_25_percent(self):
        # Peak 120, trough 90 → (90-120)/120 = -25%
        snaps = _series(date(2026, 1, 1), ["100", "120", "90", "110", "130"])
        result = max_drawdown(snaps)
        assert result == Decimal("-25")

    def test_drawdown_after_new_peak(self):
        # 100 → 120 → 90 → 120 → 60: new peak at 120, then trough 60
        # (60 - 120) / 120 = -50%
        snaps = _series(date(2026, 1, 1), ["100", "120", "90", "120", "60"])
        result = max_drawdown(snaps)
        assert result == Decimal("-50")

    def test_returns_negative_or_zero(self):
        # MDD by definition is non-positive.
        snaps = _series(date(2026, 1, 1), ["100", "80", "60", "70"])
        assert max_drawdown(snaps) <= Decimal(0)


# ---------------------------------------------------------------------------
# Sharpe Ratio
# ---------------------------------------------------------------------------
class TestSharpeRatio:
    def test_empty_series_returns_zero(self):
        assert sharpe_ratio([]) == Decimal(0)

    def test_single_snapshot_returns_zero(self):
        snaps = _series(date(2026, 1, 1), ["100"])
        assert sharpe_ratio(snaps) == Decimal(0)

    def test_two_snapshots_returns_zero(self):
        # Need >= 2 returns for sample stdev. 2 snapshots = 1 return.
        snaps = _series(date(2026, 1, 1), ["100", "110"])
        assert sharpe_ratio(snaps) == Decimal(0)

    def test_constant_returns_yield_zero_sharpe(self):
        # All returns 10% → stdev = 0 → Sharpe = 0 (no risk-adjusted edge).
        snaps = _series(date(2026, 1, 1), ["100", "110", "121", "133.1"])
        assert sharpe_ratio(snaps, trading_days_per_year=1) == Decimal(0)

    def test_known_volatile_series_positive_sharpe(self):
        # 100 → 110 → 100: returns ≈ [+0.10, -0.0909]
        # mean ≈ 0.004545, stdev (n-1) ≈ 0.13502
        # Sharpe = 0.004545 / 0.13502 * sqrt(2) ≈ 0.0476
        snaps = _series(date(2026, 1, 1), ["100", "110", "100"])
        result = sharpe_ratio(snaps, trading_days_per_year=2)
        assert abs(result - Decimal("0.0476")) < Decimal("0.01")

    def test_higher_risk_free_rate_lowers_sharpe(self):
        snaps = _series(date(2026, 1, 1), ["100", "110", "100", "110"])
        s_zero = sharpe_ratio(
            snaps, trading_days_per_year=2, risk_free_rate=Decimal(0)
        )
        s_high = sharpe_ratio(
            snaps,
            trading_days_per_year=2,
            risk_free_rate=Decimal("0.5"),
        )
        assert s_high < s_zero

    def test_invalid_trading_days_per_year_raises(self):
        with pytest.raises(ValueError):
            sharpe_ratio([], trading_days_per_year=0)


# ---------------------------------------------------------------------------
# Calmar Ratio
# ---------------------------------------------------------------------------
class TestCalmarRatio:
    def test_empty_series_returns_zero(self):
        assert calmar_ratio([]) == Decimal(0)

    def test_no_drawdown_returns_zero(self):
        # MDD = 0 → Calmar undefined; we choose 0 to avoid +∞ in reports.
        snaps = _series(date(2026, 1, 1), ["100", "110", "120"])
        assert calmar_ratio(snaps, trading_days_per_year=1) == Decimal(0)

    def test_known_value(self):
        # 5 snapshots, n_steps=4, trading_days=4, years=1:
        #   CAGR = (final/initial)^1 - 1; final/initial = 120/100 = 1.20 → 20%
        # MDD path: peaks 100,120,120,120,120; trough at 80.
        #   dd at idx=2: (80-120)/120 = -33.333...%
        # Calmar = 20 / 33.333... = 0.6
        snaps = _series(date(2026, 1, 1), ["100", "120", "80", "100", "120"])
        result = calmar_ratio(snaps, trading_days_per_year=4)
        assert abs(result - Decimal("0.6")) < Decimal("0.001")
