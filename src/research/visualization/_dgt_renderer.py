"""Phase 0.11.c.3 — `_DGTVisualizationRenderer` 구현 (ADR 0009 §1.8 sub-step 0.11.c.3).

DGT-specific full-period chart (close price line + grid envelope band +
reference price horizontal line + BUY/SELL trade markers) + comparison
mode overlay metric (time + cumulative P&L + drawdown).

ADR 0009 §1.3 정합:
- D2 (d) — `_VisualizationRenderer` Protocol (`_visualization_renderer.py`)
  structural typing 구현.
- D3 pattern B — `_DGTVisualizationArtifacts` sidecar 입력 (`_artifacts.py`).
  `BacktestResult` / `_DGTBacktestResult` 스키마 침범 zero.
- D4 (a) — matplotlib manual candle rendering via `src.research.dgt._candles`
  (mplfinance 미사용 — ADR 0015 Option A synthesis). 캔들 + 거래량 2-panel layout.
- D5 — PNG bytes 반환 (width=1600, height=900, dpi=100 고정).
- D8 정정 — DGT renderer 신규, B&H/7split 은 기존 `DefaultRenderer` /
  `SevenSplitRenderer` 활용 (재구현 zero).
- D11 — CJK font fallback = `src/adapters/reporting/chart.py:155-163`
  `_cjk_candidates` tuple + `FontProperties` per-Text override 재사용.

Pre-mortem 시나리오 A (figure leak) — `try/finally` + `plt.close(fig)`
invariant 박제 (ADR 0006 §17.8 패턴 상속, R8 mitigation).

Lifecycle (ADR 0009 §1.7): permanent. Underscore-prefix private
(ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Literal, overload

from src.research.dgt._candles import _draw_candles, _draw_volume
from src.research.dgt._interactive_chart import (
    _serialize_grid_levels,
    _serialize_markers,
    _serialize_ohlcv,
    _serialize_volume,
    build_interactive_chart_html,
)
from src.research.visualization._artifacts import _DGTVisualizationArtifacts
from src.research.visualization._visualization_renderer import (
    _OverlayPayload,
    _VisualizationArtifacts,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from src.application.reporting.trade_view import TradeView
    from src.domain.models import OHLCV


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

_COLOR_CLOSE = "#1f77b4"
_COLOR_BUY = "#d62728"
_COLOR_SELL = "#2ca02c"
_COLOR_REFERENCE = "#000000"
_COLOR_GRID_LINE = "#bbbbbb"
_COLOR_GRID_BAND = "#cccccc"


class _DGTVisualizationRenderer:
    """DGT 전용 full-period visualization 구현.

    `_VisualizationRenderer` Protocol (`_visualization_renderer.py`) 을
    structural typing 으로 구현. Registry 등록은 0.11.c.4 sub-step (또는
    별도 결정 라운드) 영역 — 본 sub-step 은 단일 구현체 박제만.

    `strategy_id = "dgt"` 은 `_OverlayPayload.strategy_id` 채움 + 미래
    Registry mapping key (D8 D9 정합).
    """

    strategy_id: ClassVar[str] = "dgt"

    def _build_render_figure(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = None,
    ) -> tuple[Any, Any]:
        """Build the 2-panel (price candles + volume) figure without saving or closing.

        Internal helper that returns ``(fig, axes)`` so tests can assert panel
        count directly without triggering savefig/close.  The caller is responsible
        for ``plt.close(fig)`` — see ``render_full_period`` for the public wrapper.

        Returns:
            ``(fig, axes)`` where ``axes`` is a 2-element array:
            ``axes[0]`` = price candle panel, ``axes[1]`` = volume panel.

        Raises:
            ValueError: bars 가 비어 있는 경우.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.font_manager import FontProperties

        if not bars:
            raise ValueError("bars is empty")

        sorted_bars = sorted(bars, key=lambda b: b.trade_date)
        dates: list[date] = [b.trade_date for b in sorted_bars]
        date_set = set(dates)

        available_fonts = {f.name for f in font_manager.fontManager.ttflist}
        cjk_font = next(
            (name for name in _CJK_CANDIDATES if name in available_fonts),
            None,
        )
        cjk_fontprop = FontProperties(family=cjk_font) if cjk_font else None

        # Bar-count-adaptive width: ~1250 bars → ~22.7 in; clamped [16, 40].
        # Lower bound 16 (vs 14 in kakao) to stay consistent with _FIGURE_WIDTH_PX=1600.
        # Height stays fixed at _FIGURE_HEIGHT_PX / _FIGURE_DPI (geometry approximate
        # due to bbox_inches="tight" — ADR 0015 R8).
        n_bars = len(sorted_bars)
        fig_w_in = min(40.0, max(float(_FIGURE_WIDTH_PX / _FIGURE_DPI), n_bars / 55.0))
        fig_h_in = _FIGURE_HEIGHT_PX / _FIGURE_DPI
        fig, axes = plt.subplots(
            2, 1,
            height_ratios=[3, 1],
            figsize=(fig_w_in, fig_h_in),
            dpi=_FIGURE_DPI,
            sharex=True,
        )
        ax = axes[0]  # price panel
        ax_vol = axes[1]  # volume panel

        # --- Price panel: candlestick + overlays ---
        _draw_candles(ax, list(sorted_bars))

        if isinstance(artifacts, _DGTVisualizationArtifacts):
            self._draw_grid_envelope(ax, artifacts)
            self._draw_reference_price(ax, artifacts)

        self._draw_trade_markers(ax, trades, date_set)

        self._apply_title(ax, dates[0], dates[-1], artifacts, cjk_fontprop)
        ax.set_ylabel("price")
        legend = ax.legend(loc="upper left", fontsize=8, framealpha=0.85)
        if cjk_fontprop is not None and legend is not None:
            for txt in legend.get_texts():
                txt.set_fontproperties(cjk_fontprop)

        # --- Volume panel ---
        _draw_volume(ax_vol, list(sorted_bars))
        ax_vol.set_ylabel("volume")
        ax_vol.grid(True, alpha=0.3)

        fig.autofmt_xdate()
        return fig, axes

    @overload
    def render_full_period(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = ...,
        *,
        fmt: Literal["png"] = ...,
    ) -> bytes: ...

    @overload
    def render_full_period(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = ...,
        *,
        fmt: Literal["html"],
    ) -> str: ...

    def render_full_period(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = None,
        *,
        fmt: Literal["png", "html"] = "png",
    ) -> bytes | str:
        """Full-period chart 산출 (ADR 0009 §1.3 D5 + ADR 0016 §1.4 Option iii).

        fmt="png" (기본값, 기존 동작 byte-identical):
            Layout (2-panel, ADR 0015 Option A synthesis):
                - axes[0] — OHLC candlestick price panel (캔들 + grid envelope +
                  reference price line + BUY/SELL trade markers)
                - axes[1] — volume bar panel (거래량, color follows candle direction)
            Returns PNG bytes (width=1600, height=900, dpi=100 고정).
            Note: bbox_inches="tight" 로 인해 출력 px 는 근사치 (기존 동작 유지).

        fmt="html":
            Returns self-contained interactive lightweight-charts HTML str.
            visualization→dgt import (forward direction — ADR 0008 D9 / ADR 0009 D9).
            Graceful degradation: artifacts=None → chart without grid levels.

        Args:
            bars: 전체 기간 OHLCV (정렬 무관 — 본 함수 내 sort).
            trades: 전체 기간 trades (TradeView).
            artifacts: DGT-specific sidecar. None 또는 non-DGT 타입이면
                캔들 + trade markers 만 (graceful degradation).
            fmt: "png" (기본값) 또는 "html" (ADR 0016 Option iii).

        Returns:
            fmt="png" → bytes. fmt="html" → str.

        Raises:
            ValueError: bars 가 비어 있는 경우.
        """
        if fmt == "html":
            return self._render_interactive(bars, trades, artifacts)

        # fmt == "png" — existing matplotlib path (behavior byte-identical)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, _axes = self._build_render_figure(bars, trades, artifacts)
        try:
            buf = io.BytesIO()
            fig.savefig(
                buf, format="png", dpi=_FIGURE_DPI, bbox_inches="tight",
            )
            return buf.getvalue()
        finally:
            plt.close(fig)

    def _render_interactive(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = None,
    ) -> str:
        """Build self-contained interactive HTML (fmt="html" dispatch).

        visualization→dgt forward import (build_interactive_chart_html) is the
        ALLOWED direction per check_namespace.sh:58-68 (same as _candles import).
        Graceful degradation: artifacts=None → no grid levels.
        """
        if not bars:
            raise ValueError("bars is empty")

        sorted_bars = sorted(bars, key=lambda b: b.trade_date)
        date_set = {b.trade_date.strftime("%Y-%m-%d") for b in sorted_bars}

        ohlcv = _serialize_ohlcv(sorted_bars)
        volume = _serialize_volume(sorted_bars)

        # Serialize trades — TradeView uses timestamp (datetime), _serialize_markers
        # uses trade_date (date).  Adapt via a duck-typed wrapper.
        class _TradeAdapter:
            def __init__(self, tv: Any) -> None:
                self._tv = tv

            @property
            def trade_date(self) -> Any:
                return self._tv.timestamp.date()

            @property
            def side(self) -> str:
                return str(self._tv.side)

            @property
            def grid_level_price(self) -> Any:
                return self._tv.price

        adapted_trades = [_TradeAdapter(t) for t in trades]
        markers = _serialize_markers(adapted_trades, date_set)

        # Grid levels from artifacts (duck-typed — no reverse import).
        # _DGTVisualizationArtifacts has grid_history / reference_price_curve;
        # we reconstruct a simple duck-type with grid_levels + reference_price.
        grid_lines: list[dict[str, Any]] = []
        if artifacts is not None and isinstance(artifacts, _DGTVisualizationArtifacts):
            history = artifacts.grid_history
            ref_curve = artifacts.reference_price_curve

            class _ArtifactAdapter:
                grid_levels = [lv for snap in history[:1] for lv in snap.levels] if history else []
                reference_price = ref_curve[0][1] if ref_curve else None

            grid_lines = _serialize_grid_levels(_ArtifactAdapter())

        # Derive title from artifacts or generic fallback.
        if artifacts is not None and isinstance(artifacts, _DGTVisualizationArtifacts):
            first_date = sorted_bars[0].trade_date
            last_date = sorted_bars[-1].trade_date
            title = f"DGT — {artifacts.asset_code} ({first_date} → {last_date})"
        else:
            first_date = sorted_bars[0].trade_date
            last_date = sorted_bars[-1].trade_date
            title = f"DGT — ({first_date} → {last_date})"

        return build_interactive_chart_html(
            title=title,
            ohlcv=ohlcv,
            volume=volume,
            markers=markers,
            grid_levels=grid_lines,
        )

    def extract_overlay_metric(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = None,
    ) -> _OverlayPayload:
        """Comparison-mode overlay 입력 추출 (ADR 0009 §1.3 D6 공통 축).

        공통 축 정의 (BacktestResult ↔ _DGTBacktestResult 매핑):
            - `time_series`     : bar.trade_date 를 UTC midnight datetime 으로.
            - `pnl_cumulative`  : 누적 cash-flow + 평가손익. costs (수수료/세금)
                                  포함 X — TradeView 시그니처 정합 한계.
                                  cross-strategy 비교 목적 상 일관 가정.
            - `drawdown`        : pnl - running_peak_pnl (≤ 0).

        공식:
            cum_cash_delta_t = Σ (BUY: -price·qty, SELL: +price·qty) up to t
            holdings_t       = Σ (BUY: +qty, SELL: -qty) up to t
            pnl_t            = cum_cash_delta_t + holdings_t · close_t
            peak_t           = max(pnl_0 ... pnl_t)
            drawdown_t       = pnl_t - peak_t

        Args:
            bars: 전체 기간 OHLCV (정렬 무관).
            trades: 전체 기간 trades.
            artifacts: 미사용 (현 runner = 고정 reference). Protocol
                시그니처 정합 위해 파라미터 유지.

        Returns:
            `_OverlayPayload` — strategy_id = "dgt" 박제.
        """
        if not bars:
            return _OverlayPayload(
                time_series=[],
                pnl_cumulative=[],
                drawdown=[],
                strategy_id=self.strategy_id,
            )

        sorted_bars = sorted(bars, key=lambda b: b.trade_date)
        sorted_trades = sorted(trades, key=lambda t: t.timestamp)

        trades_by_date: dict[date, list[TradeView]] = {}
        for t in sorted_trades:
            trades_by_date.setdefault(t.timestamp.date(), []).append(t)

        time_series: list[datetime] = []
        pnl_series: list[Decimal] = []
        drawdown_series: list[Decimal] = []

        cum_cash_delta = Decimal("0")
        holdings = Decimal("0")
        peak = Decimal("0")
        first_pnl = True

        for bar in sorted_bars:
            for trade in trades_by_date.get(bar.trade_date, []):
                notional = trade.price * trade.quantity
                if trade.side == "BUY":
                    holdings += trade.quantity
                    cum_cash_delta -= notional
                else:
                    holdings -= trade.quantity
                    cum_cash_delta += notional
            pnl = cum_cash_delta + holdings * bar.close
            if first_pnl or pnl > peak:
                peak = pnl
                first_pnl = False
            drawdown = pnl - peak

            ts = datetime(
                bar.trade_date.year,
                bar.trade_date.month,
                bar.trade_date.day,
                tzinfo=UTC,
            )
            time_series.append(ts)
            pnl_series.append(pnl)
            drawdown_series.append(drawdown)

        return _OverlayPayload(
            time_series=time_series,
            pnl_cumulative=pnl_series,
            drawdown=drawdown_series,
            strategy_id=self.strategy_id,
        )

    def _draw_grid_envelope(
        self,
        ax: object,
        artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """Grid envelope overlay — 고정 grid (단일 snapshot) 시 axhline,
        시간 가변 (다중 snapshot) 시 step-wise upper/lower band.

        현 0.11.a/0.11.b runner = 고정 reference (ohlcv[0].close) → 보통
        단일 snapshot. 미래 re-anchor 시 다중 snapshot.
        """
        history = artifacts.grid_history
        if not history:
            return
        first = history[0]
        for idx, level in enumerate(first.levels):
            ax.axhline(  # type: ignore[attr-defined]
                y=float(level),
                color=_COLOR_GRID_LINE,
                linestyle="--",
                linewidth=0.6,
                alpha=0.55,
                label="grid levels" if idx == 0 else None,
            )
        if len(history) > 1:
            ts_list = [s.timestamp for s in history]
            upper = [float(max(s.levels)) for s in history]
            lower = [float(min(s.levels)) for s in history]
            ax.fill_between(  # type: ignore[attr-defined]
                ts_list, lower, upper,
                color=_COLOR_GRID_BAND, alpha=0.18, step="post",
                label="grid envelope",
            )

    def _draw_reference_price(
        self,
        ax: object,
        artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """Reference price curve overlay.

        단일 entry (현 runner) → axhline; 다중 entry (미래 re-anchor) →
        step plot.
        """
        curve = artifacts.reference_price_curve
        if not curve:
            return
        if len(curve) == 1:
            _, ref = curve[0]
            ax.axhline(  # type: ignore[attr-defined]
                y=float(ref),
                color=_COLOR_REFERENCE,
                linestyle="-",
                linewidth=1.0,
                label=f"reference {float(ref):.2f}",
            )
        else:
            ts_list = [t for t, _ in curve]
            ref_list = [float(r) for _, r in curve]
            ax.step(  # type: ignore[attr-defined]
                ts_list, ref_list,
                where="post",
                color=_COLOR_REFERENCE,
                linewidth=1.0,
                label="reference",
            )

    def _draw_trade_markers(
        self,
        ax: object,
        trades: Sequence[TradeView],
        date_set: set[date],
    ) -> None:
        """BUY/SELL scatter markers — trade.price 위치.

        Side 별 단일 scatter 호출 (legend label 중복 회피).
        """
        buy_x: list[date] = []
        buy_y: list[float] = []
        sell_x: list[date] = []
        sell_y: list[float] = []
        for trade in trades:
            td = trade.timestamp.date()
            if td not in date_set:
                continue
            if trade.side == "BUY":
                buy_x.append(td)
                buy_y.append(float(trade.price))
            elif trade.side == "SELL":
                sell_x.append(td)
                sell_y.append(float(trade.price))
        if buy_x:
            ax.scatter(  # type: ignore[attr-defined]
                buy_x, buy_y,
                marker="^", color=_COLOR_BUY, s=40,
                label=f"BUY ({len(buy_x)})", zorder=5,
            )
        if sell_x:
            ax.scatter(  # type: ignore[attr-defined]
                sell_x, sell_y,
                marker="v", color=_COLOR_SELL, s=40,
                label=f"SELL ({len(sell_x)})", zorder=5,
            )

    def _apply_title(
        self,
        ax: object,
        first_date: date,
        last_date: date,
        artifacts: _VisualizationArtifacts | None,
        cjk_fontprop: object | None,
    ) -> None:
        """Chart title — asset_code + period + DGT 파라미터 (있으면).

        artifacts 가 `_DGTVisualizationArtifacts` 이면 asset_code +
        parameter_config (n/k/m) 박제, 아니면 generic title.
        """
        if isinstance(artifacts, _DGTVisualizationArtifacts):
            cfg = artifacts.parameter_config
            param_str = self._format_parameter_config(cfg)
            title = (
                f"DGT — {artifacts.asset_code} "
                f"({first_date} → {last_date})"
            )
            if param_str:
                title = f"{title} [{param_str}]"
        else:
            title = f"DGT — ({first_date} → {last_date})"
        if cjk_fontprop is not None:
            ax.set_title(  # type: ignore[attr-defined]
                title, fontproperties=cjk_fontprop,
            )
        else:
            ax.set_title(title)  # type: ignore[attr-defined]

    def _format_parameter_config(self, cfg: dict[str, object]) -> str:
        """n / k / m 파라미터 박제 (없으면 빈 문자열).

        Decimal 값은 `str()` 으로 정확히 직렬화 — float 미경유.
        """
        parts: list[str] = []
        for key in ("n", "k", "m"):
            if key in cfg:
                parts.append(f"{key}={cfg[key]}")
        return ", ".join(parts)
