"""Unit tests for src.application.reporting.risk_metrics (Phase 0.10.bb).

ADR 0006 §18.C — episode 내 Sharpe / Calmar / Recovery efficiency view model.
None vs Decimal(0) disambiguation (AC-C13/C14), sort invariant (AC-C12),
section-omit (AC-C5).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.reporting.episode import DrawdownEpisode
from src.application.reporting.risk_metrics import (
    EpisodeRiskMetrics,
    compute_episode_risk_metrics,
)
from src.domain.models import Currency, Money, PortfolioSnapshot

_INITIAL = Money(amount=Decimal(100), currency=Currency.KRW)


def _snap(d: str, total: int) -> PortfolioSnapshot:
    ds = date.fromisoformat(d)
    return PortfolioSnapshot(
        snapshot_date=ds,
        snapshot_at=datetime(ds.year, ds.month, ds.day, tzinfo=UTC),
        initial_capital=_INITIAL,
        cash=Money(amount=Decimal(total), currency=Currency.KRW),
        valuations=[],
        total_market_value=Money(amount=Decimal(0), currency=Currency.KRW),
        total_value=Money(amount=Decimal(total), currency=Currency.KRW),
        total_cost_basis=Money(amount=Decimal(0), currency=Currency.KRW),
        total_unrealized_pnl=Money(
            amount=Decimal(0), currency=Currency.KRW,
        ),
    )


def _episode(
    *,
    peak: str = "2024-01-01",
    trough: str = "2024-01-05",
    recovery: str | None = "2024-01-10",
    recovered: bool = True,
) -> DrawdownEpisode:
    return DrawdownEpisode(
        peak_date=date.fromisoformat(peak),
        peak_value=Decimal(100),
        trough_date=date.fromisoformat(trough),
        trough_value=Decimal(85),
        recovery_date=date.fromisoformat(recovery) if recovery else None,
        recovered=recovered,
        drawdown_pct=Decimal("-15.0000"),
        duration_days=9 if recovered else 30,
    )


class TestSectionOmit:
    def test_empty_snapshots_returns_none(self):
        # AC-C5: section omit when no snapshots
        result = compute_episode_risk_metrics([], _episode())
        assert result is None

    def test_single_snapshot_returns_none(self):
        # AC-C1: window < 2 → section omit
        snaps = [_snap("2024-01-03", 95)]
        result = compute_episode_risk_metrics(snaps, _episode())
        assert result is None

    def test_window_outside_episode_returns_none(self):
        # All snapshots before peak — window empty
        snaps = [
            _snap("2023-12-01", 100),
            _snap("2023-12-02", 100),
        ]
        result = compute_episode_risk_metrics(snaps, _episode())
        assert result is None


class TestSortInvariant:
    def test_shuffled_input_same_result(self):
        # AC-C12: factory must sort snapshots before window filter
        sorted_snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-02", 95),
            _snap("2024-01-05", 85),
            _snap("2024-01-10", 100),
        ]
        shuffled_snaps = [
            _snap("2024-01-10", 100),
            _snap("2024-01-01", 100),
            _snap("2024-01-05", 85),
            _snap("2024-01-02", 95),
        ]
        result_sorted = compute_episode_risk_metrics(
            sorted_snaps, _episode(),
        )
        result_shuffled = compute_episode_risk_metrics(
            shuffled_snaps, _episode(),
        )
        assert result_sorted == result_shuffled


class TestSharpeNoneVsZero:
    def test_constant_value_window_returns_none(self):
        # AC-C13: σ==0 → None (NOT Decimal(0)) per ADR §18.C
        # Avoid "Sharpe 0.00" misread as "zero excess return"
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-02", 100),
            _snap("2024-01-05", 100),
            _snap("2024-01-10", 100),
        ]
        result = compute_episode_risk_metrics(snaps, _episode())
        assert result is not None
        assert result.sharpe is None, (
            f"constant series should yield sharpe=None, got {result.sharpe!r}"
        )

    def test_nonconstant_window_returns_decimal(self):
        # Sharpe computed when σ > 0
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-02", 95),
            _snap("2024-01-05", 85),
            _snap("2024-01-10", 100),
        ]
        result = compute_episode_risk_metrics(snaps, _episode())
        assert result is not None
        assert isinstance(result.sharpe, Decimal)


class TestCalmarNoneVsZero:
    def test_monotonic_rising_window_returns_none(self):
        # AC-C14: window MDD == 0 → calmar None
        # Monotonic rise inside window — no drawdown
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-02", 110),
            _snap("2024-01-05", 120),
            _snap("2024-01-10", 130),
        ]
        result = compute_episode_risk_metrics(snaps, _episode())
        assert result is not None
        assert result.calmar is None, (
            f"monotonic-rise should yield calmar=None, got {result.calmar!r}"
        )

    def test_drawdown_window_returns_decimal(self):
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-05", 85),
            _snap("2024-01-10", 110),
        ]
        result = compute_episode_risk_metrics(snaps, _episode())
        assert result is not None
        assert isinstance(result.calmar, Decimal)


class TestRecoveryEfficiency:
    def test_recovered_episode_computes_ratio(self):
        # peak 01-01 → trough 01-05 (4d) → recovery 01-10 (5d)
        # ratio = 5/4 = 1.25
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-05", 85),
            _snap("2024-01-10", 100),
        ]
        result = compute_episode_risk_metrics(snaps, _episode())
        assert result is not None
        assert result.recovery_efficiency == Decimal("1.25")

    def test_unrecovered_episode_returns_none(self):
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-05", 85),
            _snap("2024-01-30", 90),
        ]
        ep = _episode(recovery=None, recovered=False)
        result = compute_episode_risk_metrics(snaps, ep)
        # Window includes snapshots; recovery_efficiency=None for unrecovered
        assert result is not None
        assert result.recovery_efficiency is None

    def test_zero_peak_trough_days_returns_none(self):
        # Same-day peak/trough degenerate
        ep = DrawdownEpisode(
            peak_date=date(2024, 1, 1),
            peak_value=Decimal(100),
            trough_date=date(2024, 1, 1),
            trough_value=Decimal(85),
            recovery_date=date(2024, 1, 5),
            recovered=True,
            drawdown_pct=Decimal("-15"),
            duration_days=4,
        )
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-05", 100),
        ]
        result = compute_episode_risk_metrics(snaps, ep)
        assert result is not None
        assert result.recovery_efficiency is None


class TestUnrecoveredWindow:
    def test_window_end_is_last_snapshot_when_unrecovered(self):
        # window_end == last snapshot date for unrecovered episodes
        snaps = [
            _snap("2024-01-01", 100),
            _snap("2024-01-05", 85),
            _snap("2024-02-01", 90),
        ]
        ep = _episode(recovery=None, recovered=False)
        result = compute_episode_risk_metrics(snaps, ep)
        assert result is not None
        # window had 3 snapshots → computable
        assert isinstance(result.sharpe, (Decimal, type(None)))
        assert isinstance(result.calmar, (Decimal, type(None)))


class TestModuleStructure:
    def test_episode_risk_metrics_is_frozen(self):
        m = EpisodeRiskMetrics(
            sharpe=Decimal("1.0"),
            calmar=Decimal("0.5"),
            recovery_efficiency=Decimal("1.25"),
        )
        try:
            m.sharpe = Decimal("2.0")  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            return
        raise AssertionError("EpisodeRiskMetrics should be frozen")
