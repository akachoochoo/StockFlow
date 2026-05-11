"""Episode-내 risk-adjusted metrics view model (Phase 0.10.bb — ADR 0006 §18.C).

Application-layer view model — NOT domain entity, NOT Protocol member.
Mirrors ``TradeView`` / ``EpisodeReportResult`` / ``StrategyInfo`` pattern
(frozen dataclass, in-memory only, no persistence).

본 모듈은 episode window 내 daily snapshots 로 위험조정 지표 (Sharpe /
Calmar) + 회복 효율 (Recovery efficiency) 을 deterministic 계산.

핵심 정책 (ADR §18.C 박제):
- **None vs Decimal(0) 명확화**: degenerate case (σ=0, MDD=0,
  unrecovered) → ``None``. `metrics.sharpe_ratio` / `calmar_ratio` 가
  반환하는 ``Decimal(0)`` sentinel 은 view layer 에서 ``None`` 으로 변환
  (Phase 0.10.x §14.7 박제 — silent N/A 거부 vs "zero excess return"
  으로 오해 방지 — 돈 관련 misinformation bug 차단)
- **Section omit 정책**: 모든 metric ``None`` 또는 window snapshots <2 →
  factory ``None`` 반환 (caller 가 section 전체 omit, row-N/A 거부)
- **Episode window 정의**: ``episode.peak_date`` ~ ``episode.recovery_date``
  (recovered) 또는 ``episode.peak_date`` ~ ``last snapshot date`` (unrecovered)
- **Sort invariant**: factory 가 snapshots 를 ``snapshot_date`` 로 sort
  보장 (caller 가 unsorted dict 등으로 전달해도 결과 deterministic)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from src.application.metrics import (
    calmar_ratio,
    has_nonzero_return_variance,
    max_drawdown,
    sharpe_ratio,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.application.reporting.episode import DrawdownEpisode
    from src.domain.models import PortfolioSnapshot


@dataclass(frozen=True)
class EpisodeRiskMetrics:
    """Episode window 내 위험조정 지표 + 회복 효율.

    Fields:
        sharpe: Episode window 내 annualized Sharpe ratio. ``None`` =
            window < 2 snapshots OR returns σ==0 (degenerate — constant
            value series). NOT ``Decimal(0)`` (그 경우는 "zero excess
            return", 본 field 에서는 "metric 계산 불가").
        calmar: Episode window 내 Calmar (CAGR / |MDD|). ``None`` =
            window MDD ==0 (단조 상승 — undefined). Episode 자체가
            threshold ≤ -5% 조건으로 detect 되어 일반적으로 발생 X.
        recovery_efficiency: ``(recovery_date - trough_date) / (trough_date
            - peak_date)`` — 회복 일수 / 하락 일수 비율. ``None`` = 미회복
            OR peak-trough days <= 0 (degenerate).
    """

    sharpe: Decimal | None
    calmar: Decimal | None
    recovery_efficiency: Decimal | None


def compute_episode_risk_metrics(
    snapshots: Sequence[PortfolioSnapshot],
    episode: DrawdownEpisode,
) -> EpisodeRiskMetrics | None:
    """Episode window 내 risk-adjusted metrics 계산.

    Args:
        snapshots: Portfolio daily snapshots (caller 가 정렬 보장 안 해도
            본 factory 가 ``snapshot_date`` 로 defensive sort)
        episode: DrawdownEpisode (peak / trough / recovery dates)

    Returns:
        EpisodeRiskMetrics: window 내 ≥2 snapshots 있을 때.
        None: window < 2 snapshots (section omit signal — caller 가
            HTML rendering 자체를 skip).
    """
    if not snapshots:
        return None

    # Defensive sort — caller (report.py) 정렬 보장하지만 contract surface
    # 에서 명시 (Phase 0.10.aa §17.7 박제 패턴 정합).
    sorted_snaps = sorted(snapshots, key=lambda s: s.snapshot_date)
    last_date = sorted_snaps[-1].snapshot_date
    window_end = episode.recovery_date or last_date

    window = [
        s for s in sorted_snaps
        if episode.peak_date <= s.snapshot_date <= window_end
    ]
    if len(window) < 2:
        return None

    window_list = list(window)

    # Sharpe — precondition: ≥2 returns AND σ > 0.
    sharpe_val: Decimal | None
    if has_nonzero_return_variance(window_list):
        sharpe_val = sharpe_ratio(window_list)
    else:
        sharpe_val = None

    # Calmar — precondition: window MDD != 0.
    mdd_val = max_drawdown(window_list)
    calmar_val: Decimal | None
    if mdd_val != Decimal(0):
        calmar_val = calmar_ratio(window_list)
    else:
        calmar_val = None

    # Recovery efficiency — precondition: recovered AND peak→trough days > 0.
    recovery_val: Decimal | None
    if (
        episode.recovered
        and episode.recovery_date is not None
        and (episode.trough_date - episode.peak_date).days > 0
    ):
        peak_to_trough_days = (episode.trough_date - episode.peak_date).days
        trough_to_recovery_days = (
            episode.recovery_date - episode.trough_date
        ).days
        recovery_val = (
            Decimal(trough_to_recovery_days) / Decimal(peak_to_trough_days)
        )
    else:
        recovery_val = None

    return EpisodeRiskMetrics(
        sharpe=sharpe_val,
        calmar=calmar_val,
        recovery_efficiency=recovery_val,
    )
