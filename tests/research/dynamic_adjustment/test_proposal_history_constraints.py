"""Phase 0.11.e.4 — D14 `proposal_history_constraints` 통합 test suite.

ADR 0011 §1.3 D14 Enforcement:
    `pytest -k proposal_history_constraints` test 로
    (a) minimum interval 위반 시 proposal 생성 차단,
    (b) cumulative drift bound 위반 시 NULL proposal 생성,
    (c) trigger cooldown 위반 시 trigger 발화 차단 검증.

본 모듈 = D14 의 3 축 (minimum_interval / cumulative_drift /
trigger_cooldown) **통합 시나리오** test — `test_proposal_history.py`
의 단위 test 와 보완 관계.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import _Proposal
from src.research.dynamic_adjustment._proposal_history import _ProposalHistory
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)


def _applied(
    *,
    proposal_id: str,
    created_at: datetime,
    target: str = "069500.drop_threshold",
    trigger: _TriggerSignal = _TriggerSignal.DRAWDOWN,
) -> _Proposal:
    spec = _ChangeSpec(
        proposal_type=_ProposalType.PARAMETER_CHANGE,
        target=target,
        from_value=Decimal("5.0"),
        to_value=Decimal("6.0"),
        delta_pct=Decimal("20"),
        rationale="test",
    )
    return _Proposal(
        trigger_signal=trigger,
        current_state_snapshot={},
        proposed_change=spec,
        reasoning_json={},
        supporting_backtest_result=None,
        state=_ProposalState.APPLIED,
        adr_reference="docs/decisions/0099.md",
        proposal_id=proposal_id,
        created_at=created_at,
    )


class TestProposalHistoryConstraintsIntegration:
    """D14 3 축 통합 — 시나리오 기반 cumulative drift + minimum interval +
    trigger cooldown 동시 검증.
    """

    def test_minimum_interval_violation_blocks_new_proposal(self) -> None:
        """(a) minimum interval 위반 시 proposal 생성 차단."""
        prior = datetime(2026, 5, 1, tzinfo=UTC)
        history = _ProposalHistory(
            applied_proposals=[
                _applied(proposal_id="p1", created_at=prior),
            ],
        )
        # 11 weeks later — within minimum interval.
        new_date = prior + timedelta(weeks=11)
        assert not history.check_minimum_interval(
            target="069500.drop_threshold",
            new_proposal_created_at=new_date,
        ), "D14 minimum interval 위반이 차단되지 않음"

    def test_cumulative_drift_bound_violation_triggers_null(self) -> None:
        """(b) cumulative drift bound 위반 = NULL proposal trigger."""
        history = _ProposalHistory(
            initial_values={"069500.drop_threshold": Decimal("5.0")},
        )
        # +40% drift — exceeds ±30% bound.
        assert not history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("7.0"),
        ), "D14 cumulative drift bound 위반이 차단되지 않음"

    def test_trigger_cooldown_violation_blocks_trigger(self) -> None:
        """(c) trigger cooldown 위반 시 trigger 발화 차단."""
        prior = datetime(2026, 5, 1, tzinfo=UTC)
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1",
                created_at=prior,
                trigger=_TriggerSignal.DRAWDOWN,
            )],
        )
        new_date = prior + timedelta(weeks=8)  # within cooldown
        assert not history.check_trigger_cooldown(
            trigger=_TriggerSignal.DRAWDOWN,
            new_proposal_created_at=new_date,
        ), "D14 trigger cooldown 위반이 차단되지 않음"

    def test_all_three_constraints_pass_after_quarter(self) -> None:
        """3 축 모두 충족 시나리오 — 분기 (13 weeks) 후 모두 통과."""
        prior = datetime(2026, 1, 1, tzinfo=UTC)
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1",
                created_at=prior,
                trigger=_TriggerSignal.DRAWDOWN,
            )],
            initial_values={"069500.drop_threshold": Decimal("5.0")},
        )
        new_date = prior + timedelta(weeks=13)
        # All three checks must pass.
        assert history.check_minimum_interval(
            target="069500.drop_threshold",
            new_proposal_created_at=new_date,
        )
        assert history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("5.5"),  # +10% drift, within bound
        )
        assert history.check_trigger_cooldown(
            trigger=_TriggerSignal.DRAWDOWN,
            new_proposal_created_at=new_date,
        )

    def test_drift_bound_at_exact_boundary_passes(self) -> None:
        """경계값 정확 (+30%) 시 통과 (≤ inclusive)."""
        history = _ProposalHistory(
            initial_values={"069500.drop_threshold": Decimal("10.0")},
        )
        # 10.0 → 13.0 = +30% exactly.
        assert history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("13.0"),
        )
        # 10.0 → 7.0 = -30% exactly.
        assert history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("7.0"),
        )

    def test_minimum_interval_at_exact_boundary_passes(self) -> None:
        """경계값 정확 (12 weeks) 시 통과 (≥ inclusive)."""
        prior = datetime(2026, 1, 1, tzinfo=UTC)
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1", created_at=prior,
            )],
        )
        new_date = prior + timedelta(weeks=12)
        assert history.check_minimum_interval(
            target="069500.drop_threshold",
            new_proposal_created_at=new_date,
        )

    def test_cascading_history_chain_detection(self) -> None:
        """Self-trigger chain — 이전 변경이 현재 trigger 의 원인 추적.

        D14 (c) self_trigger detection — `previous_proposal_ref` 체인
        따라 chain 추적.
        """
        prior_a = datetime(2026, 1, 1, tzinfo=UTC)
        prior_b = datetime(2026, 4, 1, tzinfo=UTC)
        prior_c = datetime(2026, 7, 1, tzinfo=UTC)
        p1 = _applied(proposal_id="p1", created_at=prior_a)
        p2 = _applied(proposal_id="p2", created_at=prior_b)
        # Manually set previous_ref via direct construction.
        spec = _ChangeSpec(
            proposal_type=_ProposalType.PARAMETER_CHANGE,
            target="069500.drop_threshold",
            from_value=Decimal("5.0"), to_value=Decimal("6.0"),
            delta_pct=Decimal("20"), rationale="r",
        )
        p2 = _Proposal(
            trigger_signal=_TriggerSignal.DRAWDOWN,
            current_state_snapshot={},
            proposed_change=spec,
            reasoning_json={},
            supporting_backtest_result=None,
            state=_ProposalState.APPLIED,
            adr_reference="docs/decisions/0099.md",
            previous_proposal_ref="p1",
            proposal_id="p2",
            created_at=prior_b,
        )
        history = _ProposalHistory(applied_proposals=[p1, p2])
        p3 = _Proposal(
            trigger_signal=_TriggerSignal.DRAWDOWN,
            current_state_snapshot={},
            proposed_change=spec,
            reasoning_json={},
            supporting_backtest_result=None,
            state=_ProposalState.APPLIED,
            adr_reference="docs/decisions/0100.md",
            previous_proposal_ref="p2",
            proposal_id="p3",
            created_at=prior_c,
        )
        chain = history.self_trigger_chain(p3)
        assert chain == ["p2", "p1"], (
            f"D14 chain detection failed: expected [p2, p1], got {chain}"
        )
