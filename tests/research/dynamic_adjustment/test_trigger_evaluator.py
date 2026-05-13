"""Phase 0.11.e.2 — `_TriggerEvaluator` D1 AND-gate tests.

ADR 0011 §1.3 D1 + §1.6 #2 enforcement.

검증 항목:
    - AND-gate (sharpe + drawdown + sample size) 충족 시 trigger 발화.
    - Sample size 부족 시 NULL_PROPOSAL semantics.
    - 단일 조건만 충족 시 NULL_PROPOSAL.
    - Human ad-hoc 우선순위 (D1 (iv) 정합).
    - Decimal invariant (모든 numeric input + diagnostic output).
    - 원천 데이터 제약 = backtest OOS metric only (실시간 신호 부재).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.research.dynamic_adjustment._proposal_type import _TriggerSignal
from src.research.dynamic_adjustment._trigger_evaluator import (
    _evaluate_triggers,
    _TriggerEvaluationInput,
    _TriggerEvaluationResult,
)


def _input(
    *,
    sharpe: str = "0.25",
    mdd: str = "-50",
    baseline: str = "-33",
    sample: int = 150,
    human: bool = False,
) -> _TriggerEvaluationInput:
    return _TriggerEvaluationInput(
        rolling_oos_sharpe=Decimal(sharpe),
        current_mdd_pct=Decimal(mdd),
        baseline_mdd_pct=Decimal(baseline),
        sample_size=sample,
        human_ad_hoc_request=human,
    )


class TestAC1AndGateTrigger:
    """AND-gate (sharpe + drawdown + sample) 충족 → DRAWDOWN trigger."""

    def test_both_conditions_met_triggers(self) -> None:
        # sharpe 0.25 < 0.3 ✓, mdd -50 < -33*1.5=-49.5 ✓, sample 150 ≥ 100 ✓
        result = _evaluate_triggers(_input())
        assert result.triggered
        assert result.primary_signal is _TriggerSignal.DRAWDOWN
        assert result.sample_size_sufficient
        assert result.and_gate_components["sharpe_violation"]
        assert result.and_gate_components["drawdown_violation"]

    def test_only_sharpe_violation_nullified(self) -> None:
        # sharpe 0.25 < 0.3 ✓, mdd -40 not < -49.5 ✗
        result = _evaluate_triggers(_input(mdd="-40"))
        assert not result.triggered
        assert result.primary_signal is _TriggerSignal.NULL_PROPOSAL

    def test_only_drawdown_violation_nullified(self) -> None:
        # sharpe 0.5 not < 0.3 ✗, mdd -50 < -49.5 ✓
        result = _evaluate_triggers(_input(sharpe="0.5"))
        assert not result.triggered
        assert result.primary_signal is _TriggerSignal.NULL_PROPOSAL


class TestAC2SampleSizeThreshold:
    """Sample size < threshold → NULL_PROPOSAL (자동 차단)."""

    def test_below_threshold_nullifies(self) -> None:
        # All conditions met but sample 50 < 100.
        result = _evaluate_triggers(_input(sample=50))
        assert not result.triggered
        assert result.primary_signal is _TriggerSignal.NULL_PROPOSAL
        assert not result.sample_size_sufficient

    def test_at_threshold_passes(self) -> None:
        # sample 100 exactly = threshold.
        result = _evaluate_triggers(_input(sample=100))
        assert result.triggered
        assert result.sample_size_sufficient


class TestAC3HumanAdHocPriority:
    """Human ad-hoc trigger 우선순위 — sample size 충족 시 즉시 발화."""

    def test_human_request_triggers(self) -> None:
        # Even with no statistical violations.
        result = _evaluate_triggers(_input(
            sharpe="0.5", mdd="-20", human=True,
        ))
        assert result.triggered
        assert result.primary_signal is _TriggerSignal.HUMAN_AD_HOC

    def test_human_request_blocked_by_low_sample(self) -> None:
        """Human request + low sample → NULL_PROPOSAL (sample gate hard)."""
        result = _evaluate_triggers(_input(
            sharpe="0.5", mdd="-20", human=True, sample=50,
        ))
        assert not result.triggered
        assert result.primary_signal is _TriggerSignal.NULL_PROPOSAL


class TestAC4InputValidation:
    """Input invariants (sample ≥ 0, baseline_mdd < 0)."""

    def test_negative_sample_size_raises(self) -> None:
        with pytest.raises(ValueError, match="sample_size must be ≥ 0"):
            _TriggerEvaluationInput(
                rolling_oos_sharpe=Decimal("0.3"),
                current_mdd_pct=Decimal("-30"),
                baseline_mdd_pct=Decimal("-30"),
                sample_size=-1,
            )

    def test_non_negative_baseline_mdd_raises(self) -> None:
        with pytest.raises(ValueError, match="baseline_mdd_pct must be < 0"):
            _TriggerEvaluationInput(
                rolling_oos_sharpe=Decimal("0.3"),
                current_mdd_pct=Decimal("-30"),
                baseline_mdd_pct=Decimal("0"),
                sample_size=100,
            )


class TestAC5DiagnosticOutputDecimal:
    """Diagnostic metrics Decimal str 직렬화 (CLAUDE.md §7.1 정합)."""

    def test_diagnostic_includes_all_metrics(self) -> None:
        result = _evaluate_triggers(_input())
        diag = result.diagnostic_metrics
        for key in (
            "rolling_oos_sharpe",
            "current_mdd_pct",
            "baseline_mdd_pct",
            "drawdown_threshold",
            "sample_size",
            "rolling_sharpe_threshold",
            "drawdown_multiplier",
            "sample_size_threshold",
        ):
            assert key in diag, f"diagnostic missing key: {key}"

    def test_decimal_str_not_float(self) -> None:
        result = _evaluate_triggers(_input(sharpe="0.25"))
        # str(Decimal("0.25")) = "0.25"; float 변환 시 "0.25000000000..."
        assert result.diagnostic_metrics["rolling_oos_sharpe"] == "0.25"


class TestAC6CustomThresholds:
    """Threshold override — 0.11.e.2 sub-step 시 재검토 가능 명시 정합."""

    def test_higher_sharpe_threshold(self) -> None:
        # With threshold 0.5, sharpe 0.4 violates.
        result = _evaluate_triggers(
            _input(sharpe="0.4", mdd="-50"),
            rolling_sharpe_threshold=Decimal("0.5"),
        )
        assert result.triggered
        assert result.primary_signal is _TriggerSignal.DRAWDOWN
        assert result.and_gate_components["sharpe_violation"]

    def test_higher_sample_threshold(self) -> None:
        # With threshold 200, sample 150 insufficient.
        result = _evaluate_triggers(
            _input(sample=150),
            sample_size_threshold=200,
        )
        assert not result.triggered
        assert result.primary_signal is _TriggerSignal.NULL_PROPOSAL


class TestAC7ResultStructuralTyping:
    """`_TriggerEvaluationResult` schema 검증."""

    def test_result_is_frozen(self) -> None:
        import dataclasses

        result = _evaluate_triggers(_input())
        assert isinstance(result, _TriggerEvaluationResult)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.triggered = False  # type: ignore[misc]
