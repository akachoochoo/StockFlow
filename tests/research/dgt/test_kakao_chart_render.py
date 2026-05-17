"""Phase 0.11.h — Chart-render tests for kakao_dgt_backtest.py.

ADR 0015 Test Plan: test_kakao_chart_render tests.

Pattern: pytest.importorskip("matplotlib"); synthetic OHLCV + _DGTBacktestResult
fixtures. _build_comparison_figure / _build_per_stock_figure called directly
to assert panel counts without savefig overhead.

Figure-leak invariant: every test that calls _build_*_figure() directly MUST
plt.close(fig) in a finally block (P4 / ADR 0015 R5).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

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

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# Fixture helpers
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
    """n synthetic daily OHLCV bars."""
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


def _make_snapshot(d: date, total_value: Decimal) -> _DGTSnapshot:
    return _DGTSnapshot(
        trade_date=d,
        cash=total_value,
        holdings=Decimal("0"),
        close_price=Decimal("50000"),
        total_value=total_value,
    )


def _make_result(
    bars: list[OHLCV],
    asset: Asset | None = None,
    capital: Decimal = Decimal("10_000_000"),
) -> _DGTBacktestResult:
    """Build a _DGTBacktestResult whose daily_snapshots match bars exactly (R10)."""
    if asset is None:
        asset = bars[0].asset
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
        grid_levels=[bars[0].close],
        trades=[],
        daily_snapshots=snapshots,
    )


def _make_config() -> _DGTConfig:
    return _DGTConfig(grid_count=11, grid_spacing_pct=Decimal("5"), levels_above=5)


# ---------------------------------------------------------------------------
# test_comparison_chart — _render_comparison_chart + _build_comparison_figure
# ---------------------------------------------------------------------------
class TestComparisonChart:
    """`_render_comparison_chart` and `_build_comparison_figure` tests."""

    def test_comparison_chart_returns_png(self) -> None:
        """_render_comparison_chart returns bytes starting with PNG header, len>1000."""
        pytest.importorskip("matplotlib")
        from src.research.dgt.kakao_dgt_backtest import _render_comparison_chart

        bars = _make_bars(30)
        result = _make_result(bars)
        config = _make_config()
        png = _render_comparison_chart([("Static", result)], bars, config)
        assert isinstance(png, bytes)
        assert png[:8] == _PNG_HEADER, "must return valid PNG bytes"
        assert len(png) > 1000, f"PNG too small: {len(png)}"

    def test_comparison_chart_panel_count(self) -> None:
        """_build_comparison_figure returns fig with n_strategies + 2 axes."""
        plt = pytest.importorskip("matplotlib.pyplot")
        from src.research.dgt.kakao_dgt_backtest import _build_comparison_figure

        bars = _make_bars(30)
        n_strategies = 2
        results = [
            ("Static", _make_result(bars)),
            ("Paper", _make_result(bars)),
        ]
        config = _make_config()
        fig, axes = _build_comparison_figure(results, bars, config)
        try:
            assert len(fig.axes) == n_strategies + 2, (
                f"expected {n_strategies + 2} axes (N price + 1 volume + 1 equity), "
                f"got {len(fig.axes)}"
            )
        finally:
            plt.close(fig)

    def test_comparison_chart_panel_count_single_strategy(self) -> None:
        """1 strategy → 3 axes (1 price + 1 volume + 1 equity)."""
        plt = pytest.importorskip("matplotlib.pyplot")
        from src.research.dgt.kakao_dgt_backtest import _build_comparison_figure

        bars = _make_bars(20)
        results = [("Static", _make_result(bars))]
        config = _make_config()
        fig, axes = _build_comparison_figure(results, bars, config)
        try:
            assert len(fig.axes) == 3
        finally:
            plt.close(fig)

    def test_comparison_chart_figure_leak(self) -> None:
        """plt.get_fignums() == [] before and after _render_comparison_chart (R-leak)."""
        plt = pytest.importorskip("matplotlib.pyplot")
        from src.research.dgt.kakao_dgt_backtest import _render_comparison_chart

        plt.close("all")
        baseline = plt.get_fignums()
        bars = _make_bars(20)
        result = _make_result(bars)
        config = _make_config()
        _render_comparison_chart([("Static", result)], bars, config)
        after = plt.get_fignums()
        assert after == baseline, f"figure leak: baseline={baseline}, after={after}"


# ---------------------------------------------------------------------------
# test_per_stock_chart — _render_per_stock_charts + _build_per_stock_figure
# ---------------------------------------------------------------------------
class TestPerStockChart:
    """`_render_per_stock_charts` and `_build_per_stock_figure` tests."""

    def test_per_stock_chart_returns_png(self) -> None:
        """_render_per_stock_charts returns dict; each value is valid PNG bytes."""
        pytest.importorskip("matplotlib")
        from src.research.dgt.kakao_dgt_backtest import _render_per_stock_charts

        asset = _make_asset("069500")
        bars = _make_bars(20, asset)
        result = _make_result(bars, asset)
        config = _make_config()
        pngs = _render_per_stock_charts(
            assets=[asset],
            bars_map={"069500": bars},
            strategy_per_stock={"Static": [result]},
            config=config,
        )
        assert "069500" in pngs
        png = pngs["069500"]
        assert isinstance(png, bytes)
        assert png[:8] == _PNG_HEADER, "must return valid PNG bytes"
        assert len(png) > 1000, f"PNG too small: {len(png)}"

    def test_per_stock_chart_panel_count(self) -> None:
        """_build_per_stock_figure returns fig with n_strats + 1 axes."""
        plt = pytest.importorskip("matplotlib.pyplot")
        from src.research.dgt.kakao_dgt_backtest import _build_per_stock_figure

        asset = _make_asset("069500")
        bars = _make_bars(20, asset)
        n_strats = 2
        strategy_per_stock = {
            "Static": [_make_result(bars, asset)],
            "Paper": [_make_result(bars, asset)],
        }
        strategy_labels = list(strategy_per_stock.keys())
        config = _make_config()
        fig, axes = _build_per_stock_figure(
            asset=asset,
            bars=bars,
            stock_idx=0,
            strategy_labels=strategy_labels,
            strategy_per_stock=strategy_per_stock,
            config=config,
        )
        try:
            assert len(fig.axes) == n_strats + 1, (
                f"expected {n_strats + 1} axes (N price + 1 volume), "
                f"got {len(fig.axes)}"
            )
        finally:
            plt.close(fig)

    def test_per_stock_chart_panel_count_single_strategy(self) -> None:
        """1 strategy → 2 axes (1 price + 1 volume)."""
        plt = pytest.importorskip("matplotlib.pyplot")
        from src.research.dgt.kakao_dgt_backtest import _build_per_stock_figure

        asset = _make_asset("069500")
        bars = _make_bars(20, asset)
        strategy_per_stock = {"Static": [_make_result(bars, asset)]}
        config = _make_config()
        fig, axes = _build_per_stock_figure(
            asset=asset,
            bars=bars,
            stock_idx=0,
            strategy_labels=["Static"],
            strategy_per_stock=strategy_per_stock,
            config=config,
        )
        try:
            assert len(fig.axes) == 2
        finally:
            plt.close(fig)

    def test_per_stock_chart_figure_leak(self) -> None:
        """plt.get_fignums() == [] after _render_per_stock_charts."""
        plt = pytest.importorskip("matplotlib.pyplot")
        from src.research.dgt.kakao_dgt_backtest import _render_per_stock_charts

        plt.close("all")
        baseline = plt.get_fignums()
        asset = _make_asset("069500")
        bars = _make_bars(20, asset)
        result = _make_result(bars, asset)
        config = _make_config()
        _render_per_stock_charts(
            assets=[asset],
            bars_map={"069500": bars},
            strategy_per_stock={"Static": [result]},
            config=config,
        )
        after = plt.get_fignums()
        assert after == baseline, f"figure leak: baseline={baseline}, after={after}"


# ---------------------------------------------------------------------------
# test_grid_envelope_still_drawn — P3 overlay preservation
# ---------------------------------------------------------------------------
class TestGridEnvelopePreserved:
    """After candle switch, _draw_grid_levels still adds fill_between to price axis."""

    def test_grid_envelope_still_drawn(self) -> None:
        """_draw_grid_levels on returned price axes adds a PolyCollection (fill_between)."""
        plt = pytest.importorskip("matplotlib.pyplot")
        import matplotlib.collections as mcollections
        from src.research.dgt.kakao_dgt_backtest import (
            _build_comparison_figure,
            _draw_grid_levels,
        )

        bars = _make_bars(30)
        result = _make_result(bars)
        config = _make_config()
        fig, axes = _build_comparison_figure([("Static", result)], bars, config)
        try:
            price_ax = axes[0]
            dates = [b.trade_date for b in bars]
            # Call _draw_grid_levels on the price axis — it uses fill_between
            # for the envelope band when there are multiple bars.
            _draw_grid_levels(price_ax, result, dates, config, mode="static")
            # fill_between adds a PolyCollection to the axis
            poly_collections = [
                c for c in price_ax.collections
                if isinstance(c, mcollections.PolyCollection)
            ]
            assert len(poly_collections) > 0, (
                "grid envelope fill_between (PolyCollection) not found on price axis — "
                "overlay (P3) broken after candle switch"
            )
        finally:
            plt.close(fig)


# ---------------------------------------------------------------------------
# test_candle_and_grid_share_x_domain — R10 mitigation
# ---------------------------------------------------------------------------
class TestXDomainAlignment:
    """R10: bars trade_dates must match result.daily_snapshots trade_dates."""

    def test_candle_and_grid_share_x_domain(self) -> None:
        """bars dates == daily_snapshots dates on synthetic fixtures (R10 invariant)."""
        bars = _make_bars(20)
        result = _make_result(bars)
        bar_dates = [b.trade_date for b in bars]
        snap_dates = [s.trade_date for s in result.daily_snapshots]
        assert bar_dates == snap_dates, (
            "bar dates and snapshot dates must match exactly (R10)"
        )

    def test_r10_assertion_fires_on_mismatch(self) -> None:
        """_build_comparison_figure raises AssertionError when dates mismatch."""
        pytest.importorskip("matplotlib")
        from src.research.dgt.kakao_dgt_backtest import _build_comparison_figure

        bars = _make_bars(20)
        result = _make_result(bars)
        # Truncate bars so len(bars) != len(snapshots) — triggers R10 assertion.
        short_bars = bars[:10]
        config = _make_config()
        with pytest.raises(AssertionError, match="R10 violation"):
            _build_comparison_figure([("Static", result)], short_bars, config)


# ---------------------------------------------------------------------------
# test_density_5year_render_sane — DD3 density check
# ---------------------------------------------------------------------------
class TestDensityRender:
    """~1250 synthetic bars produce a valid PNG of sane size."""

    def test_density_5year_render_sane(self) -> None:
        """Render with ~1250 synthetic bars → PNG produced, len within sane band."""
        pytest.importorskip("matplotlib")
        from src.research.dgt.kakao_dgt_backtest import _render_comparison_chart

        bars = _make_bars(1250)
        result = _make_result(bars)
        config = _make_config()
        png = _render_comparison_chart([("Static", result)], bars, config)
        assert png[:8] == _PNG_HEADER
        # Sanity band: must be > 10 KB (non-trivial render) and < 10 MB (no blow-up).
        assert len(png) > 10_000, f"PNG suspiciously small at {len(png)} bytes"
        assert len(png) < 10_000_000, f"PNG suspiciously large at {len(png)} bytes"
