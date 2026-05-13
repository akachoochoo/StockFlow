"""Phase 0.11.c.3 — `_DGTVisualizationRenderer` 구현 (ADR 0009 §1.8 sub-step 0.11.c.3).

DGT-specific full-period chart (close price line + grid envelope band +
reference price horizontal line + BUY/SELL trade markers) + comparison
mode overlay metric (time + cumulative P&L + drawdown).

ADR 0009 §1.3 정합:
- D2 (d) — `_VisualizationRenderer` Protocol (`_visualization_renderer.py`)
  structural typing 구현.
- D3 pattern B — `_DGTVisualizationArtifacts` sidecar 입력 (`_artifacts.py`).
  `BacktestResult` / `_DGTBacktestResult` 스키마 침범 zero.
- D4 (a) — matplotlib only (mplfinance 미사용 — DGT 는 캔들 미필요,
  close line + envelope 합성 chart 본질).
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
from typing import TYPE_CHECKING, ClassVar

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

    def render_full_period(
        self,
        bars: Sequence[OHLCV],
        trades: Sequence[TradeView],
        artifacts: _VisualizationArtifacts | None = None,
    ) -> bytes:
        """Full-period chart PNG bytes 산출 (ADR 0009 §1.3 D5).

        Layout:
            - close price line (전체 기간 close 곡선)
            - grid envelope band (artifacts.grid_history 첫 snapshot 의
              levels horizontal lines + 시간 가변 시 fill_between band)
            - reference price horizontal line (artifacts.reference_price_curve
              단일 entry → axhline, 다중 → step plot)
            - BUY/SELL scatter markers (`trade.price` 위치)

        Args:
            bars: 전체 기간 OHLCV (정렬 무관 — 본 함수 내 sort).
            trades: 전체 기간 trades (TradeView). 본 chart 는 bar 의
                trade_date 매칭만 사용 — episode window filtering 없음.
            artifacts: DGT-specific sidecar. None 또는 non-DGT 타입이면
                close line + trade markers 만 (graceful degradation).

        Returns:
            PNG bytes (width=1600, height=900, dpi=100 고정).

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
        closes: list[float] = [float(b.close) for b in sorted_bars]
        date_set = set(dates)

        available_fonts = {f.name for f in font_manager.fontManager.ttflist}
        cjk_font = next(
            (name for name in _CJK_CANDIDATES if name in available_fonts),
            None,
        )
        cjk_fontprop = FontProperties(family=cjk_font) if cjk_font else None

        fig_w_in = _FIGURE_WIDTH_PX / _FIGURE_DPI
        fig_h_in = _FIGURE_HEIGHT_PX / _FIGURE_DPI
        fig, ax = plt.subplots(
            figsize=(fig_w_in, fig_h_in), dpi=_FIGURE_DPI,
        )
        try:
            ax.plot(dates, closes, color=_COLOR_CLOSE, linewidth=1.2, label="Close")  # type: ignore[arg-type]

            if isinstance(artifacts, _DGTVisualizationArtifacts):
                self._draw_grid_envelope(ax, artifacts)
                self._draw_reference_price(ax, artifacts)

            self._draw_trade_markers(ax, trades, date_set)

            self._apply_title(ax, dates[0], dates[-1], artifacts, cjk_fontprop)
            ax.set_xlabel("date")
            ax.set_ylabel("price")
            legend = ax.legend(loc="upper left", fontsize=8, framealpha=0.85)
            if cjk_fontprop is not None and legend is not None:
                for txt in legend.get_texts():
                    txt.set_fontproperties(cjk_fontprop)

            fig.autofmt_xdate()
            buf = io.BytesIO()
            fig.savefig(
                buf, format="png", dpi=_FIGURE_DPI, bbox_inches="tight",
            )
            return buf.getvalue()
        finally:
            plt.close(fig)

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
