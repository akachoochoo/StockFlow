"""Phase 0.11.c.4 — comparison orchestration (ADR 0009 §1.3 D6).

여러 전략의 `_OverlayPayload` 를 합성한 PNG 산출:
    - `_render_overlay_pnl`        : 누적 수익 곡선 단일 axes (overlay)
    - `_render_overlay_drawdown`   : drawdown 곡선 단일 axes (overlay)
    - `_render_grid`               : 전략별 panel grid (각 행 = 1 strategy)

D6 (c) "overlay + grid 둘 다 지원" 정합. D11 CJK font fallback 패턴
(`src/adapters/reporting/chart.py:155-163`) 재사용. R8 mitigation —
`try/finally` + `plt.close(fig)` invariant.

Lifecycle (ADR 0009 §1.7): permanent. Underscore-prefix private
(ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from matplotlib.font_manager import FontProperties

    from src.research.visualization._visualization_renderer import (
        _OverlayPayload,
    )


__all__: list[str] = []


_FIGURE_WIDTH_PX = 1600
_FIGURE_HEIGHT_PX = 900
_FIGURE_DPI = 100

_CJK_CANDIDATES = (
    "AppleGothic",
    "Apple SD Gothic Neo",
    "Noto Sans CJK KR",
    "Nanum Gothic",
    "Malgun Gothic",
)

_STRATEGY_PALETTE = (
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#2ca02c",  # green
    "#d62728",  # red
    "#9467bd",  # purple
    "#8c564b",  # brown
)


def _resolve_cjk_fontprop() -> FontProperties | None:
    """CJK 폰트 fallback resolver — `chart.py:155-163` 패턴 정합."""
    from matplotlib import font_manager
    from matplotlib.font_manager import FontProperties

    available = {f.name for f in font_manager.fontManager.ttflist}
    name = next((n for n in _CJK_CANDIDATES if n in available), None)
    return FontProperties(family=name) if name else None


def _validate_payloads(payloads: Sequence[_OverlayPayload]) -> None:
    if not payloads:
        raise ValueError("payloads is empty — at least one strategy required")
    for p in payloads:
        if not p.time_series:
            raise ValueError(
                f"strategy {p.strategy_id!r} has empty time_series"
            )


def _render_overlay_pnl(payloads: Sequence[_OverlayPayload]) -> bytes:
    """누적 수익 곡선 overlay PNG.

    모든 전략을 동일 axes 에 그려 직접 비교. Y axis = pnl_cumulative
    (Decimal → float, 표시 전용 — 계산 path 는 Decimal 보존).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _validate_payloads(payloads)
    cjk_fp = _resolve_cjk_fontprop()

    fig_w_in = _FIGURE_WIDTH_PX / _FIGURE_DPI
    fig_h_in = _FIGURE_HEIGHT_PX / _FIGURE_DPI
    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in), dpi=_FIGURE_DPI)
    try:
        for idx, p in enumerate(payloads):
            color = _STRATEGY_PALETTE[idx % len(_STRATEGY_PALETTE)]
            xs = list(p.time_series)
            ys = [float(v) for v in p.pnl_cumulative]
            ax.plot(xs, ys, color=color, linewidth=1.4, label=p.strategy_id)  # type: ignore[arg-type]
        ax.axhline(y=0, color="#888888", linewidth=0.6, linestyle=":")
        ax.set_title("Comparison — Cumulative PnL", fontproperties=cjk_fp)
        ax.set_xlabel("date")
        ax.set_ylabel("PnL (currency units)")
        legend = ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
        if cjk_fp is not None and legend is not None:
            for txt in legend.get_texts():
                txt.set_fontproperties(cjk_fp)
        fig.autofmt_xdate()
        buf = io.BytesIO()
        fig.savefig(
            buf, format="png", dpi=_FIGURE_DPI, bbox_inches="tight",
        )
        return buf.getvalue()
    finally:
        plt.close(fig)


def _render_overlay_drawdown(payloads: Sequence[_OverlayPayload]) -> bytes:
    """Drawdown 곡선 overlay PNG (모든 series ≤ 0)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _validate_payloads(payloads)
    cjk_fp = _resolve_cjk_fontprop()

    fig_w_in = _FIGURE_WIDTH_PX / _FIGURE_DPI
    fig_h_in = _FIGURE_HEIGHT_PX / _FIGURE_DPI
    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in), dpi=_FIGURE_DPI)
    try:
        for idx, p in enumerate(payloads):
            color = _STRATEGY_PALETTE[idx % len(_STRATEGY_PALETTE)]
            xs = list(p.time_series)
            ys = [float(v) for v in p.drawdown]
            ax.plot(xs, ys, color=color, linewidth=1.4, label=p.strategy_id)  # type: ignore[arg-type]
        ax.axhline(y=0, color="#888888", linewidth=0.6, linestyle=":")
        ax.set_title("Comparison — Drawdown", fontproperties=cjk_fp)
        ax.set_xlabel("date")
        ax.set_ylabel("drawdown (currency units)")
        legend = ax.legend(loc="lower left", fontsize=9, framealpha=0.85)
        if cjk_fp is not None and legend is not None:
            for txt in legend.get_texts():
                txt.set_fontproperties(cjk_fp)
        fig.autofmt_xdate()
        buf = io.BytesIO()
        fig.savefig(
            buf, format="png", dpi=_FIGURE_DPI, bbox_inches="tight",
        )
        return buf.getvalue()
    finally:
        plt.close(fig)


def _render_grid(payloads: Sequence[_OverlayPayload]) -> bytes:
    """Grid layout — 전략별 panel (pnl + drawdown 2 column x N rows).

    각 row = 1 strategy. 왼쪽 column = 누적 수익, 오른쪽 column =
    drawdown. 단일 figure 로 visual scan + 전략별 detail 가독성.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _validate_payloads(payloads)
    cjk_fp = _resolve_cjk_fontprop()

    n = len(payloads)
    fig_w_in = _FIGURE_WIDTH_PX / _FIGURE_DPI
    fig_h_in = max(_FIGURE_HEIGHT_PX, n * 300) / _FIGURE_DPI
    fig, axes = plt.subplots(
        nrows=n, ncols=2,
        figsize=(fig_w_in, fig_h_in), dpi=_FIGURE_DPI,
        squeeze=False,
    )
    try:
        for idx, p in enumerate(payloads):
            color = _STRATEGY_PALETTE[idx % len(_STRATEGY_PALETTE)]
            ax_pnl = axes[idx][0]
            ax_dd = axes[idx][1]
            xs = list(p.time_series)
            pnl_ys = [float(v) for v in p.pnl_cumulative]
            dd_ys = [float(v) for v in p.drawdown]

            ax_pnl.plot(xs, pnl_ys, color=color, linewidth=1.3)
            ax_pnl.axhline(
                y=0, color="#888888", linewidth=0.5, linestyle=":",
            )
            ax_pnl.set_title(
                f"{p.strategy_id} — PnL", fontproperties=cjk_fp,
            )
            ax_pnl.set_ylabel("PnL")

            ax_dd.plot(xs, dd_ys, color=color, linewidth=1.3)
            ax_dd.axhline(
                y=0, color="#888888", linewidth=0.5, linestyle=":",
            )
            ax_dd.set_title(
                f"{p.strategy_id} — Drawdown", fontproperties=cjk_fp,
            )
            ax_dd.set_ylabel("drawdown")

        fig.suptitle(
            "Strategy comparison — grid layout",
            fontproperties=cjk_fp,
        )
        fig.autofmt_xdate()
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(
            buf, format="png", dpi=_FIGURE_DPI, bbox_inches="tight",
        )
        return buf.getvalue()
    finally:
        plt.close(fig)
