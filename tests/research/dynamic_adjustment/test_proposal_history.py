"""Phase 0.11.e.2 — `_ProposalHistory` D14 structural constraints tests.

ADR 0011 §1.3 D14 — Cumulative + structural bound 검증.

Constraints:
    - Minimum interval: 동일 target 12주 간격.
    - Cumulative drift bound: 초기 설정 대비 ±30%.
    - Trigger cooldown: 동일 trigger 12주.
    - Self-trigger chain: previous_proposal_ref 체인 추적.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import _Proposal
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
        rationale="test",
    )


def _applied(
    *,
    proposal_id: str,
    created_at: datetime,
    trigger: _TriggerSignal = _TriggerSignal.DRAWDOWN,
    target: str = "069500.drop_threshold",
    previous_ref: str | None = None,
    adr_reference: str = "docs/decisions/0099.md",
) -> _Proposal:
    return _Proposal(
        trigger_signal=trigger,
        current_state_snapshot={},
        proposed_change=_spec(target),
        reasoning_json={},
        supporting_backtest_result=None,
        state=_ProposalState.APPLIED,
        adr_reference=adr_reference,
        previous_proposal_ref=previous_ref,
        proposal_id=proposal_id,
        created_at=created_at,
    )


class TestAC1MinimumInterval:
    """동일 target 의 연속 변경 = 최소 12 주 간격."""

    def test_empty_history_allows(self) -> None:
        history = _ProposalHistory()
        assert history.check_minimum_interval(
            target="069500.drop_threshold",
            new_proposal_created_at=datetime(2026, 5, 13, tzinfo=UTC),
        )

    def test_12_weeks_exact_allows(self) -> None:
        prior_date = datetime(2026, 2, 18, tzinfo=UTC)  # 12 weeks before
        new_date = prior_date + timedelta(weeks=12)
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1", created_at=prior_date,
            )],
        )
        assert history.check_minimum_interval(
            target="069500.drop_threshold",
            new_proposal_created_at=new_date,
        )

    def test_11_weeks_blocks(self) -> None:
        prior_date = datetime(2026, 5, 1, tzinfo=UTC)
        new_date = prior_date + timedelta(weeks=11, days=6)  # < 12 weeks
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1", created_at=prior_date,
            )],
        )
        assert not history.check_minimum_interval(
            target="069500.drop_threshold",
            new_proposal_created_at=new_date,
        )

    def test_different_target_independent(self) -> None:
        """다른 target 은 독립 — 한 target 의 최근 변경이 다른 target 영향 zero."""
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1",
                created_at=datetime(2026, 5, 1, tzinfo=UTC),
                target="069500.drop_threshold",
            )],
        )
        # Different target — 1 week later 도 허용.
        assert history.check_minimum_interval(
            target="132030.drop_threshold",
            new_proposal_created_at=datetime(2026, 5, 8, tzinfo=UTC),
        )


class TestAC2CumulativeDriftBound:
    """초기 설정 대비 ±30% 한계 검증."""

    def test_within_bound(self) -> None:
        history = _ProposalHistory(
            initial_values={"069500.drop_threshold": Decimal("5.0")},
        )
        # 5.0 → 6.0 = +20% drift, within ±30%.
        assert history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("6.0"),
        )

    def test_at_bound(self) -> None:
        history = _ProposalHistory(
            initial_values={"069500.drop_threshold": Decimal("5.0")},
        )
        # 5.0 → 6.5 = +30% exactly.
        assert history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("6.5"),
        )

    def test_above_bound_blocks(self) -> None:
        history = _ProposalHistory(
            initial_values={"069500.drop_threshold": Decimal("5.0")},
        )
        # 5.0 → 7.0 = +40% drift, exceeds ±30%.
        assert not history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("7.0"),
        )

    def test_below_negative_bound_blocks(self) -> None:
        history = _ProposalHistory(
            initial_values={"069500.drop_threshold": Decimal("5.0")},
        )
        # 5.0 → 3.0 = -40% drift, exceeds -30%.
        assert not history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("3.0"),
        )

    def test_missing_initial_allows(self) -> None:
        """initial_values 부재 시 drift 측정 불가 → 보수적 True (별도 NULL proposal 정책 영역)."""
        history = _ProposalHistory()
        assert history.check_cumulative_drift(
            target="069500.drop_threshold",
            new_value=Decimal("100"),
        )


class TestAC3TriggerCooldown:
    """동일 trigger 재발화 cooldown 12 주."""

    def test_empty_history_allows(self) -> None:
        history = _ProposalHistory()
        assert history.check_trigger_cooldown(
            trigger=_TriggerSignal.DRAWDOWN,
            new_proposal_created_at=datetime(2026, 5, 13, tzinfo=UTC),
        )

    def test_within_cooldown_blocks(self) -> None:
        prior_date = datetime(2026, 5, 1, tzinfo=UTC)
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1",
                created_at=prior_date,
                trigger=_TriggerSignal.DRAWDOWN,
            )],
        )
        # Same trigger, 8 weeks later — within cooldown.
        new_date = prior_date + timedelta(weeks=8)
        assert not history.check_trigger_cooldown(
            trigger=_TriggerSignal.DRAWDOWN,
            new_proposal_created_at=new_date,
        )

    def test_after_cooldown_allows(self) -> None:
        prior_date = datetime(2026, 1, 1, tzinfo=UTC)
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1",
                created_at=prior_date,
                trigger=_TriggerSignal.DRAWDOWN,
            )],
        )
        new_date = prior_date + timedelta(weeks=13)
        assert history.check_trigger_cooldown(
            trigger=_TriggerSignal.DRAWDOWN,
            new_proposal_created_at=new_date,
        )

    def test_different_trigger_independent(self) -> None:
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1",
                created_at=datetime(2026, 5, 1, tzinfo=UTC),
                trigger=_TriggerSignal.DRAWDOWN,
            )],
        )
        assert history.check_trigger_cooldown(
            trigger=_TriggerSignal.ROLLING_OOS_SHARPE,
            new_proposal_created_at=datetime(2026, 5, 8, tzinfo=UTC),
        )

    def test_null_proposal_not_cooldown_gated(self) -> None:
        """NULL_PROPOSAL trigger 자체는 cooldown 미적용 (자동 차단 marker).

        Invariant: NULL_PROPOSAL 은 APPLIED state 진입 불가
        (`_Proposal.__post_init__` 가 차단). 따라서 history 에 실제
        trigger (예: DRAWDOWN) 가 있어도, *신규* NULL_PROPOSAL trigger 는
        cooldown 즉시 통과 — short-circuit.
        """
        history = _ProposalHistory(
            applied_proposals=[_applied(
                proposal_id="p1",
                created_at=datetime(2026, 5, 1, tzinfo=UTC),
                trigger=_TriggerSignal.DRAWDOWN,
            )],
        )
        # 신규 trigger 가 NULL_PROPOSAL 이면 cooldown 검사 skip → True.
        assert history.check_trigger_cooldown(
            trigger=_TriggerSignal.NULL_PROPOSAL,
            new_proposal_created_at=datetime(2026, 5, 2, tzinfo=UTC),
        )


class TestAC4SelfTriggerChain:
    """previous_proposal_ref 체인 추적 (D14 자기-trigger 감지)."""

    def test_empty_chain(self) -> None:
        history = _ProposalHistory()
        proposal = _applied(
            proposal_id="p1",
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
            previous_ref=None,
        )
        assert history.self_trigger_chain(proposal) == []

    def test_two_step_chain(self) -> None:
        p1 = _applied(
            proposal_id="p1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            previous_ref=None,
        )
        p2 = _applied(
            proposal_id="p2",
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
            previous_ref="p1",
        )
        history = _ProposalHistory(applied_proposals=[p1, p2])
        new_proposal = _applied(
            proposal_id="p3",
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
            previous_ref="p2",
        )
        chain = history.self_trigger_chain(new_proposal)
        assert chain == ["p2", "p1"]

    def test_max_depth_truncates(self) -> None:
        # Build a long chain.
        history = _ProposalHistory(
            applied_proposals=[
                _applied(
                    proposal_id=f"p{i}",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    previous_ref=f"p{i - 1}" if i > 0 else None,
                )
                for i in range(20)
            ],
        )
        new_proposal = _applied(
            proposal_id="p99",
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
            previous_ref="p19",
        )
        chain = history.self_trigger_chain(new_proposal, max_depth=5)
        assert len(chain) == 5


class TestAC5BuildAppliedHistory:
    """`_build_applied_history` factory — APPLIED 만 필터 + 시간순 정렬."""

    def test_filters_non_applied(self) -> None:
        applied_p = _applied(
            proposal_id="p1",
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        pending_p = _Proposal(
            trigger_signal=_TriggerSignal.DRAWDOWN,
            current_state_snapshot={},
            proposed_change=_spec(),
            reasoning_json={},
            supporting_backtest_result=None,
            state=_ProposalState.PENDING,
            proposal_id="p2",
            created_at=datetime(2026, 5, 2, tzinfo=UTC),
        )
        history = _build_applied_history([pending_p, applied_p])
        assert len(history.applied_proposals) == 1
        assert history.applied_proposals[0].proposal_id == "p1"

    def test_sorts_by_created_at(self) -> None:
        p1 = _applied(
            proposal_id="p1", created_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        p2 = _applied(
            proposal_id="p2", created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        history = _build_applied_history([p1, p2])
        assert [p.proposal_id for p in history.applied_proposals] == ["p2", "p1"]

    def test_filtered_by_type(self) -> None:
        p1 = _applied(proposal_id="p1", created_at=datetime(2026, 1, 1, tzinfo=UTC))
        history = _build_applied_history([p1])
        params = history.filtered_by_type(_ProposalType.PARAMETER_CHANGE)
        strategies = history.filtered_by_type(_ProposalType.STRATEGY_CHANGE)
        assert len(params) == 1
        assert len(strategies) == 0
