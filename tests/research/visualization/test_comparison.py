"""Phase 0.11.c.4 — `_comparison` orchestration tests.

ADR 0009 §1.3 D6 (c) + R8 mitigation:
  - overlay PNG (pnl + drawdown) + grid PNG 산출.
  - `plt.close(fig)` invariant (figure-leak).
  - Empty payload 거부 (early-fail).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.research.visualization._comparison import (
    _render_grid,
    _render_overlay_drawdown,
    _render_overlay_pnl,
)
from src.research.visualization._visualization_renderer import _OverlayPayload

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _payload(strategy_id: str, n_points: int = 20) -> _OverlayPayload:
    """Synthesized linear pnl curve with mild drawdown."""
    base = datetime(2024, 1, 2, tzinfo=UTC)
    time_series = [base + timedelta(days=i) for i in range(n_points)]
    pnl: list[Decimal] = []
    drawdown: list[Decimal] = []
    peak = Decimal("0")
    for i in range(n_points):
        # Saw-tooth pnl: +i for first half, declining for second.
        if i < n_points // 2:
            value = Decimal(i * 10)
        else:
            value = Decimal((n_points // 2) * 10 - (i - n_points // 2) * 5)
        if value > peak:
            peak = value
        pnl.append(value)
        drawdown.append(value - peak)
    return _OverlayPayload(
        time_series=time_series,
        pnl_cumulative=pnl,
        drawdown=drawdown,
        strategy_id=strategy_id,
    )


class TestAC1OverlayPnL:
    """`_render_overlay_pnl` — N strategies on single axes."""

    def test_png_header(self) -> None:
        pytest.importorskip("matplotlib")
        payloads = [_payload("a"), _payload("b"), _payload("c")]
        png = _render_overlay_pnl(payloads)
        assert png.startswith(_PNG_HEADER)
        assert len(png) > 1000

    def test_empty_payloads_raises(self) -> None:
        with pytest.raises(ValueError, match="payloads is empty"):
            _render_overlay_pnl([])

    def test_empty_time_series_raises(self) -> None:
        empty = _OverlayPayload(
            time_series=[],
            pnl_cumulative=[],
            drawdown=[],
            strategy_id="empty",
        )
        with pytest.raises(ValueError, match="empty time_series"):
            _render_overlay_pnl([empty])


class TestAC2OverlayDrawdown:
    """`_render_overlay_drawdown` — single axes."""

    def test_png_header(self) -> None:
        pytest.importorskip("matplotlib")
        payloads = [_payload("a"), _payload("b")]
        png = _render_overlay_drawdown(payloads)
        assert png.startswith(_PNG_HEADER)


class TestAC3Grid:
    """`_render_grid` — N rows x 2 cols (pnl / drawdown per strategy)."""

    def test_png_header(self) -> None:
        pytest.importorskip("matplotlib")
        payloads = [_payload("a"), _payload("b"), _payload("c")]
        png = _render_grid(payloads)
        assert png.startswith(_PNG_HEADER)

    def test_single_strategy(self) -> None:
        pytest.importorskip("matplotlib")
        png = _render_grid([_payload("solo")])
        assert png.startswith(_PNG_HEADER)


class TestAC4FigureLeakInvariant:
    """R8 mitigation — `plt.close(fig)` 누락 검출."""

    def test_overlay_pnl_no_leak(self) -> None:
        plt = pytest.importorskip("matplotlib.pyplot")
        plt.close("all")
        baseline = plt.get_fignums()
        _render_overlay_pnl([_payload("a"), _payload("b")])
        assert plt.get_fignums() == baseline

    def test_overlay_drawdown_no_leak(self) -> None:
        plt = pytest.importorskip("matplotlib.pyplot")
        plt.close("all")
        baseline = plt.get_fignums()
        _render_overlay_drawdown([_payload("a")])
        assert plt.get_fignums() == baseline

    def test_grid_no_leak(self) -> None:
        plt = pytest.importorskip("matplotlib.pyplot")
        plt.close("all")
        baseline = plt.get_fignums()
        _render_grid([_payload("a"), _payload("b")])
        assert plt.get_fignums() == baseline


class TestAC5Reproducibility:
    """동일 입력 2회 실행 — figure metadata 일치 (D10 (ii))."""

    def test_overlay_pnl_length_consistency(self) -> None:
        pytest.importorskip("matplotlib")
        payloads = [_payload("a"), _payload("b")]
        b1 = _render_overlay_pnl(payloads)
        b2 = _render_overlay_pnl(payloads)
        assert len(b1) == len(b2)

    def test_grid_length_consistency(self) -> None:
        pytest.importorskip("matplotlib")
        payloads = [_payload("a"), _payload("b")]
        b1 = _render_grid(payloads)
        b2 = _render_grid(payloads)
        assert len(b1) == len(b2)
