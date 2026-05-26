"""Phase 0.11.j — Tests for src/research/dgt/_interactive_chart.py.

Extended from Phase 0.11.i with _serialize_grid_series + grid_groups tests
(Steps 3+4, ADR 0017).

Tests-first (CLAUDE.md §7.1): structural + serialization + JSON-safety assertions.
No browser automation in this file (headless gate is test_interactive_render_headless.py).

Coverage targets:
  - _serialize_ohlcv: N bars → N dicts, correct keys, float values, dates ascending
  - _serialize_volume: N bars → N dicts, correct keys, float values, correct colors
  - _serialize_markers: #BUY + #SELL markers, correct position/shape, sorted by time
  - _safe_json_embed: </script> breakout prevented (m1 regression)
  - _safe_json_embed: U+2028/U+2029 escaped
  - Decimal-integrity: Decimal bars round-trip without float-drift artifacts
  - build_interactive_chart_html: non-empty str, contains LightweightCharts/createChart,
    contains data island, balanced tags, zero network references
  - data-island JSON parse: array lengths match inputs
  - _serialize_grid_levels: None input → [], attribute input → list[dict] (RETAINED)
  - _serialize_grid_series: empty → []; N-level → N series; float values; isBound;
    len-mismatch raises; grid_groups path emits LineSeries; #grid-toggles when >1 group;
    backward-compat grid_levels path unchanged
  - asset integrity: SHA-256 of vendored JS matches PROVENANCE.txt
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.research.dgt._interactive_chart import (
    _COLOR_DOWN,
    _COLOR_UP,
    _load_lightweight_charts_js,
    _safe_json_embed,
    _serialize_grid_levels,
    _serialize_grid_series,
    _serialize_markers,
    _serialize_ohlcv,
    _serialize_volume,
    build_interactive_chart_html,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class _FakeBar:
    trade_date: date
    open: Any
    high: Any
    low: Any
    close: Any
    volume: Any


@dataclass
class _FakeTrade:
    trade_date: date
    side: str  # "BUY" or "SELL"
    grid_level_price: Any


@dataclass
class _FakeArtifacts:
    grid_levels: list[Any]
    reference_price: Any


def _make_bars(n: int = 5) -> list[_FakeBar]:
    """Create n ascending-date OHLCV bars with Decimal values."""
    return [
        _FakeBar(
            trade_date=date(2024, 1, i + 1),
            open=Decimal(str(10000 + i * 100)),
            high=Decimal(str(10200 + i * 100)),
            low=Decimal(str(9900 + i * 100)),
            close=Decimal(str(10100 + i * 100)),
            volume=Decimal(str(1000000 + i * 10000)),
        )
        for i in range(n)
    ]


def _make_trades() -> list[_FakeTrade]:
    return [
        _FakeTrade(date(2024, 1, 1), "BUY",  Decimal("10000")),
        _FakeTrade(date(2024, 1, 3), "SELL", Decimal("10300")),
        _FakeTrade(date(2024, 1, 5), "BUY",  Decimal("10200")),
    ]


# ---------------------------------------------------------------------------
# _serialize_ohlcv
# ---------------------------------------------------------------------------

class TestSerializeOhlcv:
    def test_length_matches_input(self) -> None:
        bars = _make_bars(7)
        result = _serialize_ohlcv(bars)
        assert len(result) == 7

    def test_correct_keys(self) -> None:
        bars = _make_bars(1)
        result = _serialize_ohlcv(bars)
        assert set(result[0].keys()) == {"time", "open", "high", "low", "close"}

    def test_values_are_floats(self) -> None:
        bars = _make_bars(3)
        result = _serialize_ohlcv(bars)
        for item in result:
            assert isinstance(item["open"],  float)
            assert isinstance(item["high"],  float)
            assert isinstance(item["low"],   float)
            assert isinstance(item["close"], float)

    def test_dates_ascending(self) -> None:
        bars = _make_bars(5)
        result = _serialize_ohlcv(bars)
        times = [r["time"] for r in result]
        assert times == sorted(times)

    def test_date_format_yyyy_mm_dd(self) -> None:
        bars = _make_bars(1)
        result = _serialize_ohlcv(bars)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result[0]["time"])

    def test_values_are_json_serializable(self) -> None:
        bars = _make_bars(3)
        result = _serialize_ohlcv(bars)
        # Should not raise.
        json.dumps(result)

    def test_decimal_integrity_no_drift(self) -> None:
        """Decimal→float conversion must not introduce drift visible in the string."""
        bar = _FakeBar(
            trade_date=date(2024, 1, 1),
            open=Decimal("35000"),
            high=Decimal("35500"),
            low=Decimal("34500"),
            close=Decimal("35200"),
            volume=Decimal("1000000"),
        )
        result = _serialize_ohlcv([bar])
        # float(Decimal("35000")) == 35000.0 exactly — no drift for integer prices.
        assert result[0]["open"]  == 35000.0
        assert result[0]["high"]  == 35500.0
        assert result[0]["low"]   == 34500.0
        assert result[0]["close"] == 35200.0

    def test_empty_input(self) -> None:
        assert _serialize_ohlcv([]) == []


# ---------------------------------------------------------------------------
# _serialize_volume
# ---------------------------------------------------------------------------

class TestSerializeVolume:
    def test_length_matches_input(self) -> None:
        bars = _make_bars(4)
        result = _serialize_volume(bars)
        assert len(result) == 4

    def test_correct_keys(self) -> None:
        bars = _make_bars(1)
        result = _serialize_volume(bars)
        assert set(result[0].keys()) == {"time", "value", "color"}

    def test_up_day_is_red(self) -> None:
        # close > open → up day → COLOR_UP
        bar = _FakeBar(date(2024, 1, 1), Decimal("100"), Decimal("110"),
                       Decimal("90"), Decimal("105"), Decimal("500000"))
        result = _serialize_volume([bar])
        assert result[0]["color"] == _COLOR_UP

    def test_down_day_is_blue(self) -> None:
        # close < open → down day → COLOR_DOWN
        bar = _FakeBar(date(2024, 1, 1), Decimal("105"), Decimal("110"),
                       Decimal("90"), Decimal("100"), Decimal("500000"))
        result = _serialize_volume([bar])
        assert result[0]["color"] == _COLOR_DOWN

    def test_doji_is_up_color(self) -> None:
        # close == open → treated as up (>= open)
        bar = _FakeBar(date(2024, 1, 1), Decimal("100"), Decimal("102"),
                       Decimal("98"), Decimal("100"), Decimal("100000"))
        result = _serialize_volume([bar])
        assert result[0]["color"] == _COLOR_UP

    def test_volume_value_is_float(self) -> None:
        bars = _make_bars(2)
        result = _serialize_volume(bars)
        for item in result:
            assert isinstance(item["value"], float)


# ---------------------------------------------------------------------------
# _serialize_markers
# ---------------------------------------------------------------------------

class TestSerializeMarkers:
    def test_total_marker_count(self) -> None:
        trades = _make_trades()  # 2 BUY + 1 SELL
        result = _serialize_markers(trades)
        assert len(result) == 3

    def test_buy_marker_shape(self) -> None:
        trades = [_FakeTrade(date(2024, 1, 1), "BUY", Decimal("10000"))]
        result = _serialize_markers(trades)
        assert result[0]["position"] == "belowBar"
        assert result[0]["shape"]    == "arrowUp"

    def test_sell_marker_shape(self) -> None:
        trades = [_FakeTrade(date(2024, 1, 2), "SELL", Decimal("10100"))]
        result = _serialize_markers(trades)
        assert result[0]["position"] == "aboveBar"
        assert result[0]["shape"]    == "arrowDown"

    def test_markers_sorted_by_time(self) -> None:
        # Provide out-of-order trades.
        trades = [
            _FakeTrade(date(2024, 1, 5), "SELL", Decimal("10500")),
            _FakeTrade(date(2024, 1, 1), "BUY",  Decimal("10000")),
            _FakeTrade(date(2024, 1, 3), "BUY",  Decimal("10200")),
        ]
        result = _serialize_markers(trades)
        times = [m["time"] for m in result]
        assert times == sorted(times)

    def test_date_set_filtering(self) -> None:
        trades = _make_trades()
        # Only allow dates 2024-01-01 and 2024-01-03.
        date_set = {"2024-01-01", "2024-01-03"}
        result = _serialize_markers(trades, date_set=date_set)
        assert len(result) == 2
        assert all(m["time"] in date_set for m in result)

    def test_empty_trades(self) -> None:
        assert _serialize_markers([]) == []

    def test_marker_has_time_key(self) -> None:
        trades = [_FakeTrade(date(2024, 1, 1), "BUY", Decimal("10000"))]
        result = _serialize_markers(trades)
        assert "time" in result[0]


# ---------------------------------------------------------------------------
# _safe_json_embed — m1 XSS hardening
# ---------------------------------------------------------------------------

class TestSafeJsonEmbed:
    def test_script_breakout_prevented(self) -> None:
        """</script> in input MUST NOT appear as literal </script> in output."""
        dangerous = {"asset": "</script><script>alert(1)</script>"}
        result = _safe_json_embed(dangerous)
        assert "</script>" not in result

    def test_escaped_forward_slash(self) -> None:
        """</ must be escaped to <\\/ in output."""
        data = {"x": "</evil>"}
        result = _safe_json_embed(data)
        assert "<\\/" in result

    def test_u2028_escaped(self) -> None:
        """U+2028 LINE SEPARATOR must be escaped."""
        data = {"text": "line sep"}
        result = _safe_json_embed(data)
        assert " " not in result

    def test_u2029_escaped(self) -> None:
        """U+2029 PARAGRAPH SEPARATOR must be escaped."""
        data = {"text": "para sep"}
        result = _safe_json_embed(data)
        assert " " not in result

    def test_output_is_valid_json(self) -> None:
        """The escaped output must still parse as valid JSON when unescaped."""
        data = {"ohlcv": [{"time": "2024-01-01", "close": 35000.0}]}
        result = _safe_json_embed(data)
        # Undo the escaping to recover valid JSON, then parse.
        recovered = result.replace("<\\/", "</")
        recovered = recovered.replace("\\u2028", " ")
        recovered = recovered.replace("\\u2029", " ")
        parsed = json.loads(recovered)
        assert parsed["ohlcv"][0]["close"] == 35000.0

    def test_normal_data_round_trips(self) -> None:
        data = [{"time": "2024-01-01", "open": 100.0, "close": 101.0}]
        result = _safe_json_embed(data)
        # No special chars — should parse directly.
        parsed = json.loads(result)
        assert parsed[0]["open"] == 100.0


# ---------------------------------------------------------------------------
# _serialize_grid_levels
# ---------------------------------------------------------------------------

class TestSerializeGridLevels:
    def test_none_input_returns_empty(self) -> None:
        assert _serialize_grid_levels(None) == []

    def test_reference_price_present(self) -> None:
        arts = _FakeArtifacts(
            grid_levels=[Decimal("9800"), Decimal("10000"), Decimal("10200")],
            reference_price=Decimal("10000"),
        )
        result = _serialize_grid_levels(arts)
        prices = [r["price"] for r in result]
        assert 10000.0 in prices

    def test_grid_levels_count(self) -> None:
        arts = _FakeArtifacts(
            grid_levels=[Decimal("9800"), Decimal("10000"), Decimal("10200")],
            reference_price=Decimal("10000"),
        )
        result = _serialize_grid_levels(arts)
        # 1 reference + 3 grid levels
        assert len(result) == 4

    def test_dict_input_supported(self) -> None:
        arts = {
            "grid_levels": [10000.0, 10200.0],
            "reference_price": 10100.0,
        }
        result = _serialize_grid_levels(arts)
        assert len(result) == 3  # 1 ref + 2 grid

    def test_prices_are_floats(self) -> None:
        arts = _FakeArtifacts(
            grid_levels=[Decimal("9500")],
            reference_price=Decimal("10000"),
        )
        result = _serialize_grid_levels(arts)
        for item in result:
            assert isinstance(item["price"], float)

    def test_missing_reference_price_graceful(self) -> None:
        arts = _FakeArtifacts(grid_levels=[Decimal("10000")], reference_price=None)
        result = _serialize_grid_levels(arts)
        # Only grid levels, no reference line.
        assert len(result) == 1

    def test_empty_grid_levels_with_reference(self) -> None:
        arts = _FakeArtifacts(grid_levels=[], reference_price=Decimal("10000"))
        result = _serialize_grid_levels(arts)
        assert len(result) == 1
        assert result[0]["price"] == 10000.0


# ---------------------------------------------------------------------------
# build_interactive_chart_html
# ---------------------------------------------------------------------------

_ASSETS_DIR = Path(__file__).parent.parent.parent.parent / "src" / "research" / "dgt" / "assets"


def _build_html(n_bars: int = 3, n_trades: int = 2) -> str:
    bars = _make_bars(n_bars)
    trades = _make_trades()[:n_trades]
    ohlcv   = _serialize_ohlcv(bars)
    volume  = _serialize_volume(bars)
    markers = _serialize_markers(trades)
    arts    = _FakeArtifacts(
        grid_levels=[Decimal("9800"), Decimal("10000"), Decimal("10200")],
        reference_price=Decimal("10000"),
    )
    grid_levels = _serialize_grid_levels(arts)
    return build_interactive_chart_html(
        title="Test Chart — 069500",
        ohlcv=ohlcv,
        volume=volume,
        marker_groups=[{"label": "S1", "markers": markers}],
        grid_levels=grid_levels,
    )


class TestBuildInteractiveChartHtml:
    def test_output_is_non_empty_string(self) -> None:
        html = _build_html()
        assert isinstance(html, str)
        assert len(html) > 0

    def test_contains_createchart(self) -> None:
        html = _build_html()
        assert "createChart" in html

    def test_contains_lightweight_charts_reference(self) -> None:
        html = _build_html()
        assert "LightweightCharts" in html

    def test_contains_data_island(self) -> None:
        html = _build_html()
        assert '<script type="application/json" id="chart-data">' in html

    def test_data_island_parseable(self) -> None:
        html = _build_html(n_bars=5, n_trades=3)
        # Extract the data island content between the script tags.
        match = re.search(
            r'<script type="application/json" id="chart-data">\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
        assert match is not None, "data island not found"
        raw = match.group(1)
        # Undo safe_json_embed escaping before parsing.
        raw = raw.replace("<\\/", "</")
        raw = raw.replace("\\u2028", " ")
        raw = raw.replace("\\u2029", " ")
        data = json.loads(raw)
        assert len(data["ohlcv"])   == 5
        assert len(data["volume"])  == 5
        # markers nested under per-strategy markerGroups (Phase 0.11.i toggle).
        assert len(data["markerGroups"]) == 1
        assert len(data["markerGroups"][0]["markers"]) == 3

    def test_zero_network_references(self) -> None:
        """Report HTML must contain zero http/https <script src> references (P5)."""
        html = _build_html()
        # Check for CDN-style script src attributes.
        cdn_pattern = re.compile(r'<script[^>]+src=["\']https?://', re.IGNORECASE)
        assert cdn_pattern.search(html) is None, "Found network <script src> reference"

    def test_no_data_uri_png_img(self) -> None:
        """Interactive output must NOT contain base64 PNG img tags."""
        html = _build_html()
        assert "data:image/png;base64" not in html

    def test_balanced_script_tags(self) -> None:
        """Count of <script> and </script> must match."""
        html = _build_html()
        open_count  = html.count("<script")
        close_count = html.count("</script>")
        assert open_count == close_count

    def test_balanced_div_tags(self) -> None:
        html = _build_html()
        open_count  = html.count("<div")
        close_count = html.count("</div>")
        assert open_count == close_count

    def test_title_in_output(self) -> None:
        html = _build_html()
        assert "069500" in html

    def test_fitmcontent_called(self) -> None:
        """fitContent() must be called to auto-fit the visible range."""
        html = _build_html()
        assert "fitContent" in html

    def test_no_bars_produces_html(self) -> None:
        """Empty data should still produce a valid (empty) chart page."""
        html = build_interactive_chart_html(
            title="Empty",
            ohlcv=[],
            volume=[],
            marker_groups=[],
            grid_levels=[],
        )
        assert "createChart" in html
        assert isinstance(html, str)

    def test_single_group_no_toggle_bar(self) -> None:
        """One marker group → no per-strategy toggle bar rendered."""
        html = _build_html()
        assert 'id="marker-toggles"' not in html

    def test_multi_group_renders_toggle_bar(self) -> None:
        """>1 marker group → per-strategy toggle checkboxes render (Phase 0.11.i)."""
        bars = _make_bars(5)
        trades = _make_trades()
        html = build_interactive_chart_html(
            title="Multi",
            ohlcv=_serialize_ohlcv(bars),
            volume=_serialize_volume(bars),
            marker_groups=[
                {"label": "ADR-Base", "markers": _serialize_markers(trades)},
                {"label": "ADR+Vol", "markers": _serialize_markers(trades)},
            ],
            grid_levels=[],
        )
        assert 'id="marker-toggles"' in html
        assert 'data-grp="0"' in html
        assert 'data-grp="1"' in html
        assert "ADR-Base" in html and "ADR+Vol" in html
        match = re.search(
            r'<script type="application/json" id="chart-data">\s*(.*?)\s*</script>',
            html, re.DOTALL,
        )
        assert match is not None
        data = json.loads(match.group(1).replace("<\\/", "</"))
        assert len(data["markerGroups"]) == 2
        assert data["markerGroups"][0]["label"] == "ADR-Base"


# ---------------------------------------------------------------------------
# _serialize_grid_series (Phase 0.11.j Step 3)
# ---------------------------------------------------------------------------

def _make_envelope(n_bars: int = 3, n_levels: int = 3) -> list[list[Decimal]]:
    """Create a synthetic envelope: n_bars bars, n_levels levels each, ascending."""
    base = Decimal("10000")
    step = Decimal("200")
    result = []
    for b in range(n_bars):
        # Each bar shifts the reference slightly to give variety.
        ref = base + Decimal(b * 50)
        result.append([ref + step * i for i in range(n_levels)])
    return result


def _make_bar_dates(n: int = 3) -> list[date]:
    return [date(2024, 1, i + 1) for i in range(n)]


class TestSummaryBar:
    """summary 통계 패널 (ADR 0022 §11.14) — opt-in, None → 미렌더."""

    def _build(self, summary: object) -> str:
        bars = _make_bars(3)
        return build_interactive_chart_html(
            title="T", ohlcv=_serialize_ohlcv(bars), volume=_serialize_volume(bars),
            marker_groups=[{"label": "S1", "markers": []}], grid_levels=[],
            summary=summary,  # type: ignore[arg-type]
        )

    def test_renders_when_provided(self) -> None:
        html = self._build([("보유", "69 주"), ("회전율", "1.25x")])
        assert 'class="stats-bar"' in html
        assert "보유" in html and "69 주" in html
        assert "회전율" in html and "1.25x" in html

    def test_absent_when_none(self) -> None:
        assert 'class="stats-bar"' not in self._build(None)

    def test_absent_when_empty(self) -> None:
        assert 'class="stats-bar"' not in self._build([])

    def test_escapes_values(self) -> None:
        html = self._build([("x", "<b>&inject</b>")])
        assert "<b>&inject</b>" not in html
        assert "&lt;b&gt;" in html


class TestSerializeGridSeries:
    def test_empty_envelope_returns_empty(self) -> None:
        result = _serialize_grid_series([], [], color="#ff0000")
        assert result == []

    def test_n_levels_produces_n_series(self) -> None:
        n_levels = 5
        n_bars = 4
        envelope = _make_envelope(n_bars, n_levels)
        bar_dates = _make_bar_dates(n_bars)
        series = _serialize_grid_series(envelope, bar_dates, color="#aabbcc")
        assert len(series) == n_levels

    def test_each_series_has_n_bars_data_points(self) -> None:
        n_bars = 6
        envelope = _make_envelope(n_bars, 3)
        bar_dates = _make_bar_dates(n_bars)
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        for s in series:
            assert len(s["data"]) == n_bars

    def test_values_are_floats(self) -> None:
        envelope = _make_envelope(3, 4)
        bar_dates = _make_bar_dates(3)
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        for s in series:
            for point in s["data"]:
                assert isinstance(point["value"], float), (
                    f"Expected float, got {type(point['value'])}"
                )

    def test_isbound_correct_for_ends(self) -> None:
        n_levels = 7
        envelope = _make_envelope(2, n_levels)
        bar_dates = _make_bar_dates(2)
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        assert series[0]["isBound"] is True,  "first level must be bound"
        assert series[-1]["isBound"] is True, "last level must be bound"
        for s in series[1:-1]:
            assert s["isBound"] is False, f"interior level {s['levelIndex']} must not be bound"

    def test_isbound_both_ends_when_two_levels(self) -> None:
        # 2 levels → both are bound (index 0 and 1 are both ends).
        envelope = [[Decimal("9000"), Decimal("11000")]] * 2
        bar_dates = _make_bar_dates(2)
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        assert len(series) == 2
        assert series[0]["isBound"] is True
        assert series[1]["isBound"] is True

    def test_level_index_sequential(self) -> None:
        n_levels = 5
        envelope = _make_envelope(3, n_levels)
        bar_dates = _make_bar_dates(3)
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        assert [s["levelIndex"] for s in series] == list(range(n_levels))

    def test_time_format_yyyy_mm_dd(self) -> None:
        envelope = _make_envelope(3, 3)
        bar_dates = _make_bar_dates(3)
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        for s in series:
            for point in s["data"]:
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", point["time"]), (
                    f"Unexpected time format: {point['time']!r}"
                )

    def test_time_values_match_bar_dates(self) -> None:
        bar_dates = [date(2024, 3, 15), date(2024, 3, 18), date(2024, 3, 20)]
        envelope = _make_envelope(3, 3)
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        expected_times = ["2024-03-15", "2024-03-18", "2024-03-20"]
        for s in series:
            assert [p["time"] for p in s["data"]] == expected_times

    def test_decimal_values_cast_correctly(self) -> None:
        envelope = [[Decimal("35000"), Decimal("36000")]]
        bar_dates = [date(2024, 1, 1)]
        series = _serialize_grid_series(envelope, bar_dates, color="#fff")
        assert series[0]["data"][0]["value"] == 35000.0
        assert series[1]["data"][0]["value"] == 36000.0

    def test_len_mismatch_raises(self) -> None:
        envelope = _make_envelope(3, 3)
        bar_dates = _make_bar_dates(2)  # 2 != 3
        with pytest.raises(AssertionError, match="len"):
            _serialize_grid_series(envelope, bar_dates, color="#fff")

    def test_single_bar_single_level_works(self) -> None:
        envelope = [[Decimal("50000")]]
        bar_dates = [date(2024, 6, 1)]
        series = _serialize_grid_series(envelope, bar_dates, color="#e74c3c")
        assert len(series) == 1
        assert series[0]["isBound"] is True  # index 0 == n_levels-1 when n==1
        assert series[0]["data"][0]["value"] == 50000.0

    def test_output_is_json_serializable(self) -> None:
        envelope = _make_envelope(4, 5)
        bar_dates = _make_bar_dates(4)
        series = _serialize_grid_series(envelope, bar_dates, color="#abc123")
        # Should not raise
        json.dumps(series)


# ---------------------------------------------------------------------------
# build_interactive_chart_html — grid_groups path (Phase 0.11.j Step 3+4)
# ---------------------------------------------------------------------------

def _make_grid_groups(n_levels: int = 3, n_bars: int = 3) -> list[dict]:
    """Helper: produce 2 realistic grid_groups for testing toggle + LineSeries."""
    envelope = _make_envelope(n_bars, n_levels)
    bar_dates = _make_bar_dates(n_bars)
    levels_adr_base = _serialize_grid_series(envelope, bar_dates, color="#95a5a6")
    levels_adr_vol  = _serialize_grid_series(envelope, bar_dates, color="#8e44ad")
    return [
        {"label": "ADR-Base", "color": "#95a5a6", "levels": levels_adr_base},
        {"label": "ADR+Vol",  "color": "#8e44ad", "levels": levels_adr_vol},
    ]


class TestBuildInteractiveChartHtmlGridGroups:
    """Phase 0.11.j: grid_groups path — v5 LineSeries + #grid-toggles."""

    def test_grid_groups_emits_line_series(self) -> None:
        """grid_groups non-empty → HTML contains LightweightCharts.LineSeries."""
        html = build_interactive_chart_html(
            title="GridGroups Test",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[],
            grid_groups=_make_grid_groups(),
        )
        assert "LightweightCharts.LineSeries" in html, (
            "grid_groups path must use v5 LightweightCharts.LineSeries"
        )

    def test_no_v4_addseries_call(self) -> None:
        """No functional v4 addLineSeries() call — only comments may mention it."""
        html = build_interactive_chart_html(
            title="V4 Check",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[],
            grid_groups=_make_grid_groups(),
        )
        assert "addLineSeries(" not in html, (
            "v4 addLineSeries() call must not appear in output (ADR 0016 §3.6)"
        )

    def test_data_island_has_grid_groups_key(self) -> None:
        """Data island must contain gridGroups key when grid_groups provided."""
        html = build_interactive_chart_html(
            title="Island Check",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[],
            grid_groups=_make_grid_groups(n_levels=4, n_bars=5),
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match, "data island not found"
        raw = match.group(1).strip().replace("<\\/", "</")
        data = json.loads(raw)
        assert "gridGroups" in data, "gridGroups key missing from data island"
        assert len(data["gridGroups"]) == 2

    def test_grid_levels_emitted_empty_when_grid_groups_provided(self) -> None:
        """§9 note (a): when grid_groups non-empty, gridLevels must be [] in island."""
        html = build_interactive_chart_html(
            title="Mutual Excl",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[{"price": 100.0, "color": "#fff", "lineWidth": 1,
                          "lineStyle": 1, "axisLabelVisible": False, "title": "g0"}],
            grid_groups=_make_grid_groups(),
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        assert data["gridLevels"] == [], (
            "gridLevels must be [] when grid_groups provided (§9 mutual exclusivity)"
        )

    def test_grid_toggles_absent_with_single_group(self) -> None:
        """Single grid_group → #grid-toggles must NOT render (threshold >1)."""
        envelope = _make_envelope(3, 3)
        bar_dates = _make_bar_dates(3)
        levels = _serialize_grid_series(envelope, bar_dates, color="#fff")
        html = build_interactive_chart_html(
            title="Single Grp",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[],
            grid_groups=[{"label": "ADR-Base", "color": "#fff", "levels": levels}],
        )
        assert 'id="grid-toggles"' not in html, (
            "Single grid_group must NOT render #grid-toggles bar (threshold >1)"
        )

    def test_grid_toggles_present_with_two_groups(self) -> None:
        """>1 grid_group → #grid-toggles bar with per-group checkboxes."""
        html = build_interactive_chart_html(
            title="Two Grps",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[],
            grid_groups=_make_grid_groups(),
        )
        assert 'id="grid-toggles"' in html, (
            ">1 grid_groups must render #grid-toggles bar"
        )
        assert 'data-grid-grp="0"' in html
        assert 'data-grid-grp="1"' in html
        assert "ADR-Base" in html
        assert "ADR+Vol" in html

    def test_toggle_bar_uses_toggle_bar_class(self) -> None:
        """Toggle bars use .toggle-bar CSS class (not bare ID rule)."""
        html = build_interactive_chart_html(
            title="CSS",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[],
            grid_groups=_make_grid_groups(),
        )
        assert 'class="toggle-bar"' in html, ".toggle-bar CSS class missing"
        assert ".toggle-bar" in html, ".toggle-bar CSS rule missing"

    def test_backward_compat_grid_levels_only(self) -> None:
        """grid_levels only (no grid_groups) → createPriceLine path unchanged."""
        html = build_interactive_chart_html(
            title="Backward Compat",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[{"price": 35000.0, "color": "#bdc3c7", "lineWidth": 1,
                          "lineStyle": 1, "axisLabelVisible": False, "title": "g0"}],
        )
        assert "createPriceLine" in html, "backward compat: createPriceLine missing"
        # Data island must carry the static grid level
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        assert len(data["gridLevels"]) == 1, "gridLevels must be present in fallback path"
        assert data["gridGroups"] == [], "gridGroups must be [] in fallback path"

    def test_backward_compat_no_grid_toggles(self) -> None:
        """grid_levels-only path must NOT render #grid-toggles."""
        html = build_interactive_chart_html(
            title="No Grid Toggle",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[{"price": 10.0, "color": "#fff", "lineWidth": 1,
                          "lineStyle": 1, "axisLabelVisible": False, "title": "g0"}],
        )
        assert 'id="grid-toggles"' not in html

    def test_grid_groups_none_equivalent_to_empty(self) -> None:
        """grid_groups=None and grid_groups=[] should both use createPriceLine path."""
        html_none = build_interactive_chart_html(
            title="None", ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[], grid_groups=None,
        )
        html_empty = build_interactive_chart_html(
            title="Empty", ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[], grid_groups=[],
        )
        # Both should NOT have the LineSeries grid path
        assert "LightweightCharts.LineSeries" in html_none  # still in JS code
        # The key check: gridGroups in data island should be []
        for html in (html_none, html_empty):
            match = re.search(
                r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
                html, re.DOTALL,
            )
            assert match
            data = json.loads(match.group(1).strip().replace("<\\/", "</"))
            assert data["gridGroups"] == []

    def test_grid_groups_data_island_structure(self) -> None:
        """Each group in gridGroups data island has label, color, levels keys."""
        html = build_interactive_chart_html(
            title="Structure",
            ohlcv=[], volume=[], marker_groups=[],
            grid_levels=[],
            grid_groups=_make_grid_groups(n_levels=3, n_bars=2),
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        for grp in data["gridGroups"]:
            assert "label" in grp
            assert "color" in grp
            assert "levels" in grp
            # Each level has levelIndex, isBound, data
            for lvl in grp["levels"]:
                assert "levelIndex" in lvl
                assert "isBound" in lvl
                assert "data" in lvl


# ---------------------------------------------------------------------------
# Asset integrity — SHA-256 matches PROVENANCE.txt
# ---------------------------------------------------------------------------

class TestAssetIntegrity:
    def test_vendored_js_exists(self) -> None:
        js_path = _ASSETS_DIR / "lightweight-charts.standalone.production.js"
        assert js_path.exists(), f"Vendored JS not found at {js_path}"

    def test_provenance_txt_exists(self) -> None:
        prov_path = _ASSETS_DIR / "PROVENANCE.txt"
        assert prov_path.exists(), f"PROVENANCE.txt not found at {prov_path}"

    def test_sha256_matches_provenance(self) -> None:
        """SHA-256 of the vendored JS must match what is recorded in PROVENANCE.txt."""
        js_path   = _ASSETS_DIR / "lightweight-charts.standalone.production.js"
        prov_path = _ASSETS_DIR / "PROVENANCE.txt"

        computed = hashlib.sha256(js_path.read_bytes()).hexdigest()

        prov_text = prov_path.read_text(encoding="utf-8")
        # Extract the SHA-256 line: "SHA-256:  <hex>"
        match = re.search(r"SHA-256:\s+([0-9a-f]{64})", prov_text)
        assert match is not None, "SHA-256 not found in PROVENANCE.txt"
        recorded = match.group(1)

        assert computed == recorded, (
            f"Vendored JS SHA-256 mismatch!\n"
            f"  Computed:  {computed}\n"
            f"  Recorded:  {recorded}"
        )

    def test_js_loadable_via_module_function(self) -> None:
        """_load_lightweight_charts_js() must return non-empty string."""
        js = _load_lightweight_charts_js()
        assert isinstance(js, str)
        assert len(js) > 1000  # minified JS is ~196 KB
