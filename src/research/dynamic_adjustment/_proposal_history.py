"""Phase 0.11.e.2 — `_ProposalHistory` 도메인 + Structural Constraints (ADR 0011 §1.3 D14).

R2 cascading 추적 책임 + D3 SRP 분리 — `_Proposal` = 순간 snapshot,
`_ProposalHistory` = cumulative + structural bound.

ADR 0011 §1.3 D14 Structural Constraints 3 축 (Critic default 수락):
    - Minimum interval: 동일 parameter target 의 연속 변경 = **최소 12 주
      간격** (D2 주간 cron x 12 = 분기 1 회 정합).
    - Cumulative drift bound: 초기 설정 대비 parameter 절대 변동 **±30%
      한계**. 초과 시 NULL proposal + 사람 ADR (전체 재설정) 의무.
    - Trigger cooldown: trigger 발화 → APPLIED 후 **동일 trigger 재발화
      차단 12 주**.

본 모듈 = `_ProposalHistory` dataclass + 3 검증 함수 (minimum_interval /
cumulative_drift / trigger_cooldown). 실제 저장 / 영구화 = sub-step
0.11.e.3 (CLI workflow) 영역.

Lifecycle: 5th ring 영구 유지 (D13).
Underscore-prefix private (`__all__ = []`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from src.research.dynamic_adjustment._proposal import _ReadOnlyModeError
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)

if TYPE_CHECKING:
    from datetime import datetime

    from src.research.dynamic_adjustment._proposal import _Proposal


__all__: list[str] = []


_MINIMUM_INTERVAL_WEEKS = 12
_TRIGGER_COOLDOWN_WEEKS = 12
_CUMULATIVE_DRIFT_BOUND_PCT = Decimal("30")  # ±30% absolute


@dataclass(frozen=True)
class _ProposalHistory:
    """누적 proposal 히스토리 — APPLIED state 의 proposal time-ordered 보존.

    `_Proposal` (순간 snapshot) 과 SRP 분리 — 본 객체는 cumulative drift +
    self-trigger detection + structural constraints 책임 (D14 옵션 β 정합).

    Fields:
        applied_proposals: 시간순 APPLIED state proposal list (created_at
            오름차순). 외부 caller 책임 — 본 모듈은 list 가 정렬되어 있다고
            가정.
        initial_values: 초기 설정 박제 — `{target: Decimal}` mapping.
            cumulative drift 계산의 reference. 보통 Phase 0.7.3 baseline
            또는 Phase 1 ADR 0012 진입 시점 값.
        read_only: Phase 1.1 read-only 모드 (ADR 0012 D13 (a-rev)). True 시
            `accept_proposal(...)` 가 APPLIED state proposal 수락 차단 +
            APPLIED 전이 차단 — 변경 zero invariant 정합. NULL proposal
            (PENDING/REJECTED 기록) 누적은 허용 (cumulative drift 검증
            데이터 보유). 기본 False = Phase 1.2+ 정상 (회귀 zero).

    검증 함수 (메서드):
        - check_minimum_interval(...) — 동일 target 12주 간격.
        - check_cumulative_drift(...) — ±30% 한계.
        - check_trigger_cooldown(...) — 동일 trigger 12주 cooldown.
        - self_trigger_chain(...) — previous_proposal_ref 체인 추적.
        - accept_proposal(...) — read-only 모드 게이트 (D13).

    CLAUDE.md §2.1 Decimal invariant — drift 값 float 미경유.
    """

    applied_proposals: list[_Proposal] = field(default_factory=list)
    initial_values: dict[str, Decimal] = field(default_factory=dict)
    read_only: bool = False

    def accept_proposal(self, proposal: _Proposal) -> _ProposalHistory:
        """proposal 1 건을 history 에 수락 — read-only 모드 게이트 (D13).

        Read-only 모드 (`self.read_only is True`, ADR 0012 D13 (a-rev)) 의
        본질을 enforce:

        - **허용**: NULL proposal 누적 (PENDING / REJECTED 기록). cumulative
          drift 검증 데이터 축적. APPLIED 가 아닌 proposal 은 `applied_proposals`
          에 반영되지 않으므로 history snapshot 은 그대로 (read-only 관찰).
        - **차단**: APPLIED state proposal 수락 — `_ReadOnlyModeError` raise.
          Phase 1.1 변경 zero invariant 정합 (ADR 0011 §1.6 #1 강화).

        `frozen=True` dataclass — 새 instance 반환 (immutable). APPLIED
        proposal 수락 시 created_at 오름차순 유지 + APPLIED only invariant
        보존 (`_build_applied_history` 정신 정합).

        Args:
            proposal: 수락할 proposal.

        Returns:
            새 `_ProposalHistory` instance. APPLIED proposal 수락 시
            `applied_proposals` 에 정렬 삽입; non-APPLIED (NULL 포함) 수락 시
            현 snapshot 그대로 (read-only 관찰 — applied list 불변).

        Raises:
            _ReadOnlyModeError: read_only=True + proposal.state == APPLIED.
        """
        if self.read_only and proposal.state is _ProposalState.APPLIED:
            raise _ReadOnlyModeError(
                f"Read-only mode (ADR 0012 D13) blocks accepting APPLIED "
                f"proposal {proposal.proposal_id!r}. Phase 1.1 변경 zero "
                f"invariant — NULL proposal 누적은 허용, APPLIED 는 차단."
            )
        if proposal.state is not _ProposalState.APPLIED:
            # Non-APPLIED (NULL proposal 포함) — read-only 관찰. applied
            # snapshot 불변 (APPLIED only invariant 보존).
            return self
        merged = [*self.applied_proposals, proposal]
        merged.sort(key=lambda p: p.created_at)
        return _ProposalHistory(
            applied_proposals=merged,
            initial_values=dict(self.initial_values),
            read_only=self.read_only,
        )

    def check_minimum_interval(
        self,
        target: str,
        new_proposal_created_at: datetime,
    ) -> bool:
        """동일 target 의 연속 변경 = 최소 12 주 간격 (D14 minimum_interval).

        Args:
            target: 변경 대상 식별 (예: yaml field path).
            new_proposal_created_at: 신규 proposal 생성 시점 (UTC).

        Returns:
            True if interval ≥ 12 weeks since last APPLIED for same target,
            or no prior history. False if violation.
        """
        prior = [
            p for p in self.applied_proposals
            if p.proposed_change.target == target
        ]
        if not prior:
            return True
        last_applied = prior[-1]
        interval = new_proposal_created_at - last_applied.created_at
        return interval >= timedelta(weeks=_MINIMUM_INTERVAL_WEEKS)

    def check_cumulative_drift(
        self,
        target: str,
        new_value: Decimal,
    ) -> bool:
        """초기 설정 대비 절대 변동 ≤ ±30% 검증 (D14 cumulative_drift).

        Args:
            target: 변경 대상.
            new_value: 신규 값 (Decimal, percent unit 또는 절대값 — drift
                계산 시 initial_values[target] 기준 비율).

        Returns:
            True if |new_value - initial| / initial ≤ 0.30. False if drift
            bound 위반. initial 부재 시 True (drift 측정 불가, 보수적
            허용 + 별도 NULL proposal 정책 영역).
        """
        initial = self.initial_values.get(target)
        if initial is None or initial == 0:
            return True
        drift_pct = abs(new_value - initial) / abs(initial) * Decimal("100")
        return drift_pct <= _CUMULATIVE_DRIFT_BOUND_PCT

    def check_trigger_cooldown(
        self,
        trigger: _TriggerSignal,
        new_proposal_created_at: datetime,
    ) -> bool:
        """동일 trigger 재발화 cooldown 12 주 (D14 trigger_cooldown).

        Args:
            trigger: 신규 trigger 신호.
            new_proposal_created_at: 신규 proposal 생성 시점 (UTC).

        Returns:
            True if cooldown 충족 (이전 APPLIED 동일 trigger 부재 또는
            12주 이상 경과). False if violation.

        Note:
            NULL_PROPOSAL trigger 는 cooldown 미적용 (자동 차단 marker).
        """
        if trigger is _TriggerSignal.NULL_PROPOSAL:
            return True
        prior = [
            p for p in self.applied_proposals
            if p.trigger_signal is trigger
        ]
        if not prior:
            return True
        last_applied = prior[-1]
        interval = new_proposal_created_at - last_applied.created_at
        return interval >= timedelta(weeks=_TRIGGER_COOLDOWN_WEEKS)

    def self_trigger_chain(
        self,
        proposal: _Proposal,
        *,
        max_depth: int = 10,
    ) -> list[str]:
        """previous_proposal_ref 체인 추적 (D14 자기-trigger 감지).

        Args:
            proposal: 현 proposal — chain 의 head.
            max_depth: 추적 깊이 한계 (cycle defensive).

        Returns:
            proposal_id list — chain 의 history (현 proposal 의 ancestor
            sequence). 자기-trigger detection 의 입력 — caller 가 chain
            length / circularity 검증.
        """
        chain: list[str] = []
        ids_by_proposal = {p.proposal_id: p for p in self.applied_proposals}
        current_ref = proposal.previous_proposal_ref
        depth = 0
        while current_ref is not None and depth < max_depth:
            if current_ref in chain:
                # cycle 감지 — 추적 종료 + 박제
                break
            chain.append(current_ref)
            prev = ids_by_proposal.get(current_ref)
            if prev is None:
                break
            current_ref = prev.previous_proposal_ref
            depth += 1
        return chain

    def applied_count(self) -> int:
        """APPLIED state proposal 총 수 — 외부 caller diagnostic 용.

        invariant: `self.applied_proposals` 의 모든 entry 가 APPLIED state
        여야 함 — 본 메서드는 단순 length 반환 (검증은 add_applied 영역).
        """
        return len(self.applied_proposals)

    def filtered_by_type(
        self,
        proposal_type: _ProposalType,
    ) -> list[_Proposal]:
        """특정 ProposalType 의 APPLIED proposal list 추출."""
        return [
            p for p in self.applied_proposals
            if p.proposed_change.proposal_type is proposal_type
        ]


def _build_applied_history(
    proposals: list[_Proposal],
    initial_values: dict[str, Decimal] | None = None,
    *,
    read_only: bool = False,
) -> _ProposalHistory:
    """APPLIED state proposal 만 필터 + time-ordered 정렬 후 history 박제.

    factory pattern — caller 가 raw proposal list 를 넘기면 본 함수가
    invariant (APPLIED only + 정렬) 강제.

    Args:
        proposals: raw proposal list (state 혼재 가능).
        initial_values: 초기 설정 mapping (선택). None 시 빈 dict.
        read_only: Phase 1.1 read-only 모드 (ADR 0012 D13). True 시 생성된
            history 의 `accept_proposal(...)` 가 APPLIED 수락 차단. 기본
            False = 회귀 zero.

    Returns:
        `_ProposalHistory` — APPLIED 만 + created_at 오름차순 + initial_values.
    """
    applied = [p for p in proposals if p.state is _ProposalState.APPLIED]
    applied.sort(key=lambda p: p.created_at)
    return _ProposalHistory(
        applied_proposals=applied,
        initial_values=dict(initial_values) if initial_values else {},
        read_only=read_only,
    )
