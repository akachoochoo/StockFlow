"""Phase 0.11.e.3 — ADR template scaffolding + content verification tests.

ADR 0011 §1.3 D6 정합:
    - `_render_adr_template` — `<TBD>` placeholder 포함 markdown 생성.
    - `_verify_adr_content` — TBD marker 부재 + 최소 길이 검증.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.research.dynamic_adjustment._adr_template import (
    _render_adr_template,
    _verify_adr_content,
)
from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import _Proposal
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)

if TYPE_CHECKING:
    from pathlib import Path


def _approved_proposal() -> _Proposal:
    spec = _ChangeSpec(
        proposal_type=_ProposalType.PARAMETER_CHANGE,
        target="069500.drop_threshold",
        from_value=Decimal("5.0"),
        to_value=Decimal("6.0"),
        delta_pct=Decimal("20"),
        rationale="DD spike — tighten threshold",
    )
    return _Proposal(
        trigger_signal=_TriggerSignal.DRAWDOWN,
        current_state_snapshot={"baseline_mdd_pct": "-33"},
        proposed_change=spec,
        reasoning_json={"sharpe": "0.25", "mdd": "-50"},
        supporting_backtest_result=None,
        state=_ProposalState.APPROVED,
        adr_reference="docs/decisions/0099.md",
        proposal_id="prop-abc",
        created_at=datetime(2026, 5, 14, tzinfo=UTC),
    )


class TestAC1TemplateScaffolding:
    """`_render_adr_template` — 필수 placeholder + proposal 정보 포함."""

    def test_renders_with_tbd_markers(self) -> None:
        text = _render_adr_template(
            _approved_proposal(),
            adr_number="ADR-0099",
        )
        # TBD markers 있어야 함 (사람이 채워야 함).
        assert "<TBD" in text
        assert text.count("<TBD") >= 3  # date / background / decision / reasoning

    def test_includes_proposal_id(self) -> None:
        text = _render_adr_template(
            _approved_proposal(),
            adr_number="ADR-0099",
        )
        assert "prop-abc" in text

    def test_includes_adr_number(self) -> None:
        text = _render_adr_template(
            _approved_proposal(),
            adr_number="ADR-0099",
        )
        assert "ADR-0099" in text

    def test_supersedes_optional(self) -> None:
        # supersedes None → <TBD> placeholder.
        text = _render_adr_template(
            _approved_proposal(),
            adr_number="ADR-0099",
            supersedes=None,
        )
        assert "<TBD: supersede target>" in text

    def test_supersedes_supplied(self) -> None:
        text = _render_adr_template(
            _approved_proposal(),
            adr_number="ADR-0099",
            supersedes="ADR 0003 §19.4",
        )
        assert "ADR 0003 §19.4" in text


class TestAC2ContentVerification:
    """`_verify_adr_content` — 4 cases."""

    def test_missing_file_fails(self, tmp_path: Path) -> None:
        verified, msg = _verify_adr_content(tmp_path / "nonexistent.md")
        assert not verified
        assert "does not exist" in msg

    def test_tbd_markers_present_fails(self, tmp_path: Path) -> None:
        # Use template directly — TBD 잔존.
        adr_path = tmp_path / "0099.md"
        template = _render_adr_template(
            _approved_proposal(),
            adr_number="ADR-0099",
        )
        adr_path.write_text(template, encoding="utf-8")
        verified, msg = _verify_adr_content(adr_path)
        assert not verified
        assert "TBD" in msg

    def test_short_content_fails(self, tmp_path: Path) -> None:
        adr_path = tmp_path / "0099.md"
        adr_path.write_text("# tiny ADR\n\nNo content", encoding="utf-8")
        verified, msg = _verify_adr_content(adr_path)
        assert not verified
        assert "too short" in msg.lower()

    def test_full_content_verified(self, tmp_path: Path) -> None:
        # Render template + replace all TBD markers with concrete content.
        adr_path = tmp_path / "0099.md"
        template = _render_adr_template(
            _approved_proposal(),
            adr_number="ADR-0099",
            supersedes="ADR 0003 §19.4",
        )
        # Replace TBD markers with concrete text — bulk replace each
        # `<TBD: ...>` 패턴.
        import re
        filled = re.sub(
            r"<TBD: ([^>]+)>",
            lambda m: f"resolved {m.group(1)}: drop_threshold_pct 5.0 -> 6.0",
            template,
        )
        # Confirm template now has no TBD markers.
        assert "<TBD" not in filled
        # Add additional content to ensure length threshold satisfied.
        filled += "\n\n## Additional analysis\n\n" + ("verified content. " * 50)
        adr_path.write_text(filled, encoding="utf-8")
        verified, msg = _verify_adr_content(adr_path)
        assert verified, f"verification failed: {msg}"
