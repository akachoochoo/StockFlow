"""Grid (DGT) multi-asset portfolio backtest aggregator (ADR 0022 §11 D13).

``grid-backtest --config`` 가 여러 종목을 한 번에 돌릴 때, 종목별로 ``GridRunner``
를 **독립 실행**(D9 격리 — GridRunner 는 단일 asset 자기완결)하고 일별 가치를
합산해 포트폴리오 수익/MDD 산출을 가능케 한다. BacktestRunner(split 조합 엔진)와
무관한 별도 application 함수 — grid 패러다임은 자본 배분 외 종목 간 상호작용이
없다(D8: DGT = 1종 집중 MDD 방어 도구, 멀티는 편의).

자본 배분 = **균등 분할**(``capital // N`` per asset). 나머지(``capital % N``)는
미투자 현금으로 포트폴리오 가치에 상수로 더해진다(초기자본 보존).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.models import Money
from src.use_cases.grid_runner import GridRunner

if TYPE_CHECKING:
    from datetime import date

    from src.domain.cost_model import KoreanMarketCostModel
    from src.domain.models import OHLCV, Asset
    from src.domain.strategies.grid import GridConfig
    from src.use_cases.grid_runner import GridRunResult


@dataclass(frozen=True)
class GridAssetInput:
    """One asset's backtest inputs (asset + windowed bars + its GridConfig)."""

    asset: Asset
    bars: list[OHLCV]
    config: GridConfig


@dataclass(frozen=True)
class GridAssetRun:
    """One asset's allocated capital + GridRunner result."""

    asset: Asset
    allocated: Money
    result: GridRunResult


@dataclass(frozen=True)
class GridPortfolioResult:
    """Aggregated multi-asset DGT backtest.

    ``daily_values`` is the portfolio total value on each date common to all
    assets (sum of per-asset ``total_value`` + constant ``unallocated`` cash).
    """

    initial_capital: Money
    unallocated: Decimal
    per_asset: list[GridAssetRun]
    daily_values: list[tuple[date, Decimal]]
    final_value: Decimal


def run_grid_portfolio(
    inputs: list[GridAssetInput],
    *,
    initial_capital: Money,
    cost_model: KoreanMarketCostModel | None = None,
) -> GridPortfolioResult:
    """Run ``GridRunner`` per asset on an equal capital split, then aggregate.

    Raises:
        ValueError: empty ``inputs`` (or propagated from ``GridRunner`` —
            empty bars / currency mismatch).
    """
    if not inputs:
        raise ValueError("inputs must be non-empty")

    currency = initial_capital.currency
    n = len(inputs)
    per_asset_amount = initial_capital.amount // n  # Decimal floor → whole KRW
    unallocated = initial_capital.amount - per_asset_amount * n

    runner = GridRunner(cost_model)
    runs: list[GridAssetRun] = []
    series: list[dict[date, Decimal]] = []
    for inp in inputs:
        allocated = Money(amount=per_asset_amount, currency=currency)
        result = runner.run(
            asset=inp.asset,
            bars=inp.bars,
            config=inp.config,
            initial_capital=allocated,
        )
        runs.append(
            GridAssetRun(asset=inp.asset, allocated=allocated, result=result)
        )
        series.append({d.trade_date: d.total_value for d in result.daily_values})

    # Portfolio timeline = dates common to every asset (consistent value series
    # even when CSV windows differ slightly). Single-asset → that asset's dates.
    common: set[date] = set(series[0])
    for s in series[1:]:
        common &= set(s)
    daily_values = [
        (d, sum((s[d] for s in series), Decimal("0")) + unallocated)
        for d in sorted(common)
    ]
    final_value = (
        sum((r.result.final_value for r in runs), Decimal("0")) + unallocated
    )
    return GridPortfolioResult(
        initial_capital=initial_capital,
        unallocated=unallocated,
        per_asset=runs,
        daily_values=daily_values,
        final_value=final_value,
    )
