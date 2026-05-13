"""Phase 0.11.e.2 — `_ChangeSpec` invariants tests.

ADR 0011 §1.3 D3 #3 — proposal_type 분기 정합.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal_type import _ProposalType


class TestAC1ParameterChangeRequiresDelta:
    """PARAMETER_CHANGE 는 delta_pct (Decimal) 필수 — D14 drift 입력."""

    def test_param_change_valid(self) -> None:
        spec = _ChangeSpec(
            proposal_type=_ProposalType.PARAMETER_CHANGE,
            target="069500.buy_parameters.drop_threshold_pct",
            from_value=Decimal("5.0"),
            to_value=Decimal("7.0"),
            delta_pct=Decimal("40"),  # (7-5)/5 * 100
            rationale="Drop threshold raised",
        )
        assert spec.delta_pct == Decimal("40")

    def test_param_change_missing_delta_raises(self) -> None:
        with pytest.raises(ValueError, match="PARAMETER_CHANGE requires delta_pct"):
            _ChangeSpec(
                proposal_type=_ProposalType.PARAMETER_CHANGE,
                target="069500.buy_parameters.drop_threshold_pct",
                from_value=Decimal("5.0"),
                to_value=Decimal("7.0"),
                delta_pct=None,
                rationale="rationale",
            )

    def test_param_change_float_delta_raises(self) -> None:
        with pytest.raises(TypeError, match="delta_pct must be Decimal"):
            _ChangeSpec(
                proposal_type=_ProposalType.PARAMETER_CHANGE,
                target="x",
                from_value=Decimal("1"),
                to_value=Decimal("2"),
                delta_pct=100.0,  # type: ignore[arg-type]
                rationale="r",
            )


class TestAC2StrategyAndUniverseAllowNoneDelta:
    """STRATEGY_CHANGE / UNIVERSE_CHANGE delta_pct None 허용 (정성적 변경)."""

    def test_strategy_change(self) -> None:
        spec = _ChangeSpec(
            proposal_type=_ProposalType.STRATEGY_CHANGE,
            target="price_drop",
            from_value="price_drop",
            to_value="support_level",
            delta_pct=None,
            rationale="Switch to support level for 069500",
        )
        assert spec.delta_pct is None

    def test_universe_add(self) -> None:
        spec = _ChangeSpec(
            proposal_type=_ProposalType.UNIVERSE_CHANGE,
            target="132030",
            from_value=None,
            to_value="132030",
            delta_pct=None,
            rationale="Add bond ETF for diversification",
        )
        assert spec.from_value is None


class TestAC3FrozenDataclass:
    """Frozen — mutation 차단."""

    def test_frozen_mutation_raises(self) -> None:
        spec = _ChangeSpec(
            proposal_type=_ProposalType.STRATEGY_CHANGE,
            target="x",
            from_value="a",
            to_value="b",
            delta_pct=None,
            rationale="r",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.target = "y"  # type: ignore[misc]


class TestAC4ValidationGuards:
    """Empty target / rationale 거부."""

    def test_empty_target_raises(self) -> None:
        with pytest.raises(ValueError, match="target must be non-empty"):
            _ChangeSpec(
                proposal_type=_ProposalType.STRATEGY_CHANGE,
                target="",
                from_value="a",
                to_value="b",
                delta_pct=None,
                rationale="r",
            )

    def test_empty_rationale_raises(self) -> None:
        with pytest.raises(ValueError, match="rationale must be non-empty"):
            _ChangeSpec(
                proposal_type=_ProposalType.STRATEGY_CHANGE,
                target="x",
                from_value="a",
                to_value="b",
                delta_pct=None,
                rationale="",
            )
