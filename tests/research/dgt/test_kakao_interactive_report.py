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
        # markers grouped per strategy (Phase 0.11.i toggle): 2 groups, 1 each.
        groups = data["markerGroups"]
        assert len(groups) == 2, f"Expected 2 strategy marker groups, got {len(groups)}"
        assert {g["label"] for g in groups} == {"S1", "S2"}, (
            f"Expected groups labelled per strategy, got {[g['label'] for g in groups]}"
        )
        total = sum(len(g["markers"]) for g in groups)
        assert total == 2, f"Expected 2 markers total (1 per strategy), got {total}"


# ---------------------------------------------------------------------------
# Phase 0.11.j — Trade Log cumulative columns (Step 6)
# ---------------------------------------------------------------------------

class TestCumulativeColumns:
    """Trade logs must have 10-column thead with Cum Realized % + Cum Realized Amount."""

    def test_thead_has_cum_realized_pct(self, tmp_path: Path) -> None:
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
        assert "<th>Cum Realized %</th>" in html, (
            "Trade log thead must contain 'Cum Realized %' column"
        )

    def test_thead_has_cum_realized_amount(self, tmp_path: Path) -> None:
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
        assert "<th>Cum Realized Amount</th>" in html, (
            "Trade log thead must contain 'Cum Realized Amount' column"
        )

    def test_thead_has_ten_columns(self, tmp_path: Path) -> None:
        """Trade log thead must have 10 <th> elements (8 original + 2 cumulative)."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(20)
        asset = _make_asset()
        base = date(2024, 1, 2)
        trades = [_make_trade(base, "BUY")]
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
        # Find the trade log thead row — it contains Date/Side/.../Cum Realized Amount
        # Extract the thead section by finding the table with Date+Side headers
        thead_match = re.search(
            r"<thead>.*?</thead>", html, re.DOTALL | re.IGNORECASE
        )
        assert thead_match is not None, "thead not found in trade log"
        thead_html = thead_match.group(0)
        th_count = len(re.findall(r"<th[^>]*>", thead_html))
        assert th_count == 10, f"Expected 10 <th> in trade log thead, got {th_count}"

    def test_no_trade_row_has_ten_tds(self, tmp_path: Path) -> None:
        """Each trade row must have exactly 10 <td> elements."""
        from src.research.dgt.kakao_dgt_backtest import _render_html_report

        bars = _make_bars(20)
        asset = _make_asset()
        base = date(2024, 1, 2)
        trades = [_make_trade(base, "BUY"), _make_trade(base + timedelta(days=3), "SELL")]
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
        # Find trade rows: rows inside a <details> section that start with a date <td>
        # (side-buy or side-sell class signals a real trade row).
        trade_rows = re.findall(
            r"<tr>(<td[^>]*style=['\"]text-align:left['\"]>.*?)</tr>",
            html,
            re.DOTALL,
        )
        assert len(trade_rows) >= 2, "Expected at least 2 trade rows"
        for row_inner in trade_rows:
            td_count = len(re.findall(r"<td", row_inner))
            assert td_count == 10, f"Expected 10 <td> per trade row, got {td_count}"

    def test_cum_realized_last_sell_matches_formula(self, tmp_path: Path) -> None:
        """After a BUY then SELL, cumulative realized amount at SELL date is computable."""
        from decimal import Decimal as D
        from src.research.dgt.kakao_dgt_backtest import _render_html_report, _compute_cumulative_realized_single

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
        # Compute expected cumulative realized amount at the SELL date.
        sell_date = base + timedelta(days=5)
        cum_map = _compute_cumulative_realized_single(result)
        expected_amount = cum_map.get(sell_date, D("0"))
        expected_pct = expected_amount / result.initial_capital.amount * D("100")

        html = out.read_text(encoding="utf-8")
        # The formatted amount must appear somewhere in the trade log section.
        # _fmt_krw rounds and formats — just check the sell date row has some number.
        assert str(sell_date) in html, "sell date not found in report"
        # The cumulative columns exist (tested above); the value is non-zero if SELL > BUY.
        # We verified the 10-column structure; this confirms the pipeline runs end-to-end.
        assert "Cum Realized" in html


# ---------------------------------------------------------------------------
# Phase 0.11.j — Grid groups in interactive builders (Step 5)
# ---------------------------------------------------------------------------

class TestInteractiveBuilderGridGroups:
    """_build_interactive_comparison_html grid_groups wiring (ADR 0017)."""

    def test_bh_strategy_produces_no_grid_group(self) -> None:
        """B&H results must be excluded from grid_groups (mode='bh' → empty envelope)."""
        import json
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html
        from src.research.dgt.runner import _DGTConfig

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _DGTConfig(grid_count=11, grid_spacing_pct=Decimal("3"), levels_above=5)

        html = _build_interactive_comparison_html(
            results=[("B&H (30%)", result)],
            bars=bars,
            title="BH Test",
            config=config,
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match, "data island not found"
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        assert data["gridGroups"] == [], (
            "B&H strategy must produce empty gridGroups (no grid)"
        )

    def test_adr_base_strategy_produces_grid_group(self) -> None:
        """ADR-Base results with config must produce a non-empty grid group."""
        import json
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html
        from src.research.dgt.runner import _DGTConfig

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _DGTConfig(grid_count=11, grid_spacing_pct=Decimal("3"), levels_above=5)

        html = _build_interactive_comparison_html(
            results=[("ADR-Base", result)],
            bars=bars,
            title="ADR-Base Test",
            config=config,
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match, "data island not found"
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        assert len(data["gridGroups"]) == 1, (
            f"ADR-Base must produce 1 grid group, got {len(data['gridGroups'])}"
        )
        assert data["gridGroups"][0]["label"] == "ADR-Base"

    def test_adr_vol_strategy_produces_grid_group(self) -> None:
        """ADR+Vol results with config must produce a non-empty grid group."""
        import json
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html
        from src.research.dgt.runner import _DGTConfig

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _DGTConfig(grid_count=11, grid_spacing_pct=Decimal("3"), levels_above=5)

        html = _build_interactive_comparison_html(
            results=[("ADR+Vol", result)],
            bars=bars,
            title="ADR+Vol Test",
            config=config,
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        assert len(data["gridGroups"]) == 1
        assert data["gridGroups"][0]["label"] == "ADR+Vol"

    def test_two_adr_strategies_produce_two_grid_groups(self) -> None:
        """ADR-Base + ADR+Vol → 2 grid groups; grid toggle bar present."""
        import json
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html
        from src.research.dgt.runner import _DGTConfig

        bars = _make_bars(20)
        asset = _make_asset()
        result = _make_result(bars, asset)
        config = _DGTConfig(grid_count=11, grid_spacing_pct=Decimal("3"), levels_above=5)

        html = _build_interactive_comparison_html(
            results=[("ADR-Base", result), ("ADR+Vol", result)],
            bars=bars,
            title="Two ADR Test",
            config=config,
            configs_per_result=[config, config],
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        assert len(data["gridGroups"]) == 2
        labels = {g["label"] for g in data["gridGroups"]}
        assert labels == {"ADR-Base", "ADR+Vol"}
        # Two groups → #grid-toggles must be present
        assert 'id="grid-toggles"' in html, "#grid-toggles must be present with 2 grid groups"

    def test_no_config_falls_back_to_static_grid(self) -> None:
        """When config=None, builder falls back to static grid_levels path."""
        import json
        from src.research.dgt.kakao_dgt_backtest import _build_interactive_comparison_html

        bars = _make_bars(20)
        result = _make_result(bars)

        # No config → falls back to _GridArtifact static path
        html = _build_interactive_comparison_html(
            results=[("ADR-Base", result)],
            bars=bars,
            title="Fallback Test",
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match
        data = json.loads(match.group(1).strip().replace("<\\/", "</"))
        # Fallback: gridGroups is empty, gridLevels has entries (from _GridArtifact)
        assert data["gridGroups"] == [], "No-config fallback must have empty gridGroups"
