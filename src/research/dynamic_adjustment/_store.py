"""Phase 0.11.e.3 — `_ProposalStore` JSON file-based persistence (ADR 0011 §1.3 D4 + D6).

CLI 명령 사이 proposal state 보존. 단일 JSON 파일 — `<state_dir>/proposals.json`.
간단한 file-based store (sub-step .3 영역) — sqlite / 영구화 = Phase 1
promote 후 영역 (D13).

Serialization 규칙:
    - StrEnum (TriggerSignal / ProposalState / ProposalType) → `.value` str.
    - Decimal → str (예: "5.0"). Tagged dict 미사용 — 형식 단순화.
    - datetime → ISO 8601 (UTC, "+00:00" suffix).
    - dict / list → native JSON.
    - `from_value` / `to_value` (Any) → `{"value": str, "kind": "decimal|str|none"}`
      tagged form — round-trip 정확성 보장.

Atomic write: 임시 파일 + os.replace 패턴 — race condition 회피
(CLAUDE.md §10.1 단일 프로세스 정신 정합 — 다중 process 가정 X but
중단 시 corrupt 회피).

Lifecycle: 5th ring 영구 유지 (D13).
Underscore-prefix private (`__all__ = []`).
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.research.dynamic_adjustment._change_spec import _ChangeSpec
from src.research.dynamic_adjustment._proposal import _Proposal
from src.research.dynamic_adjustment._proposal_type import (
    _ProposalState,
    _ProposalType,
    _TriggerSignal,
)

__all__: list[str] = []


_DEFAULT_STORE_FILENAME = "proposals.json"


def _encode_value(value: Any) -> dict[str, str | None]:
    """`Any` → tagged dict (`from_value` / `to_value` round-trip)."""
    if value is None:
        return {"kind": "none", "value": None}
    if isinstance(value, Decimal):
        return {"kind": "decimal", "value": str(value)}
    if isinstance(value, str):
        return {"kind": "str", "value": value}
    raise TypeError(
        f"Unsupported value type for store: {type(value).__name__} "
        f"(expected Decimal / str / None)"
    )


def _decode_value(tagged: dict[str, str | None]) -> Any:
    kind = tagged.get("kind")
    raw = tagged.get("value")
    if kind == "none":
        return None
    if kind == "decimal":
        if raw is None:
            raise ValueError("decimal kind missing value")
        return Decimal(raw)
    if kind == "str":
        return raw
    raise ValueError(f"Unknown value kind in store: {kind!r}")


def _encode_change_spec(spec: _ChangeSpec) -> dict[str, Any]:
    return {
        "proposal_type": spec.proposal_type.value,
        "target": spec.target,
        "from_value": _encode_value(spec.from_value),
        "to_value": _encode_value(spec.to_value),
        "delta_pct": str(spec.delta_pct) if spec.delta_pct is not None else None,
        "rationale": spec.rationale,
    }


def _decode_change_spec(data: dict[str, Any]) -> _ChangeSpec:
    delta_raw = data.get("delta_pct")
    return _ChangeSpec(
        proposal_type=_ProposalType(data["proposal_type"]),
        target=data["target"],
        from_value=_decode_value(data["from_value"]),
        to_value=_decode_value(data["to_value"]),
        delta_pct=Decimal(delta_raw) if delta_raw is not None else None,
        rationale=data["rationale"],
    )


def _encode_proposal(p: _Proposal) -> dict[str, Any]:
    return {
        "proposal_id": p.proposal_id,
        "trigger_signal": p.trigger_signal.value,
        "current_state_snapshot": p.current_state_snapshot,
        "proposed_change": _encode_change_spec(p.proposed_change),
        "reasoning_json": p.reasoning_json,
        "supporting_backtest_result": p.supporting_backtest_result,
        "state": p.state.value,
        "adr_reference": p.adr_reference,
        "previous_proposal_ref": p.previous_proposal_ref,
        "created_at": p.created_at.isoformat(),
    }


def _decode_proposal(data: dict[str, Any]) -> _Proposal:
    return _Proposal(
        trigger_signal=_TriggerSignal(data["trigger_signal"]),
        current_state_snapshot=dict(data["current_state_snapshot"]),
        proposed_change=_decode_change_spec(data["proposed_change"]),
        reasoning_json=dict(data["reasoning_json"]),
        supporting_backtest_result=(
            dict(data["supporting_backtest_result"])
            if data.get("supporting_backtest_result") is not None
            else None
        ),
        state=_ProposalState(data["state"]),
        adr_reference=data.get("adr_reference"),
        previous_proposal_ref=data.get("previous_proposal_ref"),
        proposal_id=data["proposal_id"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )


@dataclass
class _ProposalStore:
    """JSON file-based proposal store — CLI 명령 간 state 보존.

    Mutable wrapper around in-memory proposal list with file persistence.
    Caller responsibility: load() 후 변경 → save(). Atomic write 으로
    corrupt 회피.

    Attributes:
        state_dir: store 파일 위치 (default `.proposal_state/`).
        proposals: in-memory proposal list (load() 이후 채워짐).
    """

    state_dir: Path
    proposals: list[_Proposal] = field(default_factory=list)

    def file_path(self) -> Path:
        return self.state_dir / _DEFAULT_STORE_FILENAME

    def load(self) -> None:
        """파일에서 proposal list 로드. 파일 부재 시 빈 list."""
        path = self.file_path()
        if not path.exists():
            self.proposals = []
            return
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        self.proposals = [_decode_proposal(d) for d in raw.get("proposals", [])]

    def save(self) -> None:
        """Atomic write — 임시 파일 + os.replace 패턴."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.file_path()
        payload = {"proposals": [_encode_proposal(p) for p in self.proposals]}
        # Atomic write
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(self.state_dir),
            prefix=".proposals_",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, indent=2, sort_keys=True, ensure_ascii=False)
            tmp_path = tmp.name
        Path(tmp_path).replace(path)

    def get_by_id(self, proposal_id: str) -> _Proposal | None:
        for p in self.proposals:
            if p.proposal_id == proposal_id:
                return p
        return None

    def upsert(self, proposal: _Proposal) -> None:
        """proposal_id 기준 in-place 교체 또는 append."""
        for i, p in enumerate(self.proposals):
            if p.proposal_id == proposal.proposal_id:
                self.proposals[i] = proposal
                return
        self.proposals.append(proposal)

    def list_by_state(
        self, state: _ProposalState | None = None,
    ) -> list[_Proposal]:
        if state is None:
            return list(self.proposals)
        return [p for p in self.proposals if p.state is state]
