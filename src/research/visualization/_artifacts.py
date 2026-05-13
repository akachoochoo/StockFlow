"""Phase 0.11.c — `_DGTVisualizationArtifacts` sidecar (ADR 0009 §1.3 D3 pattern B).

DGT-specific 전체 metadata 를 `BacktestResult` / `_DGTBacktestResult`
스키마 침범 없이 5th ring sidecar dataclass 로 전달. `_VisualizationRenderer`
구현체 (0.11.c.3 의 DGT renderer) 가 본 sidecar 를 입력으로 받아
full-period chart 의 grid envelope / reference price curve / level marker
를 산출.

본 sub-step (0.11.c.2) = **interface-only** — dataclass 정의 + private
marker 만. 생성 (factory from `_DGTBacktestResult`) 은 0.11.c.3 영역.

Lifecycle (ADR 0009 §1.7): permanent.
Underscore-prefix private (ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime
    from decimal import Decimal


__all__: list[str] = []


@dataclass(frozen=True)
class _GridSnapshot:
    """Single point-in-time DGT grid state — 시간 가변 grid envelope 의 sample.

    `_DGTVisualizationArtifacts.grid_history` 의 element. DGT prototype
    runner (`src/research/dgt/runner.py`) 의 step-by-step state 에서
    추출. 0.11.c.3 의 DGT renderer 가 이 list 를 read 해서 grid
    envelope band 를 차트에 overlay.

    Fields:
        timestamp: bar 시점 (UTC datetime — bar 의 trade_date 를 UTC
            instant 으로 변환).
        reference_price: 해당 시점의 DGT reference price (현 runner =
            ohlcv[0].close 고정. 미래 re-anchor 시 시간 가변).
        levels: 해당 시점의 grid 가격대 list (sorted ascending).
            DGT formula = reference * (1 ± k * i / n), i ∈ [1, n].
        triggered_level: 해당 step 에서 발화한 level (없으면 None).
            None 일 때는 grid envelope 만 그리고 trade marker 미생성.

    CLAUDE.md §2.1 Decimal invariant.
    """

    timestamp: datetime
    reference_price: Decimal
    levels: Sequence[Decimal]
    triggered_level: Decimal | None


@dataclass(frozen=True)
class _DGTVisualizationArtifacts:
    """DGT-specific sidecar — `_VisualizationRenderer` 의 `artifacts` 입력.

    `_DGTBacktestResult.trades` / `.daily_snapshots` 에서 직접 추출
    가능하지 않은 (또는 추출 비싼) full-period DGT metadata 를 사전
    계산해서 박제. 0.11.c.3 의 DGT renderer 가 본 sidecar 만으로 grid
    envelope + reference price curve overlay 가능.

    `_VisualizationArtifacts` Protocol (marker, 메서드 0개) 을 structural
    typing 으로 implements.

    Fields:
        grid_history: 시간 가변 grid snapshots (sub-step .3 sensitivity
            heatmap 의 grid 값과 연관 — 동일 runner 에서 추출).
        reference_price_curve: (timestamp, reference_price) tuples.
            현 runner = 고정 (ohlcv[0].close) → 단일 entry. 미래
            re-anchor 시 다중 entry.
        parameter_config: n / k / m 박제 (`_DGTConfig` 직렬화 dict).
            JSON serializable 제약 없음 — 5th ring 내부 only, 영구화 X.
        asset_code: 069500 등 (`Asset.code`).
        period_start: backtest 시작 business date.
        period_end: backtest 종료 business date.

    CLAUDE.md §2.1 Decimal invariant — float 미경유.
    """

    grid_history: Sequence[_GridSnapshot]
    reference_price_curve: Sequence[tuple[datetime, Decimal]]
    parameter_config: dict[str, Any]
    asset_code: str
    period_start: date
    period_end: date
