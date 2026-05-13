"""Phase 0.11.e.2 — `_Proposal` invariants + state machine tests.

ADR 0011 §1.3 D3 + D6 + §1.6 #4 enforcement.

검증 항목:
    - 8 필드 + identity (proposal_id / created_at) frozen.
    - 4-state machine 전이 가드 (`_can_transition` + `_transition`).
    - APPROVED → APPLIED 직접 전이 차단 (§1.6 #4).
    - REJECTED terminal 재진입 불가.
    - NULL_PROPOSAL semantics — auto-blocked (state ∈ {PENDING, REJECTED}).
    - UTC tzinfo guard (CLAUDE.md §3.1).
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import (
    _can_transition,
    _Proposal,
    _transition,
)
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)


def _make_spec() -> _ChangeSpec:
    return _ChangeSpec(
        proposal_type=_ProposalType.PARAMETER_CHANGE,
        target="069500.buy_parameters.drop_threshold_pct",
        from_value=Decimal("5.0"),
        to_value=Decimal("6.0"),
        delta_pct=Decimal("20"),
        rationale="DD spike — tighten threshold",
    )


def _make_proposal(
    *,
    state: _ProposalState = _ProposalState.PENDING,
    trigger: _TriggerSignal = _TriggerSignal.DRAWDOWN,
    adr_reference: str | None = None,
    proposal_id: str = "prop-001",
    previous_ref: str | None = None,
) -> _Proposal:
    return _Proposal(
        trigger_signal=trigger,
        current_state_snapshot={"baseline_mdd_pct": "-33"},
        proposed_change=_make_spec(),
        reasoning_json={"sharpe": "0.25", "mdd": "-50"},
        supporting_backtest_result=None,
        state=state,
        adr_reference=adr_reference,
        previous_proposal_ref=previous_ref,
        proposal_id=proposal_id,
        created_at=datetime(2026, 5, 13, tzinfo=UTC),
    )


class TestAC1FrozenAndConstruction:
    """8 필드 + identity frozen + 정상 인스턴스화."""

    def test_construct(self) -> None:
        p = _make_proposal()
        assert p.trigger_signal is _TriggerSignal.DRAWDOWN
        assert p.state is _ProposalState.PENDING
        assert p.proposed_change.target.startswith("069500")

    def test_frozen_mutation_raises(self) -> None:
        p = _make_proposal()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.state = _ProposalState.APPROVED  # type: ignore[misc]


class TestAC2NullProposalSemantics:
    """NULL_PROPOSAL trigger → state ∈ {PENDING, REJECTED} (자동 차단)."""

    def test_null_pending_allowed(self) -> None:
        p = _make_proposal(
            trigger=_TriggerSignal.NULL_PROPOSAL,
            state=_ProposalState.PENDING,
        )
        assert p.trigger_signal is _TriggerSignal.NULL_PROPOSAL

    def test_null_rejected_allowed(self) -> None:
        p = _make_proposal(
            trigger=_TriggerSignal.NULL_PROPOSAL,
            state=_ProposalState.REJECTED,
        )
        assert p.state is _ProposalState.REJECTED

    def test_null_approved_blocked(self) -> None:
        with pytest.raises(ValueError, match="NULL_PROPOSAL"):
            _make_proposal(
                trigger=_TriggerSignal.NULL_PROPOSAL,
                state=_ProposalState.APPROVED,
            )

    def test_null_applied_blocked(self) -> None:
        with pytest.raises(ValueError, match="NULL_PROPOSAL"):
            _make_proposal(
                trigger=_TriggerSignal.NULL_PROPOSAL,
                state=_ProposalState.APPLIED,
                adr_reference="docs/decisions/0099-null-proposal.md",
            )


class TestAC3AdrReferenceInvariants:
    """ADR_FILED / APPLIED 는 adr_reference 필수."""

    def test_adr_filed_requires_reference(self) -> None:
        with pytest.raises(ValueError, match="ADR_FILED state requires adr_reference"):
            _make_proposal(
                state=_ProposalState.ADR_FILED,
                adr_reference=None,
            )

    def test_applied_requires_reference(self) -> None:
        with pytest.raises(ValueError, match="APPLIED state requires adr_reference"):
            _make_proposal(
                state=_ProposalState.APPLIED,
                adr_reference=None,
            )

    def test_adr_filed_with_reference_ok(self) -> None:
        p = _make_proposal(
            state=_ProposalState.ADR_FILED,
            adr_reference="docs/decisions/0099-param-change.md",
        )
        assert p.adr_reference is not None


class TestAC4SelfLoopGuard:
    """previous_proposal_ref ≠ self.proposal_id (chain integrity)."""

    def test_self_loop_blocked(self) -> None:
        with pytest.raises(ValueError, match="self-loop blocked"):
            _make_proposal(
                proposal_id="prop-001",
                previous_ref="prop-001",
            )


class TestAC5UtcTzinfoGuard:
    """created_at tzinfo UTC invariant (CLAUDE.md §3.1)."""

    def test_naive_datetime_raises(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware UTC"):
            _Proposal(
                trigger_signal=_TriggerSignal.DRAWDOWN,
                current_state_snapshot={},
                proposed_change=_make_spec(),
                reasoning_json={},
                supporting_backtest_result=None,
                state=_ProposalState.PENDING,
                proposal_id="x",
                created_at=datetime(2026, 5, 13),  # naive
            )


class TestAC6StateMachineTransitions:
    """`_can_transition` 검증 — 4-state + REJECTED terminal."""

    def test_pending_to_approved(self) -> None:
        assert _can_transition(_ProposalState.PENDING, _ProposalState.APPROVED)

    def test_pending_to_rejected(self) -> None:
        assert _can_transition(_ProposalState.PENDING, _ProposalState.REJECTED)

    def test_approved_to_adr_filed(self) -> None:
        assert _can_transition(_ProposalState.APPROVED, _ProposalState.ADR_FILED)

    def test_adr_filed_to_applied(self) -> None:
        assert _can_transition(_ProposalState.ADR_FILED, _ProposalState.APPLIED)

    def test_approved_to_applied_blocked(self) -> None:
        """§1.6 #4 — APPROVED → APPLIED 직접 전이 차단 hard."""
        assert not _can_transition(_ProposalState.APPROVED, _ProposalState.APPLIED)

    def test_rejected_terminal(self) -> None:
        for to in (
            _ProposalState.PENDING,
            _ProposalState.APPROVED,
            _ProposalState.ADR_FILED,
            _ProposalState.APPLIED,
        ):
            assert not _can_transition(_ProposalState.REJECTED, to), (
                f"REJECTED → {to.value} should be blocked (terminal)"
            )

    def test_applied_terminal(self) -> None:
        for to in (
            _ProposalState.PENDING,
            _ProposalState.APPROVED,
            _ProposalState.ADR_FILED,
            _ProposalState.REJECTED,
        ):
            assert not _can_transition(_ProposalState.APPLIED, to)

    def test_reverse_transitions_blocked(self) -> None:
        """역전이 차단 (예: ADR_FILED → APPROVED)."""
        assert not _can_transition(
            _ProposalState.ADR_FILED, _ProposalState.APPROVED,
        )
        assert not _can_transition(
            _ProposalState.APPROVED, _ProposalState.PENDING,
        )


class TestAC7TransitionFunction:
    """`_transition` — 새 instance 반환 + adr_reference 박제."""

    def test_pending_to_approved(self) -> None:
        p = _make_proposal()
        next_p = _transition(p, to_state=_ProposalState.APPROVED)
        assert next_p.state is _ProposalState.APPROVED
        assert next_p.proposal_id == p.proposal_id
        # Original unchanged (frozen).
        assert p.state is _ProposalState.PENDING

    def test_approved_to_adr_filed_with_reference(self) -> None:
        approved = _make_proposal(state=_ProposalState.APPROVED)
        adr_filed = _transition(
            approved,
            to_state=_ProposalState.ADR_FILED,
            adr_reference="docs/decisions/0099.md",
        )
        assert adr_filed.state is _ProposalState.ADR_FILED
        assert adr_filed.adr_reference == "docs/decisions/0099.md"

    def test_blocked_transition_raises(self) -> None:
        approved = _make_proposal(state=_ProposalState.APPROVED)
        with pytest.raises(ValueError, match="Transition blocked"):
            _transition(approved, to_state=_ProposalState.APPLIED)

    def test_full_happy_path(self) -> None:
        """PENDING → APPROVED → ADR_FILED → APPLIED end-to-end."""
        p = _make_proposal()
        p = _transition(p, to_state=_ProposalState.APPROVED)
        p = _transition(
            p,
            to_state=_ProposalState.ADR_FILED,
            adr_reference="docs/decisions/0099.md",
        )
        p = _transition(p, to_state=_ProposalState.APPLIED)
        assert p.state is _ProposalState.APPLIED
        assert p.adr_reference == "docs/decisions/0099.md"
