"""Phase 0.11.c.2 — `_enrich_with_dgt_*` helper tests.

ADR 0009 §1.3 D3 pattern A 정합:
  - Helper 호출 시 annotations dict 에 DGT-specific metadata inject.
  - Strict no-collision invariant — 이미 key 존재 시 `AssertionError`
    (ADR 0006 §16.3 `_enrich_with_slot_number` 패턴 정합).
  - Reference price Decimal → str 변환 정확.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from src.research.visualization._trade_view_enrichment import (
    _enrich_with_dgt_grid_level,
    _enrich_with_dgt_reference_change,
)


class TestAC1EnrichGridLevel:
    """`_enrich_with_dgt_grid_level` 호출 → annotations 에 grid_level 추가."""

    def test_grid_level_added(self) -> None:
        annotations: dict[str, Any] = {"existing_key": "existing_value"}
        result = _enrich_with_dgt_grid_level(
            annotations,
            grid_level=2,
            reference_price=Decimal("35000"),
            asset_code="069500",
            side="BUY",
        )
        assert result["dgt_grid_level"] == "2"
        assert result["dgt_reference_price"] == "35000"
        # 기존 키 보존.
        assert result["existing_key"] == "existing_value"


class TestAC2EnrichRefChange:
    """`_enrich_with_dgt_reference_change` 호출 → annotations 에 ref_change 추가."""

    def test_ref_change_added(self) -> None:
        annotations: dict[str, Any] = {}
        result = _enrich_with_dgt_reference_change(
            annotations,
            old_ref=Decimal("35000"),
            new_ref=Decimal("36000"),
            asset_code="069500",
        )
        assert result["dgt_ref_change"] == "35000→36000"


class TestAC3NoCollisionGrid:
    """이미 `dgt_grid_level` 존재 시 `AssertionError` (strict no-collision)."""

    def test_collision_grid_level_raises(self) -> None:
        annotations: dict[str, Any] = {"dgt_grid_level": "999"}
        with pytest.raises(AssertionError, match="dgt_grid_level"):
            _enrich_with_dgt_grid_level(
                annotations,
                grid_level=1,
                reference_price=Decimal("35000"),
                asset_code="069500",
                side="BUY",
            )

    def test_collision_reference_price_raises(self) -> None:
        annotations: dict[str, Any] = {"dgt_reference_price": "99999"}
        with pytest.raises(AssertionError, match="dgt_reference_price"):
            _enrich_with_dgt_grid_level(
                annotations,
                grid_level=1,
                reference_price=Decimal("35000"),
                asset_code="069500",
                side="BUY",
            )

    def test_collision_ref_change_raises(self) -> None:
        annotations: dict[str, Any] = {"dgt_ref_change": "stale_value"}
        with pytest.raises(AssertionError, match="dgt_ref_change"):
            _enrich_with_dgt_reference_change(
                annotations,
                old_ref=Decimal("1"),
                new_ref=Decimal("2"),
                asset_code="069500",
            )


class TestAC4DecimalString:
    """Reference price Decimal → str 변환 정확성."""

    def test_decimal_with_fraction(self) -> None:
        annotations: dict[str, Any] = {}
        result = _enrich_with_dgt_grid_level(
            annotations,
            grid_level=1,
            reference_price=Decimal("35000.50"),
            asset_code="069500",
            side="BUY",
        )
        # str(Decimal("35000.50")) = "35000.50" — float 미경유.
        assert result["dgt_reference_price"] == "35000.50"

    def test_negative_grid_level(self) -> None:
        annotations: dict[str, Any] = {}
        result = _enrich_with_dgt_grid_level(
            annotations,
            grid_level=-3,
            reference_price=Decimal("35000"),
            asset_code="069500",
            side="SELL",
        )
        assert result["dgt_grid_level"] == "-3"


class TestAC5DoesNotMutateDomainReasoning:
    """Helper 는 전달받은 dict 를 in-place mutate + return — caller 가 copy 책임.

    ADR 0006 §16.3 패턴 정합 — caller (`trades_from_decisions`) 가
    `dict(record.reasoning)` 로 copy 후 view-side dict 전달. 본 helper 는
    view-side dict 를 mutate (domain 의 `reasoning` 은 unaffected — caller
    의 copy 보장).
    """

    def test_input_dict_mutated_in_place(self) -> None:
        # 본 helper 는 `_enrich_with_slot_number` 패턴 정합 — input dict
        # 자체를 mutate + return. Caller (`trades_from_decisions`) 가
        # 미리 dict() 로 copy 책임.
        annotations: dict[str, Any] = {}
        result = _enrich_with_dgt_grid_level(
            annotations,
            grid_level=1,
            reference_price=Decimal("35000"),
            asset_code="069500",
            side="BUY",
        )
        # Same object (mutation, not copy).
        assert result is annotations
        # Mutation 정합.
        assert "dgt_grid_level" in annotations
