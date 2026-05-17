"""Phase 0.11.i — Tests for src/research/dgt/_interactive_chart.py.

Tests-first (CLAUDE.md §7.1): structural + serialization + JSON-safety assertions.
No browser automation (DD3 — accepted bounded coverage gap).

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
  - _serialize_grid_levels: None input → [], attribute input → list[dict]
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
