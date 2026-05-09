"""Episode chart adapter (Phase 0.10 — ADR 0006 §6, Phase 0.10.y §15).

mplfinance 기반 정적 PNG 차트 — 캔들 + 이동평균 + 매매 마커 + 거래량 +
**범례 (Phase 0.10.y)**.

ADR §6.2 spec:
- 상단: OHLC 캔들 + MA20 / MA60 (조건부) + 매매 마커 (renderer)
- 중단: 거래량
- 하단: episode 강조 (peak / trough / recovery vlines)

Phase 0.10.y 추가 (ADR §15.1 paraded):
- 범례 (Korean labels): 상승/하락, MA20/MA60 (조건부), 고점/저점/회복,
  매수/매도 (data-driven from MarkerStyle.label set actually emitted)
- ``returnfig=True`` 로 전환, 명시적 ``fig.savefig`` (D6) +
  layout-regression assertion ``len(fig.axes) >= 3`` (AC9)
- ``by_style`` key 가 `trade.side` 포함 — 라벨 문자열 파싱 미사용 (D1)

색상 정책:
- 캔들 상승 = 빨강 (KR 표준), 하락 = 파랑 (KR 표준)
- 마커 face = renderer.marker_style (strategy-agnostic)
- vlines = peak (green) / trough (red) / recovery (blue) 점선

신규 의존성: ``[project.optional-dependencies] reporting``
(matplotlib / mplfinance / pandas). 핵심 백테스트는 의존성 zero —
``uv run --extra reporting trading report ...``
"""
from __future__ import annotations

import io
import re
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.application.reporting.episode import DrawdownEpisode
    from src.application.reporting.trade_view import TradeView
    from src.domain.models import OHLCV
    from src.ports.strategy_renderer import StrategyRenderer


_PREFIX_NUM_RE = re.compile(r"^(.+?)(\d+)$")


def _summarize_labels(labels: Sequence[str]) -> str:
    """Strategy-neutral legend phrasing (Phase 0.10.y §15.1, regex pinned).

    Decision rules (regex ``r"^(.+?)(\\d+)$"`` — greedy prefix capture +
    numeric suffix capture):

    - **No labels** → ``""`` (caller should omit the row entirely).
    - **Single label** → that label literal (e.g. ``"B"`` for
      DefaultRenderer; ``"B3"`` if SevenSplit only emitted slot 3).
    - **All labels share the same prefix AND have integer suffixes that
      are contiguous from N..M** → range form ``"B1~B7"``.
    - **All labels share the same prefix BUT integer suffixes are NOT
      contiguous** (e.g. ``B1, B3, B5``) → comma list ``"B1, B3, B5"``
      (NOT ``"B1~B5"``).
    - **Labels do NOT share a prefix OR don't match the regex** (e.g.
      ``BUY1, BREAKOUT_2``; or same prefix but suffixes 20/40/60) →
      comma list of input labels in input order.
    - Comma list capped at first 5 + ``"…"`` (defensive for hypothetical
      strategies with many labels).
    """
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]

    parsed = [(_PREFIX_NUM_RE.match(label), label) for label in labels]
    if all(m is not None for m, _ in parsed):
        prefixes = {m.group(1) for m, _ in parsed}  # type: ignore[union-attr]
        if len(prefixes) == 1:
            nums = sorted(int(m.group(2))  # type: ignore[union-attr]
                          for m, _ in parsed)
            if nums == list(range(nums[0], nums[-1] + 1)):
                prefix = next(iter(prefixes))
                return f"{prefix}{nums[0]}~{prefix}{nums[-1]}"

    items = list(labels)
    if len(items) > 5:
        items = items[:5] + ["…"]
    return ", ".join(items)


def render_episode_chart(
    episode: DrawdownEpisode,
    ohlcv_bars: Sequence[OHLCV],
    trades: Sequence[TradeView],
    renderer: StrategyRenderer,
    *,
    chart_window_pad_days: int = 10,
) -> bytes:
    """Episode 구간 차트 PNG 생성 — bytes 반환.

    Args:
        episode: DrawdownEpisode 분석 결과
        ohlcv_bars: 차트 그릴 OHLCV (전체 또는 episode 구간 + 패딩 포함).
            Episode window (peak_date - pad ~ recovery_date or end + pad)
            로 자동 필터링.
        trades: 차트에 표시할 매매 기록 (전체). episode window 내만 표시.
        renderer: StrategyRenderer 구현체 — marker_style 호출
        chart_window_pad_days: episode 양 끝 padding (default 10 calendar days)

    Returns:
        PNG bytes (in-memory).

    Raises:
        ValueError: ohlcv_bars 빈 경우 또는 window 내 bars 없는 경우.
    """
    import matplotlib.pyplot as plt

    fig, _axes = _build_figure(
        episode, ohlcv_bars, trades, renderer,
        chart_window_pad_days=chart_window_pad_days,
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _build_figure(
    episode: DrawdownEpisode,
    ohlcv_bars: Sequence[OHLCV],
    trades: Sequence[TradeView],
    renderer: StrategyRenderer,
    *,
    chart_window_pad_days: int = 10,
):
    """Build matplotlib Figure + axes (no savefig). Test-friendly internal.

    Returns:
        (fig, axes) — caller saves and closes.

    Raises:
        ValueError: ohlcv_bars empty or no bars in episode window.
        AssertionError: layout regression (fig.axes < 3) — AC9.
    """
    # External deps imported lazily — 핵심 백테스트는 본 의존성 zero
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend (no display)
    import mplfinance as mpf
    import pandas as pd
    from matplotlib import font_manager
    from matplotlib.font_manager import FontProperties
    from matplotlib.lines import Line2D

    # Korean glyph fallback — pick first CJK font present on the system.
    # We apply this via FontProperties on individual Text elements (legend,
    # title) AFTER mpf.plot, since mpf's internal style override fights
    # rcParams setters. None present → Korean renders as boxes (PNG visual
    # only); test assertions still pass.
    _cjk_candidates = (
        "AppleGothic", "Apple SD Gothic Neo", "Noto Sans CJK KR",
        "Nanum Gothic", "Malgun Gothic",
    )
    available = {f.name for f in font_manager.fontManager.ttflist}
    cjk_font: str | None = next(
        (name for name in _cjk_candidates if name in available), None,
    )
    cjk_fontprop = FontProperties(family=cjk_font) if cjk_font else None

    if not ohlcv_bars:
        raise ValueError("ohlcv_bars is empty")

    # Sort + filter to chart window
    sorted_bars = sorted(ohlcv_bars, key=lambda b: b.trade_date)
    pad = timedelta(days=chart_window_pad_days)
    window_start = episode.peak_date - pad
    window_end_anchor = (
        episode.recovery_date if episode.recovered and episode.recovery_date
        else sorted_bars[-1].trade_date
    )
    window_end = window_end_anchor + pad

    bars_in_window = [
        b for b in sorted_bars
        if window_start <= b.trade_date <= window_end
    ]
    if not bars_in_window:
        raise ValueError(
            f"No OHLCV bars in episode window "
            f"[{window_start}, {window_end}]"
        )

    # Build DataFrame
    df = pd.DataFrame(
        {
            "Open": [float(b.open) for b in bars_in_window],
            "High": [float(b.high) for b in bars_in_window],
            "Low": [float(b.low) for b in bars_in_window],
            "Close": [float(b.close) for b in bars_in_window],
            "Volume": [float(b.volume) for b in bars_in_window],
        },
        index=pd.DatetimeIndex([b.trade_date for b in bars_in_window]),
    )

    # Trade markers — group by (side, color, marker, size, label) to keep
    # side-aware grouping without parsing label strings (D1).
    addplots = []
    by_style: dict[
        tuple[str, str, str, int, str],
        list[tuple[pd.Timestamp, float]],
    ] = {}
    # Side → label set (preserves first-seen order via dict insertion order)
    labels_by_side: dict[str, list[str]] = {"BUY": [], "SELL": []}
    seen_labels: dict[str, set[str]] = {"BUY": set(), "SELL": set()}
    for trade in trades:
        td = pd.Timestamp(trade.timestamp.date())
        if td not in df.index:
            continue
        style = renderer.marker_style(trade)
        key = (trade.side, style.color, style.marker, style.size, style.label)
        by_style.setdefault(key, []).append((td, float(trade.price)))
        if trade.side in labels_by_side and style.label not in seen_labels[
            trade.side
        ]:
            seen_labels[trade.side].add(style.label)
            labels_by_side[trade.side].append(style.label)

    for (_side, color, marker, size, _label), points in by_style.items():
        series = pd.Series(index=df.index, dtype=float)
        for ts, price in points:
            series[ts] = price
        addplots.append(
            mpf.make_addplot(
                series,
                type="scatter",
                marker=marker,
                color=color,
                markersize=size * size,
            )
        )

    # vlines — peak / trough / recovery (if in window)
    vline_dates: list[str] = []
    vline_colors: list[str] = []
    vline_in_window: dict[str, bool] = {
        "peak": False, "trough": False, "recovery": False,
    }

    def _add_vline(d, c: str, kind: str) -> None:
        if window_start <= d <= window_end:
            vline_dates.append(d.isoformat())
            vline_colors.append(c)
            vline_in_window[kind] = True

    _add_vline(episode.peak_date, "green", "peak")
    _add_vline(episode.trough_date, "red", "trough")
    if episode.recovered and episode.recovery_date is not None:
        _add_vline(episode.recovery_date, "blue", "recovery")

    # MA selection — computed from FULL sorted_bars (pre-window included)
    # so MA lines cover the entire visible window without leading-NaN gap.
    # User feedback (Phase 0.10.y.d): MA20/MA60 must span full chart range.
    full_close = pd.Series(
        [float(b.close) for b in sorted_bars],
        index=pd.DatetimeIndex([b.trade_date for b in sorted_bars]),
    )
    candidate_periods: list[int] = []
    if len(sorted_bars) >= 60:
        candidate_periods = [20, 60]
    elif len(sorted_bars) >= 20:
        candidate_periods = [20]
    ma_palette = ("#1f77b4", "#ff7f0e")  # blue, orange
    ma_addplots = []
    ma_periods: list[int] = []
    for idx, n in enumerate(candidate_periods):
        ma_full = full_close.rolling(window=n, min_periods=n).mean()
        ma_window = ma_full.reindex(df.index)
        # Skip periods that have no valid values in the displayed window
        # (e.g. MA60 when the window starts before bar 60 of sorted_bars).
        if ma_window.notna().any():
            ma_addplots.append(
                mpf.make_addplot(
                    ma_window,
                    color=ma_palette[idx % len(ma_palette)],
                    width=1.5,
                )
            )
            ma_periods.append(n)
    # Combine MA addplots with trade marker addplots
    addplots = ma_addplots + addplots

    # Style — KR convention (up=red, down=blue)
    style = mpf.make_mpf_style(
        marketcolors=mpf.make_marketcolors(
            up="red", down="blue", edge="inherit", wick="inherit",
            volume="inherit",
        ),
        gridstyle="--",
    )

    asset_label = episode.asset_code or "(portfolio)"
    title = (
        f"{asset_label} — peak {episode.peak_date} → trough "
        f"{episode.trough_date} (drawdown {episode.drawdown_pct:+.4f}%)"
    )

    plot_kwargs: dict = {
        "type": "candle",
        "style": style,
        "volume": True,
        "title": title,
        "returnfig": True,
    }
    if addplots:
        plot_kwargs["addplot"] = addplots
    if vline_dates:
        plot_kwargs["vlines"] = {
            "vlines": vline_dates,
            "colors": vline_colors,
            "linestyle": "--",
            "linewidths": 1.0,
        }

    fig, axes = mpf.plot(df, **plot_kwargs)

    # Layout-regression assertion (AC9) — price + volume + (panel/spacer)
    assert len(fig.axes) >= 3, (
        f"chart layout regression: expected >= 3 axes "
        f"(price + volume + panel), got {len(fig.axes)}"
    )

    # Build manual legend on the price axis. Manual proxies are the
    # SOLE source of truth — passing both `handles` and `labels` to
    # ax.legend overrides any mpf-emitted handles (mav dedup).
    # User feedback (Phase 0.10.y.d): 상승/하락 entries removed (KR
    # red/blue candle convention is implicit, redundant in legend).
    proxies: list[Line2D] = []
    # MA proxies — only when actually drawn
    for idx, n in enumerate(ma_periods):
        proxies.append(
            Line2D([0], [0], color=ma_palette[idx % len(ma_palette)],
                   linewidth=1.5, label=f"MA{n}")
        )
    # vline proxies — only when within window
    if vline_in_window["peak"]:
        proxies.append(
            Line2D([0], [0], color="green", linestyle="--", linewidth=1.0,
                   label="고점")
        )
    if vline_in_window["trough"]:
        proxies.append(
            Line2D([0], [0], color="red", linestyle="--", linewidth=1.0,
                   label="저점")
        )
    if vline_in_window["recovery"]:
        proxies.append(
            Line2D([0], [0], color="blue", linestyle="--", linewidth=1.0,
                   label="회복")
        )
    # Side reps — data-driven from observed MarkerStyle.label sets.
    # User feedback (Phase 0.10.y.d): 매수=빨강, 매도=초록 swatch
    # (legend representative only; actual chart marker face stays slot
    # palette per §4.3.1). Swatch matches KR-rising-positive intuition.
    buy_summary = _summarize_labels(labels_by_side["BUY"])
    if buy_summary:
        proxies.append(
            Line2D([0], [0], marker="^", color="w",
                   markerfacecolor="#d62728", markeredgecolor="#d62728",
                   markersize=10, label=f"매수 ({buy_summary})")
        )
    sell_summary = _summarize_labels(labels_by_side["SELL"])
    if sell_summary:
        proxies.append(
            Line2D([0], [0], marker="v", color="w",
                   markerfacecolor="#2ca02c", markeredgecolor="#2ca02c",
                   markersize=10, label=f"매도 ({sell_summary})")
        )

    legend = axes[0].legend(
        handles=proxies,
        labels=[p.get_label() for p in proxies],
        loc="upper left",
        fontsize=8,
        framealpha=0.85,
        ncol=2,
    )

    # Korean font fallback — apply FontProperties to legend texts and title.
    # mpf's style hardcodes font.family at axes level; per-Text override
    # is the reliable path.
    if cjk_fontprop is not None:
        for txt in legend.get_texts():
            txt.set_fontproperties(cjk_fontprop)
        # Title — mpf sets it via fig.suptitle or axes.set_title
        title_obj = axes[0].get_title()
        if title_obj:
            axes[0].set_title(title_obj, fontproperties=cjk_fontprop)
        if fig._suptitle is not None:
            fig._suptitle.set_fontproperties(cjk_fontprop)

    return fig, axes
