"""Phase 0.11.e.3 — `_ProposalStore` JSON persistence tests.

검증 항목:
    - load / save round-trip (8 필드 + identity 보존).
    - Decimal / enum / datetime tagged serialization 정확성.
    - upsert + get_by_id + list_by_state 동작.
    - Atomic write (임시 파일 → os.replace).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import _Proposal
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)
from src.research.dynamic_adjustment._store import _ProposalStore

if TYPE_CHECKING:
    from pathlib import Path


def _proposal(
    *,
    proposal_id: str = "p1",
    state: _ProposalState = _ProposalState.PENDING,
    from_v: object = Decimal("5.0"),
    to_v: object = Decimal("6.0"),
    delta: Decimal | None = Decimal("20"),
    adr_ref: str | None = None,
) -> _Proposal:
    spec = _ChangeSpec(
        proposal_type=_ProposalType.PARAMETER_CHANGE,
        target="069500.drop_threshold",
        from_value=from_v,
        to_value=to_v,
        delta_pct=delta,
        rationale="test",
    )
    return _Proposal(
        trigger_signal=_TriggerSignal.DRAWDOWN,
        current_state_snapshot={"baseline_mdd_pct": "-33"},
        proposed_change=spec,
        reasoning_json={"sharpe": "0.25"},
        supporting_backtest_result=None,
        state=state,
        adr_reference=adr_ref,
        proposal_id=proposal_id,
        created_at=datetime(2026, 5, 13, tzinfo=UTC),
    )


class TestAC1EmptyStore:
    """File 부재 시 load → empty list."""

    def test_load_missing_file(self, tmp_path: Path) -> None:
        store = _ProposalStore(state_dir=tmp_path / "state")
        store.load()
        assert store.proposals == []

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "newdir"
        store = _ProposalStore(state_dir=state_dir)
        store.save()
        assert state_dir.exists()
        assert (state_dir / "proposals.json").exists()


class TestAC2RoundTripPersistence:
    """save → load 후 proposal 동일성."""

    def test_single_param_change_proposal(self, tmp_path: Path) -> None:
        store = _ProposalStore(state_dir=tmp_path / "s")
        store.proposals = [_proposal()]
        store.save()

        loaded = _ProposalStore(state_dir=tmp_path / "s")
        loaded.load()
        assert len(loaded.proposals) == 1
        p = loaded.proposals[0]
        assert p.proposal_id == "p1"
        assert p.trigger_signal is _TriggerSignal.DRAWDOWN
        assert p.state is _ProposalState.PENDING
        assert p.proposed_change.from_value == Decimal("5.0")
        assert p.proposed_change.to_value == Decimal("6.0")
        assert p.proposed_change.delta_pct == Decimal("20")
        assert p.created_at == datetime(2026, 5, 13, tzinfo=UTC)

    def test_strategy_change_str_values(self, tmp_path: Path) -> None:
        spec = _ChangeSpec(
            proposal_type=_ProposalType.STRATEGY_CHANGE,
            target="price_drop",
            from_value="price_drop",
            to_value="support_level",
            delta_pct=None,
            rationale="switch to support",
        )
        p = _Proposal(
            trigger_signal=_TriggerSignal.HUMAN_AD_HOC,
            current_state_snapshot={},
            proposed_change=spec,
            reasoning_json={},
            supporting_backtest_result=None,
            state=_ProposalState.PENDING,
            proposal_id="p2",
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
        )
        store = _ProposalStore(state_dir=tmp_path / "s")
        store.proposals = [p]
        store.save()

        loaded = _ProposalStore(state_dir=tmp_path / "s")
        loaded.load()
        rp = loaded.proposals[0]
        assert rp.proposed_change.from_value == "price_drop"
        assert rp.proposed_change.to_value == "support_level"
        assert rp.proposed_change.delta_pct is None

    def test_universe_change_none_from(self, tmp_path: Path) -> None:
        spec = _ChangeSpec(
            proposal_type=_ProposalType.UNIVERSE_CHANGE,
            target="132030",
            from_value=None,
            to_value="132030",
            delta_pct=None,
            rationale="add bond ETF",
        )
        p = _Proposal(
            trigger_signal=_TriggerSignal.HUMAN_AD_HOC,
            current_state_snapshot={},
            proposed_change=spec,
            reasoning_json={},
            supporting_backtest_result=None,
            state=_ProposalState.PENDING,
            proposal_id="p3",
            created_at=datetime(2026, 5, 13, tzinfo=UTC),
        )
        store = _ProposalStore(state_dir=tmp_path / "s")
        store.proposals = [p]
        store.save()

        loaded = _ProposalStore(state_dir=tmp_path / "s")
        loaded.load()
        rp = loaded.proposals[0]
        assert rp.proposed_change.from_value is None
        assert rp.proposed_change.to_value == "132030"

    def test_adr_filed_state(self, tmp_path: Path) -> None:
        p = _proposal(
            state=_ProposalState.ADR_FILED,
            adr_ref="docs/decisions/0099.md",
        )
        store = _ProposalStore(state_dir=tmp_path / "s")
        store.proposals = [p]
        store.save()

        loaded = _ProposalStore(state_dir=tmp_path / "s")
        loaded.load()
        rp = loaded.proposals[0]
        assert rp.state is _ProposalState.ADR_FILED
        assert rp.adr_reference == "docs/decisions/0099.md"


class TestAC3StoreOperations:
    """upsert / get_by_id / list_by_state."""

    def test_upsert_new_appends(self, tmp_path: Path) -> None:
        store = _ProposalStore(state_dir=tmp_path / "s")
        store.upsert(_proposal(proposal_id="p1"))
        store.upsert(_proposal(proposal_id="p2"))
        assert len(store.proposals) == 2

    def test_upsert_existing_replaces(self, tmp_path: Path) -> None:
        store = _ProposalStore(state_dir=tmp_path / "s")
        store.upsert(_proposal(proposal_id="p1", state=_ProposalState.PENDING))
        store.upsert(
            _proposal(
                proposal_id="p1",
                state=_ProposalState.APPROVED,
                adr_ref="docs/decisions/0099.md",
            )
        )
        assert len(store.proposals) == 1
        assert store.proposals[0].state is _ProposalState.APPROVED

    def test_get_by_id_missing(self, tmp_path: Path) -> None:
        store = _ProposalStore(state_dir=tmp_path / "s")
        assert store.get_by_id("nonexistent") is None

    def test_list_by_state_filter(self, tmp_path: Path) -> None:
        store = _ProposalStore(state_dir=tmp_path / "s")
        store.upsert(_proposal(proposal_id="p1", state=_ProposalState.PENDING))
        store.upsert(
            _proposal(
                proposal_id="p2",
                state=_ProposalState.APPROVED,
                adr_ref="x.md",
            )
        )
        pending = store.list_by_state(_ProposalState.PENDING)
        assert len(pending) == 1
        assert pending[0].proposal_id == "p1"

        approved = store.list_by_state(_ProposalState.APPROVED)
        assert len(approved) == 1
        assert approved[0].proposal_id == "p2"

        all_proposals = store.list_by_state(None)
        assert len(all_proposals) == 2


class TestAC4AtomicWrite:
    """Atomic write — 임시 파일 → os.replace 패턴 검증."""

    def test_no_tmp_residue(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "s"
        store = _ProposalStore(state_dir=state_dir)
        store.proposals = [_proposal()]
        store.save()
        # Ensure no .tmp files left.
        tmps = list(state_dir.glob(".proposals_*.tmp"))
        assert tmps == [], f"tmp residue: {tmps}"
