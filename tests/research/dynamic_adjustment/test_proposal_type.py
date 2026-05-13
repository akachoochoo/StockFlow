"""Phase 0.11.e.2 — `_TriggerSignal` / `_ProposalState` / `_ProposalType` enum tests.

ADR 0011 §1.6 #5 + #6 + D9 + D12 enforcement — exhaustive match invariant.

부재 강제 (컴파일 타임 차단):
    - TriggerSignal: REGIME_CHANGE / VIX / NEWS_SENTIMENT / TWITTER_TREND 부재.
    - ProposalType: STOP_LOSS / REALTIME_HALT / VIX_CIRCUIT_BREAK /
      SELL_STRATEGY_CHANGE 부재.
    - ProposalState: 4-state + REJECTED terminal 만, 추가 state 부재.
"""
from __future__ import annotations

from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)


class TestAC1TriggerSignalExhaustive:
    """`_TriggerSignal` enum exhaustive match — §1.6 #5 enforcement."""

    def test_expected_variants_present(self) -> None:
        expected = {
            "ROLLING_OOS_SHARPE",
            "DRAWDOWN",
            "HUMAN_AD_HOC",
            "NULL_PROPOSAL",
        }
        actual = {member.name for member in _TriggerSignal}
        assert actual == expected, (
            f"TriggerSignal variants mismatch — expected {expected}, "
            f"got {actual}. §1.6 #5 exhaustive match invariant 위반."
        )

    def test_forbidden_variants_absent(self) -> None:
        """L1-shadow / 실시간 신호 / 외부 sentiment 부재 강제."""
        forbidden = {
            "REGIME_CHANGE",
            "VIX_TRIGGER",
            "NEWS_SENTIMENT",
            "TWITTER_TREND",
            "REALTIME_HALT",
        }
        actual = {member.name for member in _TriggerSignal}
        violations = forbidden & actual
        assert not violations, (
            f"Forbidden trigger variants present: {violations}. "
            f"D9 + §1.6 #5 enforcement 위반."
        )


class TestAC2ProposalStateMachine:
    """`_ProposalState` 4-state + REJECTED terminal exhaustive."""

    def test_expected_states_present(self) -> None:
        expected = {"PENDING", "APPROVED", "ADR_FILED", "APPLIED", "REJECTED"}
        actual = {member.name for member in _ProposalState}
        assert actual == expected, (
            f"ProposalState mismatch — expected {expected}, got {actual}."
        )

    def test_str_values(self) -> None:
        assert _ProposalState.PENDING.value == "pending"
        assert _ProposalState.APPROVED.value == "approved"
        assert _ProposalState.ADR_FILED.value == "adr_filed"
        assert _ProposalState.APPLIED.value == "applied"
        assert _ProposalState.REJECTED.value == "rejected"


class TestAC3ProposalTypeExhaustive:
    """`_ProposalType` enum exhaustive — §1.6 #4 + #6 + D9 + D12 enforcement.

    부재 강제:
        - STOP_LOSS — Phase 1 ADR 0012 별도 영역 (§11.4 정합).
        - REALTIME_HALT / VIX_CIRCUIT_BREAK — L1 = Phase 2 영역.
        - SELL_STRATEGY_CHANGE — ADR 0010 §3 D4 미확정 시 부재 (§1.6 #6).
    """

    def test_expected_variants_present(self) -> None:
        expected = {
            "PARAMETER_CHANGE",
            "STRATEGY_CHANGE",
            "UNIVERSE_CHANGE",
        }
        actual = {member.name for member in _ProposalType}
        assert actual == expected, (
            f"ProposalType variants mismatch — expected {expected}, "
            f"got {actual}. §1.6 #4 + #6 exhaustive match invariant 위반."
        )

    def test_forbidden_variants_absent(self) -> None:
        forbidden = {
            "STOP_LOSS",
            "REALTIME_HALT",
            "VIX_CIRCUIT_BREAK",
            "SELL_STRATEGY_CHANGE",
        }
        actual = {member.name for member in _ProposalType}
        violations = forbidden & actual
        assert not violations, (
            f"Forbidden ProposalType variants present: {violations}. "
            f"D8 + §1.6 #6 + ADR 0010 D4 종속 invariant 위반."
        )

    def test_l2_l3_only_scope(self) -> None:
        """L1 영역 type 부재 + L4 / 알고리즘 교체 부재."""
        l1_l4_forbidden = {
            "L1_HALT",
            "L4_ALGORITHM_REPLACE",
            "VIX_CIRCUIT_BREAK",
        }
        actual = {member.name for member in _ProposalType}
        violations = l1_l4_forbidden & actual
        assert not violations, f"L1/L4 영역 type 부재 강제 위반: {violations}"
