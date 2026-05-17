"""Phase 0.11.c.3 — `_DGTVisualizationRenderer` 구현 tests.

ADR 0009 §1.4 G1+G2+G4 + §1.11 Test Plan 정합:

| 계층            | 검증                                                          |
|-----------------|---------------------------------------------------------------|
| Protocol        | `isinstance(renderer, _VisualizationRenderer)` (D2 (d))      |
| PNG render      | 헤더 + figure-leak invariant (D5 + R8 mitigation)             |
| Overlay         | 공통 축 (time + pnl + drawdown) Decimal 정확성 (D6 + §2.1)   |
| Drawdown        | drawdown ≤ 0 invariant (§1.3 D6)                              |
| Reproducibility | 2회 실행 metadata 일치 (D10 (ii) + D12)                       |

`matplotlib` 의존성 부재 시 PNG 테스트는 `pytest.importorskip` 으로 skip.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.application.reporting.trade_view import TradeView
from src.domain.models import OHLCV, Asset
from src.research.visualization._artifacts import (
    _DGTVisualizationArtifacts,
    _GridSnapshot,
)
from src.research.visualization._dgt_renderer import (
    _DGTVisualizationRenderer,
)
from src.research.visualization._visualization_renderer import (
    _OverlayPayload,
    _VisualizationRenderer,
)

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def synthesized_bars(kr_etf_069500: Asset) -> list[OHLCV]:
    """30 bars: 100원 → 130원 (15 up) → 100원 (15 down) — runner_smoke 패턴 정합."""
    bars: list[OHLCV] = []
    base_date = date(2024, 1, 2)
    for i in range(15):
        price = Decimal(100 + 2 * i)
        bars.append(
            OHLCV(
                asset=kr_etf_069500,
                trade_date=base_date + timedelta(days=i),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("1000"),
            )
        )
    for i in range(15):
        price = Decimal(130 - 2 * i)
        bars.append(
            OHLCV(
                asset=kr_etf_069500,
                trade_date=base_date + timedelta(days=15 + i),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("1000"),
            )
        )
    return bars


@pytest.fixture
def synthesized_trades() -> list[TradeView]:
    """3 trades: BUY at 100, BUY at 110, SELL at 128 — synthesized_bars 정렬 정합."""
    return [
        TradeView(
            timestamp=datetime(2024, 1, 2, 6, 0, tzinfo=UTC),
            symbol="069500",
            side="BUY",
            price=Decimal("100"),
            quantity=Decimal("10"),
            strategy_id="dgt",
            annotations={"dgt_grid_level": "-2",
                         "dgt_reference_price": "100"},
        ),
        TradeView(
            timestamp=datetime(2024, 1, 7, 6, 0, tzinfo=UTC),
            symbol="069500",
            side="BUY",
            price=Decimal("110"),
            quantity=Decimal("5"),
            strategy_id="dgt",
            annotations={"dgt_grid_level": "-1",
                         "dgt_reference_price": "100"},
        ),
        TradeView(
            timestamp=datetime(2024, 1, 16, 6, 0, tzinfo=UTC),
            symbol="069500",
            side="SELL",
            price=Decimal("128"),
            quantity=Decimal("10"),
            strategy_id="dgt",
            annotations={"dgt_grid_level": "2",
                         "dgt_reference_price": "100"},
        ),
    ]


@pytest.fixture
def synthesized_artifacts() -> _DGTVisualizationArtifacts:
    """Static-reference artifacts — 단일 grid snapshot + reference."""
    return _DGTVisualizationArtifacts(
        grid_history=[
            _GridSnapshot(
                timestamp=datetime(2024, 1, 2, tzinfo=UTC),
                reference_price=Decimal("100"),
                levels=[
                    Decimal("85"),
                    Decimal("90"),
                    Decimal("95"),
                    Decimal("100"),
                    Decimal("105"),
                    Decimal("110"),
                    Decimal("115"),
                ],
                triggered_level=None,
            ),
        ],
        reference_price_curve=[
            (datetime(2024, 1, 2, tzinfo=UTC), Decimal("100")),
        ],
        parameter_config={"n": 6, "k": Decimal("0.05"), "m": 3},
        asset_code="069500",
        period_start=date(2024, 1, 2),
        period_end=date(2024, 1, 31),
    )


# ---------------------------------------------------------------------------
# AC1 — Protocol compliance (D2 (d) + G1)
# ---------------------------------------------------------------------------
class TestAC1ProtocolCompliance:
    """`_DGTVisualizationRenderer` implements `_VisualizationRenderer` Protocol."""

    def test_strategy_id(self) -> None:
        assert _DGTVisualizationRenderer.strategy_id == "dgt"

    def test_isinstance_visualization_renderer(self) -> None:
        renderer = _DGTVisualizationRenderer()
        assert isinstance(renderer, _VisualizationRenderer)

    def test_methods_present(self) -> None:
        renderer = _DGTVisualizationRenderer()
        assert hasattr(renderer, "render_full_period")
        assert hasattr(renderer, "extract_overlay_metric")


# ---------------------------------------------------------------------------
# AC2 — PNG render (D5 + R8 figure-leak)
# ---------------------------------------------------------------------------
class TestAC2RenderFullPeriod:
    """`render_full_period` 산출 검증."""

    def test_png_header(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        pytest.importorskip("matplotlib")
        renderer = _DGTVisualizationRenderer()
        png = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        assert isinstance(png, bytes)
        assert png.startswith(_PNG_HEADER), (
            "render_full_period must return PNG bytes (header mismatch)"
        )
        # Non-empty 확인 — render 실패 시 헤더만 있을 수 있음
        assert len(png) > 1000, f"PNG too small: {len(png)} bytes"

    def test_render_without_artifacts(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """artifacts=None — close line + trade markers 만 (graceful degradation)."""
        pytest.importorskip("matplotlib")
        renderer = _DGTVisualizationRenderer()
        png = renderer.render_full_period(
            synthesized_bars, synthesized_trades, artifacts=None,
        )
        assert png.startswith(_PNG_HEADER)

    def test_render_empty_bars_raises(self) -> None:
        renderer = _DGTVisualizationRenderer()
        with pytest.raises(ValueError, match="bars is empty"):
            renderer.render_full_period(bars=[], trades=[], artifacts=None)

    def test_figure_leak_invariant(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """R8 mitigation — `plt.close(fig)` invariant (ADR 0006 §17.8 pattern)."""
        plt = pytest.importorskip("matplotlib.pyplot")
        plt.close("all")
        baseline = plt.get_fignums()
        renderer = _DGTVisualizationRenderer()
        renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        after = plt.get_fignums()
        assert after == baseline, (
            f"figure leak: baseline={baseline}, after={after}"
        )


# ---------------------------------------------------------------------------
# AC3 — Overlay metric (D6 공통 축 + §2.1 Decimal)
# ---------------------------------------------------------------------------
class TestAC3ExtractOverlayMetric:
    """`extract_overlay_metric` 산출 검증 — `_OverlayPayload` 정확성."""

    def test_empty_bars(self) -> None:
        renderer = _DGTVisualizationRenderer()
        payload = renderer.extract_overlay_metric(bars=[], trades=[])
        assert isinstance(payload, _OverlayPayload)
        assert payload.time_series == []
        assert payload.pnl_cumulative == []
        assert payload.drawdown == []
        assert payload.strategy_id == "dgt"

    def test_length_matches_bars(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        renderer = _DGTVisualizationRenderer()
        payload = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        assert len(payload.time_series) == len(synthesized_bars)
        assert len(payload.pnl_cumulative) == len(synthesized_bars)
        assert len(payload.drawdown) == len(synthesized_bars)

    def test_decimal_invariant(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """CLAUDE.md §2.1 — 모든 numeric 은 Decimal."""
        renderer = _DGTVisualizationRenderer()
        payload = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        for v in payload.pnl_cumulative:
            assert isinstance(v, Decimal), f"non-Decimal pnl: {type(v)}"
        for v in payload.drawdown:
            assert isinstance(v, Decimal), f"non-Decimal drawdown: {type(v)}"

    def test_time_series_utc_and_sorted(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        renderer = _DGTVisualizationRenderer()
        payload = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        for ts in payload.time_series:
            assert ts.tzinfo is not None, "naive datetime — UTC 박제 위반"
            assert ts.utcoffset() == timedelta(0), (
                f"non-UTC offset: {ts.utcoffset()}"
            )
        for a, b in zip(
            payload.time_series, payload.time_series[1:], strict=False,
        ):
            assert a < b, "time_series must be strictly ascending"

    def test_pnl_computation_correct(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """Manual oracle — 첫 BUY 직전 pnl = 0, 첫 BUY 시점 = (close - price) * qty."""
        renderer = _DGTVisualizationRenderer()
        payload = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        # bar[0] (2024-01-02) = first BUY @ 100, qty=10. close=100.
        # cum_cash_delta = -100*10 = -1000, holdings = 10, pnl = -1000 + 10*100 = 0
        assert payload.pnl_cumulative[0] == Decimal("0")
        # bar[5] (2024-01-07) = second BUY @ 110, qty=5. close=110.
        # cum_cash_delta = -1000 - 550 = -1550, holdings = 15, pnl = -1550 + 15*110 = 100
        assert payload.pnl_cumulative[5] == Decimal("100")
        # bar[14] (2024-01-16) = SELL @ 128, qty=10. close=128.
        # cum_cash_delta = -1550 + 1280 = -270, holdings = 5,
        # pnl = -270 + 5*128 = 370
        assert payload.pnl_cumulative[14] == Decimal("370")

    def test_drawdown_non_positive(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """§1.3 D6 — drawdown 은 보통 음수 또는 0 (peak 기준)."""
        renderer = _DGTVisualizationRenderer()
        payload = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        for dd in payload.drawdown:
            assert dd <= 0, f"drawdown > 0 (invariant 위반): {dd}"

    def test_drawdown_zero_at_peak(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """Peak 시점 drawdown == 0 invariant."""
        renderer = _DGTVisualizationRenderer()
        payload = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        # At least one drawdown==0 점 존재 (peak)
        assert any(d == Decimal("0") for d in payload.drawdown), (
            "drawdown series must touch 0 at running peak"
        )


# ---------------------------------------------------------------------------
# AC4 — Reproducibility (D10 (ii) + D12)
# ---------------------------------------------------------------------------
class TestAC4Reproducibility:
    """동일 입력 2회 실행 = byte-identical overlay metric (D12)."""

    def test_overlay_metric_byte_identical(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        renderer = _DGTVisualizationRenderer()
        p1 = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        p2 = renderer.extract_overlay_metric(
            synthesized_bars, synthesized_trades,
        )
        assert p1.time_series == p2.time_series
        assert p1.pnl_cumulative == p2.pnl_cumulative
        assert p1.drawdown == p2.drawdown
        assert p1.strategy_id == p2.strategy_id

    def test_png_render_byte_identical(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """D10 (i) → (ii) downgrade — byte-identical 은 환경 의존이므로 길이만."""
        pytest.importorskip("matplotlib")
        renderer = _DGTVisualizationRenderer()
        b1 = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        b2 = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        # 길이 일치 invariant — 폰트/anti-aliasing drift 우회.
        # 동일 figure metadata 산출 검증 (D10 (ii) 패턴).
        assert len(b1) == len(b2), (
            f"PNG length drift: b1={len(b1)}, b2={len(b2)}"
        )


# ---------------------------------------------------------------------------
# AC2b — New 2-panel layout assertions (Phase 0.11.h)
# ---------------------------------------------------------------------------
class TestAC2bCandleVolumeLayout:
    """2-panel candlestick + volume layout (ADR 0015 G2)."""

    def test_render_has_volume_panel(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """_build_render_figure returns fig with exactly 2 axes (price + volume)."""
        plt = pytest.importorskip("matplotlib.pyplot")
        renderer = _DGTVisualizationRenderer()
        fig, axes = renderer._build_render_figure(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        try:
            assert len(fig.axes) == 2, (
                f"expected 2 axes (price + volume), got {len(fig.axes)}"
            )
        finally:
            plt.close(fig)

    def test_render_grid_envelope_preserved(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """Grid axhlines are present on axes[0] (price axis) after candle switch."""
        import matplotlib.lines as mlines
        plt = pytest.importorskip("matplotlib.pyplot")
        renderer = _DGTVisualizationRenderer()
        fig, axes = renderer._build_render_figure(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        try:
            price_ax = axes[0]
            # _draw_grid_envelope draws axhline for each grid level.
            # axhline adds a Line2D to ax.lines — check at least one is present.
            hlines = [
                ln for ln in price_ax.lines
                if isinstance(ln, mlines.Line2D)
            ]
            assert len(hlines) > 0, (
                "no lines on price axis — grid envelope axhlines missing after candle switch"
            )
        finally:
            plt.close(fig)

    def test_build_render_figure_does_not_close_fig(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """_build_render_figure must not close fig — that is render_full_period's job."""
        plt = pytest.importorskip("matplotlib.pyplot")
        renderer = _DGTVisualizationRenderer()
        fig, _axes = renderer._build_render_figure(
            synthesized_bars, synthesized_trades, artifacts=None,
        )
        try:
            # If fig were already closed, fig.axes would raise or be empty.
            assert hasattr(fig, "axes"), "fig must remain open after _build_render_figure"
            assert len(fig.axes) == 2
        finally:
            plt.close(fig)


# ---------------------------------------------------------------------------
# AC5 — Title / parameter formatting
# ---------------------------------------------------------------------------
class TestAC5ParameterConfigFormatting:
    """`_format_parameter_config` Decimal 직렬화 정확성 (CLAUDE.md §2.1)."""

    def test_full_n_k_m(self) -> None:
        renderer = _DGTVisualizationRenderer()
        out = renderer._format_parameter_config(
            {"n": 6, "k": Decimal("0.05"), "m": 3},
        )
        assert out == "n=6, k=0.05, m=3"

    def test_partial_missing_key_skipped(self) -> None:
        renderer = _DGTVisualizationRenderer()
        out = renderer._format_parameter_config({"n": 11})
        assert out == "n=11"

    def test_empty_cfg(self) -> None:
        renderer = _DGTVisualizationRenderer()
        assert renderer._format_parameter_config({}) == ""

    def test_decimal_not_float(self) -> None:
        """Decimal str() = 정확 직렬화 — float 미경유 (§2.3)."""
        renderer = _DGTVisualizationRenderer()
        out = renderer._format_parameter_config({"k": Decimal("0.1")})
        # str(Decimal("0.1")) = "0.1"; float 변환 시 "0.1000...0055" 가 됨.
        assert out == "k=0.1"


# ---------------------------------------------------------------------------
# AC6 — fmt kwarg (ADR 0016 §1.4 Option iii + G2)
# ---------------------------------------------------------------------------
class TestAC6FmtKwarg:
    """render_full_period fmt="png"/"html" dispatch (ADR 0016)."""

    def test_default_fmt_returns_png_bytes(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """render_full_period(bars, trades, artifacts) — no fmt — returns PNG bytes (regression)."""
        pytest.importorskip("matplotlib")
        renderer = _DGTVisualizationRenderer()
        result = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        assert isinstance(result, bytes), "Default fmt must return bytes"
        assert result.startswith(_PNG_HEADER), "Default fmt must return valid PNG"

    def test_fmt_png_explicit_returns_png_bytes(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """render_full_period(..., fmt='png') returns PNG bytes."""
        pytest.importorskip("matplotlib")
        renderer = _DGTVisualizationRenderer()
        result = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts, fmt="png",
        )
        assert isinstance(result, bytes)
        assert result.startswith(_PNG_HEADER)

    def test_fmt_html_returns_str(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """render_full_period(..., fmt='html') returns non-empty str."""
        renderer = _DGTVisualizationRenderer()
        result = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts, fmt="html",
        )
        assert isinstance(result, str), "fmt='html' must return str"
        assert len(result) > 0, "fmt='html' must return non-empty string"

    def test_fmt_html_contains_lightweight_charts(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """fmt='html' output must embed the lightweight-charts JS reference."""
        renderer = _DGTVisualizationRenderer()
        html = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts, fmt="html",
        )
        assert "LightweightCharts" in html or "createChart" in html, (
            "fmt='html' output must embed lightweight-charts JS"
        )

    def test_fmt_html_contains_data_island(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """fmt='html' output contains a JSON data island with correct bar count."""
        import json
        import re
        renderer = _DGTVisualizationRenderer()
        html = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts, fmt="html",
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match, "fmt='html' output must contain a JSON data island"
        raw_json = match.group(1).strip().replace("<\\/", "</").replace("\\u2028", " ").replace("\\u2029", " ")
        data = json.loads(raw_json)
        assert len(data["ohlcv"]) == len(synthesized_bars), (
            f"OHLCV array length {len(data['ohlcv'])} != bars {len(synthesized_bars)}"
        )

    def test_fmt_html_graceful_degrade_no_artifacts(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """fmt='html' with artifacts=None returns valid HTML (graceful degradation)."""
        renderer = _DGTVisualizationRenderer()
        html = renderer.render_full_period(
            synthesized_bars, synthesized_trades, artifacts=None, fmt="html",
        )
        assert isinstance(html, str)
        assert "createChart" in html or "LightweightCharts" in html

    def test_fmt_html_grid_levels_serialized_when_artifacts(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """fmt='html' with artifacts includes grid level price-lines in data island."""
        import json
        import re
        renderer = _DGTVisualizationRenderer()
        html = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts, fmt="html",
        )
        match = re.search(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        assert match, "data island missing"
        raw_json = match.group(1).strip().replace("<\\/", "</").replace("\\u2028", " ").replace("\\u2029", " ")
        data = json.loads(raw_json)
        # synthesized_artifacts has 7 grid levels — at least one grid entry expected
        assert len(data["gridLevels"]) > 0, (
            "Grid levels must be serialized when artifacts are provided"
        )

    def test_fmt_html_zero_network_refs(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
    ) -> None:
        """fmt='html' output must be offline-self-contained (P5)."""
        import re
        renderer = _DGTVisualizationRenderer()
        html = renderer.render_full_period(
            synthesized_bars, synthesized_trades, artifacts=None, fmt="html",
        )
        network_refs = re.findall(
            r'<script[^>]+src=["\']https?://', html, re.IGNORECASE,
        )
        assert network_refs == [], f"fmt='html' must contain no network <script src>: {network_refs}"

    def test_fmt_html_empty_bars_raises(self) -> None:
        """fmt='html' with empty bars raises ValueError (same as fmt='png')."""
        renderer = _DGTVisualizationRenderer()
        with pytest.raises(ValueError, match="bars is empty"):
            renderer.render_full_period(bars=[], trades=[], artifacts=None, fmt="html")


# ---------------------------------------------------------------------------
# AC7 — Protocol structural typing after fmt kwarg addition (G2)
# ---------------------------------------------------------------------------
class TestAC7ProtocolStructuralTypingAfterFmt:
    """`_DGTVisualizationRenderer` still satisfies `_VisualizationRenderer` after fmt kwarg."""

    def test_isinstance_still_true_after_fmt(self) -> None:
        """isinstance check must pass after Protocol gained the fmt kwarg."""
        renderer = _DGTVisualizationRenderer()
        assert isinstance(renderer, _VisualizationRenderer), (
            "_DGTVisualizationRenderer must still satisfy _VisualizationRenderer Protocol "
            "after fmt kwarg addition (ADR 0016 §1.4 Option iii)"
        )

    def test_cli_caller_regression_no_fmt_kwarg(
        self,
        synthesized_bars: list[OHLCV],
        synthesized_trades: list[TradeView],
        synthesized_artifacts: _DGTVisualizationArtifacts,
    ) -> None:
        """cli.py:400 pattern — render_full_period called with no fmt → PNG bytes."""
        pytest.importorskip("matplotlib")
        renderer = _DGTVisualizationRenderer()
        # Mimics: dgt_renderer.render_full_period(bars, trades, artifacts)
        result = renderer.render_full_period(
            synthesized_bars, synthesized_trades, synthesized_artifacts,
        )
        assert isinstance(result, bytes), (
            "Existing cli.py:400 caller pattern (no fmt) must still return bytes"
        )
        assert result.startswith(_PNG_HEADER)
