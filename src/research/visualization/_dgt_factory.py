"""Phase 0.11.c.4 — `_DGTBacktestResult` → visualization 입력 factory.

DGT prototype runner 산출 (`_DGTBacktestResult`) 을 visualization Protocol
입력 (`_DGTVisualizationArtifacts` + `list[TradeView]`) 으로 변환.

ADR 0009 §1.3 정합:
- D3 pattern A — `_dgt_trades_to_trade_views` 가 `_DGTTrade` → `TradeView`
  변환 시 `_enrich_with_dgt_grid_level` helper 로 annotations 박제.
- D3 pattern B — `_build_dgt_visualization_artifacts` 가 single-snapshot
  sidecar 박제 (현 runner = 고정 reference).

Lifecycle (ADR 0009 §1.7): permanent. Underscore-prefix private
(ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from src.application.reporting.trade_view import SideT, TradeView
from src.research.visualization._artifacts import (
    _DGTVisualizationArtifacts,
    _GridSnapshot,
)
from src.research.visualization._trade_view_enrichment import (
    _enrich_with_dgt_grid_level,
)

if TYPE_CHECKING:
    from src.research.dgt.results import _DGTBacktestResult
    from src.research.dgt.runner import _DGTConfig


__all__: list[str] = []


def _build_dgt_visualization_artifacts(
    result: _DGTBacktestResult,
    config: _DGTConfig,
) -> _DGTVisualizationArtifacts:
    """`_DGTBacktestResult` → `_DGTVisualizationArtifacts` (D3 pattern B).

    현 runner = 고정 reference (`ohlcv[0].close`) → 단일 `_GridSnapshot`
    + 단일 reference entry. 미래 re-anchor 도입 시 본 factory 가 다중
    snapshot 산출하도록 확장 (sub-step 별도 ADR).

    Args:
        result: DGT runner 산출.
        config: 동일 run 의 `_DGTConfig` — parameter_config (n/k/m) 박제.

    Returns:
        `_DGTVisualizationArtifacts` — visualization renderer 입력.
    """
    snapshot_ts = datetime(
        result.start.year,
        result.start.month,
        result.start.day,
        tzinfo=UTC,
    )
    snapshot = _GridSnapshot(
        timestamp=snapshot_ts,
        reference_price=result.reference_price,
        levels=list(result.grid_levels),
        triggered_level=None,
    )
    return _DGTVisualizationArtifacts(
        grid_history=[snapshot],
        reference_price_curve=[(snapshot_ts, result.reference_price)],
        parameter_config={
            "n": config.grid_count,
            "k": config.grid_spacing_pct,
            "m": config.levels_above,
        },
        asset_code=result.asset.code,
        period_start=result.start,
        period_end=result.end,
    )


def _dgt_trades_to_trade_views(
    result: _DGTBacktestResult,
    config: _DGTConfig,
) -> list[TradeView]:
    """`_DGTTrade` list → `list[TradeView]` + DGT annotations.

    각 trade 의 `grid_level_price` 를 `result.grid_levels` 에서 검색해
    signed index (m offset 기준) 산출 후 `_enrich_with_dgt_grid_level`
    helper 로 annotations 박제 (D3 pattern A precedent).

    Signed index 공식 (Phase 0.11.a `grid_levels_table1` 정합):
        levels[i] = ref · (1 + k)^(i - levels_below)
        levels_below = n - m
        signed_index = i - levels_below

    Args:
        result: DGT runner 산출.
        config: 동일 run 의 `_DGTConfig` — levels_above 산출용.

    Returns:
        `list[TradeView]` — DGT 전략의 trade 시계열 (timestamp 오름차순).
    """
    levels = list(result.grid_levels)
    levels_below = config.grid_count - config.levels_above
    asset_code = result.asset.code
    reference_price = result.reference_price

    trade_views: list[TradeView] = []
    for trade in result.trades:
        try:
            idx = levels.index(trade.grid_level_price)
        except ValueError:
            # Defensive — level 매칭 실패 시 0 fallback (정상 runner 에서
            # 발생 X). enrich 가 dict 변경하므로 raise 대신 graceful.
            signed_index = 0
        else:
            signed_index = idx - levels_below

        annotations: dict[str, str] = {}
        side_literal = cast("SideT", trade.side)
        _enrich_with_dgt_grid_level(
            annotations,
            grid_level=signed_index,
            reference_price=reference_price,
            asset_code=asset_code,
            side=side_literal,
        )
        # UTC midnight (DGT 일봉 — 시점 정보 없음)
        ts = datetime(
            trade.trade_date.year,
            trade.trade_date.month,
            trade.trade_date.day,
            tzinfo=UTC,
        )
        trade_views.append(
            TradeView(
                timestamp=ts,
                symbol=asset_code,
                side=side_literal,
                price=trade.rounded_price,
                quantity=Decimal(trade.quantity),
                strategy_id="dgt",
                annotations=annotations,
            )
        )
    return trade_views
