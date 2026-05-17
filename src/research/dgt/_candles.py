# Phase 0.11.h — Shared candlestick + volume drawing helpers.
#
# ADR 0015 Option A synthesis: one manual-drawing helper used by BOTH
# `kakao_dgt_backtest.py` (dgt/) and `_dgt_renderer.py` (visualization/).
# visualization→dgt import is ALLOWED by check_namespace.sh (outer→inner read).
# dgt→visualization is FORBIDDEN — these helpers live in dgt/ for that reason.
#
# KR convention: up-day (close >= open) = red, down-day = blue.
# Decimal→float conversion happens ONLY at the plotting boundary inside these
# functions — values stay Decimal throughout the domain (CLAUDE.md §2.1 / §15).
#
# Figure-leak responsibility: callers own the figure and must call plt.close(fig)
# in a try/finally block. These helpers draw onto a caller-owned ax and do NOT
# create or close figures (P4 / ADR 0015 R5).
#
# Density note (DD3): candle width = median inter-bar spacing * width_frac.
# For ~1250 daily bars over 5 years this yields thin-but-distinct candles.
# At >~2000 bars candles visually merge — acceptable for research tooling;
# no resampling/aggregation is added here (would change data semantics, ADR 0015).

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class _HasOHLCV(Protocol):
    """Structural protocol for OHLCV-duck-typed bars (avoids domain import)."""
    trade_date: Any
    open: Any
    high: Any
    low: Any
    close: Any
    volume: Any


__all__: list[str] = []

# Up/down color palette — KR convention (up=red, down=blue).
_COLOR_UP = "#e74c3c"
_COLOR_DOWN = "#3498db"
_COLOR_UP_EDGE = "#c0392b"
_COLOR_DOWN_EDGE = "#2980b9"

# Minimum candle body height in price units to avoid zero-height bars
# (doji candles where open == close).
_BODY_EPSILON = 1e-8


def _draw_candles(ax: Any, bars: Sequence[Any], *, width_frac: float = 0.6) -> None:
    """Draw OHLC candlestick bars onto *ax* using matplotlib primitives.

    Parameters
    ----------
    ax:
        A matplotlib ``Axes`` instance. x-axis is expected to be a date axis
        (matplotlib internally uses ``date2num`` float values for dates).
        Typed as ``Any`` because matplotlib does not ship PEP 561 stubs.
    bars:
        Sequence of ``OHLCV`` domain objects.  Each bar must have:
        ``trade_date: date``, ``open/high/low/close: Decimal``, ``volume: Decimal``.
        ``Sequence[Any]`` (covariant) so callers can pass ``list[OHLCV]`` directly.
    width_frac:
        Fraction of the median inter-bar spacing used as the candle body width.
        Default 0.6 yields distinct candles at ~1250-bar (5y daily) scale.

    Decimal→float boundary
    ----------------------
    ``open``, ``high``, ``low``, ``close`` are converted from ``Decimal`` to
    ``float`` here — the ONLY place where that conversion occurs per CLAUDE.md §2.1.

    date2num requirement
    --------------------
    ``matplotlib.dates.date2num`` converts Python ``date`` / ``datetime`` objects to
    the float offset (days since 0001-01-01) that matplotlib uses internally for its
    date axis.  ``ax.bar`` and ``ax.vlines`` both accept these floats directly and
    render them on the date axis without further conversion.
    """
    # Lazy import — same pattern as render functions in kakao_dgt_backtest.py.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import numpy as np

    if not bars:
        return

    # --- Convert to numeric arrays (Decimal→float boundary) ---
    # mdates.date2num: no PEP 561 stubs → type: ignore[no-untyped-call]
    dates_num = np.array(
        [mdates.date2num(b.trade_date) for b in bars]  # type: ignore[no-untyped-call]
    )
    opens  = np.array([float(b.open)  for b in bars])
    highs  = np.array([float(b.high)  for b in bars])
    lows   = np.array([float(b.low)   for b in bars])
    closes = np.array([float(b.close) for b in bars])

    # Candle width in date2num units (days).
    if len(dates_num) >= 2:
        spacing = float(np.median(np.diff(dates_num)))
    else:
        spacing = 1.0  # single-bar edge case
    width = spacing * width_frac

    # Up/down masks — KR convention: up (close >= open) = red, down = blue.
    up_mask = closes >= opens

    body_bottoms = np.minimum(opens, closes)
    body_heights = np.abs(closes - opens)
    # Replace zero-height doji bodies with a small epsilon so they remain visible.
    body_heights = np.where(body_heights == 0, _BODY_EPSILON, body_heights)

    up_x   = dates_num[up_mask]
    up_bot = body_bottoms[up_mask]
    up_h   = body_heights[up_mask]
    up_lo  = lows[up_mask]
    up_hi  = highs[up_mask]

    dn_x   = dates_num[~up_mask]
    dn_bot = body_bottoms[~up_mask]
    dn_h   = body_heights[~up_mask]
    dn_lo  = lows[~up_mask]
    dn_hi  = highs[~up_mask]

    # --- Wicks (vlines from low to high) — drawn first at zorder=1 ---
    if len(up_x):
        ax.vlines(up_x, up_lo, up_hi, color=_COLOR_UP, linewidth=0.6, zorder=1)
    if len(dn_x):
        ax.vlines(dn_x, dn_lo, dn_hi, color=_COLOR_DOWN, linewidth=0.6, zorder=1)

    # --- Bodies (bar rectangles) — drawn above wicks at zorder=2 ---
    if len(up_x):
        ax.bar(
            up_x, up_h, bottom=up_bot, width=width,
            color=_COLOR_UP, edgecolor=_COLOR_UP_EDGE,
            linewidth=0.3, zorder=2,
        )
    if len(dn_x):
        ax.bar(
            dn_x, dn_h, bottom=dn_bot, width=width,
            color=_COLOR_DOWN, edgecolor=_COLOR_DOWN_EDGE,
            linewidth=0.3, zorder=2,
        )


def _draw_volume(ax: Any, bars: Sequence[Any], *, width_frac: float = 0.6) -> None:
    """Draw a volume bar chart onto *ax* using matplotlib primitives.

    Parameters
    ----------
    ax:
        A matplotlib ``Axes`` instance on a shared x-axis with the price panel.
        Typed as ``Any`` because matplotlib does not ship PEP 561 stubs.
    bars:
        Same sequence of ``OHLCV`` domain objects passed to ``_draw_candles``.
        ``Sequence[Any]`` (covariant) so callers can pass ``list[OHLCV]`` directly.
    width_frac:
        Fraction of median inter-bar spacing used as bar width — should match
        the value passed to ``_draw_candles`` so widths are visually consistent.

    Color follows candle direction: up-day (close >= open) red, down-day blue,
    at alpha=0.5 for a lighter appearance.

    Decimal→float boundary
    ----------------------
    ``volume`` is converted from ``Decimal`` to ``float`` here.
    ``trade_date`` is converted via ``date2num`` (same as ``_draw_candles``).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import numpy as np

    if not bars:
        return

    # mdates.date2num: no PEP 561 stubs → type: ignore[no-untyped-call]
    dates_num = np.array(
        [mdates.date2num(b.trade_date) for b in bars]  # type: ignore[no-untyped-call]
    )
    volumes = np.array([float(b.volume) for b in bars])
    closes  = np.array([float(b.close)  for b in bars])
    opens   = np.array([float(b.open)   for b in bars])

    if len(dates_num) >= 2:
        spacing = float(np.median(np.diff(dates_num)))
    else:
        spacing = 1.0
    width = spacing * width_frac

    up_mask = closes >= opens
    colors_arr = [_COLOR_UP if u else _COLOR_DOWN for u in up_mask]

    ax.bar(dates_num, volumes, width=width, color=colors_arr, alpha=0.5, zorder=1)
