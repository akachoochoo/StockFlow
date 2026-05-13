"""Phase 0.11.e.2 — L2/L3 trigger evaluator (ADR 0011 §1.3 D1).

원천 데이터 제약 hard (§1.6 #2 + D1):
    - 입력 = **backtest OOS metric + 확정 OHLCV only**.
    - 실시간 가격 / VIX / 뉴스 / sentiment / 소셜 미디어 = **절대 금지**.

AND-gate 조건 (D1 권고 default = (i) AND (ii) AND (iv)):
    - (i) Rolling OOS Sharpe < 임계 (예: 0.3)
    - (ii) MDD < baseline x 1.50 (예: -50% 악화)
    - (iv) 사람 ad-hoc trigger (CLI command)
    - Sample size threshold: ≥ 100 거래

NULL proposal semantics (Architect 권고 #1):
    - AND-gate 미충족 또는 sample size 부족 시 NULL_PROPOSAL trigger 생성
      (자동 제안 차단 + 추적성 보존).

거부된 trigger:
    - (iii) Regime change — Patch 12, Phase 2 위임 (실시간 변동성 신호).

본 모듈 = 순수 함수 evaluator (외부 데이터 dependency = 입력 인자 dict
형식). 실제 backtest 호출 / cron 진입 = sub-step 0.11.e.3 영역.

Lifecycle: 5th ring 영구 유지 (D13).
Underscore-prefix private (`__all__ = []`).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.research.dynamic_adjustment._proposal_type import _TriggerSignal

__all__: list[str] = []


# D1 권고 default 임계 (Critic default 수락 — 0.11.e.2 sub-step 진입 시
# 재검토 가능 명시):
_DEFAULT_ROLLING_SHARPE_THRESHOLD = Decimal("0.3")
_DEFAULT_DRAWDOWN_MULTIPLIER = Decimal("1.50")  # baseline MDD x 1.50
_DEFAULT_SAMPLE_SIZE_THRESHOLD = 100  # 거래 수


@dataclass(frozen=True)
class _TriggerEvaluationInput:
    """Trigger evaluator 입력 — D1 원천 데이터 제약 hard 정합.

    Fields (모두 backtest OOS metric / 확정 통계 기반 — 실시간 신호 zero):
        rolling_oos_sharpe: 36-month rolling OOS Sharpe (Decimal).
        current_mdd_pct: 현재 MDD percent (음수 Decimal, 예: -45 = -45%).
        baseline_mdd_pct: 기준 MDD (ADR 0007 §3 G2 baseline 등).
        sample_size: 누적 거래 수 (int).
        human_ad_hoc_request: 사람 명시 trigger (CLI command 진입 시 True).

    Invariants (CLAUDE.md §2.1):
        - 모든 percent 필드 Decimal.
        - sample_size ≥ 0.
        - baseline_mdd_pct < 0 (drawdown 은 음수 정의).
    """

    rolling_oos_sharpe: Decimal
    current_mdd_pct: Decimal
    baseline_mdd_pct: Decimal
    sample_size: int
    human_ad_hoc_request: bool = False

    def __post_init__(self) -> None:
        if self.sample_size < 0:
            raise ValueError(f"sample_size must be ≥ 0, got {self.sample_size}")
        if self.baseline_mdd_pct >= 0:
            raise ValueError(
                f"baseline_mdd_pct must be < 0 (drawdown convention), "
                f"got {self.baseline_mdd_pct}"
            )


@dataclass(frozen=True)
class _TriggerEvaluationResult:
    """Evaluator 산출 — trigger 발화 결과 + AND-gate 충족 여부.

    Fields:
        triggered: AND-gate 충족 + sample size 충족 시 True.
        primary_signal: 발화 시 D1 trigger enum (ROLLING_OOS_SHARPE /
            DRAWDOWN / HUMAN_AD_HOC), 미충족 시 NULL_PROPOSAL.
        sample_size_sufficient: ≥ 100 거래 충족 여부.
        and_gate_components: 각 조건 충족 boolean dict — 추적성 (CLAUDE.md
            §7.1 정신, Decision reasoning 보존 정합).
        diagnostic_metrics: 평가 시점 입력 metric (sharpe / mdd / sample_size)
            보존 — proposal.reasoning_json 입력 예정.

    NULL_PROPOSAL semantics: triggered=False + primary_signal=NULL_PROPOSAL +
    추적성 보존 (자동 제안 차단, Architect 권고 #1).
    """

    triggered: bool
    primary_signal: _TriggerSignal
    sample_size_sufficient: bool
    and_gate_components: dict[str, bool]
    diagnostic_metrics: dict[str, str]


def _evaluate_triggers(
    inputs: _TriggerEvaluationInput,
    *,
    rolling_sharpe_threshold: Decimal = _DEFAULT_ROLLING_SHARPE_THRESHOLD,
    drawdown_multiplier: Decimal = _DEFAULT_DRAWDOWN_MULTIPLIER,
    sample_size_threshold: int = _DEFAULT_SAMPLE_SIZE_THRESHOLD,
) -> _TriggerEvaluationResult:
    """L2/L3 trigger AND-gate evaluation — D1 default.

    AND-gate (권고 default):
        (a) rolling_oos_sharpe < threshold
        (b) current_mdd_pct < baseline_mdd_pct x multiplier (악화)
        (c) sample_size ≥ threshold
        (d) human_ad_hoc_request (선택, OR-조합)

    충족 시 primary_signal 우선순위:
        1. HUMAN_AD_HOC (사람 명시 trigger 우선)
        2. DRAWDOWN (시장 적정성 우선)
        3. ROLLING_OOS_SHARPE (장기 통계 우선)

    미충족 시 primary_signal = NULL_PROPOSAL (자동 제안 차단).

    Args:
        inputs: 평가 입력 (D1 원천 데이터 제약 hard).
        rolling_sharpe_threshold: (i) 조건 임계 (default 0.3).
        drawdown_multiplier: (ii) baseline 악화 multiplier (default 1.50).
        sample_size_threshold: (c) 최소 거래 수 (default 100).

    Returns:
        `_TriggerEvaluationResult` — triggered / primary_signal /
        and_gate_components / diagnostic_metrics.
    """
    sharpe_violation = inputs.rolling_oos_sharpe < rolling_sharpe_threshold
    # MDD 악화 = current < baseline x multiplier (둘 다 음수, multiplier > 1)
    # 예: baseline -33%, multiplier 1.50 → threshold = -49.5%, current -55% 시 violation.
    drawdown_threshold = inputs.baseline_mdd_pct * drawdown_multiplier
    drawdown_violation = inputs.current_mdd_pct < drawdown_threshold
    sample_sufficient = inputs.sample_size >= sample_size_threshold
    human_request = inputs.human_ad_hoc_request

    components = {
        "sharpe_violation": sharpe_violation,
        "drawdown_violation": drawdown_violation,
        "sample_size_sufficient": sample_sufficient,
        "human_ad_hoc_request": human_request,
    }
    diagnostic = {
        "rolling_oos_sharpe": str(inputs.rolling_oos_sharpe),
        "current_mdd_pct": str(inputs.current_mdd_pct),
        "baseline_mdd_pct": str(inputs.baseline_mdd_pct),
        "drawdown_threshold": str(drawdown_threshold),
        "sample_size": str(inputs.sample_size),
        "rolling_sharpe_threshold": str(rolling_sharpe_threshold),
        "drawdown_multiplier": str(drawdown_multiplier),
        "sample_size_threshold": str(sample_size_threshold),
    }

    # Sample size hard gate — D14 minimum + NULL proposal semantics.
    if not sample_sufficient:
        return _TriggerEvaluationResult(
            triggered=False,
            primary_signal=_TriggerSignal.NULL_PROPOSAL,
            sample_size_sufficient=False,
            and_gate_components=components,
            diagnostic_metrics=diagnostic,
        )

    # Human ad-hoc 명시 우선 (D1 (iv) 정합).
    if human_request:
        return _TriggerEvaluationResult(
            triggered=True,
            primary_signal=_TriggerSignal.HUMAN_AD_HOC,
            sample_size_sufficient=True,
            and_gate_components=components,
            diagnostic_metrics=diagnostic,
        )

    # AND-gate (i) + (ii) — both 통계 임계 충족 필요.
    if sharpe_violation and drawdown_violation:
        # Drawdown 시장 적정성 우선 — primary_signal = DRAWDOWN.
        return _TriggerEvaluationResult(
            triggered=True,
            primary_signal=_TriggerSignal.DRAWDOWN,
            sample_size_sufficient=True,
            and_gate_components=components,
            diagnostic_metrics=diagnostic,
        )

    # 단일 조건만 충족 시 NULL_PROPOSAL (AND-gate 미충족).
    return _TriggerEvaluationResult(
        triggered=False,
        primary_signal=_TriggerSignal.NULL_PROPOSAL,
        sample_size_sufficient=True,
        and_gate_components=components,
        diagnostic_metrics=diagnostic,
    )
