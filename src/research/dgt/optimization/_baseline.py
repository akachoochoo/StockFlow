"""Phase 0.11.b — D7 4-way baseline (sub-step .3, ADR 0008 §1.6 D7).

4 baselines:
    (i) Phase 0.7.3 정본 verbatim — `phase-0.11.a-comparison.md` §1 수치 인용.
    (ii) 069500 단독 Buy-and-Hold — 신규 실행 (full period).
    (iii) 069500 단독 세븐스플릿 — 재실행 (KIS regime 정합).
    (iv) 069500 단독 DGT (튜닝 후 best) — `_run_wfo_grid` best 후보.

Decimal-only (CLAUDE.md §2.1). Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.models import OHLCV, Asset, Currency, Money
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.optimization._grid_runner import (
    _GridPointResult,
    _fold_metrics_from_result,
)
from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner


_INITIAL_CAPITAL_KRW = Decimal("10000000")  # 10M KRW (Phase 0.11.a 정합)
_TRADING_DAYS_PER_YEAR = Decimal("252")


@dataclass(frozen=True)
class _BaselineMetrics:
    """4 baselines 공통 metrics view."""

    label: str
    cagr_pct: Decimal
    mdd_pct: Decimal
    sharpe: Decimal
    calmar: Decimal
    trade_count: int
    note: str = ""


def _phase_073_baseline_verbatim() -> _BaselineMetrics:
    """(i) Phase 0.7.3 정본 — `phase-0.11.a-comparison.md` §1 verbatim.

    (069500 + 132030 EQUAL, PriceDropStrategy, 2020-01-02 ~ 2024-12-30,
    initial capital 100M KRW).
    """
    return _BaselineMetrics(
        label="Phase 0.7.3 (069500+132030 EQUAL)",
        cagr_pct=Decimal("2.5779"),
        mdd_pct=Decimal("-8.2737"),
        sharpe=Decimal("0.5255"),
        calmar=Decimal("0.3116"),
        trade_count=28,
        note="verbatim from phase-0.11.a-comparison.md §1",
    )


def _run_buy_and_hold(
    bars: list[OHLCV],
    asset: Asset,
    *,
    initial_capital_krw: Decimal = _INITIAL_CAPITAL_KRW,
) -> _BaselineMetrics:
    """(ii) 069500 단독 Buy-and-Hold — D7 fairness baseline.

    Day-0 close 에 100% 매수 → 마지막 day close 에 100% 매도.
    KoreanMarketCostModel: compute_buy_cost (1회) + compute_sell_cost (1회).
    """
    if len(bars) < 2:
        raise ValueError(f"bars too short for B&H: {len(bars)}")

    cost_model = _KoreanMarketCostModel()
    initial = initial_capital_krw
    day0_close = bars[0].close
    # Buy quantity — allocate full capital (floor to lot size).
    rounded_buy_price = asset.round_to_tick(day0_close)
    # quantity floor
    raw_qty = initial / rounded_buy_price
    quantity = raw_qty.quantize(Decimal("1"), rounding="ROUND_DOWN")
    if quantity <= 0:
        raise ValueError("insufficient capital to buy any quantity")
    buy_cost = cost_model.compute_buy_cost(
        price=day0_close, quantity=quantity, asset=asset
    )
    if buy_cost.total_cost > initial:
        # 한 단위 줄여 재시도
        quantity -= Decimal("1")
        if quantity <= 0:
            raise ValueError("insufficient capital after rounding")
        buy_cost = cost_model.compute_buy_cost(
            price=day0_close, quantity=quantity, asset=asset
        )

    cash_after_buy = initial - buy_cost.total_cost

    # Build daily portfolio value series — cash + holdings × close.
    values: list[Decimal] = []
    for bar in bars:
        values.append(cash_after_buy + quantity * bar.close)

    # Final SELL on last bar close.
    sell_cost = cost_model.compute_sell_cost(
        price=bars[-1].close, quantity=quantity, asset=asset
    )
    # Override final value with net proceeds + cash_after_buy.
    final_total = cash_after_buy + sell_cost.net_proceeds
    values[-1] = final_total

    # Compute metrics.
    return _compute_baseline_metrics(
        label="069500 Buy-and-Hold",
        values=values,
        trade_count=2,  # 1 BUY + 1 SELL
        note=(
            f"qty={quantity} day0_close={day0_close} "
            f"final_close={bars[-1].close}"
        ),
    )


def _run_seven_split_dgt_proxy(
    bars: list[OHLCV],
    asset: Asset,
    *,
    initial_capital_krw: Decimal = _INITIAL_CAPITAL_KRW,
) -> _BaselineMetrics:
    """(iii) 069500 단독 세븐스플릿 proxy — DGT runner 의 7-grid 근사.

    Note: 본 sub-step (.3) 은 `src/application/backtest_runner.py` 의
    PriceDropStrategy 직접 호출이 *production rings 변경 zero* 제약과
    충돌 가능 (DGT optimization 모듈은 `src/research/dgt/optimization/`
    5th ring isolation). 따라서:

      - 정합 path: `BacktestRunner` 직접 호출 (Phase 0.7.3 정합) — 5th
        ring → inner ring read 만 발생 (CLAUDE.md §1.1 outer→inner OK).
      - 단순화 path (본 함수): DGT runner 의 grid_count=7 + spacing=5% +
        levels_above=3 (Phase 0.11.a 정합) 적용. PriceDropStrategy 정신
        과 의미 다름 (grid mechanism ≠ split entry) — **D7 (iii) 의 KIS
        regime 정합 정신은 cost_model 공유만 박제**.

    Decision: 정합 path 채택 (BacktestRunner 직접 호출).
    """
    # 정합 path — Phase 0.7.3 baseline 정합 (PriceDropStrategy 단독 069500).
    return _run_seven_split_baseline_runner(
        bars=bars,
        asset=asset,
        initial_capital_krw=initial_capital_krw,
    )


def _run_seven_split_baseline_runner(
    bars: list[OHLCV],
    asset: Asset,
    *,
    initial_capital_krw: Decimal,
) -> _BaselineMetrics:
    """PriceDropStrategy 단독 069500 — `BacktestRunner` 직접 호출.

    5th ring (research overlay) → inner ring (application) read 만 발생
    (CLAUDE.md §1.1 outer→inner OK). production rings 변경 zero (read-only).

    config (Phase 0.7.3 정합, `config/strategies-0.7.3.yaml`):
        - drop_threshold_pct = 5.0%
        - max_split_count = 7
        - per_split_amount = capital / 7
        - max_split_per_day = 1
        - profit_target_pct = 10.0%
        - reentry = hybrid (cooldown 60)
    """
    from src.application.backtest_runner import BacktestRunner
    from src.domain.strategies.price_drop import SplitStrategyConfig
    from src.domain.strategies.profit_target import SellStrategyConfig

    per_split = (initial_capital_krw / Decimal("7")).quantize(Decimal("1"))
    strategy_config = SplitStrategyConfig(
        drop_threshold_pct=Decimal("5.0"),
        max_split_count=7,
        per_split_amount=Money(amount=per_split, currency=Currency.KRW),
        max_split_per_day=1,
    )
    sell_config = SellStrategyConfig(
        profit_target_pct=Decimal("10.0"),
        max_sells_per_day=7,
    )
    runner = BacktestRunner(
        assets=[asset],
        strategy_config=strategy_config,
        initial_capital=Money(amount=initial_capital_krw, currency=Currency.KRW),
        ohlcv_by_asset={asset: bars},
        sell_strategy_config=sell_config,
        reentry_strategy_name="hybrid",
        reentry_parameters={"cooldown_days": 60},
    )
    result = runner.run(bars[0].trade_date, bars[-1].trade_date)

    # trade_count = buy_action 있는 결정 + sell_actions 누적 합.
    buy_decisions = sum(
        1 for d in result.decisions if d.buy_action is not None
    )
    sell_decisions = sum(len(d.sell_actions) for d in result.decisions)
    trade_count = buy_decisions + sell_decisions

    return _BaselineMetrics(
        label="069500 SevenSplit (re-run, KIS regime)",
        cagr_pct=result.cagr_pct,
        mdd_pct=result.max_drawdown_pct,
        sharpe=result.sharpe_ratio,
        calmar=result.calmar_ratio,
        trade_count=trade_count,
        note="BacktestRunner 직접 호출 (PriceDropStrategy + ProfitTargetSell)",
    )


def _run_dgt_best_full_period(
    bars: list[OHLCV],
    asset: Asset,
    best_point: _GridPointResult,
    *,
    initial_capital_krw: Decimal = _INITIAL_CAPITAL_KRW,
) -> _BaselineMetrics:
    """(iv) 069500 단독 DGT (튜닝 후 best) — `_WFOGridResult` 최적 점 full-period 재실행.

    WFO fold mean 이 아닌 full-period 단일 run — 본 sub-step .3 의 informational
    "튜닝 후 단일 실행" 측면.
    """
    config = _DGTConfig(
        grid_count=best_point.config_n,
        grid_spacing_pct=best_point.config_k_pct,
        levels_above=best_point.config_m,
    )
    cost_model = _KoreanMarketCostModel()
    runner = _DGTPrototypeRunner(cost_model=cost_model, config=config)
    result = runner.run(
        asset=asset,
        start=bars[0].trade_date,
        end=bars[-1].trade_date,
        initial_capital=Money(amount=initial_capital_krw, currency=Currency.KRW),
        ohlcv=bars,
    )
    fm = _fold_metrics_from_result(result)
    return _BaselineMetrics(
        label=(
            f"069500 DGT-best (n={best_point.config_n} "
            f"k={best_point.config_k_pct}% m={best_point.config_m})"
        ),
        cagr_pct=fm.cagr_pct,
        mdd_pct=fm.mdd_pct,
        sharpe=fm.sharpe,
        calmar=fm.calmar,
        trade_count=fm.trade_count,
        note="full-period DGT run (no WFO split)",
    )


def _run_baselines(
    bars_069500: list[OHLCV],
    asset_069500: Asset,
    best_dgt_point: _GridPointResult,
    *,
    initial_capital_krw: Decimal = _INITIAL_CAPITAL_KRW,
) -> dict[str, _BaselineMetrics]:
    """D7 4-way baseline 종합 실행.

    Args:
        bars_069500: 069500 full-period OHLCV.
        asset_069500: 069500 Asset.
        best_dgt_point: WFO grid 의 OOS Sharpe 최대 grid point.
        initial_capital_krw: 단일 baseline 초기 자본.

    Returns:
        {(i)~(iv)} dict of `_BaselineMetrics`.
    """
    return {
        "(i) Phase 0.7.3 verbatim": _phase_073_baseline_verbatim(),
        "(ii) 069500 B&H": _run_buy_and_hold(
            bars=bars_069500,
            asset=asset_069500,
            initial_capital_krw=initial_capital_krw,
        ),
        "(iii) 069500 SevenSplit": _run_seven_split_dgt_proxy(
            bars=bars_069500,
            asset=asset_069500,
            initial_capital_krw=initial_capital_krw,
        ),
        "(iv) 069500 DGT-best": _run_dgt_best_full_period(
            bars=bars_069500,
            asset=asset_069500,
            best_point=best_dgt_point,
            initial_capital_krw=initial_capital_krw,
        ),
    }


def _compute_baseline_metrics(
    *,
    label: str,
    values: list[Decimal],
    trade_count: int,
    note: str = "",
) -> _BaselineMetrics:
    """portfolio value 시계열 → CAGR / MDD / Sharpe / Calmar 산출."""
    if len(values) < 2:
        return _BaselineMetrics(
            label=label,
            cagr_pct=Decimal("0"),
            mdd_pct=Decimal("0"),
            sharpe=Decimal("0"),
            calmar=Decimal("0"),
            trade_count=trade_count,
            note=note,
        )

    initial = values[0]
    final = values[-1]
    n = len(values)
    years = Decimal(n - 1) / _TRADING_DAYS_PER_YEAR
    if initial > 0 and final > 0 and years > 0:
        ratio = final / initial
        cagr_pct = ((ratio.ln() / years).exp() - Decimal(1)) * Decimal(100)
    else:
        cagr_pct = Decimal("0")

    peak = values[0]
    max_dd = Decimal("0")
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
    mdd_pct = max_dd * Decimal("100")

    daily_rets: list[Decimal] = []
    for prev, curr in zip(values[:-1], values[1:]):
        if prev > 0:
            daily_rets.append((curr - prev) / prev)

    sharpe = Decimal("0")
    if len(daily_rets) >= 2:
        mean_r = sum(daily_rets, Decimal("0")) / Decimal(len(daily_rets))
        var = sum(
            ((r - mean_r) ** 2 for r in daily_rets), Decimal("0")
        ) / Decimal(len(daily_rets) - 1)
        if var > 0:
            std_r = var.sqrt()
            if std_r > 0:
                sharpe = mean_r / std_r * _TRADING_DAYS_PER_YEAR.sqrt()

    abs_mdd = abs(mdd_pct)
    calmar = cagr_pct / abs_mdd if abs_mdd > 0 else Decimal("0")

    return _BaselineMetrics(
        label=label,
        cagr_pct=cagr_pct,
        mdd_pct=mdd_pct,
        sharpe=sharpe,
        calmar=calmar,
        trade_count=trade_count,
        note=note,
    )


__all__: list[str] = []
