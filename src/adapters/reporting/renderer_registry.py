"""StrategyRendererRegistry (Phase 0.10 — ADR 0006 §4.4).

strategy_id → StrategyRenderer mapping. 정적 dict 기반 (Phase 0.10).
미등록 strategy 는 DefaultRenderer fallback (Acceptance Criteria 3 —
신규 dummy strategy 추가 시 코어 변경 zero).

동적 plugin discovery (entry points 등) 는 Phase 0.11+ 검토 (ADR §4.4
박제 + §10 명시적 제외).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.adapters.reporting.renderers.default import DefaultRenderer
from src.adapters.reporting.renderers.seven_split import SevenSplitRenderer

if TYPE_CHECKING:
    from src.ports.strategy_renderer import StrategyRenderer


class StrategyRendererRegistry:
    """strategy_id → StrategyRenderer mapping. Phase 0.10 정적 dict.

    Built-in mapping (Phase 0.10):
        - "price_drop"     → SevenSplitRenderer (PriceDropStrategy)
        - "support_level"  → SevenSplitRenderer (SupportLevelStrategy)

    미등록 strategy_id → DefaultRenderer fallback (Acceptance Criteria 3
    충족 — 신규 dummy strategy 추가 시 코어 reporting 모듈 변경 zero).

    Runtime ``register`` API 로 외부 plugin / 테스트용 등록 가능.
    """

    def __init__(self) -> None:
        seven_split = SevenSplitRenderer()
        self._renderers: dict[str, StrategyRenderer] = {
            "price_drop": seven_split,
            "support_level": seven_split,
        }
        self._default: StrategyRenderer = DefaultRenderer()

    def get(self, strategy_id: str) -> StrategyRenderer:
        """Lookup. 미등록 시 DefaultRenderer 반환 (fallback)."""
        return self._renderers.get(strategy_id, self._default)

    def register(
        self, strategy_id: str, renderer: StrategyRenderer,
    ) -> None:
        """런타임 등록 — 외부 plugin / 테스트 / 신규 strategy."""
        self._renderers[strategy_id] = renderer

    def registered_ids(self) -> list[str]:
        """등록된 strategy_id list (default fallback 제외)."""
        return list(self._renderers.keys())
