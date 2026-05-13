"""Phase 0.11.c.4 — `_dgt_factory` tests.

ADR 0009 §1.3 정합:
  - D3 pattern A — trade view annotations 박제 via `_enrich_with_dgt_grid_level`.
  - D3 pattern B — single-snapshot sidecar (현 runner = 고정 reference).
  - Signed grid_level index 산출 정확성.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.domain.models import OHLCV, Asset, Currency, Money
from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner
from src.research.visualization._artifacts import (
    _DGTVisualizationArtifacts,
    _GridSnapshot,
)
from src.research.visualization._dgt_factory import (
    _build_dgt_visualization_artifacts,
    _dgt_trades_to_trade_views,
)

if TYPE_CHECKING:
    from src.research.dgt.cost_model import _KoreanMarketCostModel


@pytest.fixture
def dgt_run(
    kr_etf_069500: Asset,
    cost_model: _KoreanMarketCostModel,
) -> tuple[object, _DGTConfig]:
    """Synthesized 30-bar run that fires several BUY/SELL grid trades."""
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
    config = _DGTConfig(
        grid_count=4,
        grid_spacing_pct=Decimal("5"),
        levels_above=2,
    )
    runner = _DGTPrototypeRunner(cost_model=cost_model, config=config)
    result = runner.run(
        asset=kr_etf_069500,
        start=base_date,
        end=bars[-1].trade_date,
        initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
        ohlcv=bars,
    )
    return result, config


class TestAC1ArtifactsFactory:
    """`_build_dgt_visualization_artifacts` 산출 정확성."""

    def test_artifacts_type(self, dgt_run: tuple[object, _DGTConfig]) -> None:
        result, config = dgt_run
        artifacts = _build_dgt_visualization_artifacts(result, config)
        assert isinstance(artifacts, _DGTVisualizationArtifacts)

    def test_single_snapshot(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        """현 runner = 고정 reference → 단일 snapshot."""
        result, config = dgt_run
        artifacts = _build_dgt_visualization_artifacts(result, config)
        assert len(artifacts.grid_history) == 1
        assert len(artifacts.reference_price_curve) == 1

    def test_grid_snapshot_levels_match(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        result, config = dgt_run
        artifacts = _build_dgt_visualization_artifacts(result, config)
        snap: _GridSnapshot = artifacts.grid_history[0]
        assert list(snap.levels) == list(result.grid_levels)  # type: ignore[attr-defined]
        assert snap.reference_price == result.reference_price  # type: ignore[attr-defined]

    def test_parameter_config_complete(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        result, config = dgt_run
        artifacts = _build_dgt_visualization_artifacts(result, config)
        assert artifacts.parameter_config["n"] == config.grid_count
        assert artifacts.parameter_config["k"] == config.grid_spacing_pct
        assert artifacts.parameter_config["m"] == config.levels_above

    def test_period_fields_match(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        result, config = dgt_run
        artifacts = _build_dgt_visualization_artifacts(result, config)
        assert artifacts.period_start == result.start  # type: ignore[attr-defined]
        assert artifacts.period_end == result.end  # type: ignore[attr-defined]
        assert artifacts.asset_code == result.asset.code  # type: ignore[attr-defined]


class TestAC2TradesToTradeViews:
    """`_dgt_trades_to_trade_views` 산출 정확성."""

    def test_count_matches(self, dgt_run: tuple[object, _DGTConfig]) -> None:
        result, config = dgt_run
        views = _dgt_trades_to_trade_views(result, config)
        assert len(views) == len(result.trades)  # type: ignore[attr-defined]

    def test_annotations_present(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        result, config = dgt_run
        views = _dgt_trades_to_trade_views(result, config)
        assert views, "Synthesized run should produce at least one trade"
        for v in views:
            assert "dgt_grid_level" in v.annotations
            assert "dgt_reference_price" in v.annotations

    def test_strategy_id_is_dgt(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        result, config = dgt_run
        views = _dgt_trades_to_trade_views(result, config)
        for v in views:
            assert v.strategy_id == "dgt"

    def test_decimal_price_quantity(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        result, config = dgt_run
        views = _dgt_trades_to_trade_views(result, config)
        for v in views:
            assert isinstance(v.price, Decimal)
            assert isinstance(v.quantity, Decimal)

    def test_signed_grid_level_in_range(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        """Signed level index ∈ [-(n-m), m] — 논문 Table 1 정합."""
        result, config = dgt_run
        views = _dgt_trades_to_trade_views(result, config)
        max_above = config.levels_above
        min_below = -(config.grid_count - config.levels_above)
        for v in views:
            signed = int(v.annotations["dgt_grid_level"])
            assert min_below <= signed <= max_above, (
                f"signed level {signed} outside [{min_below}, {max_above}]"
            )

    def test_reference_price_annotation_matches(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        """모든 trade 의 reference_price annotation = result.reference_price."""
        result, config = dgt_run
        views = _dgt_trades_to_trade_views(result, config)
        expected = str(result.reference_price)  # type: ignore[attr-defined]
        for v in views:
            assert v.annotations["dgt_reference_price"] == expected


class TestAC3ArtifactsFeedsRenderer:
    """Factory 산출이 `_DGTVisualizationRenderer` 입력으로 통과."""

    def test_render_full_period_works(
        self, dgt_run: tuple[object, _DGTConfig],
    ) -> None:
        pytest.importorskip("matplotlib")
        from src.research.visualization._dgt_renderer import (
            _DGTVisualizationRenderer,
        )

        result, config = dgt_run
        artifacts = _build_dgt_visualization_artifacts(result, config)
        trades = _dgt_trades_to_trade_views(result, config)
        renderer = _DGTVisualizationRenderer()
        # daily_snapshots only have (date, close) — synthesize OHLCV via
        # OHLC=close. Simplest path to verify renderer accepts the input.
        bars: list[OHLCV] = []
        for snap in result.daily_snapshots:  # type: ignore[attr-defined]
            bars.append(
                OHLCV(
                    asset=result.asset,  # type: ignore[attr-defined]
                    trade_date=snap.trade_date,
                    open=snap.close_price,
                    high=snap.close_price,
                    low=snap.close_price,
                    close=snap.close_price,
                    volume=Decimal("1000"),
                )
            )
        png = renderer.render_full_period(
            bars=bars, trades=trades, artifacts=artifacts,
        )
        assert png.startswith(b"\x89PNG"), "render should produce PNG"
