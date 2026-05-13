"""Phase 0.11.e.2 — Proposal-related enums (ADR 0011 §1.3 D1 + D6 + D8).

`_TriggerSignal` (D1) + `_ProposalState` (D6) + `_ProposalType` (D8) —
exhaustive match invariant 의무 (§1.6 #5 + #6 enforcement).

`_ProposalType` 의 enum variants 부재 강제 (D9 L1-shadow 차단 + D12 ADR
0010 D4 종속) — 컴파일 타임 차단 (mypy + runtime exhaustive match):
    - `STOP_LOSS` 부재 — Phase 1 ADR 0012 별도 영역 (§11.4 정합).
    - `REALTIME_HALT` / `VIX_CIRCUIT_BREAK` 부재 — L1 = Phase 2 영역.
    - `SELL_STRATEGY_CHANGE` 부재 — ADR 0010 §3 D4 미확정 시 enum
      variant 자체 부재 (§1.6 #6 정합).

Lifecycle (ADR 0011 §1.6 + D13): 5th ring 영구 유지 (promote 조건 = Phase
1 안정화 6개월 + Phase 2 완료 후).
Underscore-prefix private (ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

from enum import StrEnum

__all__: list[str] = []


class _TriggerSignal(StrEnum):
    """L2/L3 trigger 신호 — D1 원천 데이터 제약 hard 정합.

    원천 데이터 = **backtest OOS metric + 확정 OHLCV only**. 실시간 가격 /
    VIX / 뉴스 / sentiment / 소셜 미디어 = 절대 금지 (L1 Phase 2 영역).

    Variants:
        ROLLING_OOS_SHARPE — (i) 36-month rolling OOS Sharpe 임계 (예: < 0.3).
            AND-gate: sample size ≥ 100 거래 + drawdown 임계 동시 충족.
        DRAWDOWN — (ii) MDD < ADR 0007 §3 G2 baseline x 1.50 = -50% 악화.
            drawdown trigger ≠ 손절 제안 (Patch 7, §11.4 정합).
        HUMAN_AD_HOC — (iv) CLI command 진입, ad-hoc 사람 trigger.
        NULL_PROPOSAL — Sample size 부족 또는 AND-gate 미충족 시 "평가 보류"
            NULL marker (Patch 4 Architect 권고 #1).

    부재 강제 (§1.6 #5 + D9 enforcement):
        - REGIME_CHANGE 부재 — Patch 12 (Phase 2 위임, 실시간 변동성 신호).
        - VIX_TRIGGER / NEWS_SENTIMENT / TWITTER_TREND 부재 — §13.3 + §1.6 #2.
    """

    ROLLING_OOS_SHARPE = "rolling_oos_sharpe"
    DRAWDOWN = "drawdown"
    HUMAN_AD_HOC = "human_ad_hoc"
    NULL_PROPOSAL = "null_proposal"


class _ProposalState(StrEnum):
    """Proposal 4-state 머신 + REJECTED terminal (ADR 0011 §1.3 D6).

    전이 규칙 (§1.6 #4 enforcement):
        PENDING ──사람 CLI 승인──> APPROVED
        APPROVED ──ADR 파일 존재 + reference 박제──> ADR_FILED
        ADR_FILED ──다음 cron pickup──> APPLIED
        PENDING ──사람 CLI 거부──> REJECTED (terminal)

    APPROVED → APPLIED 직접 전이 = **차단 hard** (§1.6 #4 invariant).
    REJECTED = terminal, 재진입 불가.
    """

    PENDING = "pending"
    APPROVED = "approved"
    ADR_FILED = "adr_filed"
    APPLIED = "applied"
    REJECTED = "rejected"


class _ProposalType(StrEnum):
    """Proposal 영역 분리 — L2/L3 권한 분리 + L1-shadow 차단 (D8).

    Variants (본 phase scope = L2/L3 만):
        PARAMETER_CHANGE — L2 영역. SplitStrategyConfig / SellStrategyConfig
            등 파라미터 delta.
        STRATEGY_CHANGE — L3 영역. 전략 type 교체 (예: PriceDrop ↔ SupportLevel).
        UNIVERSE_CHANGE — L3 영역. 종목 추가/제거 (§14 영역과 분리 — 사람
            인지 trigger only).

    부재 강제 (§1.6 #4 + #6 + D9 + D12 enforcement):
        - STOP_LOSS 부재 — Phase 1 ADR 0012 별도 영역 (§11.4 정합).
        - REALTIME_HALT / VIX_CIRCUIT_BREAK 부재 — L1 = Phase 2 영역
          (D9 NO 정합).
        - SELL_STRATEGY_CHANGE 부재 — ADR 0010 §3 D4 미확정 시 enum
          variant 자체 부재 (§1.6 #6 + D12 정합).

    Enum exhaustive match test (`test_proposal_type.py`) 가 위 부재 항목
    추가 시 FAIL — 컴파일 타임 차단 패턴.
    """

    PARAMETER_CHANGE = "parameter"
    STRATEGY_CHANGE = "strategy"
    UNIVERSE_CHANGE = "universe"


# Public type alias — proposal id 는 단순 str (uuid). 별도 NewType 으로
# 강제하면 외부 API 호환성 약화 — Decimal 패턴 정합 (str 기반).
_ProposalId = str
