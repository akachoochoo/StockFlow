"""Phase 0.11.e.3 — CLI end-to-end 4-state machine tests.

ADR 0011 §1.4 G2 + §1.6 #4 enforcement — `trigger → proposal → human
approve → ADR 박제 → 변경 적용` 한 사이클.

검증 항목:
    - PENDING → APPROVED → ADR_FILED → APPLIED 전체 cycle.
    - APPROVED → APPLIED 직접 전이 차단 hard (§1.6 #4).
    - REJECTED terminal.
    - ADR template scaffolding + content verification gate.
    - JSON store persistence 사이.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from src.research.dynamic_adjustment._proposal_type import _ProposalState
from src.research.dynamic_adjustment._store import _ProposalStore
from src.research.dynamic_adjustment.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    from src.research.dynamic_adjustment._proposal import _Proposal


def _create_pending(
    *,
    state_dir: Path,
    proposal_id: str = "prop-e2e-1",
) -> None:
    """Helper — create PENDING proposal via CLI."""
    exit_code = main(
        [
            "--state-dir",
            str(state_dir),
            "proposal",
            "create-pending",
            "--target",
            "069500.buy_parameters.drop_threshold_pct",
            "--from",
            "5.0",
            "--to",
            "6.0",
            "--delta-pct",
            "20",
            "--rationale",
            "DD spike — tighten threshold",
            "--trigger",
            "drawdown",
            "--type",
            "parameter",
            "--proposal-id",
            proposal_id,
        ]
    )
    assert exit_code == 0


def _load_proposal(state_dir: Path, proposal_id: str) -> _Proposal:
    store = _ProposalStore(state_dir=state_dir)
    store.load()
    p = store.get_by_id(proposal_id)
    assert p is not None
    return p


def _fill_adr_template(adr_path: Path) -> None:
    """Replace all `<TBD: ...>` markers + add bulk content (size threshold)."""
    text = adr_path.read_text(encoding="utf-8")
    filled = re.sub(
        r"<TBD: ([^>]+)>",
        lambda m: f"filled {m.group(1)}: 사용자 확정 / 5.0 -> 6.0",
        text,
    )
    filled += "\n\n## Additional reasoning\n\n" + ("verified analysis. " * 60)
    adr_path.write_text(filled, encoding="utf-8")


class TestAC1HappyPathFullCycle:
    """PENDING → APPROVED → ADR_FILED → APPLIED 전체 cycle."""

    def test_full_state_machine(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        adr_path = tmp_path / "docs/decisions/0099-test.md"

        # 1. Create PENDING.
        _create_pending(state_dir=state_dir)
        p = _load_proposal(state_dir, "prop-e2e-1")
        assert p.state is _ProposalState.PENDING

        # 2. Approve — PENDING → APPROVED + ADR template generated.
        exit_code = main(
            [
                "--state-dir", str(state_dir),
                "proposal", "approve", "prop-e2e-1",
                "--adr-number", "ADR-0099",
                "--adr-path", str(adr_path),
            ]
        )
        assert exit_code == 0
        p = _load_proposal(state_dir, "prop-e2e-1")
        assert p.state is _ProposalState.APPROVED
        assert p.adr_reference == str(adr_path)
        assert adr_path.exists()
        # Template should have TBD markers.
        assert "<TBD" in adr_path.read_text(encoding="utf-8")

        # 3. Verify-adr with TBD markers still present → fail (still APPROVED).
        exit_code = main(
            [
                "--state-dir", str(state_dir),
                "proposal", "verify-adr", "prop-e2e-1",
            ]
        )
        assert exit_code == 1  # verification failed
        p = _load_proposal(state_dir, "prop-e2e-1")
        assert p.state is _ProposalState.APPROVED  # unchanged

        # 4. Human fills template → verify-adr passes → ADR_FILED.
        _fill_adr_template(adr_path)
        exit_code = main(
            [
                "--state-dir", str(state_dir),
                "proposal", "verify-adr", "prop-e2e-1",
            ]
        )
        assert exit_code == 0
        p = _load_proposal(state_dir, "prop-e2e-1")
        assert p.state is _ProposalState.ADR_FILED

        # 5. Apply — ADR_FILED → APPLIED.
        exit_code = main(
            [
                "--state-dir", str(state_dir),
                "proposal", "apply", "prop-e2e-1",
            ]
        )
        assert exit_code == 0
        p = _load_proposal(state_dir, "prop-e2e-1")
        assert p.state is _ProposalState.APPLIED


class TestAC2RejectTerminal:
    """PENDING → REJECTED, re-approve 차단."""

    def test_reject_pending(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        _create_pending(state_dir=state_dir)
        exit_code = main(
            [
                "--state-dir", str(state_dir),
                "proposal", "reject", "prop-e2e-1",
            ]
        )
        assert exit_code == 0
        p = _load_proposal(state_dir, "prop-e2e-1")
        assert p.state is _ProposalState.REJECTED

    def test_re_approve_rejected_blocks(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        adr_path = tmp_path / "docs/decisions/0099-test.md"
        _create_pending(state_dir=state_dir)
        main(["--state-dir", str(state_dir), "proposal", "reject", "prop-e2e-1"])
        with pytest.raises(SystemExit, match="approve requires PENDING state"):
            main(
                [
                    "--state-dir", str(state_dir),
                    "proposal", "approve", "prop-e2e-1",
                    "--adr-number", "ADR-0099",
                    "--adr-path", str(adr_path),
                ]
            )


class TestAC3ApprovedToAppliedDirectBlocked:
    """§1.6 #4 — APPROVED → APPLIED 직접 전이 차단 hard."""

    def test_apply_from_approved_blocked(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        adr_path = tmp_path / "docs/decisions/0099-test.md"
        _create_pending(state_dir=state_dir)
        main(
            [
                "--state-dir", str(state_dir),
                "proposal", "approve", "prop-e2e-1",
                "--adr-number", "ADR-0099",
                "--adr-path", str(adr_path),
            ]
        )
        # verify-adr 부재로 ADR_FILED 미진입 — apply 시 차단.
        with pytest.raises(SystemExit, match="apply requires ADR_FILED state"):
            main(
                [
                    "--state-dir", str(state_dir),
                    "proposal", "apply", "prop-e2e-1",
                ]
            )

    def test_verify_from_pending_blocked(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        _create_pending(state_dir=state_dir)
        with pytest.raises(SystemExit, match="verify-adr requires APPROVED state"):
            main(
                [
                    "--state-dir", str(state_dir),
                    "proposal", "verify-adr", "prop-e2e-1",
                ]
            )


class TestAC4ListCommand:
    """`proposal list` — filter + display."""

    def test_list_empty(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        exit_code = main(
            [
                "--state-dir", str(tmp_path / "state"),
                "proposal", "list",
            ]
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "no proposals" in captured.out

    def test_list_filter_by_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        state_dir = tmp_path / "state"
        _create_pending(state_dir=state_dir, proposal_id="p1")
        _create_pending(state_dir=state_dir, proposal_id="p2")
        # Reject p2.
        main(["--state-dir", str(state_dir), "proposal", "reject", "p2"])
        # List PENDING only.
        capsys.readouterr()  # clear
        main(
            [
                "--state-dir", str(state_dir),
                "proposal", "list", "--state", "pending",
            ]
        )
        out = capsys.readouterr().out
        assert "p1" in out
        assert "p2" not in out


class TestAC5OverwriteRefusal:
    """Approve refuses if ADR path already exists (race safety)."""

    def test_existing_adr_path_blocks(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        adr_path = tmp_path / "docs/decisions/0099-existing.md"
        adr_path.parent.mkdir(parents=True, exist_ok=True)
        adr_path.write_text("# Existing ADR\n", encoding="utf-8")

        _create_pending(state_dir=state_dir)
        with pytest.raises(SystemExit, match="adr_path already exists"):
            main(
                [
                    "--state-dir", str(state_dir),
                    "proposal", "approve", "prop-e2e-1",
                    "--adr-number", "ADR-0099",
                    "--adr-path", str(adr_path),
                ]
            )


class TestAC6MissingProposal:
    """Approve / reject / verify / apply on missing id → SystemExit."""

    def test_missing_id_approve(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="not found"):
            main(
                [
                    "--state-dir", str(tmp_path / "state"),
                    "proposal", "approve", "nonexistent",
                    "--adr-number", "ADR-0099",
                    "--adr-path", str(tmp_path / "x.md"),
                ]
            )

    def test_missing_id_reject(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="not found"):
            main(
                [
                    "--state-dir", str(tmp_path / "state"),
                    "proposal", "reject", "nonexistent",
                ]
            )


class TestAC7CreatePendingDuplicateBlocked:
    """create-pending: duplicate proposal_id → SystemExit."""

    def test_duplicate_id_blocked(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "state"
        _create_pending(state_dir=state_dir, proposal_id="dup-id")
        with pytest.raises(SystemExit, match="already exists"):
            _create_pending(state_dir=state_dir, proposal_id="dup-id")
