"""Phase 0.11.b — D11 (c) perturbation robustness (ADR 0008 §1.6 D8/D11, sub-step .4).

Best parameter (n=11, k=3%, m=1) 의 ±10% 변동 27-point grid 에서 WFO 5-fold
OOS Sharpe 측정 → `worst_oos_sharpe > 0.3` 임계로 lucky parameter cliff 차단.

ADR 0008 §1.6 D8 (iii) PRIMARY + D11 (c) AND-gate 조건.

Decimal-only (CLAUDE.md §2.1). stdlib only. Underscore-prefix private
(ADR 0007 §1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from src.domain.models import OHLCV, Asset
from src.research.dgt.optimization._grid_runner import (
    _GridPointResult,
    _aggregate_fold_metrics,
    _check_d11_baseline_band,
    _compute_pnl_histogram,
    _fold_metrics_from_result,
    _holding_periods,
    _median,
    _safe_dsr,
)
from src.research.dgt.optimization._wfo_splitter import _wfo_split
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner

from src.domain.models import Currency, Money


_INITIAL_CAPITAL_KRW = Decimal("10000000")  # 10M KRW (Phase 0.11.a 정합)
_D11_C_THRESHOLD = Decimal("0.3")  # ADR 0008 §1.6 D8 (iii) + D11 (c).


@dataclass(frozen=True)
class _PerturbationResult:
    """Best parameter ±10% 27-point perturbation 산출 (ADR 0008 §1.6 D11 (c))."""

    best_config: _DGTConfig
    perturbation_results: list[_GridPointResult]
    worst_oos_sharpe: Decimal
    mean_oos_sharpe: Decimal
    passes_d11_c: bool
    delta_pct: Decimal = field(default=Decimal("0.10"))


def _build_perturbation_grid(
    best_config: _DGTConfig,
    *,
    delta_pct: Decimal = Decimal("0.10"),
) -> list[dict[str, int | Decimal]]:
    """Best parameter 의 ±delta_pct 변동 grid 생성.

    n: int → round(n × (1±delta)) 의 3 값 (중복 제거 안 함 — best ±)
    k: Decimal → k × (1±delta) 의 3 값
    m: int → m-1 / m / m+1 (±1 absolute, m=0 시 0/1/2)

    Returns:
        27-point grid (3 × 3 × 3). m < n 필터링 적용 (ADR 0008 D4 paper 정합).
    """
    n_best = best_config.grid_count
    k_best = best_config.grid_spacing_pct
    m_best = best_config.levels_above

    # n perturbation: ±delta_pct rounded to int (n=11 → [10, 11, 12])
    n_low = int((Decimal(n_best) * (Decimal("1") - delta_pct)).to_integral_value())
    n_high = int((Decimal(n_best) * (Decimal("1") + delta_pct)).to_integral_value())
    if n_low == n_best:
        n_low = max(1, n_best - 1)
    if n_high == n_best:
        n_high = n_best + 1
    n_values = sorted({n_low, n_best, n_high})

    # k perturbation: ±delta_pct (3 × 0.9 = 2.7 / 3.0 / 3.3)
    k_low = k_best * (Decimal("1") - delta_pct)
    k_high = k_best * (Decimal("1") + delta_pct)
    k_values = [k_low, k_best, k_high]

    # m perturbation: ±1 absolute (m=1 → [0, 1, 2]; m=0 → [-1=clamped 0, 0, 1])
    m_low = max(0, m_best - 1)
    m_high = m_best + 1
    if m_low == m_best:
        # m=0 case: alternative neighbors = 0/1/2
        m_values = sorted({m_best, m_best + 1, m_best + 2})
    else:
        m_values = sorted({m_low, m_best, m_high})

    raw: list[dict[str, int | Decimal]] = []
    for n in n_values:
        for k in k_values:
            for m in m_values:
                if m < n:  # paper Table 1 정합 (m=n 단방향 grid 회피)
                    raw.append({"n": n, "k": k, "m": m})
    return raw


def _run_perturbation(
    bars: list[OHLCV],
    asset: Asset,
    best_config: _DGTConfig,
    *,
    delta_pct: Decimal = Decimal("0.10"),
    n_folds: int = 5,
    train_ratio: Decimal = Decimal("0.8"),
    purge_gap: int = 5,
    initial_capital_krw: Decimal = _INITIAL_CAPITAL_KRW,
) -> _PerturbationResult:
    """Best parameter ±delta_pct 27-point WFO perturbation 실행.

    Args:
        bars: full-period OHLCV (ascending trade_date).
        asset: 069500 ETF (D3 default).
        best_config: sub-step .3 산출 best parameter set.
        delta_pct: 변동 폭 (default 0.10 = ±10%, ADR 0008 D11 (c)).
        n_folds: WFO fold 수 (default 5).
        train_ratio: train / fold 비율.
        purge_gap: train_end ↔ test_start buffer (default 5).
        initial_capital_krw: 단일 fold 초기 자본 (default 10M KRW).

    Returns:
        `_PerturbationResult` — 27-point grid 결과 + worst/mean OOS Sharpe + D11 (c) PASS/FAIL.

    Raises:
        ValueError: bars 부족.
    """
    if not bars:
        raise ValueError("bars must be non-empty")
    if len(bars) < 60 * 5:
        raise ValueError(
            f"bars length ({len(bars)}) too short — need >= 300 (5 folds × 60 cycle)"
        )

    perturbation_grid = _build_perturbation_grid(best_config, delta_pct=delta_pct)
    cost_model = _KoreanMarketCostModel()
    splits = _wfo_split(
        n_bars=len(bars),
        n_folds=n_folds,
        train_ratio=train_ratio,
        purge_gap=purge_gap,
    )
    n_trials = len(perturbation_grid)

    results: list[_GridPointResult] = []
    for point in perturbation_grid:
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

        is_fold_metrics_list = []
        oos_fold_metrics_list = []
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
            is_fm = _fold_metrics_from_result(is_result)
            oos_fm = _fold_metrics_from_result(oos_result)
            is_fold_metrics_list.append(is_fm)
            oos_fold_metrics_list.append(oos_fm)
            oos_returns_concat.extend(oos_fm.daily_returns)

        is_agg = _aggregate_fold_metrics(is_fold_metrics_list)
        oos_agg = _aggregate_fold_metrics(oos_fold_metrics_list)
        dsr = _safe_dsr(oos_returns_concat, n_trials=n_trials)

        total_trade_count = sum(fm.trade_count for fm in oos_fold_metrics_list)
        all_periods: list[Decimal] = []
        for fm in oos_fold_metrics_list:
            if fm.trade_count > 0:
                all_periods.extend(
                    [fm.median_holding_period_days] * fm.trade_count
                )
        median_period = _median(all_periods) if all_periods else Decimal("0")
        mean_period = (
            sum(all_periods, Decimal("0")) / Decimal(len(all_periods))
            if all_periods
            else Decimal("0")
        )
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

    if not results:
        raise ValueError("perturbation grid produced no results (m < n filter empty)")

    sharpes = [r.oos_sharpe for r in results]
    worst = min(sharpes)
    mean = sum(sharpes, Decimal("0")) / Decimal(len(sharpes))
    passes = worst > _D11_C_THRESHOLD

    return _PerturbationResult(
        best_config=best_config,
        perturbation_results=results,
        worst_oos_sharpe=worst,
        mean_oos_sharpe=mean,
        passes_d11_c=passes,
        delta_pct=delta_pct,
    )


__all__: list[str] = []
