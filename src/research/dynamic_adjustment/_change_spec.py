"""Phase 0.11.e.2 — `_ChangeSpec` 도메인 객체 (ADR 0011 §1.3 D3 #3).

`_Proposal.proposed_change` 필드의 type — L2 (parameter delta) 또는 L3
(strategy/universe delta) 의 변경 내용 박제. ProposalType 분기에 따라
다른 의미적 구조.

ADR 0011 §1.6 #5 + D14 cumulative drift bound (±30%) 측정 입력 — `field` /
`from_value` / `to_value` triple 이 drift 계산의 단위.

Lifecycle: 5th ring 영구 유지 (ADR 0011 D13).
Underscore-prefix private (ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.research.dynamic_adjustment._proposal_type import _ProposalType

__all__: list[str] = []


@dataclass(frozen=True)
class _ChangeSpec:
    """변경 내용 박제 — L2/L3 영역 ProposalType 분기.

    Fields:
        proposal_type: PARAMETER_CHANGE / STRATEGY_CHANGE / UNIVERSE_CHANGE.
        target: 변경 대상 식별 — L2 의 경우 yaml field path
            (예: "069500.buy_parameters.drop_threshold_pct"), L3 의 경우
            strategy_id (예: "price_drop", "support_level") 또는 universe
            entry (예: "069500" 추가/제거).
        from_value: 변경 전 값 — L2 의 경우 Decimal, L3 의 경우 str
            (strategy_id) 또는 None (UNIVERSE_CHANGE add 시).
        to_value: 변경 후 값 — 동일 type space.
        delta_pct: L2 의 경우 변동률 (Decimal, percent — 예: +5% =
            Decimal("5")). L3 의 경우 None (정성적 변경).
        rationale: 변경 정성적 사유 — CLI display 용 짧은 문구. JSON
            reasoning 은 `_Proposal.reasoning_json` 영역.

    Invariant:
        - PARAMETER_CHANGE: delta_pct 필수 (D14 cumulative drift bound
          입력).
        - STRATEGY_CHANGE / UNIVERSE_CHANGE: delta_pct None 허용.

    CLAUDE.md §2.1 Decimal invariant — 모든 numeric 은 Decimal.
    """

    proposal_type: _ProposalType
    target: str
    from_value: Any
    to_value: Any
    delta_pct: Decimal | None
    rationale: str

    def __post_init__(self) -> None:
        if self.proposal_type is _ProposalType.PARAMETER_CHANGE:
            if self.delta_pct is None:
                raise ValueError(
                    f"PARAMETER_CHANGE requires delta_pct (target={self.target!r})"
                )
            if not isinstance(self.delta_pct, Decimal):
                raise TypeError(
                    f"delta_pct must be Decimal, got {type(self.delta_pct).__name__}"
                )
        if not self.target:
            raise ValueError("target must be non-empty")
        if not self.rationale:
            raise ValueError("rationale must be non-empty")
