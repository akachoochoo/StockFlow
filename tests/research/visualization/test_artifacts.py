"""Phase 0.11.c.2 — `_DGTVisualizationArtifacts` sidecar dataclass tests.

ADR 0009 §1.3 D3 pattern B 정합:
  - `_DGTVisualizationArtifacts` 는 frozen dataclass.
  - `_GridSnapshot.levels` 는 `Sequence[Decimal]` — CLAUDE.md §2.1
    Decimal invariant.
  - `_DGTVisualizationArtifacts` 는 `_VisualizationArtifacts` Protocol
    (marker) 을 structural typing 으로 implements.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from src.research.visualization._artifacts import (
    _DGTVisualizationArtifacts,
    _GridSnapshot,
)
from src.research.visualization._visualization_renderer import (
    _VisualizationArtifacts,
)


class TestAC1DGTArtifactsFrozen:
    """`_DGTVisualizationArtifacts` instantiate + frozen invariant."""

    def test_instantiate(self) -> None:
        artifacts = _DGTVisualizationArtifacts(
            grid_history=[],
            reference_price_curve=[
                (datetime(2026, 1, 1, tzinfo=timezone.utc), Decimal("35000")),
            ],
            parameter_config={"n": 5, "k": Decimal("0.05"), "m": 1},
            asset_code="069500",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )
        assert artifacts.asset_code == "069500"
        assert artifacts.period_start == date(2026, 1, 1)
        assert artifacts.parameter_config["n"] == 5

    def test_frozen(self) -> None:
        artifacts = _DGTVisualizationArtifacts(
            grid_history=[],
            reference_price_curve=[],
            parameter_config={},
            asset_code="069500",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            artifacts.asset_code = "005930"  # type: ignore[misc]


class TestAC2GridSnapshotDecimal:
    """`_GridSnapshot.levels` = Sequence[Decimal] — Decimal invariant."""

    def test_grid_snapshot_levels_decimal(self) -> None:
        snap = _GridSnapshot(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            reference_price=Decimal("35000"),
            levels=[
                Decimal("33250"),
                Decimal("34125"),
                Decimal("35000"),
                Decimal("35875"),
                Decimal("36750"),
            ],
            triggered_level=Decimal("33250"),
        )
        for level in snap.levels:
            assert isinstance(level, Decimal), (
                f"Decimal invariant 위반 — level={level!r} ({type(level)})"
            )
        assert isinstance(snap.reference_price, Decimal)
        assert isinstance(snap.triggered_level, Decimal)

    def test_grid_snapshot_triggered_level_optional(self) -> None:
        snap = _GridSnapshot(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            reference_price=Decimal("35000"),
            levels=[Decimal("35000")],
            triggered_level=None,
        )
        assert snap.triggered_level is None


class TestAC3VisualizationArtifactsProtocol:
    """`_DGTVisualizationArtifacts` implements `_VisualizationArtifacts` marker Protocol."""

    def test_dgt_artifacts_is_visualization_artifacts(self) -> None:
        artifacts = _DGTVisualizationArtifacts(
            grid_history=[],
            reference_price_curve=[],
            parameter_config={},
            asset_code="069500",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )
        # Marker Protocol (메서드 0개) — 모든 객체가 structurally implements.
        # runtime_checkable + 빈 Protocol = isinstance True.
        assert isinstance(artifacts, _VisualizationArtifacts)
