# Phase 0.11.c — DGT / strategy-agnostic visualization overlay.
# Reference: ADR 0009 §1.6 namespace + §1.7 lifecycle (permanent).
#
# Informational namespace. All symbols underscore-prefix private —
# `from src.research.visualization import *` exposes zero symbols.
#
# Outer→inner read OK (e.g., `from src.application.reporting.trade_view
# import TradeView`).
# Intra-research cross-import:
#   - 정방향 허용: `src.research.visualization` → `src.research.dgt`
#     (DGT 결과 읽기, ADR 0009 D9 정방향 + scripts/check_namespace.sh
#     intra-visualization grep rule).
#   - 역방향 차단: `src.research.dgt` → `src.research.visualization`
#     (ADR 0008 D9 intra-research grep rule).
#
# Sub-step 0.11.c.2 산출: Protocol + sidecar + enrichment helper +
# namespace test (interface-only).
# Sub-step 0.11.c.3 산출: `_DGTVisualizationRenderer` (`_dgt_renderer.py`)
# — DGT 전용 full-period chart (close + grid envelope + reference price +
# trade markers) + `_OverlayPayload` 추출 (D6 공통 축).
# Sub-step 0.11.c.4 산출: `_align.py` (BacktestResult ↔ _DGTBacktestResult
# 공통 축 매핑) + `_dgt_factory.py` (artifacts/TradeView 변환) +
# `_comparison.py` (overlay + grid 합성 PNG) + `cli.py` /
# `__main__.py` (`python -m src.research.visualization compare ...`).

__all__: list[str] = []
