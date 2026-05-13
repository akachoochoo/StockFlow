"""Phase 0.11.e.2 — `_Proposal` 도메인 객체 (ADR 0011 §1.3 D3 + D6).

순간 snapshot 박제 (cumulative history 는 `_ProposalHistory` 영역, D14
SRP 분리).

8 필드 (D3 + Round 1 ITERATE Patch 1):
    1. trigger_signal — D1 trigger enum
    2. current_state_snapshot — proposal 시점 portfolio + parameter 상태
    3. proposed_change — L2 = parameter delta, L3 = strategy/universe delta
    4. reasoning_json — CLAUDE.md §7.1 결정 시점 입력값 전체 JSON
    5. supporting_backtest_result — ADR 0008/0009 산출 직접 호출 (D11)
    6. state — 4-state 머신 + REJECTED terminal (D6)
    7. adr_reference — APPROVED→ADR_FILED 전이 시 박제
    8. previous_proposal_ref — 직전 동일-parameter proposal 참조 (D14 입력)

추가 identity 필드 (D3 8 필드 외):
    - proposal_id — uuid str 식별자 (D14 chain + storage key)
    - created_at — UTC datetime (D14 minimum interval 입력)

State transition 가드 (§1.6 #4 enforcement):
    - PENDING → APPROVED: 사람 CLI 명령 (sub-step .3 영역).
    - APPROVED → ADR_FILED: `os.path.exists` (sub-step .3 영역).
    - ADR_FILED → APPLIED: cron pickup (sub-step .3 영역).
    - APPROVED → APPLIED 직접 전이 = **차단 hard**.
    - REJECTED = terminal.

본 모듈은 *상태 전이 검증 함수 + frozen Proposal* 만 제공. 실제 전이
trigger (CLI / cron) 는 sub-step 0.11.e.3 영역.

Lifecycle: 5th ring 영구 유지 (D13).
Underscore-prefix private (`__all__ = []`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _TriggerSignal,
)

if TYPE_CHECKING:
    from src.research.dynamic_adjustment._change_spec import _ChangeSpec


__all__: list[str] = []


@dataclass(frozen=True)
class _Proposal:
    """L2/L3 변경 제안 — 순간 snapshot (D14 cumulative history 와 분리).

    D3 8 필드 + identity (proposal_id / created_at). frozen — state 전이
    시 새 instance 생성 (immutable transition).

    Invariants (model-level):
        - state == APPROVED → adr_reference 는 None 일 수 있음 (ADR file 박제 전).
        - state == ADR_FILED → adr_reference is not None 필수.
        - state == APPLIED → adr_reference is not None 필수 (ADR_FILED 경유).
        - trigger_signal == NULL_PROPOSAL → state ∈ {PENDING, REJECTED}
          (자동 제안 차단, Architect 권고 #1).
        - previous_proposal_ref != self.proposal_id (self-loop 차단).
    """

    trigger_signal: _TriggerSignal
    current_state_snapshot: dict[str, Any]
    proposed_change: _ChangeSpec
    reasoning_json: dict[str, Any]
    supporting_backtest_result: dict[str, Any] | None
    state: _ProposalState
    adr_reference: str | None = None
    previous_proposal_ref: str | None = None
    proposal_id: str = field(default="")
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC),
    )

    def __post_init__(self) -> None:
        # ADR file reference invariant per state
        if self.state is _ProposalState.ADR_FILED and self.adr_reference is None:
            raise ValueError(
                "ADR_FILED state requires adr_reference (file path / id)"
            )
        if self.state is _ProposalState.APPLIED and self.adr_reference is None:
            raise ValueError(
                "APPLIED state requires adr_reference — APPROVED→APPLIED "
                "direct transition is blocked (§1.6 #4 invariant)"
            )

        # NULL_PROPOSAL semantics — auto-blocked, only PENDING/REJECTED
        if self.trigger_signal is _TriggerSignal.NULL_PROPOSAL and (
            self.state
            not in {_ProposalState.PENDING, _ProposalState.REJECTED}
        ):
            raise ValueError(
                f"NULL_PROPOSAL trigger requires state ∈ {{PENDING, REJECTED}}, "
                f"got {self.state.value}"
            )

        # Self-loop guard (D14 chain integrity)
        if (
            self.previous_proposal_ref is not None
            and self.proposal_id
            and self.previous_proposal_ref == self.proposal_id
        ):
            raise ValueError(
                f"previous_proposal_ref ({self.previous_proposal_ref}) must "
                f"not equal proposal_id (self-loop blocked)"
            )

        # UTC tzinfo guard (CLAUDE.md §3.1)
        if self.created_at.tzinfo is None:
            raise ValueError(
                "created_at must be timezone-aware UTC (CLAUDE.md §3.1)"
            )
        if self.created_at.utcoffset() != timedelta(0):
            raise ValueError(
                f"created_at must be UTC offset 0, got {self.created_at.utcoffset()}"
            )


def _can_transition(
    from_state: _ProposalState,
    to_state: _ProposalState,
) -> bool:
    """4-state 머신 + REJECTED terminal 전이 검증 (§1.6 #4).

    허용 전이:
        PENDING → APPROVED / REJECTED
        APPROVED → ADR_FILED
        ADR_FILED → APPLIED

    차단 전이 (정신적으로 invalid):
        - APPROVED → APPLIED (direct, §1.6 #4 invariant)
        - REJECTED → * (terminal)
        - APPLIED → * (terminal)
        - 역전이 (예: APPLIED → APPROVED)

    Returns True if transition is allowed, False otherwise.
    """
    allowed: dict[_ProposalState, set[_ProposalState]] = {
        _ProposalState.PENDING: {_ProposalState.APPROVED, _ProposalState.REJECTED},
        _ProposalState.APPROVED: {_ProposalState.ADR_FILED},
        _ProposalState.ADR_FILED: {_ProposalState.APPLIED},
        _ProposalState.APPLIED: set(),
        _ProposalState.REJECTED: set(),
    }
    return to_state in allowed.get(from_state, set())


def _transition(
    proposal: _Proposal,
    *,
    to_state: _ProposalState,
    adr_reference: str | None = None,
) -> _Proposal:
    """순수 함수 전이 — 새 Proposal instance 반환 (immutable).

    Args:
        proposal: 현 proposal.
        to_state: 목적 state.
        adr_reference: APPROVED → ADR_FILED 전이 시 의무 (file path).

    Returns:
        새 `_Proposal` instance (frozen) — 동일 8 필드 + 변경된 state +
        선택적 adr_reference.

    Raises:
        ValueError: 차단 전이 시도.
    """
    if not _can_transition(proposal.state, to_state):
        raise ValueError(
            f"Transition blocked: {proposal.state.value} → {to_state.value} "
            f"(§1.6 #4 4-state 머신 invariant)"
        )
    new_adr = adr_reference if adr_reference is not None else proposal.adr_reference
    return _Proposal(
        trigger_signal=proposal.trigger_signal,
        current_state_snapshot=proposal.current_state_snapshot,
        proposed_change=proposal.proposed_change,
        reasoning_json=proposal.reasoning_json,
        supporting_backtest_result=proposal.supporting_backtest_result,
        state=to_state,
        adr_reference=new_adr,
        previous_proposal_ref=proposal.previous_proposal_ref,
        proposal_id=proposal.proposal_id,
        created_at=proposal.created_at,
    )
