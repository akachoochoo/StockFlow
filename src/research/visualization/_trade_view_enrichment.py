"""Phase 0.11.c — `TradeView.annotations` enrichment helpers (ADR 0009 §1.3 D3 pattern A).

ADR 0006 §16.3 `_enrich_with_slot_number` (`src/application/reporting/
trade_view.py:116-145`) 패턴 정합 — application layer view-side
enrichment + 도메인 변경 zero. 단, 본 helper 는 5th ring 내부 박제
(outer→inner read 로 `TradeView` 사용). 0.11.x "production rings 변경
zero" invariant 정합.

DGT-specific marker metadata (grid_level / reference_price / reference
change) 를 `TradeView.annotations` dict 에 inject. 0.11.c.4 의 comparison
orchestrator 가 episode-scope `StrategyRenderer.marker_label` 호출 시
enriched annotations 가 read 됨.

Strict no-collision invariant (ADR 0006 §16.3 정합) — 이미 동일 key 가
존재하면 `AssertionError`. 미래 회귀 (DGT strategy 가 reasoning 에 동일
key 를 emit 시) 를 fail-fast 로 노출.

Lifecycle (ADR 0009 §1.7): permanent.
Underscore-prefix private (ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from decimal import Decimal

    from src.application.reporting.trade_view import SideT


__all__: list[str] = []


def _enrich_with_dgt_grid_level(
    annotations: dict[str, Any],
    *,
    grid_level: int,
    reference_price: Decimal,
    asset_code: str,
    side: SideT,
) -> dict[str, Any]:
    """Inject DGT grid level + reference price 을 view-time annotations dict 에 박제.

    ADR 0006 §16.3 `_enrich_with_slot_number` 패턴 정합 — caller 가 미리
    `dict(record.reasoning)` 로 copy 한 view-side dict 를 전달. 도메인
    reasoning dict 은 mutate 되지 않음.

    Strict no-collision invariant: `dgt_grid_level` / `dgt_reference_price`
    key 가 이미 존재하면 `AssertionError`. 회귀 fail-fast.

    Args:
        annotations: view-side annotations dict (mutate 됨 + return 됨).
        grid_level: DGT grid level index (예: 1 ~ n, signed — 매수 음수
            영역 / 매도 양수 영역).
        reference_price: 해당 trade 시점의 DGT reference price (Decimal).
        asset_code: 종목 코드 (assertion 메시지용).
        side: "BUY" | "SELL" (assertion 메시지용).

    Returns:
        Enriched annotations dict (mutated in place + returned).
    """
    assert "dgt_grid_level" not in annotations, (
        f"unexpected dgt_grid_level={annotations.get('dgt_grid_level')!r} in "
        f"annotations for {side} {asset_code} — strategy reasoning must not "
        f"emit this key. Application/research layer enriches from typed "
        f"DGT runner state (ADR 0009 §1.3 D3 pattern A)."
    )
    assert "dgt_reference_price" not in annotations, (
        f"unexpected dgt_reference_price="
        f"{annotations.get('dgt_reference_price')!r} in annotations for "
        f"{side} {asset_code} — strategy reasoning must not emit this key."
    )
    annotations["dgt_grid_level"] = str(grid_level)
    annotations["dgt_reference_price"] = str(reference_price)
    return annotations


def _enrich_with_dgt_reference_change(
    annotations: dict[str, Any],
    *,
    old_ref: Decimal,
    new_ref: Decimal,
    asset_code: str,
) -> dict[str, Any]:
    """Inject DGT reference price 변경 (re-anchor) 을 annotations 에 박제.

    Re-anchor event marker — 현 0.11.a/0.11.b runner = 고정 reference
    (ohlcv[0].close) 이지만, 미래 re-anchor 도입 시 본 helper 가
    `TradeView.annotations` 에 변경 기록 inject. 0.11.c.3 의 DGT renderer
    가 본 annotation 을 chart 의 vertical line marker 로 표시 가능.

    Strict no-collision invariant.

    Args:
        annotations: view-side annotations dict (mutate 됨 + return 됨).
        old_ref: 이전 reference price (Decimal).
        new_ref: 신규 reference price (Decimal).
        asset_code: 종목 코드 (assertion 메시지용).

    Returns:
        Enriched annotations dict (mutated in place + returned).
    """
    assert "dgt_ref_change" not in annotations, (
        f"unexpected dgt_ref_change={annotations.get('dgt_ref_change')!r} in "
        f"annotations for {asset_code} — strategy reasoning must not emit "
        f"this key. Application/research layer enriches from typed DGT "
        f"runner re-anchor event (ADR 0009 §1.3 D3 pattern A)."
    )
    annotations["dgt_ref_change"] = f"{old_ref}→{new_ref}"
    return annotations
