"""Backtest reporting layer (Phase 0.10 — ADR 0006).

Strategy-agnostic analytical reporting:
- TradeView: application view model (Decision/BuyActionRecord/SellActionRecord
  → unified Trade view, ADR 0006 §3)
- DrawdownEpisode + detector: equity curve drawdown episode 추출 (ADR 0006 §5)

CLAUDE.md §1.1 — application layer. Domain 엔티티 추가 zero (ADR 0006 §3.2
박제 — 사용자 spec ADR-1 거부 + 기존 모델 활용). Hexagonal port for renderer
는 src/ports/strategy_renderer.py (ADR 0006 §4 — sub-step 0.10.c).
"""
