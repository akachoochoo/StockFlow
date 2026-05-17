"""Phase 0.11.c — `_VisualizationRenderer` Protocol (ADR 0009 §1.3 D2 (d) + D6 + D8).

`StrategyRenderer` (ADR 0006 §4.2, `src/ports/strategy_renderer.py`) 의
episode-scope marker / panel 책임과 **완전히 별도** 인 full-period
strategy-agnostic 시각화 Protocol. 기존 `StrategyRenderer` 시그니처 변경
zero (ADR 0006 §15.2 frozen).

본 sub-step (0.11.c.2) = **interface-only** — 실제 rendering body
(matplotlib / mplfinance import + figure 생성) 은 0.11.c.3 영역.
모듈 import zero — stdlib + typing only.

Lifecycle (ADR 0009 §1.7): permanent (5th ring 영구 유지).
Underscore-prefix private (ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, overload, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from decimal import Decimal

    from src.application.reporting.trade_view import TradeView
    from src.domain.models import OHLCV


__all__: list[str] = []


@runtime_checkable
class _VisualizationArtifacts(Protocol):
    """Sidecar marker Protocol — strategy-specific metadata 의 base type.

    빈 Protocol (메서드 0개). 모든 sidecar dataclass (예:
    `_DGTVisualizationArtifacts`) 가 structural typing 으로 implements.
    `_VisualizationRenderer.render_full_period` / `.extract_overlay_metric`
    의 `artifacts` 파라미터 type 으로 사용.

    ADR 0009 §1.3 D3 pattern B 정합 — DGT-specific 전체 metadata 를
    `BacktestResult` 침범 없이 sidecar 로 전달.
    """


@dataclass(frozen=True)
class _OverlayPayload:
    """Comparison-mode overlay 입력 dataclass (ADR 0009 §1.3 D6 공통 축).

    `BacktestResult` (production, B&H/7split) ↔ `_DGTBacktestResult`
    (research, DGT) 의 공통 축 metric — cross-strategy aligned series.
    `_VisualizationRenderer.extract_overlay_metric` 의 반환 type.

    Fields:
        time_series: time axis (UTC datetime sequence)
        pnl_cumulative: 누적 수익 (Decimal sequence) — D6 핵심 공통 metric
        drawdown: drawdown curve (Decimal sequence, 보통 음수 또는 0)
        strategy_id: overlay 의 legend label (예: "dgt", "price_drop")

    CLAUDE.md §2.1 Decimal invariant — float 미경유.
    """

    time_series: Sequence[datetime]
    pnl_cumulative: Sequence[Decimal]
    drawdown: Sequence[Decimal]
    strategy_id: str


@runtime_checkable
class _VisualizationRenderer(Protocol):
    """Strategy-agnostic full-period visualization 책임 (ADR 0009 §1.3 D2 (d)).

    `StrategyRenderer` (ADR 0006 §4.2, episode-scope marker / panel) 와
    완전히 별도. 본 Protocol 은 full-period chart (전체 기간 가격 +
    매수/매도 시점 + 전략별 overlay — grid envelope / split 라인 등) +
    comparison-mode overlay metric 추출 책임.

    구현체:
        - DGT VisualizationRenderer (0.11.c.3 신규 영역)
        - (B&H / 7split 은 ADR 0009 §1.3 D8 정합 — 본 phase 신규 구현
          없음. 기존 `DefaultRenderer` / `SevenSplitRenderer` 는
          episode-scope `StrategyRenderer` 책임만 보유.)

    Attributes:
        strategy_id: Registry mapping key (예: "dgt", "price_drop").
    """

    strategy_id: str

    @overload
    def render_full_period(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = ...,
        *,
        fmt: Literal["png"] = ...,
    ) -> bytes: ...

    @overload
    def render_full_period(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = ...,
        *,
        fmt: Literal["html"],
    ) -> str: ...

    def render_full_period(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = None,
        *,
        fmt: Literal["png", "html"] = "png",
    ) -> bytes | str:
        """Full-period chart 산출.

        Args:
            bars: 전체 기간 OHLCV (정렬: trade_date 오름차순).
            trades: 전체 기간 매수/매도 시점 (`TradeView` list).
            artifacts: strategy-specific sidecar metadata (예:
                `_DGTVisualizationArtifacts` — grid_history /
                reference_price_curve). None 이면 generic chart.
            fmt: 출력 포맷 (ADR 0016 §1.4 Option iii).
                "png" (기본값) — PNG bytes (D5 정합, width=1600 height=900 dpi=100).
                "html" — self-contained interactive lightweight-charts HTML str.
                기존 호출자 (`cli.py:400`, 모든 기존 테스트) 는 fmt 미전달 →
                bytes 반환, 동작 byte-identical.

        Returns:
            fmt="png" → bytes (PNG). fmt="html" → str (interactive HTML).

        Body 는 0.11.c.3 영역 (matplotlib import + figure 생성) 및
        0.11.i 영역 (_interactive_chart 호출).

        ADR 0016 §1.4 (iii) 편차 인정:
            ADR 0009 :188 "Protocol 변경 zero" 정신 보존 — 기존 호출자 변경 zero.
            letter 는 defaulted kwarg 추가로 narrowly 위반. traceability 박제.
        """
        ...

    def extract_overlay_metric(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = None,
    ) -> _OverlayPayload:
        """Comparison-mode overlay 입력 추출 (D6 공통 축 매핑).

        Args:
            bars: 전체 기간 OHLCV.
            trades: 전체 기간 trades.
            artifacts: sidecar metadata (DGT 의 경우 reference_price 변화).

        Returns:
            `_OverlayPayload` — time + pnl_cumulative + drawdown +
            strategy_id (cross-strategy aligned). PNG 가 아닌 numeric
            series → comparison orchestrator (0.11.c.4) 가 합성.
        """
        ...
