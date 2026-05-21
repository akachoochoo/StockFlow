"""Phase 1.1 Stage 2.6 — ProposalHistory read-only 모드 tests (ADR 0012 D13).

D13 (a-rev) ProposalHistory read-only 모드 — Phase 1.1 변경 zero invariant
정합 (ADR 0011 §1.6 #1 강화):

- **차단**: read_only=True 시 Proposal 의 APPLIED state 전이 / 수락 차단
  (자동 적용 zero — 시스템 변경 막음).
- **허용**: trigger 발화 시 NULL proposal (PENDING/REJECTED 기록) 누적 허용
  (cumulative drift 검증 데이터 축적).
- **회귀**: read_only=False (기본) 시 기존 동작 그대로 (APPLIED 전이 정상).

게이트 token: 함수명에 `proposal_history_read_only` 포함.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import (
    _Proposal,
    _ReadOnlyModeError,
    _transition,
)
from src.research.dynamic_adjustment._proposal_history import (
    _build_applied_history,
    _ProposalHistory,
)
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)


def _spec(target: str = "069500.drop_threshold") -> _ChangeSpec:
    return _ChangeSpec(
        proposal_type=_ProposalType.PARAMETER_CHANGE,
        target=target,
        from_value=Decimal("5.0"),
        to_value=Decimal("6.0"),
        delta_pct=Decimal("20"),
        rationale="read-only mode test",
    )


def _proposal(
    *,
    proposal_id: str,
    state: _ProposalState,
    created_at: datetime,
    trigger: _TriggerSignal = _TriggerSignal.DRAWDOWN,
    adr_reference: str | None = None,
    previous_ref: str | None = None,
) -> _Proposal:
    return _Proposal(
        trigger_signal=trigger,
        current_state_snapshot={},
        proposed_change=_spec(),
        reasoning_json={},
        supporting_backtest_result=None,
        state=state,
        adr_reference=adr_reference,
        previous_proposal_ref=previous_ref,
        proposal_id=proposal_id,
        created_at=created_at,
    )


def _null_proposal(
    *,
    proposal_id: str,
    state: _ProposalState = _ProposalState.PENDING,
    created_at: datetime,
) -> _Proposal:
    """NULL_PROPOSAL trigger proposal (drift 검증 marker — APPLIED 진입 불가)."""
    return _proposal(
        proposal_id=proposal_id,
        state=state,
        created_at=created_at,
        trigger=_TriggerSignal.NULL_PROPOSAL,
    )


# ---------------------------------------------------------------------------
# 차단 — read_only=True: APPLIED 전이 시도 → raise
# ---------------------------------------------------------------------------
class TestReadOnlyBlocksApplied:
    """read_only=True 시 APPLIED 전이 / 수락 차단 (자동 적용 zero, D13)."""

    def test_proposal_history_read_only_transition_to_applied_blocked(self) -> None:
        """`_transition(..., read_only=True)` 가 ADR_FILED → APPLIED 차단."""
        adr_filed = _proposal(
            proposal_id="p1",
            state=_ProposalState.ADR_FILED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        with pytest.raises(_ReadOnlyModeError, match="Read-only mode"):
            _transition(
                adr_filed,
                to_state=_ProposalState.APPLIED,
                read_only=True,
            )

    def test_proposal_history_read_only_block_raises_value_error_subclass(
        self,
    ) -> None:
        """차단 예외는 `ValueError` subclass — 기존 catch 패턴 호환."""
        adr_filed = _proposal(
            proposal_id="p1",
            state=_ProposalState.ADR_FILED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        with pytest.raises(ValueError, match="blocks transition to APPLIED"):
            _transition(
                adr_filed,
                to_state=_ProposalState.APPLIED,
                read_only=True,
            )

    def test_proposal_history_read_only_accept_applied_proposal_blocked(
        self,
    ) -> None:
        """`_ProposalHistory(read_only=True).accept_proposal(APPLIED)` 차단."""
        history = _ProposalHistory(read_only=True)
        applied = _proposal(
            proposal_id="p1",
            state=_ProposalState.APPLIED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        with pytest.raises(_ReadOnlyModeError, match="blocks accepting APPLIED"):
            history.accept_proposal(applied)

    def test_proposal_history_read_only_non_applied_transitions_still_allowed(
        self,
    ) -> None:
        """read_only=True 라도 비-APPLIED 전이 (PENDING→APPROVED 등) 는 허용.

        Read-only = "APPLIED (시스템 변경) 만 차단". 승인/거부/ADR 박제 단계
        자체는 관찰/기록 흐름이므로 허용 (drift 데이터 + 사람 검토 가능).
        """
        pending = _proposal(
            proposal_id="p1",
            state=_ProposalState.PENDING,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
        )
        approved = _transition(
            pending,
            to_state=_ProposalState.APPROVED,
            read_only=True,
        )
        assert approved.state is _ProposalState.APPROVED
        adr_filed = _transition(
            approved,
            to_state=_ProposalState.ADR_FILED,
            adr_reference="docs/decisions/0099.md",
            read_only=True,
        )
        assert adr_filed.state is _ProposalState.ADR_FILED


# ---------------------------------------------------------------------------
# 허용 — read_only=True: NULL proposal 누적 (drift 데이터 축적)
# ---------------------------------------------------------------------------
class TestReadOnlyAllowsNullProposalAccumulation:
    """read_only=True 시 NULL proposal 누적 허용 (cumulative drift 검증)."""

    def test_proposal_history_read_only_null_proposal_accumulation_allowed(
        self,
    ) -> None:
        """NULL proposal (PENDING) accept → applied snapshot 불변 + raise 없음.

        NULL_PROPOSAL 은 APPLIED 진입 불가 (`_Proposal.__post_init__`).
        read-only history 가 NULL proposal 을 받아도 차단되지 않으며,
        applied_proposals snapshot 은 그대로 (관찰/기록 only).
        """
        history = _ProposalHistory(read_only=True)
        null_p = _null_proposal(
            proposal_id="null-1",
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
        )
        result = history.accept_proposal(null_p)
        assert result.read_only is True
        # NULL proposal 은 applied list 에 들어가지 않음 (APPLIED only invariant).
        assert result.applied_count() == 0

    def test_proposal_history_read_only_multiple_null_proposals_accumulate(
        self,
    ) -> None:
        """여러 NULL proposal 연속 accept — 차단 zero (drift 데이터 누적 흐름)."""
        history = _ProposalHistory(read_only=True)
        for i in range(5):
            null_p = _null_proposal(
                proposal_id=f"null-{i}",
                created_at=datetime(2026, 5, 13, tzinfo=UTC) + timedelta(weeks=i),
            )
            # 차단 없이 통과해야 함.
            history = history.accept_proposal(null_p)
        assert history.read_only is True
        assert history.applied_count() == 0

    def test_proposal_history_read_only_rejected_null_proposal_allowed(
        self,
    ) -> None:
        """NULL_PROPOSAL REJECTED 기록도 read-only 에서 accept 허용."""
        history = _ProposalHistory(read_only=True)
        rejected_null = _null_proposal(
            proposal_id="null-rej",
            state=_ProposalState.REJECTED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
        )
        result = history.accept_proposal(rejected_null)
        assert result.applied_count() == 0


# ---------------------------------------------------------------------------
# 회귀 — read_only=False (기본): 기존 동작 그대로
# ---------------------------------------------------------------------------
class TestReadOnlyDefaultFalseRegression:
    """read_only=False (기본) 시 APPLIED 전이 / 수락 정상 (회귀 zero)."""

    def test_proposal_history_read_only_default_false_transition_applied_ok(
        self,
    ) -> None:
        """기본 (read_only 미지정) — ADR_FILED → APPLIED 정상 전이."""
        adr_filed = _proposal(
            proposal_id="p1",
            state=_ProposalState.ADR_FILED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        applied = _transition(adr_filed, to_state=_ProposalState.APPLIED)
        assert applied.state is _ProposalState.APPLIED
        assert applied.adr_reference == "docs/decisions/0099.md"

    def test_proposal_history_read_only_explicit_false_transition_applied_ok(
        self,
    ) -> None:
        """read_only=False 명시 — APPLIED 전이 정상 (회귀)."""
        adr_filed = _proposal(
            proposal_id="p1",
            state=_ProposalState.ADR_FILED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        applied = _transition(
            adr_filed,
            to_state=_ProposalState.APPLIED,
            read_only=False,
        )
        assert applied.state is _ProposalState.APPLIED

    def test_proposal_history_read_only_default_false_accept_applied_ok(
        self,
    ) -> None:
        """기본 history (read_only=False) — APPLIED proposal accept 정상."""
        history = _ProposalHistory()
        assert history.read_only is False
        applied = _proposal(
            proposal_id="p1",
            state=_ProposalState.APPLIED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        result = history.accept_proposal(applied)
        assert result.applied_count() == 1
        assert result.applied_proposals[0].proposal_id == "p1"

    def test_proposal_history_read_only_accept_preserves_sort_order(
        self,
    ) -> None:
        """read_only=False accept — created_at 오름차순 invariant 보존."""
        history = _ProposalHistory()
        later = _proposal(
            proposal_id="p2",
            state=_ProposalState.APPLIED,
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        earlier = _proposal(
            proposal_id="p1",
            state=_ProposalState.APPLIED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        history = history.accept_proposal(later)
        history = history.accept_proposal(earlier)
        assert [p.proposal_id for p in history.applied_proposals] == ["p1", "p2"]


# ---------------------------------------------------------------------------
# Factory — _build_applied_history(..., read_only=...)
# ---------------------------------------------------------------------------
class TestBuildAppliedHistoryReadOnlyFlag:
    """`_build_applied_history` read_only passthrough."""

    def test_proposal_history_read_only_factory_default_false(self) -> None:
        history = _build_applied_history([])
        assert history.read_only is False

    def test_proposal_history_read_only_factory_true_propagates(self) -> None:
        applied = _proposal(
            proposal_id="p1",
            state=_ProposalState.APPLIED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        history = _build_applied_history([applied], read_only=True)
        assert history.read_only is True
        # 기존 invariant 유지 — APPLIED 만 필터됨.
        assert history.applied_count() == 1

    def test_proposal_history_read_only_factory_true_blocks_further_applied(
        self,
    ) -> None:
        """read_only=True 로 build 된 history 의 accept_proposal(APPLIED) 차단."""
        history = _build_applied_history([], read_only=True)
        applied = _proposal(
            proposal_id="p1",
            state=_ProposalState.APPLIED,
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            adr_reference="docs/decisions/0099.md",
        )
        with pytest.raises(_ReadOnlyModeError):
            history.accept_proposal(applied)
