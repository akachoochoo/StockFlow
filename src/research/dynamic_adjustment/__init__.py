# Phase 0.11.e — Dynamic Adjustment Proposal Engine (L2/L3).
# Reference: ADR 0011 §1.6 Design Contract + §1.7 R8 namespace invariant.
#
# Informational namespace. All symbols underscore-prefix private —
# `from src.research.dynamic_adjustment import *` exposes zero symbols.
#
# 본 phase 의 핵심 invariant (§1.6, supersede 차단 D15):
#   1. 시스템은 *제안만* 한다 — 변경 적용은 사람 승인 + ADR 박제 후.
#   2. AI 결정 시스템 아님 — *통계 기반 trigger evaluator* (D1 원천 데이터
#      = backtest OOS only).
#   3. Reflexive overfitting 방지 — Phase 1 실거래 데이터 backtest input
#      사용 절대 금지.
#   4. ADR 박제 없이 변경 적용 차단 — 4-state 머신 (PENDING / APPROVED /
#      ADR_FILED / APPLIED) + REJECTED terminal.
#   5. CLAUDE.md §13.3 "친절한 추가 금지" — 사용자 spec 외 trigger 신호
#      추가 절대 금지.
#   6. CLAUDE.md §16.1 항목 #4 단일 sell strategy 가정 종속 — ADR 0010
#      §3 D4 결정 부재 시 SELL_STRATEGY_CHANGE enum variant 부재.
#
# Outer→inner read OK (e.g., `from src.application.backtest_runner import
# BacktestResult`).
# Intra-research cross-import (ADR 0011 D10):
#   - 정방향 허용: `src.research.dynamic_adjustment` →
#     `src.research.dgt` / `src.research.visualization` (D11 산출 호출).
#   - 역방향 차단: ADR 0008 D9 grep rule 으로 enforce.
#
# Sub-step 0.11.e.2 산출: `_Proposal` domain + `_ProposalHistory` +
# `_TriggerSignal` / `_ProposalType` enum + `_TriggerEvaluator` +
# namespace test.

__all__: list[str] = []
