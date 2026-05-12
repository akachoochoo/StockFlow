"""Phase 0.11.b — WFO grid runner (sub-step .3, ADR 0008 §1.8 + §1.11).

Walk-Forward Optimization 그리드 탐색. 각 grid point (n / k / m) 에 대해
n_folds (default 5) WFO split → train bars (IS) + test bars (OOS) 양쪽에
`_DGTPrototypeRunner.run` 실행 → CAGR / MDD / Sharpe / Calmar / DSR /
trade-level diagnostics 산출.

Decimal-only (CLAUDE.md §2.1). stdlib only. Underscore-prefix private
(ADR 0007 §1.6.3).

Algorithm (Architect 권고 D5 단순화 path):
    For each grid point (n, k, m):
        For each WFO fold (train_indices, test_indices):
            config = _DGTConfig(n, k, m)
            IS_result = run DGT on bars[train_indices]
            OOS_result = run DGT on bars[test_indices]
            collect IS metrics + OOS metrics + OOS returns
        DSR = _compute_dsr(OOS_returns_concatenated, n_trials=len(grid))
        aggregate IS / OOS metrics (mean across folds)

산출 데이터 = `_GridPointResult` per grid point + `_WFOGridResult` 전체.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.domain.models import OHLCV, Asset, Currency, Money
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.optimization._dsr import _compute_dsr
from src.research.dgt.optimization._grid_generator import _generate_grid
from src.research.dgt.optimization._wfo_splitter import _wfo_split
from src.research.dgt.results import _DGTBacktestResult
from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner


_INITIAL_CAPITAL_KRW = Decimal("10000000")  # 10M KRW (Phase 0.11.a 정합)
_TRADING_DAYS_PER_YEAR = Decimal("252")


@dataclass(frozen=True)
class _FoldMetrics:
    """단일 fold metrics (IS 또는 OOS)."""

    cagr_pct: Decimal
    mdd_pct: Decimal
    sharpe: Decimal
    calmar: Decimal
    trade_count: int
    median_holding_period_days: Decimal
    mean_holding_period_days: Decimal
    daily_returns: list[Decimal]


@dataclass(frozen=True)
class _GridPointResult:
    """단일 grid point (n, k, m) 의 WFO 전체 fold 종합 결과."""

    config_n: int
    config_k_pct: Decimal
    config_m: int
    is_cagr_pct: Decimal
    is_mdd_pct: Decimal
    is_sharpe: Decimal
    is_calmar: Decimal
    oos_cagr_pct: Decimal
    oos_mdd_pct: Decimal
    oos_sharpe: Decimal
    oos_calmar: Decimal
    dsr: Decimal
    total_trade_count: int
    median_holding_period_days: Decimal
    mean_holding_period_days: Decimal
    pnl_histogram: list[tuple[Decimal, Decimal, int]] = field(default_factory=list)
    # status_passes — D11 (a) AND-gate 4지표 모두 충족 여부 (informational).
    passes_d11_baseline_band: bool = False


@dataclass(frozen=True)
class _WFOGridResult:
    """전체 grid 탐색 산출 — `_GridPointResult` list (OOS Sharpe desc)."""

    asset_code: str
    grid_size: int
    n_folds: int
    n_bars: int
    points: list[_GridPointResult]


_PNL_BIN_BOUNDS: tuple[Decimal, ...] = (
    Decimal("-20"),
    Decimal("-15"),
    Decimal("-10"),
    Decimal("-5"),
    Decimal("0"),
    Decimal("5"),
    Decimal("10"),
    Decimal("15"),
    Decimal("20"),
    Decimal("25"),
)


def _run_wfo_grid(
    bars: list[OHLCV],
    asset: Asset,
    *,
    include_re_anchor: bool = False,
    n_folds: int = 5,
    train_ratio: Decimal = Decimal("0.8"),
    purge_gap: int = 5,
    initial_capital_krw: Decimal = _INITIAL_CAPITAL_KRW,
) -> _WFOGridResult:
    """WFO + grid search 실행.

    Args:
        bars: full-period OHLCV (ascending trade_date).
        asset: 069500 ETF (D3 default).
        include_re_anchor: True 시 4 차원 grid (re_anchor_period 포함).
        n_folds: WFO fold 수 (default 5, ADR 0008 §1.6 D5).
        train_ratio: train / fold 비율 (default 0.8).
        purge_gap: train_end ↔ test_start buffer (default 5, ADR 0008 D8 (ii)).
        initial_capital_krw: 단일 fold 초기 자본 (default 10M KRW).

    Returns:
        `_WFOGridResult` — points 는 OOS Sharpe desc 로 정렬.

    Note:
        D5 단순화 path (Architect 권고 alt) — 전체 95 grid 각각의 OOS 평균
        SR 직접 계산. fold-별 in-sample best parameter 선택 후 OOS 평가하는
        엄밀 WFO 방식 (CV-best 선택) 은 sub-step .4 영역.
    """
    if not bars:
        raise ValueError("bars must be non-empty")
    if len(bars) < 60 * 5:
        raise ValueError(
            f"bars length ({len(bars)}) too short — need >= 300 (5 folds × 60 cycle)"
        )

    grid = _generate_grid(include_re_anchor=include_re_anchor)
    cost_model = _KoreanMarketCostModel()
    splits = _wfo_split(
        n_bars=len(bars),
        n_folds=n_folds,
        train_ratio=train_ratio,
        purge_gap=purge_gap,
    )
    n_trials = len(grid)

    results: list[_GridPointResult] = []
    for point in grid:
        n_val = int(point["n"])
        k_val = point["k"]
        if not isinstance(k_val, Decimal):
            raise TypeError(f"k must be Decimal, got {type(k_val)}")
        m_val = int(point["m"])
        config = _DGTConfig(
            grid_count=n_val,
            grid_spacing_pct=k_val,
            levels_above=m_val,
        )
        runner = _DGTPrototypeRunner(cost_model=cost_model, config=config)

        is_fold_metrics: list[_FoldMetrics] = []
        oos_fold_metrics: list[_FoldMetrics] = []
        oos_returns_concat: list[Decimal] = []
        for train_idx, test_idx in splits:
            train_bars = bars[train_idx.start : train_idx.stop]
            test_bars = bars[test_idx.start : test_idx.stop]
            is_result = runner.run(
                asset=asset,
                start=train_bars[0].trade_date,
                end=train_bars[-1].trade_date,
                initial_capital=Money(
                    amount=initial_capital_krw, currency=Currency.KRW
                ),
                ohlcv=train_bars,
            )
            oos_result = runner.run(
                asset=asset,
                start=test_bars[0].trade_date,
                end=test_bars[-1].trade_date,
                initial_capital=Money(
                    amount=initial_capital_krw, currency=Currency.KRW
                ),
                ohlcv=test_bars,
            )
            is_metrics = _fold_metrics_from_result(is_result)
            oos_metrics = _fold_metrics_from_result(oos_result)
            is_fold_metrics.append(is_metrics)
            oos_fold_metrics.append(oos_metrics)
            oos_returns_concat.extend(oos_metrics.daily_returns)

        # Aggregate IS / OOS metrics across folds (mean).
        is_agg = _aggregate_fold_metrics(is_fold_metrics)
        oos_agg = _aggregate_fold_metrics(oos_fold_metrics)

        # DSR over concatenated OOS returns.
        dsr = _safe_dsr(oos_returns_concat, n_trials=n_trials)

        # Trade-level diagnostics — collect across all OOS folds.
        total_trade_count = sum(fm.trade_count for fm in oos_fold_metrics)
        # Weighted median + mean holding period — fold-aggregated.
        all_periods: list[Decimal] = []
        for fm in oos_fold_metrics:
            if fm.trade_count > 0:
                # Re-derive: trade_count > 0 가정. Per-fold median stored as
                # representative; aggregate by trade_count weight.
                all_periods.extend(
                    [fm.median_holding_period_days] * fm.trade_count
                )
        median_period = _median(all_periods) if all_periods else Decimal("0")
        mean_period = (
            sum(all_periods, Decimal("0")) / Decimal(len(all_periods))
            if all_periods
            else Decimal("0")
        )

        # P&L histogram — pseudo (per-fold daily-return distribution, %).
        pnl_hist = _compute_pnl_histogram(oos_returns_concat)

        passes_band = _check_d11_baseline_band(
            oos_cagr_pct=oos_agg.cagr_pct,
            oos_mdd_pct=oos_agg.mdd_pct,
            oos_sharpe=oos_agg.sharpe,
            oos_calmar=oos_agg.calmar,
        )

        results.append(
            _GridPointResult(
                config_n=n_val,
                config_k_pct=k_val,
                config_m=m_val,
                is_cagr_pct=is_agg.cagr_pct,
                is_mdd_pct=is_agg.mdd_pct,
                is_sharpe=is_agg.sharpe,
                is_calmar=is_agg.calmar,
                oos_cagr_pct=oos_agg.cagr_pct,
                oos_mdd_pct=oos_agg.mdd_pct,
                oos_sharpe=oos_agg.sharpe,
                oos_calmar=oos_agg.calmar,
                dsr=dsr,
                total_trade_count=total_trade_count,
                median_holding_period_days=median_period,
                mean_holding_period_days=mean_period,
                pnl_histogram=pnl_hist,
                passes_d11_baseline_band=passes_band,
            )
        )

    # Sort by OOS Sharpe desc (deterministic — equal Sharpe sorted by n,k,m).
    results.sort(
        key=lambda r: (
            -r.oos_sharpe,
            r.config_n,
            r.config_k_pct,
            r.config_m,
        )
    )

    return _WFOGridResult(
        asset_code=asset.code,
        grid_size=n_trials,
        n_folds=n_folds,
        n_bars=len(bars),
        points=results,
    )


def _compute_oos_returns(
    test_bars: list[OHLCV],
    config: _DGTConfig,
    asset: Asset,
    *,
    initial_capital_krw: Decimal = _INITIAL_CAPITAL_KRW,
) -> list[Decimal]:
    """단일 fold OOS daily return series 산출.

    DGT runner 실행 → daily_snapshots 의 인접 total_value 비율 - 1.
    Decimal-only.
    """
    if not test_bars:
        raise ValueError("test_bars must be non-empty")
    cost_model = _KoreanMarketCostModel()
    runner = _DGTPrototypeRunner(cost_model=cost_model, config=config)
    result = runner.run(
        asset=asset,
        start=test_bars[0].trade_date,
        end=test_bars[-1].trade_date,
        initial_capital=Money(amount=initial_capital_krw, currency=Currency.KRW),
        ohlcv=test_bars,
    )
    return _daily_returns_from_result(result)


def _daily_returns_from_result(result: _DGTBacktestResult) -> list[Decimal]:
    """daily_snapshots → list of (curr/prev - 1) Decimal.

    Length = len(snapshots) - 1.
    """
    values = [s.total_value for s in result.daily_snapshots]
    returns: list[Decimal] = []
    for prev, curr in zip(values[:-1], values[1:]):
        if prev > 0:
            returns.append((curr - prev) / prev)
        else:
            returns.append(Decimal("0"))
    return returns


def _fold_metrics_from_result(result: _DGTBacktestResult) -> _FoldMetrics:
    """단일 fold backtest 결과 → CAGR / MDD / Sharpe / Calmar + 거래 통계."""
    snapshots = result.daily_snapshots
    if len(snapshots) < 2:
        return _FoldMetrics(
            cagr_pct=Decimal("0"),
            mdd_pct=Decimal("0"),
            sharpe=Decimal("0"),
            calmar=Decimal("0"),
            trade_count=len(result.trades),
            median_holding_period_days=Decimal("0"),
            mean_holding_period_days=Decimal("0"),
            daily_returns=[],
        )

    values = [s.total_value for s in snapshots]
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

    daily_rets = _daily_returns_from_result(result)
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

    median_period, mean_period = _holding_periods(result)

    return _FoldMetrics(
        cagr_pct=cagr_pct,
        mdd_pct=mdd_pct,
        sharpe=sharpe,
        calmar=calmar,
        trade_count=len(result.trades),
        median_holding_period_days=median_period,
        mean_holding_period_days=mean_period,
        daily_returns=daily_rets,
    )


def _holding_periods(result: _DGTBacktestResult) -> tuple[Decimal, Decimal]:
    """trade BUY→SELL pairs 의 holding period (days) — median + mean.

    DGT 의 grid trading 은 BUY ↔ SELL 1:1 pairing 아님 (allocation = cash /
    (n+1), 한 BUY 가 여러 SELL 로 부분 처분 가능). 단순화: BUY 와 다음
    SELL 사이 trade_date 차이를 FIFO 로 매칭.
    """
    buys: list[date] = []  # FIFO queue of BUY trade_date
    periods: list[Decimal] = []
    for trade in result.trades:
        if trade.side == "BUY":
            buys.append(trade.trade_date)
        elif trade.side == "SELL" and buys:
            buy_date = buys.pop(0)  # FIFO
            delta_days = (trade.trade_date - buy_date).days
            periods.append(Decimal(delta_days))
    if not periods:
        return (Decimal("0"), Decimal("0"))
    median_period = _median(periods)
    mean_period = sum(periods, Decimal("0")) / Decimal(len(periods))
    return (median_period, mean_period)


def _median(values: list[Decimal]) -> Decimal:
    """Decimal-only median (sorted middle, even → average of two middles)."""
    if not values:
        return Decimal("0")
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n % 2 == 1:
        return sorted_v[n // 2]
    a, b = sorted_v[n // 2 - 1], sorted_v[n // 2]
    return (a + b) / Decimal("2")


def _aggregate_fold_metrics(fms: list[_FoldMetrics]) -> _FoldMetrics:
    """Fold-별 metrics → 산술 평균 aggregate."""
    if not fms:
        return _FoldMetrics(
            cagr_pct=Decimal("0"),
            mdd_pct=Decimal("0"),
            sharpe=Decimal("0"),
            calmar=Decimal("0"),
            trade_count=0,
            median_holding_period_days=Decimal("0"),
            mean_holding_period_days=Decimal("0"),
            daily_returns=[],
        )
    n = Decimal(len(fms))
    return _FoldMetrics(
        cagr_pct=sum((fm.cagr_pct for fm in fms), Decimal("0")) / n,
        mdd_pct=sum((fm.mdd_pct for fm in fms), Decimal("0")) / n,
        sharpe=sum((fm.sharpe for fm in fms), Decimal("0")) / n,
        calmar=sum((fm.calmar for fm in fms), Decimal("0")) / n,
        trade_count=sum(fm.trade_count for fm in fms),
        median_holding_period_days=_median(
            [fm.median_holding_period_days for fm in fms]
        ),
        mean_holding_period_days=sum(
            (fm.mean_holding_period_days for fm in fms), Decimal("0")
        ) / n,
        daily_returns=[],  # aggregate 시 의미 없음
    )


def _safe_dsr(returns: list[Decimal], *, n_trials: int) -> Decimal:
    """DSR 계산 — zero variance / length < 2 시 Decimal('0') 반환 (silent skip).

    Note: production 코드 silence 금지 (CLAUDE.md §6.3) 이지만 본 함수는
    research overlay (5th ring) + grid 95 point 의 일부가 zero variance 시
    (no trade 으로 cash 만 유지) DSR 계산 불가 자연 — Decimal('0') = 의미상
    "no signal" 박제.
    """
    if len(returns) < 2:
        return Decimal("0")
    try:
        return _compute_dsr(returns, n_trials=n_trials)
    except ValueError:
        return Decimal("0")


def _compute_pnl_histogram(
    returns: list[Decimal],
) -> list[tuple[Decimal, Decimal, int]]:
    """Daily-return 분포 histogram — bin_low / bin_high / count.

    Bin bounds (percent): -20, -15, -10, -5, 0, 5, 10, 15, 20, 25.
    Returns 단위는 ratio (예: 0.01 = 1%). bin 비교 시 ratio * 100 적용.
    """
    bounds = _PNL_BIN_BOUNDS
    bins: list[list[Decimal | int]] = []
    for i in range(len(bounds) - 1):
        bins.append([bounds[i], bounds[i + 1], 0])

    for r in returns:
        r_pct = r * Decimal("100")
        for b in bins:
            low = b[0]
            high = b[1]
            if isinstance(low, Decimal) and isinstance(high, Decimal):
                if low <= r_pct < high:
                    b[2] = int(b[2]) + 1  # type: ignore[assignment]
                    break

    return [
        (
            b[0] if isinstance(b[0], Decimal) else Decimal("0"),
            b[1] if isinstance(b[1], Decimal) else Decimal("0"),
            int(b[2]),
        )
        for b in bins
    ]


# D11 (a) AND-gate baseline ±10% band (ADR 0008 §1.6 D11 (a) 박제).
# Phase 0.7.3 baseline (phase-0.11.a-comparison.md §1):
#   CAGR 2.5779 / MDD -8.2737 / Sharpe 0.5255 / Calmar 0.3116.
_BASELINE_CAGR_MIN = Decimal("2.32")  # 2.5779 * 0.9
_BASELINE_MDD_MIN = Decimal("-9.10")  # -8.2737 * 1.10 (악화폭 ≤ 10%)
_BASELINE_SHARPE_MIN = Decimal("0.473")  # 0.5255 * 0.9
_BASELINE_CALMAR_MIN = Decimal("0.280")  # 0.3116 * 0.9


def _check_d11_baseline_band(
    *,
    oos_cagr_pct: Decimal,
    oos_mdd_pct: Decimal,
    oos_sharpe: Decimal,
    oos_calmar: Decimal,
) -> bool:
    """D11 (a) AND-gate — 4 지표 모두 baseline ±10% 충족 여부.

    Note: OOS 지표 = mean-across-folds 산출 (D5 단순화 path). 엄밀 WFO
    full-period OOS 계산은 sub-step .4 영역.
    """
    return (
        oos_cagr_pct >= _BASELINE_CAGR_MIN
        and oos_mdd_pct >= _BASELINE_MDD_MIN
        and oos_sharpe >= _BASELINE_SHARPE_MIN
        and oos_calmar >= _BASELINE_CALMAR_MIN
    )


__all__: list[str] = []
