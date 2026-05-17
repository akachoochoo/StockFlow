# Phase 0.11.i — Interactive HTML chart builder for DGT backtest reports.
#
# Produces self-contained HTML using TradingView's lightweight-charts v5.2.0
# (vendored at src/research/dgt/assets/lightweight-charts.standalone.production.js).
#
# Design principles (ADR 0016):
#   P2 — Contained external dependency (JS runs only in the browser, never in Python).
#   P4 — Decimal→float conversion happens ONLY at the JSON-serialization boundary here.
#   P5 — Self-contained offline HTML (no CDN / network references).
#
# Namespace constraint (ADR 0008 D9 / ADR 0009 D9 / check_namespace.sh:58-68):
#   This file lives in src/research/dgt/ (NOT visualization/) so kakao_dgt_backtest.py
#   can import it intra-dgt (legal), and _dgt_renderer.py (visualization/) can import
#   it via the allowed forward direction (visualization→dgt).
#   MUST NOT import from src.research.visualization.* (reverse import = forbidden).
#
# Underscore-prefix private (ADR 0007 §1.6.3).

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any, Sequence

__all__: list[str] = []

# KR convention: up-day (close >= open) = red, down-day = blue — matches _candles.py.
_COLOR_UP = "#e74c3c"
_COLOR_DOWN = "#3498db"

_ASSETS_DIR = Path(__file__).parent / "assets"
_JS_FILENAME = "lightweight-charts.standalone.production.js"


# ---------------------------------------------------------------------------
# Asset loading
# ---------------------------------------------------------------------------

def _load_lightweight_charts_js() -> str:
    """Read the vendored lightweight-charts standalone JS from assets/.

    Single loading mechanism: Path(__file__).parent / "assets" / <filename>.
    No importlib.resources alternative — one path only (plan Step 2 / m3 fix).
    """
    js_path = _ASSETS_DIR / _JS_FILENAME
    return js_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Serialization helpers — Decimal→float boundary (P4)
# ---------------------------------------------------------------------------

def _serialize_ohlcv(bars: Sequence[Any]) -> list[dict[str, Any]]:
    """Serialize OHLCV bars to lightweight-charts candlestick data format.

    Each bar must have: trade_date (date), open/high/low/close (Decimal or float).
    Returns list of {time, open, high, low, close} dicts with float values.
    Decimal→float conversion happens ONLY here (P4 / CLAUDE.md §2.1).
    """
    result = []
    for bar in bars:
        result.append({
            "time": bar.trade_date.strftime("%Y-%m-%d"),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
        })
    return result


def _serialize_volume(bars: Sequence[Any]) -> list[dict[str, Any]]:
    """Serialize OHLCV bars to lightweight-charts volume histogram data format.

    Each bar must have: trade_date (date), volume (Decimal or float),
    open/close (Decimal or float) for direction coloring.
    KR convention: up-day (close >= open) = red, down-day = blue — matches _candles.py.
    """
    result = []
    for bar in bars:
        is_up = float(bar.close) >= float(bar.open)
        result.append({
            "time": bar.trade_date.strftime("%Y-%m-%d"),
            "value": float(bar.volume),
            "color": _COLOR_UP if is_up else _COLOR_DOWN,
        })
    return result


def _serialize_markers(
    trades: Sequence[Any],
    date_set: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Serialize DGT trades to lightweight-charts series markers.

    Each trade must have: trade_date (date), side (str "BUY" or "SELL"),
    grid_level_price (Decimal or float).

    BUY  → position:'belowBar', shape:'arrowUp',  color:'#27ae60' (green)
    SELL → position:'aboveBar', shape:'arrowDown', color:'#e74c3c' (red)

    date_set: optional set of "YYYY-MM-DD" strings for filtering to known bars.
    """
    markers = []
    for trade in trades:
        time_str = trade.trade_date.strftime("%Y-%m-%d")
        if date_set is not None and time_str not in date_set:
            continue
        if trade.side == "BUY":
            marker = {
                "time": time_str,
                "position": "belowBar",
                "shape": "arrowUp",
                "color": "#27ae60",
                "text": f"B@{float(trade.grid_level_price):,.0f}",
            }
        else:
            marker = {
                "time": time_str,
                "position": "aboveBar",
                "shape": "arrowDown",
                "color": "#e74c3c",
                "text": f"S@{float(trade.grid_level_price):,.0f}",
            }
        markers.append(marker)
    # lightweight-charts requires markers sorted by time ascending.
    markers.sort(key=lambda m: m["time"])
    return markers


def _serialize_grid_levels(artifacts: Any) -> list[dict[str, Any]]:
    """Serialize DGT grid level prices to lightweight-charts price-line descriptors.

    Accepts duck-typed input — does NOT import _DGTVisualizationArtifacts from
    src.research.visualization._artifacts (that would be a dgt→visualization reverse
    import, forbidden by check_namespace.sh:59-61).

    Expected duck-type shape (any object or dict with these attributes / keys):
      artifacts.grid_levels: list of Decimal/float — ordered grid price levels
      artifacts.reference_price: Decimal/float — DGT reference/anchor price

    If artifacts is None or lacks expected attributes, returns [].

    Returns list of {price, color, lineWidth, lineStyle, axisLabelVisible, title}
    dicts suitable for use as lightweight-charts price lines.
    """
    if artifacts is None:
        return []

    # Support both attribute access (dataclass) and dict access.
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    grid_levels = _get(artifacts, "grid_levels", [])
    reference_price = _get(artifacts, "reference_price", None)

    result: list[dict[str, Any]] = []

    if reference_price is not None:
        try:
            result.append({
                "price": float(reference_price),
                "color": "#f39c12",       # orange — reference anchor
                "lineWidth": 2,
                "lineStyle": 2,           # 2 = dashed in lightweight-charts
                "axisLabelVisible": True,
                "title": "ref",
            })
        except (TypeError, ValueError):
            pass

    for i, level in enumerate(grid_levels):
        try:
            result.append({
                "price": float(level),
                "color": "#bdc3c7",       # grey — grid levels
                "lineWidth": 1,
                "lineStyle": 1,           # 1 = dotted
                "axisLabelVisible": False,
                "title": f"g{i}",
            })
        except (TypeError, ValueError):
            continue

    return result


# ---------------------------------------------------------------------------
# JSON safety
# ---------------------------------------------------------------------------

def _safe_json_embed(obj: Any) -> str:
    """JSON-serialize obj for safe embedding inside a <script> block.

    Applies two escapes beyond json.dumps:
      1. Replace '</' with '<\\/' to prevent </script> tag breakout (m1 hardening).
      2. Escape U+2028 (LINE SEPARATOR) and U+2029 (PARAGRAPH SEPARATOR) which are
         valid JSON but terminate JS string literals in some engines.

    Never interpolates raw strings into JS code — all data goes through json.dumps.
    """
    serialized = json.dumps(obj, ensure_ascii=False)
    # Prevent </script> breakout.
    serialized = serialized.replace("</", "<\\/")
    # Escape JS-unsafe line terminators.
    serialized = serialized.replace(" ", "\\u2028")
    serialized = serialized.replace(" ", "\\u2029")
    return serialized


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_interactive_chart_html(
    *,
    title: str,
    ohlcv: list[dict[str, Any]],
    volume: list[dict[str, Any]],
    marker_groups: list[dict[str, Any]],
    grid_levels: list[dict[str, Any]],
    extra_panels: list[dict[str, Any]] | None = None,
) -> str:
    """Assemble a self-contained interactive HTML chart page.

    Embeds the vendored lightweight-charts JS and serializes all data into a
    <script type="application/json"> data island (safe for HTML embedding via
    _safe_json_embed).  No network references — entirely offline-openable (P5).

    Parameters
    ----------
    title:
        Page title / chart header.
    ohlcv:
        List of dicts from _serialize_ohlcv — candlestick data.
    volume:
        List of dicts from _serialize_volume — volume histogram data.
    marker_groups:
        List of {"label": str, "markers": [...]} dicts — per-strategy trade
        marker groups. When >1 group, per-strategy toggle checkboxes render
        above the chart; each toggle re-merges the visible marker set.
    grid_levels:
        List of dicts from _serialize_grid_levels — price lines.
    extra_panels:
        Reserved for future equity-curve / additional panes (unused in v1).
    """
    js_lib = _load_lightweight_charts_js()

    data_island = _safe_json_embed({
        "ohlcv": ohlcv,
        "volume": volume,
        "markerGroups": marker_groups,
        "gridLevels": grid_levels,
    })

    # Per-strategy marker toggle bar — rendered only when >1 group
    # (Phase 0.11.i follow-up: marker overcrowding fix).
    if len(marker_groups) > 1:
        _toggles = "".join(
            f'<label><input type="checkbox" data-grp="{i}" checked /> '
            f'{escape(str(g.get("label", f"group {i}")))}</label>'
            for i, g in enumerate(marker_groups)
        )
        marker_toggle_html = f'<div id="marker-toggles">{_toggles}</div>'
    else:
        marker_toggle_html = ""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ height: 100%; }}
    body {{ background: #1a1a2e; color: #eee; font-family: sans-serif;
            display: flex; flex-direction: column; overflow: hidden; }}
    h1 {{ flex: none; padding: 12px 16px; font-size: 14px; font-weight: 600;
          color: #a8b2d8; border-bottom: 1px solid #2d2d4e; }}
    #marker-toggles {{ flex: none; display: flex; gap: 14px; flex-wrap: wrap;
          padding: 6px 16px; font-size: 12px; color: #a8b2d8;
          border-bottom: 1px solid #2d2d4e; }}
    #marker-toggles label {{ cursor: pointer; user-select: none; }}
    #marker-toggles input {{ vertical-align: middle; margin-right: 4px; }}
    #chart-container {{
      flex: 1; min-height: 0;
      display: flex; flex-direction: column; width: 100%;
    }}
    #price-chart  {{ flex: 3; width: 100%; min-height: 0; }}
    #volume-chart {{ flex: 1; width: 100%; min-height: 0;
                     border-top: 1px solid #2d2d4e; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  {marker_toggle_html}
  <div id="chart-container">
    <div id="price-chart"></div>
    <div id="volume-chart"></div>
  </div>

  <!-- vendored lightweight-charts v5.2.0 (Phase 0.11.i ADR 0016) -->
  <script>
{js_lib}
  </script>

  <!-- chart data island — safe-embedded JSON, no raw string interpolation -->
  <script type="application/json" id="chart-data">
{data_island}
  </script>

  <script>
    (function () {{
      var rawData = JSON.parse(
        document.getElementById('chart-data').textContent
      );

      // --- Price chart ---
      var priceEl = document.getElementById('price-chart');
      var priceChart = LightweightCharts.createChart(priceEl, {{
        layout: {{
          background: {{ color: '#1a1a2e' }},
          textColor:  '#a8b2d8',
        }},
        grid: {{
          vertLines: {{ color: '#2d2d4e' }},
          horzLines: {{ color: '#2d2d4e' }},
        }},
        crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
        rightPriceScale: {{ borderColor: '#2d2d4e' }},
        timeScale: {{
          borderColor:     '#2d2d4e',
          timeVisible:     true,
          secondsVisible:  false,
        }},
        width:  priceEl.clientWidth,
        height: priceEl.clientHeight,
      }});

      var candleSeries = priceChart.addSeries(LightweightCharts.CandlestickSeries, {{
        upColor:         '{_COLOR_UP}',
        downColor:       '{_COLOR_DOWN}',
        borderUpColor:   '#c0392b',
        borderDownColor: '#2980b9',
        wickUpColor:     '{_COLOR_UP}',
        wickDownColor:   '{_COLOR_DOWN}',
      }});
      candleSeries.setData(rawData.ohlcv);

      // Grid price lines
      rawData.gridLevels.forEach(function (gl) {{
        candleSeries.createPriceLine({{
          price:            gl.price,
          color:            gl.color,
          lineWidth:        gl.lineWidth,
          lineStyle:        gl.lineStyle,
          axisLabelVisible: gl.axisLabelVisible,
          title:            gl.title,
        }});
      }});

      // Trade markers — per-strategy groups with toggle (v5: createSeriesMarkers).
      var markerGroups = rawData.markerGroups || [];
      function _mergedMarkers() {{
        var inputs = document.querySelectorAll(
          '#marker-toggles input[type=checkbox]');
        var merged = [];
        if (inputs.length === 0) {{
          markerGroups.forEach(function (g) {{
            merged = merged.concat(g.markers || []);
          }});
        }} else {{
          inputs.forEach(function (inp) {{
            if (inp.checked) {{
              var gi = parseInt(inp.getAttribute('data-grp'), 10);
              if (markerGroups[gi]) {{
                merged = merged.concat(markerGroups[gi].markers || []);
              }}
            }}
          }});
        }}
        merged.sort(function (a, b) {{
          return a.time < b.time ? -1 : (a.time > b.time ? 1 : 0);
        }});
        return merged;
      }}
      var _markersPrimitive = LightweightCharts.createSeriesMarkers(
        candleSeries, _mergedMarkers());
      document.querySelectorAll('#marker-toggles input[type=checkbox]')
        .forEach(function (inp) {{
          inp.addEventListener('change', function () {{
            _markersPrimitive.setMarkers(_mergedMarkers());
          }});
        }});

      // --- Volume chart (separate pane) ---
      var volumeEl = document.getElementById('volume-chart');
      var volumeChart = LightweightCharts.createChart(volumeEl, {{
        layout: {{
          background: {{ color: '#1a1a2e' }},
          textColor:  '#a8b2d8',
        }},
        grid: {{
          vertLines: {{ color: '#2d2d4e' }},
          horzLines: {{ color: '#2d2d4e' }},
        }},
        rightPriceScale: {{ borderColor: '#2d2d4e' }},
        timeScale: {{
          borderColor:     '#2d2d4e',
          timeVisible:     true,
          secondsVisible:  false,
        }},
        width:  volumeEl.clientWidth,
        height: volumeEl.clientHeight,
      }});

      var volumeSeries = volumeChart.addSeries(LightweightCharts.HistogramSeries, {{
        priceFormat: {{ type: 'volume' }},
        priceScaleId: '',
      }});
      volumeSeries.priceScale().applyOptions({{
        scaleMargins: {{ top: 0.1, bottom: 0 }},
      }});
      volumeSeries.setData(rawData.volume);

      // Sync time scales between price and volume charts.
      priceChart.timeScale().subscribeVisibleLogicalRangeChange(function (range) {{
        if (range !== null) {{
          volumeChart.timeScale().setVisibleLogicalRange(range);
        }}
      }});
      volumeChart.timeScale().subscribeVisibleLogicalRangeChange(function (range) {{
        if (range !== null) {{
          priceChart.timeScale().setVisibleLogicalRange(range);
        }}
      }});

      // Fit full period on load.
      priceChart.timeScale().fitContent();
      volumeChart.timeScale().fitContent();

      // Responsive resize.
      window.addEventListener('resize', function () {{
        priceChart.applyOptions({{
          width:  priceEl.clientWidth,
          height: priceEl.clientHeight,
        }});
        volumeChart.applyOptions({{
          width:  volumeEl.clientWidth,
          height: volumeEl.clientHeight,
        }});
      }});
    }})();
  </script>
</body>
</html>"""

    return html
