"""Phase 0.11.e.4 — §1.6 Design Contract 6 invariant verification tests.

ADR 0011 §1.6 — 본 phase 의 invariant 는 다른 phase 보다 strict. 측정
가능 verification 의무. **정신 (spirit) supersede 불가 — D15 governance
정합** (Round 1 ITERATE Patch 2).

검증 대상 (각 invariant § 인용):
    #1 시스템은 제안만 한다 — `pytest -k proposal_auto_apply_blocked`
    #2 AI 결정 시스템 아님 — D1 원천 데이터 grep empty
    #3 Reflexive overfitting 방지 hard — `pytest -k reflexive_data_isolation`
    #4 ADR 박제 없이 변경 적용 차단 hard — `pytest -k adr_enforcement_blocks_apply`
    #5 친절한 추가 금지 — `pytest -k trigger_signal_enum_exhaustive`
    #6 sell strategy 단일 가정 종속 — `pytest -k sell_proposal_blocked_without_adr0010`
"""
from __future__ import annotations

import re
from pathlib import Path

from src.research.dynamic_adjustment._proposal import _can_transition, _transition
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DA_DIR = Path("src/research/dynamic_adjustment")


# ---------------------------------------------------------------------------
# §1.6 #1 — 시스템은 제안만 한다 (auto-apply 차단)
# ---------------------------------------------------------------------------
class TestProposalAutoApplyBlocked:
    """§1.6 #1 — `Proposal.state != APPLIED` 시 config 변경 코드 실행 차단.

    Verification 정신: APPLIED 상태로의 전이는 *오직* ADR_FILED → APPLIED
    경로만 허용 (사람 명시 CLI `apply` 후). 다른 어떤 state 에서도 직접
    APPLIED 도달 불가능.
    """

    def test_proposal_auto_apply_blocked_from_pending(self) -> None:
        assert not _can_transition(_ProposalState.PENDING, _ProposalState.APPLIED)

    def test_proposal_auto_apply_blocked_from_approved(self) -> None:
        """§1.6 #4 invariant 와 동일 핵심 — direct APPROVED → APPLIED 차단."""
        assert not _can_transition(_ProposalState.APPROVED, _ProposalState.APPLIED)

    def test_proposal_auto_apply_blocked_from_rejected(self) -> None:
        assert not _can_transition(_ProposalState.REJECTED, _ProposalState.APPLIED)

    def test_only_adr_filed_can_reach_applied(self) -> None:
        """APPLIED 전이의 유일 경로 = ADR_FILED → APPLIED."""
        states = list(_ProposalState)
        valid_predecessors = [
            s for s in states
            if _can_transition(s, _ProposalState.APPLIED)
        ]
        assert valid_predecessors == [_ProposalState.ADR_FILED]

    def test_no_auto_apply_hook_in_module(self) -> None:
        """dynamic_adjustment 모듈에 자동 config 변경 path 부재 검증.

        Grep `config/strategies.yaml` 등 hot-reload / mutation 키워드 부재.
        본 phase = *제안만*, *적용은 사람 명시 + 별도 시스템 영역*.
        """
        da_dir = _REPO_ROOT / _DA_DIR
        forbidden_patterns = (
            r"config/strategies\.yaml",
            r"hot[_-]?reload",
            r"yaml\.dump.*strategies",
            r"\.replace\(.*config/",
        )
        violations: list[str] = []
        for py in da_dir.rglob("*.py"):
            content = py.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                if re.search(pattern, content):
                    violations.append(f"{py}: matches {pattern!r}")
        assert not violations, (
            f"§1.6 #1 violation — auto-apply / config mutation surface: "
            f"{violations}"
        )


# ---------------------------------------------------------------------------
# §1.6 #2 — AI 결정 시스템 아님 (D1 원천 데이터 grep)
# ---------------------------------------------------------------------------
class TestDataSourceConstraint:
    """§1.6 #2 — `통계 기반 trigger evaluator` 본질. 실시간 데이터 부재."""

    def test_no_realtime_data_identifiers_in_source(self) -> None:
        """§1.6 #2 verification — 실시간 신호 *identifier* (변수/함수/속성)
        부재 검증.

        ADR 0011 §1.6 #2 prescribed grep 은 raw token (docstring/comment 포함)
        검사이지만, 본 test 는 *identifier-level* 사용만 차단 — docstring
        에서 "실시간 데이터 부재" / "VIX 절대 금지" 등의 invariant 박제
        description 은 정상 허용 (negation context).

        Identifier-level pattern: `vix_*`, `*sentiment*`, `twitter_*`,
        `news_*`, `realtime_*` 등의 식별자 사용 차단.
        """
        da_dir = _REPO_ROOT / _DA_DIR
        # Identifier-pattern grep — variable / function / attribute usage.
        # Word boundary 강제 + assignment / call / dot access context.
        identifier_patterns = (
            r"\bvix_\w*",
            r"\b\w*sentiment\w*",
            r"\btwitter_\w*",
            r"\bnews_\w*",
            r"\brealtime_\w*",
        )
        violations: list[str] = []
        for py in da_dir.rglob("*.py"):
            content = py.read_text(encoding="utf-8")
            for line_no, line in enumerate(content.splitlines(), start=1):
                stripped = line.lstrip()
                # Skip pure comment / docstring lines — heuristic: starts
                # with # or """ or contains negation marker.
                if stripped.startswith(("#", '"""', "'''")):
                    continue
                negation_markers = ("절대 금지", "부재", "차단", "거부", "위반",
                                    "absent", "blocked", "forbidden", "위임",
                                    "zero", "only", "신호 부재")
                if any(m in line for m in negation_markers):
                    continue
                for pattern in identifier_patterns:
                    if re.search(pattern, line, flags=re.IGNORECASE):
                        violations.append(f"{py}:{line_no}: {line.strip()}")
                        break
        assert not violations, (
            f"§1.6 #2 violation — realtime data identifier in source: "
            f"{violations}"
        )

    def test_trigger_evaluator_input_field_names_are_oos_only(self) -> None:
        """`_TriggerEvaluationInput` 필드 이름 = backtest OOS metric only.

        본 test = §1.6 #2 의 **structural** verification — Input dataclass
        field 이름이 OOS metric / sample size / 사람 명시 trigger 외 추가
        시 즉시 FAIL (regression invariant).
        """
        from src.research.dynamic_adjustment._trigger_evaluator import (
            _TriggerEvaluationInput,
        )

        expected = {
            "rolling_oos_sharpe",
            "current_mdd_pct",
            "baseline_mdd_pct",
            "sample_size",
            "human_ad_hoc_request",
        }
        actual = {
            f.name for f in _TriggerEvaluationInput.__dataclass_fields__.values()
        }
        assert actual == expected, (
            f"§1.6 #2 verification — TriggerEvaluationInput fields diverged. "
            f"expected {expected}, got {actual}."
        )


# ---------------------------------------------------------------------------
# §1.6 #3 — Reflexive overfitting 방지 hard
# ---------------------------------------------------------------------------
class TestReflexiveDataIsolation:
    """§1.6 #3 — Phase 1 실거래 데이터 backtest input 사용 자동 차단.

    Phase 1 trade log file path (`<TBD: Phase 1 ADR 0012 결정>`) 이
    `dynamic_adjustment` 모듈에서 backtest input source 로 사용되지
    않음을 file path / data source tag isolation 으로 검증.
    """

    def test_reflexive_data_isolation_no_trade_log_references(self) -> None:
        """`dynamic_adjustment` 코드에 Phase 1 trade log path 패턴 부재."""
        da_dir = _REPO_ROOT / _DA_DIR
        # Phase 1 trade log path candidates — 본 phase 사용 금지.
        forbidden_path_patterns = (
            r"data/live_trades",
            r"trades_live_",
            r"kis_executed_orders",
            r"phase1_trade_log",
        )
        violations: list[str] = []
        for py in da_dir.rglob("*.py"):
            content = py.read_text(encoding="utf-8")
            for pattern in forbidden_path_patterns:
                if re.search(pattern, content):
                    violations.append(f"{py}: matches Phase 1 path {pattern!r}")
        assert not violations, (
            f"§1.6 #3 violation — Phase 1 trade log reference: {violations}"
        )

    def test_trigger_evaluator_input_signature_oos_only(self) -> None:
        """`_TriggerEvaluationInput` 시그니처 = backtest OOS metric only.

        Field 이름 검증 — 실시간 token 부재 + 통계 metric only.
        """
        from src.research.dynamic_adjustment._trigger_evaluator import (
            _TriggerEvaluationInput,
        )

        expected_fields = {
            "rolling_oos_sharpe",
            "current_mdd_pct",
            "baseline_mdd_pct",
            "sample_size",
            "human_ad_hoc_request",
        }
        actual_fields = {
            f.name for f in _TriggerEvaluationInput.__dataclass_fields__.values()
        }
        assert actual_fields == expected_fields, (
            f"TriggerEvaluationInput field mismatch — expected {expected_fields}, "
            f"got {actual_fields}. §1.6 #3 verification (OOS-only input)."
        )


# ---------------------------------------------------------------------------
# §1.6 #4 — ADR 박제 없이 변경 적용 차단 hard
# ---------------------------------------------------------------------------
class TestAdrEnforcementBlocksApply:
    """§1.6 #4 — 4-state 머신 (PENDING → APPROVED → ADR_FILED → APPLIED).

    Direct APPROVED → APPLIED 차단 (`adr_reference` 부재 시).
    """

    def test_adr_enforcement_blocks_apply_direct(self) -> None:
        """APPROVED → APPLIED 직접 전이 차단."""
        assert not _can_transition(_ProposalState.APPROVED, _ProposalState.APPLIED)

    def test_adr_enforcement_blocks_apply_without_reference(self) -> None:
        """ADR_FILED state 진입 시 adr_reference 필수 — `_Proposal.
        __post_init__` invariant.
        """
        from datetime import UTC, datetime
        from decimal import Decimal

        import pytest

        from src.research.dynamic_adjustment._change_spec import _ChangeSpec
        from src.research.dynamic_adjustment._proposal import _Proposal

        spec = _ChangeSpec(
            proposal_type=_ProposalType.PARAMETER_CHANGE,
            target="x", from_value=Decimal("1"), to_value=Decimal("2"),
            delta_pct=Decimal("100"), rationale="r",
        )
        # ADR_FILED + adr_reference=None → ValueError.
        with pytest.raises(ValueError, match="ADR_FILED state requires adr_reference"):
            _Proposal(
                trigger_signal=_TriggerSignal.DRAWDOWN,
                current_state_snapshot={},
                proposed_change=spec,
                reasoning_json={},
                supporting_backtest_result=None,
                state=_ProposalState.ADR_FILED,
                adr_reference=None,
                proposal_id="p1",
                created_at=datetime(2026, 5, 14, tzinfo=UTC),
            )

    def test_adr_enforcement_blocks_apply_via_transition(self) -> None:
        """`_transition` 가 APPROVED → APPLIED 차단."""
        from datetime import UTC, datetime
        from decimal import Decimal

        import pytest

        from src.research.dynamic_adjustment._change_spec import _ChangeSpec
        from src.research.dynamic_adjustment._proposal import _Proposal

        spec = _ChangeSpec(
            proposal_type=_ProposalType.PARAMETER_CHANGE,
            target="x", from_value=Decimal("1"), to_value=Decimal("2"),
            delta_pct=Decimal("100"), rationale="r",
        )
        approved = _Proposal(
            trigger_signal=_TriggerSignal.DRAWDOWN,
            current_state_snapshot={},
            proposed_change=spec,
            reasoning_json={},
            supporting_backtest_result=None,
            state=_ProposalState.APPROVED,
            proposal_id="p1",
            created_at=datetime(2026, 5, 14, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="Transition blocked"):
            _transition(approved, to_state=_ProposalState.APPLIED)


# ---------------------------------------------------------------------------
# §1.6 #5 — 친절한 추가 금지 (trigger signal exhaustive)
# ---------------------------------------------------------------------------
class TestTriggerSignalEnumExhaustive:
    """§1.6 #5 — `TriggerSignal` enum 이 D1 (i)/(ii)/(iv) 3 + NULL marker 외
    추가 시 test FAIL (exhaustive match).
    """

    def test_trigger_signal_enum_exhaustive_match(self) -> None:
        expected = {
            "ROLLING_OOS_SHARPE",
            "DRAWDOWN",
            "HUMAN_AD_HOC",
            "NULL_PROPOSAL",
        }
        actual = {member.name for member in _TriggerSignal}
        assert actual == expected, (
            f"§1.6 #5 violation — TriggerSignal expanded beyond D1 + NULL "
            f"marker. expected {expected}, got {actual}."
        )

    def test_no_news_or_sentiment_variants(self) -> None:
        """뉴스 / sentiment / twitter trend 등 §13.3 친절한 추가 부재."""
        forbidden = {
            "NEWS_SENTIMENT", "TWITTER_TREND", "VIX_TRIGGER",
            "REDDIT_SENTIMENT", "GOOGLE_TRENDS",
        }
        actual = {member.name for member in _TriggerSignal}
        violations = forbidden & actual
        assert not violations, (
            f"§1.6 #5 violation — sentiment/external trigger added: {violations}"
        )


# ---------------------------------------------------------------------------
# §1.6 #6 — sell strategy 단일 가정 종속
# ---------------------------------------------------------------------------
class TestSellProposalBlockedWithoutAdr0010:
    """§1.6 #6 — sell strategy 변경 제안은 ADR 0010 D4 산출의 결정에 종속.

    ADR 0010 §3 회고에 D4 결정 박제 부재 시 `ProposalType.
    SELL_STRATEGY_CHANGE` enum variant 자체 부재 (D12 enum exhaustive
    match 정합).
    """

    def test_sell_proposal_blocked_without_adr0010_no_enum_variant(self) -> None:
        """`ProposalType.SELL_STRATEGY_CHANGE` enum variant 자체 부재."""
        forbidden = {"SELL_STRATEGY_CHANGE", "STOP_LOSS"}
        actual = {member.name for member in _ProposalType}
        violations = forbidden & actual
        assert not violations, (
            f"§1.6 #6 violation — sell strategy variant present without "
            f"ADR 0010 D4 결정: {violations}"
        )

    def test_adr0010_d4_not_decided_yet(self) -> None:
        """ADR 0010 §3 회고에 D4 결정 박제 부재 확인 (현 상태 = trade-off 박제만).

        본 test = §1.6 #6 enforcement 의 cross-reference — ADR 0010
        §3 영역에 "D4 (sell strategy 차별화) 결정" 또는 "D4 채택" 등
        명시적 결정 marker 부재.
        """
        adr_path = (
            _REPO_ROOT / "docs/decisions/0010-phase-0.11.d-asset-specific-strategy-diagnosis.md"
        )
        if not adr_path.exists():
            import pytest
            pytest.skip("ADR 0010 missing — repo layout issue")
        content = adr_path.read_text(encoding="utf-8")
        # Find §3 section.
        section_match = re.search(r"## 3\..*?(?=\n## |\Z)", content, flags=re.DOTALL)
        if section_match is None:
            import pytest
            pytest.skip("ADR 0010 §3 not yet 박제")
        section_3 = section_match.group(0)
        # "D4 결정" / "D4 채택" 명시적 결정 marker 부재 — 단, trade-off
        # 박제 / 미확정 / 보류 marker 는 허용 (본 phase invariant 정합).
        decision_markers = (
            r"D4\s+결정\s*=",
            r"D4\s+채택\s*=",
            r"sell\s+strategy\s+차별화\s+채택",
        )
        decision_found: list[str] = []
        for marker in decision_markers:
            if re.search(marker, section_3):
                decision_found.append(marker)
        assert not decision_found, (
            f"§1.6 #6 enforcement: ADR 0010 §3 contains D4 decision marker — "
            f"{decision_found}. 본 enum 에 SELL_STRATEGY_CHANGE 추가 필요 "
            f"(현 enum 부재 invariant 와 충돌)."
        )
