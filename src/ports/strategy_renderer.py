"""StrategyRenderer Port (Phase 0.10 — ADR 0006 §4).

Strategy 별 marker / panel 렌더링 책임을 plugin 으로 분리하기 위한
Hexagonal Port. 코어 리포팅 모듈 (`src/application/reporting/`) 은 본
Protocol 만 의존 — strategy 무지.

구현체는 `src/adapters/reporting/renderers/` 에 위치. Registry
(`src/adapters/reporting/renderer_registry.py`) 가 strategy_id →
renderer mapping 보유.

CLAUDE.md §1.3 (Port/Adapter) 정합. ADR 0006 §4.1 박제 = 옵션 A
(Port + Adapter 분리, application layer 내 abstract class 거부).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.application.reporting.episode import DrawdownEpisode
    from src.application.reporting.trade_view import TradeView


@dataclass(frozen=True)
class MarkerStyle:
    """차트 마커 시각 속성 — 차트 라이브러리 무관 spec.

    Fields:
        color: CSS hex or named color (예: "#1f77b4", "green")
        marker: matplotlib / mplfinance marker code (예: "^" for buy,
            "v" for sell, "o" "s" 등)
        size: pt
        label: 차트 위 표기 (예: "B1", "S3")
    """

    color: str
    marker: str
    size: int
    label: str


@dataclass(frozen=True)
class Panel:
    """리포트 진단 패널 — HTML 출력 무관 spec.

    Fields:
        title: 패널 제목 (예: "차수별 거래 횟수")
        rows: (label, value) pairs — HTML 테이블 행
    """

    title: str
    rows: list[tuple[str, str]]


@runtime_checkable
class StrategyRenderer(Protocol):
    """Strategy 별 marker / panel 렌더링 책임.

    구현체는 `src/adapters/reporting/renderers/` 에 위치. Registry
    가 strategy_id → renderer mapping 보유. 신규 strategy 추가 시:
    Renderer 구현체 작성 + Registry 등록만 — 코어 리포팅 모듈
    (`src/application/reporting/`) 변경 zero (Acceptance Criteria 3).
    """

    def marker_label(self, trade: TradeView) -> str:
        """차트 마커 위 짧은 라벨 (예: "B1", "S", "Buy")."""
        ...

    def marker_style(self, trade: TradeView) -> MarkerStyle:
        """차트 마커 시각 속성 (color / marker / size / label)."""
        ...

    def diagnostic_panels(
        self,
        trades: Sequence[TradeView],
        episode: DrawdownEpisode,
    ) -> Sequence[Panel]:
        """Episode 구간 진단 패널 list — strategy 별 분석 통계."""
        ...
