"""Drawdown episode detector (Phase 0.10 — ADR 0006 §5).

Equity curve 만 입력받는 strategy-agnostic 분석 모듈. 임계치 (default
-5%) 이상 peak-to-trough 구간을 episode 로 추출.

도메인 엔티티 아님 — application layer dataclass + pure function.
영구화 X (in-memory only).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class DrawdownEpisode:
    """Equity curve 의 1 개 drawdown episode.

    peak_date → trough_date 손실 구간 + recovery_date (옵션, peak 회복
    시점). 회복 안 된 경우 ``recovered=False`` / ``recovery_date=None``,
    ``duration_days`` 는 series end 기준.

    Fields:
        peak_date: episode 직전 peak 일자
        peak_value: peak 시점 equity (>0)
        trough_date: episode 내 minimum 일자
        trough_value: minimum equity (>0, < peak_value)
        recovery_date: peak_value 회복 첫 시점 (None = 미회복)
        recovered: peak 회복 여부
        drawdown_pct: (trough_value - peak_value) / peak_value * 100
            — 항상 negative (예: Decimal("-22.6639"))
        duration_days: peak_date 부터 recovery_date (또는 series end)
            까지 calendar days
        asset_code: portfolio level = None, asset level = code
    """

    peak_date: date
    peak_value: Decimal
    trough_date: date
    trough_value: Decimal
    recovery_date: date | None
    recovered: bool
    drawdown_pct: Decimal
    duration_days: int
    asset_code: str | None = None


def detect_drawdown_episodes(
    equity_curve: Sequence[tuple[date, Decimal]],
    threshold_pct: Decimal = Decimal("-5"),
    *,
    asset_code: str | None = None,
) -> list[DrawdownEpisode]:
    """Equity curve 에서 |drawdown| ≥ |threshold_pct| 인 episode 추출.

    Algorithm (state machine):

    1. running ``peak_value`` (peak_date) 추적 — 첫 데이터 포인트로 초기화
    2. 각 (date, value) 순회:

       a. ``value >= peak_value``:
          - 진행 중 episode 있으면 → 회복 (recovered=True, recovery_date=date)
          - peak update (after close)
       b. ``value < peak_value``:
          - drawdown = (value - peak_value) / peak_value * 100
          - 진행 중 episode 없으면:
              - drawdown ≤ threshold_pct → 새 episode 시작
                (peak = current peak, trough = current value)
          - 진행 중 episode 있으면:
              - value < current trough → trough update

    3. 마지막 episode 회복 안 된 경우 → recovered=False, recovery_date=None,
       duration = series_end - peak_date

    Args:
        equity_curve: (date, value) sorted ascending by date.
            len < 2 시 [] 반환.
        threshold_pct: 음수 (예: Decimal("-5") for -5%). 양수/0 시 ValueError.
        asset_code: portfolio level = None (default), asset level = code.

    Returns:
        Episodes ordered by peak_date.

    Raises:
        ValueError: threshold_pct >= 0
    """
    if threshold_pct >= 0:
        raise ValueError(
            f"threshold_pct must be negative, got {threshold_pct}"
        )
    if len(equity_curve) < 2:
        return []

    # State
    peak_date, peak_value = equity_curve[0]
    # current_episode = (peak_date, peak_value, trough_date, trough_value)
    current_episode: tuple[date, Decimal, date, Decimal] | None = None
    episodes: list[DrawdownEpisode] = []
    last_date = equity_curve[-1][0]

    for d, v in equity_curve[1:]:
        if v >= peak_value:
            # New peak or recovery
            if current_episode is not None:
                # Episode 종료 — recovered
                ep_peak_d, ep_peak_v, ep_trough_d, ep_trough_v = current_episode
                drawdown = (ep_trough_v - ep_peak_v) / ep_peak_v * _HUNDRED
                episodes.append(
                    DrawdownEpisode(
                        peak_date=ep_peak_d,
                        peak_value=ep_peak_v,
                        trough_date=ep_trough_d,
                        trough_value=ep_trough_v,
                        recovery_date=d,
                        recovered=True,
                        drawdown_pct=drawdown,
                        duration_days=(d - ep_peak_d).days,
                        asset_code=asset_code,
                    )
                )
                current_episode = None
            # peak update
            peak_value = v
            peak_date = d
        else:
            # value < peak_value
            drawdown = (v - peak_value) / peak_value * _HUNDRED
            if current_episode is None:
                # 새 episode 시작 검사
                if drawdown <= threshold_pct:
                    current_episode = (peak_date, peak_value, d, v)
            else:
                # 진행 중 trough update
                _, _, _, current_trough_v = current_episode
                if v < current_trough_v:
                    current_episode = (
                        current_episode[0],
                        current_episode[1],
                        d,
                        v,
                    )

    # 마지막 episode 미회복
    if current_episode is not None:
        ep_peak_d, ep_peak_v, ep_trough_d, ep_trough_v = current_episode
        drawdown = (ep_trough_v - ep_peak_v) / ep_peak_v * _HUNDRED
        episodes.append(
            DrawdownEpisode(
                peak_date=ep_peak_d,
                peak_value=ep_peak_v,
                trough_date=ep_trough_d,
                trough_value=ep_trough_v,
                recovery_date=None,
                recovered=False,
                drawdown_pct=drawdown,
                duration_days=(last_date - ep_peak_d).days,
                asset_code=asset_code,
            )
        )

    return episodes
