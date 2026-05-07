"""Episode chart adapter (Phase 0.10 — ADR 0006 §6).

mplfinance 기반 정적 PNG 차트 — 캔들 + 이동평균 + 매매 마커 + 거래량.

ADR §6.2 spec:
- 상단: OHLC 캔들 + MA20 / MA60 (조건부) + 매매 마커 (renderer)
- 중단: 거래량
- 하단: episode 강조 (peak / trough / recovery vlines)

색상 정책:
- 캔들 상승 = 빨강 (KR 표준), 하락 = 파랑 (KR 표준)
- 마커 = renderer.marker_style (strategy-agnostic)
- vlines = peak (green) / trough (red) / recovery (blue) 점선

신규 의존성: ``[project.optional-dependencies] reporting``
(matplotlib / mplfinance / pandas). 핵심 백테스트는 의존성 zero —
``uv run --extra reporting trading report ...``
"""
from __future__ import annotations

import io
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.application.reporting.episode import DrawdownEpisode
    from src.application.reporting.trade_view import TradeView
    from src.domain.models import OHLCV
    from src.ports.strategy_renderer import StrategyRenderer


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
    # External deps imported lazily — 핵심 백테스트는 본 의존성 zero
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend (no display)
    import mplfinance as mpf
    import pandas as pd

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

    # Trade markers — group by (color, marker, size)
    addplots = []
    by_style: dict[
        tuple[str, str, int], list[tuple[pd.Timestamp, float]]
    ] = {}
    for trade in trades:
        td = pd.Timestamp(trade.timestamp.date())
        if td not in df.index:
            continue
        style = renderer.marker_style(trade)
        key = (style.color, style.marker, style.size)
        by_style.setdefault(key, []).append((td, float(trade.price)))

    for (color, marker, size), points in by_style.items():
        series = pd.Series(index=df.index, dtype=float)
        for ts, price in points:
            series[ts] = price
        # mplfinance scatter — markersize is area (size**2 approx)
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

    def _add_vline(d, c: str) -> None:
        if window_start <= d <= window_end:
            vline_dates.append(d.isoformat())
            vline_colors.append(c)

    _add_vline(episode.peak_date, "green")
    _add_vline(episode.trough_date, "red")
    if episode.recovered and episode.recovery_date is not None:
        _add_vline(episode.recovery_date, "blue")

    # MA selection — adapt to window length
    if len(df) >= 60:
        mav: tuple[int, ...] | None = (20, 60)
    elif len(df) >= 20:
        mav = (20,)
    else:
        mav = None

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

    buf = io.BytesIO()
    plot_kwargs: dict = {
        "type": "candle",
        "style": style,
        "volume": True,
        "savefig": {"fname": buf, "format": "png", "dpi": 100,
                    "bbox_inches": "tight"},
        "title": title,
    }
    if addplots:
        plot_kwargs["addplot"] = addplots
    if mav is not None:
        plot_kwargs["mav"] = mav
    if vline_dates:
        plot_kwargs["vlines"] = {
            "vlines": vline_dates,
            "colors": vline_colors,
            "linestyle": "--",
            "linewidths": 1.0,
        }

    mpf.plot(df, **plot_kwargs)
    return buf.getvalue()
