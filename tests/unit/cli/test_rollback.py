"""Unit tests for src.cli.rollback (Phase 1.1 Stage 8-8 / ADR 0012 D19)."""
from __future__ import annotations

import pytest

from src.cli.live_gate import CapitalTier
from src.cli.rollback import (
    RollbackLogEntry,
    plan_capital_rollback,
    previous_tier,
)

_OCCURRED = "2026-06-01T00:00:00+00:00"


def test_previous_tier_ladder() -> None:
    assert previous_tier(CapitalTier.TIER_500) is CapitalTier.TIER_300
    assert previous_tier(CapitalTier.TIER_300) is CapitalTier.TIER_200
    assert previous_tier(CapitalTier.TIER_200) is None  # floor


def test_rollback_reverts_capital_tier() -> None:
    entry = plan_capital_rollback(
        current_tier=CapitalTier.TIER_300,
        prior_rollback_count=0,
        reason="recon mismatch",
        occurred_at=_OCCURRED,
    )
    assert entry.from_tier == "TIER_300"
    assert entry.to_tier == "TIER_200"
    assert entry.phase_terminated is False
    assert entry.cumulative_rollbacks == 1

    entry500 = plan_capital_rollback(
        current_tier=CapitalTier.TIER_500,
        prior_rollback_count=0,
        reason="clock skew",
        occurred_at=_OCCURRED,
    )
    assert entry500.to_tier == "TIER_300"
    assert entry500.phase_terminated is False


def test_rollback_at_floor_terminates_phase() -> None:
    entry = plan_capital_rollback(
        current_tier=CapitalTier.TIER_200,
        prior_rollback_count=0,
        reason="incident at floor",
        occurred_at=_OCCURRED,
    )
    assert entry.phase_terminated is True
    assert entry.to_tier == "TIER_200"  # nowhere lower → no productive rollback


def test_cumulative_max_terminates_phase() -> None:
    # 3rd rollback (prior=2) reaches DEFAULT_MAX_ROLLBACKS=3 → terminate.
    entry = plan_capital_rollback(
        current_tier=CapitalTier.TIER_500,
        prior_rollback_count=2,
        reason="third incident",
        occurred_at=_OCCURRED,
    )
    assert entry.cumulative_rollbacks == 3
    assert entry.phase_terminated is True
    assert entry.from_tier == "TIER_500"
    assert entry.to_tier == "TIER_500"  # phase ends rather than rolling back


def test_rollback_log_schema_valid() -> None:
    entry = plan_capital_rollback(
        current_tier=CapitalTier.TIER_300,
        prior_rollback_count=0,
        reason="recon mismatch",
        occurred_at=_OCCURRED,
    )
    d = entry.to_dict()
    assert set(d) == {
        "occurred_at",
        "from_tier",
        "to_tier",
        "reason",
        "cumulative_rollbacks",
        "phase_terminated",
    }
    assert isinstance(d["occurred_at"], str)
    assert isinstance(d["from_tier"], str)
    assert isinstance(d["to_tier"], str)
    assert isinstance(d["reason"], str)
    assert isinstance(d["cumulative_rollbacks"], int)
    assert isinstance(d["phase_terminated"], bool)
    # JSON-serialisable.
    import json

    assert json.loads(json.dumps(d)) == d


def test_negative_prior_count_raises() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        plan_capital_rollback(
            current_tier=CapitalTier.TIER_300,
            prior_rollback_count=-1,
            reason="x",
            occurred_at=_OCCURRED,
        )


def test_rollback_entry_is_frozen() -> None:
    entry = RollbackLogEntry(
        occurred_at=_OCCURRED, from_tier="TIER_300", to_tier="TIER_200",
        reason="x", cumulative_rollbacks=1, phase_terminated=False,
    )
    with pytest.raises((AttributeError, TypeError)):
        entry.to_tier = "TIER_500"  # type: ignore[misc]


def test_rollback_runbook_checklist_present() -> None:
    """The D13/D19 emergency-change runbook exists with the 4 reasons +
    checklists + the rollback procedure (Stage 8-9 verifiable artifact)."""
    from pathlib import Path

    runbook = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "runbooks"
        / "phase-1.1-emergency-change.md"
    )
    assert runbook.exists(), f"runbook missing: {runbook}"
    text = runbook.read_text(encoding="utf-8")
    # D13 비상 변경 4 사유.
    assert "Kill switch" in text
    assert "Reconciliation" in text
    assert "KIS API 시그니처" in text
    assert "-20%" in text
    # Verifiable checklist + rollback (D19) + resume.
    assert "- [ ]" in text
    assert "plan_capital_rollback" in text
    assert "trading resume" in text
    assert "변경 zero" in text
