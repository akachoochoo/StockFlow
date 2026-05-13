"""Phase 0.11.c.2 — `_VisualizationRenderer` Protocol structural typing tests.

ADR 0009 §1.3 D2 (d) + §1.4 G1 정합:
  - `_VisualizationRenderer` Protocol 신규 + `runtime_checkable`.
  - 기존 `StrategyRenderer` Protocol (ADR 0006 §4.2) 시그니처 변경 zero
    (frozen invariant 보존).
  - Structural typing — `isinstance(impl, _VisualizationRenderer)` 가
    duck-typed class 에 대해 True (메서드 시그니처 정합 시).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.research.visualization._visualization_renderer import (
    _OverlayPayload,
    _VisualizationArtifacts,
    _VisualizationRenderer,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.application.reporting.trade_view import TradeView
    from src.domain.models import OHLCV


class TestAC1ProtocolDefined:
    """`_VisualizationRenderer` import OK + `runtime_checkable` 활성."""

    def test_protocol_imported(self) -> None:
        assert _VisualizationRenderer is not None

    def test_runtime_checkable(self) -> None:
        # `@runtime_checkable` decorator 가 `_is_runtime_protocol` 또는
        # `_is_protocol` attribute 를 set 함 (Python 3.11+).
        assert getattr(_VisualizationRenderer, "_is_runtime_protocol", False) or (
            getattr(_VisualizationRenderer, "_is_protocol", False)
        )


class TestAC2OverlayPayloadDataclass:
    """`_OverlayPayload` instantiate + frozen + Decimal type 검증."""

    def test_instantiate(self) -> None:
        payload = _OverlayPayload(
            time_series=[datetime(2026, 1, 1, tzinfo=timezone.utc)],
            pnl_cumulative=[Decimal("0.0")],
            drawdown=[Decimal("0.0")],
            strategy_id="dgt",
        )
        assert payload.strategy_id == "dgt"
        assert payload.pnl_cumulative[0] == Decimal("0.0")

    def test_frozen(self) -> None:
        payload = _OverlayPayload(
            time_series=[],
            pnl_cumulative=[],
            drawdown=[],
            strategy_id="dgt",
        )
        # @dataclass(frozen=True) — assignment FrozenInstanceError
        with pytest.raises(dataclasses.FrozenInstanceError):
            payload.strategy_id = "other"  # type: ignore[misc]

    def test_decimal_type_preserved(self) -> None:
        payload = _OverlayPayload(
            time_series=[],
            pnl_cumulative=[Decimal("1234.56")],
            drawdown=[Decimal("-100.0")],
            strategy_id="dgt",
        )
        # CLAUDE.md §2.1 invariant — float 미경유.
        assert isinstance(payload.pnl_cumulative[0], Decimal)
        assert isinstance(payload.drawdown[0], Decimal)


class TestAC3StrategyRendererUntouched:
    """기존 `StrategyRenderer` Protocol 시그니처 변경 zero (ADR 0006 §15.2 frozen)."""

    def test_strategy_renderer_methods_present(self) -> None:
        from src.ports.strategy_renderer import StrategyRenderer

        # marker_label / marker_style / diagnostic_panels 3 메서드 존재.
        for name in ("marker_label", "marker_style", "diagnostic_panels"):
            assert hasattr(StrategyRenderer, name), (
                f"StrategyRenderer.{name} missing — ADR 0006 §4.2 frozen "
                f"invariant 위반"
            )

    def test_strategy_renderer_distinct_from_visualization_renderer(self) -> None:
        # 두 Protocol = 완전히 별도 (D2 (d) 채택 정합).
        from src.ports.strategy_renderer import StrategyRenderer

        assert StrategyRenderer is not _VisualizationRenderer


class TestAC4StructuralTyping:
    """Dummy class with matching signatures → `isinstance` True."""

    def test_dummy_renderer_structurally_typed(self) -> None:
        @dataclass
        class _Dummy:
            strategy_id: str = "dummy"

            def render_full_period(
                self,
                bars: Sequence[OHLCV],
                trades: Sequence[TradeView],
                artifacts: _VisualizationArtifacts | None = None,
            ) -> bytes:
                return b""

            def extract_overlay_metric(
                self,
                bars: Sequence[OHLCV],
                trades: Sequence[TradeView],
                artifacts: _VisualizationArtifacts | None = None,
            ) -> _OverlayPayload:
                return _OverlayPayload(
                    time_series=[],
                    pnl_cumulative=[],
                    drawdown=[],
                    strategy_id=self.strategy_id,
                )

        dummy = _Dummy()
        assert isinstance(dummy, _VisualizationRenderer)


class TestAC5MissingMethodFails:
    """Dummy class missing `render_full_period` → `isinstance` False."""

    def test_missing_render_full_period_fails(self) -> None:
        @dataclass
        class _Incomplete:
            strategy_id: str = "incomplete"

            def extract_overlay_metric(
                self,
                bars: Sequence[OHLCV],
                trades: Sequence[TradeView],
                artifacts: _VisualizationArtifacts | None = None,
            ) -> _OverlayPayload:
                return _OverlayPayload(
                    time_series=[],
                    pnl_cumulative=[],
                    drawdown=[],
                    strategy_id="incomplete",
                )

        incomplete = _Incomplete()
        # `@runtime_checkable` Protocol — missing method → isinstance False.
        assert not isinstance(incomplete, _VisualizationRenderer)
