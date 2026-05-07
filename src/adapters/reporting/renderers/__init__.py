"""Built-in StrategyRenderer 구현체 (Phase 0.10 — ADR 0006 §4.3).

- ``seven_split``: SevenSplitRenderer (price_drop / support_level)
- ``default``: DefaultRenderer (annotation 무관 fallback)

신규 strategy 추가 시 본 디렉토리에 새 모듈 추가 + Registry 등록만.
"""

from src.adapters.reporting.renderers.default import DefaultRenderer
from src.adapters.reporting.renderers.seven_split import SevenSplitRenderer

__all__ = ["DefaultRenderer", "SevenSplitRenderer"]
