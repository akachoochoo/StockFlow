"""Phase 0.11.i — Interactive report.html tests for kakao_dgt_backtest.py.

Plan Step 3 / Gate G1:
  - Default mode report.html contains zero data:image/png;base64 main-chart <img>
  - Default mode contains lightweight-charts init + data islands
  - Default mode contains zero network references (http:// / https:// in <script src>)
  - --static-charts / _STATIC_CHARTS=1 rollback: produces base64 PNG <img> (old path)
  - _render_html_report signature accepts bars_map + static_charts params

All tests work WITHOUT pykrx — fixtures are synthetic.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
)
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot, _DGTTrade
from src.research.dgt.runner import _DGTConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _make_bars(n: int, asset: Asset | None = None) -> list[OHLCV]:
    if asset is None:
        asset = _make_asset()
    base = date(2024, 1, 2)
    bars: list[OHLCV] = []
    for i in range(n):
        p = Decimal(50000 + i * 100)
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base + timedelta(days=i),
                open=p - Decimal("50"),
                high=p + Decimal("200"),
                low=p - Decimal("200"),
                close=p,
                volume=Decimal("5000"),
            )
        )
    return bars


def _make_result(
    bars: list[OHLCV],
    asset: Asset | None = None,
    capital: Decimal = Decimal("10_000_000"),
    trades: list[_DGTTrade] | None = None,
) -> _DGTBacktestResult:
    if asset is None:
        asset = bars[0].asset
    if trades is None:
        trades = []
    money = Money(amount=capital, currency=Currency.KRW)
    snapshots = [
        _DGTSnapshot(
            trade_date=b.trade_date,
            cash=capital,
            holdings=Decimal("0"),
            close_price=b.close,
            total_value=capital,
        )
        for b in bars
    ]
    return _DGTBacktestResult(
        asset=asset,
        start=bars[0].trade_date,
        end=bars[-1].trade_date,
        initial_capital=money,
        final_cash=capital,
        final_holdings=Decimal("0"),
        final_close_price=bars[-1].close,
        final_balance=money,
        wallet_total=capital,
        reference_price=bars[0].close,
        grid_levels=[bars[0].close * Decimal("0.95"),
                     bars[0].close,
                     bars[0].close * Decimal("1.05")],
        trades=trades,
        daily_snapshots=snapshots,
    )


def _make_config() -> _DGTConfig:
    return _DGTConfig(grid_count=11, grid_spacing_pct=Decimal("3"), levels_above=5)


def _make_trade(d: date, side: str = "BUY") -> _DGTTrade:
    return _DGTTrade(
        trade_date=d,
        side=side,
        grid_level_price=Decimal("50000"),
        quantity=Decimal("10"),
        rounded_price=Decimal("50000"),
        gross=Decimal("500000"),
        tax=Decimal("1500"),
        commission=Decimal("250"),
        cash_delta=Decimal("-501750") if side == "BUY" else Decimal("498500"),
    )


# ---------------------------------------------------------------------------
# G1 — Default interactive report (no --static-charts)
# ---------------------------------------------------------------------------

class TestInteractiveReportDefault:
    """Default mode: report.html uses interactive lightweight-charts, zero PNG blobs."""

    def test_report_contains_no_main_chart_base64_img(self, tmp_path: Path) -> None:
        """Default mode report must have zero data:image/png;base64 main-chart <img>."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(30)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=b"",  # not used in interactive mode
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=False,
        )
        html = out.read_text(encoding="utf-8")
        # Must not contain base64-encoded PNG img tags for main chart
        assert "data:image/png;base64" not in html, (
            "Default interactive mode must not embed base64 PNG <img> blocks"
        )

    def test_report_contains_lightweight_charts_reference(self, tmp_path: Path) -> None:
        """Default report must reference LightweightCharts / createChart."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(30)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=b"",
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=False,
        )
        html = out.read_text(encoding="utf-8")
        assert "LightweightCharts" in html or "createChart" in html, (
            "Default interactive mode must embed the lightweight-charts JS library"
        )

    def test_report_contains_data_island(self, tmp_path: Path) -> None:
        """Default report must have a <script type=application/json> data island."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(30)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=b"",
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=False,
        )
        html = out.read_text(encoding="utf-8")
        assert 'type="application/json"' in html or "application/json" in html, (
            "Default interactive report must contain a JSON data island"
        )

    def test_report_contains_zero_network_script_src(self, tmp_path: Path) -> None:
        """Default report must contain zero http:// / https:// <script src> refs (P5)."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(30)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=b"",
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=False,
        )
        html = out.read_text(encoding="utf-8")
        # Check for <script src="http... or <script src='https...
        network_refs = re.findall(
            r'<script[^>]+src=["\']https?://', html, re.IGNORECASE
        )
        assert network_refs == [], (
            f"Interactive report must be offline-self-contained — "
            f"found network <script src>: {network_refs}"
        )

    def test_report_html_is_valid_structure(self, tmp_path: Path) -> None:
        """Report must contain essential HTML structural elements."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=b"",
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=False,
        )
        html = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "<title>" in html


# ---------------------------------------------------------------------------
# Rollback flag — --static-charts / _STATIC_CHARTS=1
# ---------------------------------------------------------------------------

class TestStaticChartsRollback:
    """--static-charts flag and _STATIC_CHARTS env var restore the old PNG path."""

    def _make_dummy_png(self) -> bytes:
        """Minimal valid PNG bytes for tests (1x1 transparent)."""
        # Real PNG header + IHDR + IDAT + IEND for a 1x1 image
        import base64
        # This is a known-good 1x1 PNG
        b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
            "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
        return base64.b64decode(b64)

    def test_static_charts_flag_embeds_base64_png(self, tmp_path: Path) -> None:
        """static_charts=True must produce a report with data:image/png;base64 <img>."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"
        dummy_png = self._make_dummy_png()

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=dummy_png,
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=True,
        )
        html = out.read_text(encoding="utf-8")
        assert "data:image/png;base64," in html, (
            "static_charts=True must embed base64 PNG <img> (rollback path)"
        )

    def test_static_charts_env_var_embeds_base64_png(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_STATIC_CHARTS=1 env var must activate the static PNG path."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        monkeypatch.setenv("_STATIC_CHARTS", "1")
        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"
        dummy_png = self._make_dummy_png()

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=dummy_png,
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=False,  # env var overrides
        )
        html = out.read_text(encoding="utf-8")
        assert "data:image/png;base64," in html, (
            "_STATIC_CHARTS=1 env var must activate static PNG rollback path"
        )

    def test_static_charts_no_lightweight_charts(self, tmp_path: Path) -> None:
        """Static rollback report must NOT embed interactive JS (redundant weight)."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _make_config()
        out = tmp_path / "report.html"
        dummy_png = self._make_dummy_png()

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=dummy_png,
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=True,
        )
        html = out.read_text(encoding="utf-8")
        # The static rollback must NOT embed the heavyweight JS library
        assert "LightweightCharts" not in html, (
            "Static rollback path must not embed the lightweight-charts JS library"
        )


# ---------------------------------------------------------------------------
# CLI parser — --static-charts flag present
# ---------------------------------------------------------------------------

class TestCliStaticChartsFlag:
    """`--static-charts` is a valid CLI argument."""

    def test_parser_accepts_static_charts(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--start", "2025-01-02", "--end", "2025-12-31"])
        # Default: False
        assert args.static_charts is False

    def test_parser_static_charts_flag_sets_true(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "--start", "2025-01-02", "--end", "2025-12-31", "--static-charts",
        ])
        assert args.static_charts is True


# ---------------------------------------------------------------------------
# Trade log sections — kept as-is (static HTML, chart surfaces only change)
# ---------------------------------------------------------------------------

class TestTradeLogSectionsPreserved:
    """Trade log <details> sections must survive interactive migration."""

    def test_trade_log_details_present(self, tmp_path: Path) -> None:
        """Report must still contain <details> / <summary> trade log sections."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(20)
        asset = _make_asset()
        base = date(2024, 1, 2)
        trades = [_make_trade(base, "BUY"), _make_trade(base + timedelta(days=5), "SELL")]
        result = _make_result(bars, asset, trades=trades)
        config = _make_config()
        out = tmp_path / "report.html"

        _render_html_report(
            results=[("ADR-Base", result)],
            config=config,
            chart_png=b"",
            output_path=out,
            assets=None,
            bars_map={"069500": bars},
            static_charts=False,
        )
        html = out.read_text(encoding="utf-8")
        assert "<details>" in html, "Trade log <details> sections must be present"
        assert "<summary>" in html, "Trade log <summary> element must be present"
        assert "Trade Log" in html, "Trade Log heading must appear in report"


# ---------------------------------------------------------------------------
# _build_interactive_comparison_html — structure check
# ---------------------------------------------------------------------------

class TestBuildInteractiveComparisonHtml:
    """_build_interactive_comparison_html returns well-formed interactive HTML."""

    def test_returns_string_with_create_chart(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)

        html = _build_interactive_comparison_html(
            results=[("ADR-Base", result)],
            bars=bars,
            title="Test Chart",
        )
        assert isinstance(html, str)
        assert len(html) > 0
        assert "createChart" in html or "LightweightCharts" in html

    def test_returns_offline_html(self) -> None:
        """Output contains no http:// / https:// <script src> references."""
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html

        bars = _make_bars(20)
        result = _make_result(bars)
        html = _build_interactive_comparison_html(
            results=[("ADR-Base", result)],
            bars=bars,
            title="Test",
        )
        network_refs = re.findall(r'<script[^>]+src=["\']https?://', html, re.IGNORECASE)
        assert network_refs == [], f"Offline violation: found {network_refs}"

    def test_aggregates_all_strategy_trades(self) -> None:
        """Markers from all strategies are aggregated into the chart."""
        import json
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html

        bars = _make_bars(20)
        asset = _make_asset()
        base = date(2024, 1, 2)
        # Two strategies with 1 trade each
        trades1 = [_make_trade(base, "BUY")]
        trades2 = [_make_trade(base + timedelta(days=5), "SELL")]
        r1 = _make_result(bars, asset, trades=trades1)
        r2 = _make_result(bars, asset, trades=trades2)

        html = _build_interactive_comparison_html(
            results=[("S1", r1), ("S2", r2)],
            bars=bars,
            title="Multi-strategy Test",
        )
        # Extract the data island and parse it
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match, "Data island not found in interactive chart HTML"
        # Unescape the <\\/ back to </
        raw_json = match.group(1).strip().replace("<\\/", "</").replace("\\u2028", " ").replace("\\u2029", " ")
        data = json.loads(raw_json)
        # 2 trades total across both strategies
        assert len(data["markers"]) == 2, (
            f"Expected 2 markers (1 per strategy), got {len(data['markers'])}"
        )
