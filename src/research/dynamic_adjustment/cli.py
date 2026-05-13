"""Phase 0.11.e.3 — Proposal CLI (ADR 0011 §1.3 D4 + D6 + D7).

진입점:
    python -m src.research.dynamic_adjustment proposal list [--state STATE]
    python -m src.research.dynamic_adjustment proposal create-pending \\
        --target STR --from VAL --to VAL --delta-pct PCT --rationale STR \\
        [--trigger TRIGGER] [--type TYPE] [--proposal-id ID]
    python -m src.research.dynamic_adjustment proposal approve <id> \\
        --adr-number STR --adr-path PATH [--supersedes STR]
    python -m src.research.dynamic_adjustment proposal reject <id>
    python -m src.research.dynamic_adjustment proposal verify-adr <id>
    python -m src.research.dynamic_adjustment proposal apply <id>

4-state 머신 (§1.6 #4 enforcement):
    PENDING → APPROVED (approve)
    PENDING → REJECTED (reject, terminal)
    APPROVED → ADR_FILED (verify-adr, file_exists + content gate)
    ADR_FILED → APPLIED (apply, cron pickup pattern)

ADR 0007 §1.6 — `python -m src.research.<...>` CLI 진입은 ring boundary
위반 아님. 본 CLI 는 outer (5th ring) → inner ring read 만 발생 (Phase
0.11.x "production rings 변경 zero" invariant 보존).

Lifecycle: 5th ring 영구 유지 (D13).
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.research.dynamic_adjustment._adr_template import (
    _render_adr_template,
    _verify_adr_content,
)
from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import _Proposal, _transition
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)
from src.research.dynamic_adjustment._store import _ProposalStore

__all__: list[str] = []


_DEFAULT_STATE_DIR = Path(".proposal_state")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="src.research.dynamic_adjustment",
        description=(
            "Phase 0.11.e Dynamic Adjustment Proposal CLI "
            "(ADR 0011 §1.3 D4 + D6 + D7)."
        ),
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=_DEFAULT_STATE_DIR,
        help="proposal state JSON directory (default .proposal_state/)",
    )

    sub = parser.add_subparsers(dest="domain", required=True)
    proposal = sub.add_parser("proposal", help="Proposal management")
    psub = proposal.add_subparsers(dest="action", required=True)

    p_list = psub.add_parser("list", help="List proposals")
    p_list.add_argument("--state", type=str, default=None,
                        help="filter by state (pending/approved/...)")

    p_create = psub.add_parser(
        "create-pending",
        help="Create a PENDING proposal (test/dev convenience)",
    )
    p_create.add_argument("--target", required=True)
    p_create.add_argument("--from", dest="from_value", required=True)
    p_create.add_argument("--to", dest="to_value", required=True)
    p_create.add_argument("--delta-pct", default=None,
                          help="Decimal-safe str; required for PARAMETER_CHANGE")
    p_create.add_argument("--rationale", required=True)
    p_create.add_argument("--trigger", default="human_ad_hoc")
    p_create.add_argument("--type", dest="ptype", default="parameter")
    p_create.add_argument("--proposal-id", default=None)

    p_approve = psub.add_parser("approve", help="PENDING → APPROVED")
    p_approve.add_argument("proposal_id")
    p_approve.add_argument("--adr-number", required=True,
                           help="ADR identifier (e.g. ADR-0099)")
    p_approve.add_argument("--adr-path", type=Path, required=True,
                           help="ADR markdown destination path")
    p_approve.add_argument("--supersedes", default=None)

    p_reject = psub.add_parser("reject", help="PENDING → REJECTED")
    p_reject.add_argument("proposal_id")

    p_verify = psub.add_parser(
        "verify-adr",
        help="Verify ADR content; if ready APPROVED → ADR_FILED",
    )
    p_verify.add_argument("proposal_id")

    p_apply = psub.add_parser("apply", help="ADR_FILED → APPLIED (cron pickup)")
    p_apply.add_argument("proposal_id")

    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_store(state_dir: Path) -> _ProposalStore:
    store = _ProposalStore(state_dir=state_dir)
    store.load()
    return store


def _build_change_spec_from_args(args: argparse.Namespace) -> _ChangeSpec:
    proposal_type = _ProposalType(args.ptype)
    delta = Decimal(args.delta_pct) if args.delta_pct is not None else None
    # from_value / to_value 는 type 분기:
    if proposal_type is _ProposalType.PARAMETER_CHANGE:
        from_v: object = Decimal(args.from_value)
        to_v: object = Decimal(args.to_value)
    else:
        # STRATEGY_CHANGE / UNIVERSE_CHANGE — str.
        from_v = args.from_value if args.from_value != "none" else None
        to_v = args.to_value if args.to_value != "none" else None
    return _ChangeSpec(
        proposal_type=proposal_type,
        target=args.target,
        from_value=from_v,
        to_value=to_v,
        delta_pct=delta,
        rationale=args.rationale,
    )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def _cmd_list(args: argparse.Namespace) -> int:
    store = _load_store(args.state_dir)
    state_filter = _ProposalState(args.state) if args.state else None
    proposals = store.list_by_state(state_filter)
    if not proposals:
        print("(no proposals)")
        return 0
    for p in proposals:
        print(
            f"{p.proposal_id}\t{p.state.value}\t{p.trigger_signal.value}\t"
            f"{p.proposed_change.proposal_type.value}\t{p.proposed_change.target}\t"
            f"adr={p.adr_reference or '-'}\tcreated={p.created_at.isoformat()}"
        )
    return 0


def _cmd_create_pending(args: argparse.Namespace) -> int:
    store = _load_store(args.state_dir)
    proposal_id = args.proposal_id or str(uuid.uuid4())
    if store.get_by_id(proposal_id) is not None:
        raise SystemExit(f"proposal_id {proposal_id!r} already exists")
    spec = _build_change_spec_from_args(args)
    trigger = _TriggerSignal(args.trigger)
    proposal = _Proposal(
        trigger_signal=trigger,
        current_state_snapshot={},
        proposed_change=spec,
        reasoning_json={"source": "cli create-pending"},
        supporting_backtest_result=None,
        state=_ProposalState.PENDING,
        proposal_id=proposal_id,
        created_at=datetime.now(tz=UTC),
    )
    store.upsert(proposal)
    store.save()
    print(json.dumps({"proposal_id": proposal_id, "state": "pending"}))
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    store = _load_store(args.state_dir)
    proposal = store.get_by_id(args.proposal_id)
    if proposal is None:
        raise SystemExit(f"proposal {args.proposal_id!r} not found")
    if proposal.state is not _ProposalState.PENDING:
        raise SystemExit(
            f"approve requires PENDING state, got {proposal.state.value}"
        )
    adr_path: Path = args.adr_path
    if adr_path.exists():
        raise SystemExit(
            f"adr_path already exists: {adr_path} — refusing to overwrite. "
            f"Choose a different path or delete the existing file."
        )
    # Render template + write (file exists invariant for verify-adr).
    template = _render_adr_template(
        proposal,
        adr_number=args.adr_number,
        supersedes=args.supersedes,
    )
    adr_path.parent.mkdir(parents=True, exist_ok=True)
    adr_path.write_text(template, encoding="utf-8")
    # Transition PENDING → APPROVED, set adr_reference.
    approved = _transition(
        proposal,
        to_state=_ProposalState.APPROVED,
        adr_reference=str(adr_path),
    )
    store.upsert(approved)
    store.save()
    print(json.dumps({
        "proposal_id": proposal.proposal_id,
        "state": "approved",
        "adr_path": str(adr_path),
    }))
    return 0


def _cmd_reject(args: argparse.Namespace) -> int:
    store = _load_store(args.state_dir)
    proposal = store.get_by_id(args.proposal_id)
    if proposal is None:
        raise SystemExit(f"proposal {args.proposal_id!r} not found")
    if proposal.state is not _ProposalState.PENDING:
        raise SystemExit(
            f"reject requires PENDING state, got {proposal.state.value}"
        )
    rejected = _transition(proposal, to_state=_ProposalState.REJECTED)
    store.upsert(rejected)
    store.save()
    print(json.dumps({
        "proposal_id": proposal.proposal_id,
        "state": "rejected",
    }))
    return 0


def _cmd_verify_adr(args: argparse.Namespace) -> int:
    store = _load_store(args.state_dir)
    proposal = store.get_by_id(args.proposal_id)
    if proposal is None:
        raise SystemExit(f"proposal {args.proposal_id!r} not found")
    if proposal.state is not _ProposalState.APPROVED:
        raise SystemExit(
            f"verify-adr requires APPROVED state, got {proposal.state.value}"
        )
    if proposal.adr_reference is None:
        raise SystemExit(
            f"proposal {proposal.proposal_id!r} has no adr_reference"
        )
    adr_path = Path(proposal.adr_reference)
    verified, message = _verify_adr_content(adr_path)
    if not verified:
        print(json.dumps({
            "proposal_id": proposal.proposal_id,
            "state": "approved",
            "verified": False,
            "message": message,
        }))
        return 1
    filed = _transition(proposal, to_state=_ProposalState.ADR_FILED)
    store.upsert(filed)
    store.save()
    print(json.dumps({
        "proposal_id": proposal.proposal_id,
        "state": "adr_filed",
        "verified": True,
        "message": message,
    }))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    store = _load_store(args.state_dir)
    proposal = store.get_by_id(args.proposal_id)
    if proposal is None:
        raise SystemExit(f"proposal {args.proposal_id!r} not found")
    if proposal.state is not _ProposalState.ADR_FILED:
        raise SystemExit(
            f"apply requires ADR_FILED state, got {proposal.state.value}. "
            f"APPROVED→APPLIED 직접 전이는 차단 (§1.6 #4 invariant). "
            f"verify-adr 통과 후 apply 호출 필요."
        )
    applied = _transition(proposal, to_state=_ProposalState.APPLIED)
    store.upsert(applied)
    store.save()
    print(json.dumps({
        "proposal_id": proposal.proposal_id,
        "state": "applied",
    }))
    return 0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
_HANDLERS = {
    ("proposal", "list"): _cmd_list,
    ("proposal", "create-pending"): _cmd_create_pending,
    ("proposal", "approve"): _cmd_approve,
    ("proposal", "reject"): _cmd_reject,
    ("proposal", "verify-adr"): _cmd_verify_adr,
    ("proposal", "apply"): _cmd_apply,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS.get((args.domain, args.action))
    if handler is None:
        raise SystemExit(f"Unknown command: {args.domain} {args.action}")
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
