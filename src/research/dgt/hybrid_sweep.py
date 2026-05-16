"""Phase 0.11.g.2 — Core-Satellite ratio × rebalance mode sweep.

16-config experiment matrix:
  - 4 ratios: 50%, 60%, 70%, 80% (B&H core portion)
  - 4 rebalance modes: static, drift-5% (cd20), drift-5% (cd40), calendar-60

Outputs comparison table with: total return, MDD, Sharpe, Calmar, rebalance count, alpha.

Usage:
    python -m src.research.dgt.hybrid_sweep --ticker 005930 --period bull
    python -m src.research.dgt.hybrid_sweep --multi4  # 4-stock portfolio

5th ring research-only. Underscore-prefix private.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from typing import Sequence

from src.domain.models import Asset, AssetClass, Currency, Exchange, Market, Money, OHLCV
from src.research.dgt.adaptive_runner import _AdaptiveConfig
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.hybrid_runner import (
    _HybridBacktestResult,
    _HybridConfig,
    _HybridCoreRunner,
    _HybridSnapshot,
)
from src.research.dgt.runner import _DGTConfig


# --- Period definitions (same as Phase 0.11.f) ---
_PERIODS: dict[str, tuple[str, str]] = {
    "bull": ("2020-04-01", "2021-07-01"),
    "bear": ("2021-07-01", "2022-10-01"),
    "full": ("2020-04-01", "2023-04-01"),
}

# --- Sweep configurations ---
_RATIOS = [Decimal("0.5"), Decimal("0.6"), Decimal("0.7"), Decimal("0.8")]

_REBALANCE_MODES: list[tuple[str, _HybridConfig]] = [
    ("Static", _HybridConfig(rebalance_mode="static")),
    ("Drift-5%/cd20", _HybridConfig(
        rebalance_mode="drift", drift_threshold=Decimal("0.05"), cooldown_days=20,
    )),
    ("Drift-5%/cd40", _HybridConfig(
        rebalance_mode="drift", drift_threshold=Decimal("0.05"), cooldown_days=40,
    )),
    ("Calendar-60", _HybridConfig(
        rebalance_mode="calendar", calendar_period=60, cooldown_days=20,
    )),
]


def _compute_mdd(snapshots: list[_HybridSnapshot]) -> Decimal:
    """Maximum drawdown from daily snapshots."""
    if not snapshots:
        return Decimal("0")
    peak = snapshots[0].total_value
    max_dd = Decimal("0")
    for snap in snapshots:
        if snap.total_value > peak:
            peak = snap.total_value
        dd = (snap.total_value - peak) / peak if peak > 0 else Decimal("0")
        if dd < max_dd:
            max_dd = dd
    return max_dd * Decimal("100")  # as percentage


def _compute_sharpe(snapshots: list[_HybridSnapshot]) -> Decimal:
    """Annualized Sharpe ratio (risk-free=0) from daily returns."""
    if len(snapshots) < 2:
        return Decimal("0")
    returns = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1].total_value
        curr = snapshots[i].total_value
        if prev > 0:
            returns.append((curr - prev) / prev)
    if not returns:
        return Decimal("0")
    n = len(returns)
    mean = sum(returns) / Decimal(n)
    variance = sum((r - mean) ** 2 for r in returns) / Decimal(n)
    if variance <= 0:
        return Decimal("0")
    # sqrt via Newton's method (Decimal doesn't have sqrt)
    std = _decimal_sqrt(variance)
    if std <= 0:
        return Decimal("0")
    return (mean / std) * _decimal_sqrt(Decimal("250"))


def _decimal_sqrt(val: Decimal, precision: int = 20) -> Decimal:
    """Newton's method sqrt for Decimal."""
    if val <= 0:
        return Decimal("0")
    x = val
    for _ in range(precision):
        x = (x + val / x) / Decimal("2")
    return x


def _compute_calmar(total_return_pct: Decimal, mdd: Decimal, years: Decimal) -> Decimal:
    """Calmar ratio = annualized return / |MDD|."""
    if mdd == 0 or years <= 0:
        return Decimal("0")
    ann_return = total_return_pct / years
    return ann_return / abs(mdd)


def _run_sweep_single(
    asset: Asset,
    ohlcv: list[OHLCV],
    capital: Decimal,
    period_name: str,
) -> list[dict]:
    """Run 16-config sweep for a single asset."""
    cost_model = _KoreanMarketCostModel()
    dgt_config = _DGTConfig(
        grid_count=11,
        grid_spacing_pct=Decimal("0.02"),
        levels_above=5,
    )
    adaptive = _AdaptiveConfig(
        atr_period=14,
        multiplier=Decimal("1.0"),
        k_min=Decimal("0.005"),
        k_max=Decimal("0.05"),
    )

    start = ohlcv[0].trade_date
    end = ohlcv[-1].trade_date
    days = len(ohlcv)
    years = Decimal(days) / Decimal("250")

    results = []
    for ratio in _RATIOS:
        for mode_name, mode_cfg in _REBALANCE_MODES:
            hybrid_cfg = _HybridConfig(
                core_ratio=ratio,
                rebalance_mode=mode_cfg.rebalance_mode,
                drift_threshold=mode_cfg.drift_threshold,
                cooldown_days=mode_cfg.cooldown_days,
                calendar_period=mode_cfg.calendar_period,
            )
            runner = _HybridCoreRunner(
                cost_model=cost_model,
                dgt_config=dgt_config,
                adaptive=adaptive,
                hybrid=hybrid_cfg,
                volume_gate=True,
                volume_gate_period=10,
                volume_gate_multiplier=Decimal("1.5"),
            )
            result = runner.run(
                asset=asset,
                start=start,
                end=end,
                initial_capital=Money(amount=capital, currency=Currency.KRW),
                ohlcv=ohlcv,
            )

            mdd = _compute_mdd(result.daily_snapshots)
            sharpe = _compute_sharpe(result.daily_snapshots)
            calmar = _compute_calmar(result.total_return_pct, mdd, years)

            results.append({
                "ratio": f"{int(ratio * 100)}%",
                "mode": mode_name,
                "return_pct": result.total_return_pct,
                "mdd_pct": mdd,
                "sharpe": sharpe,
                "calmar": calmar,
                "rebalances": len(result.rebalance_events),
                "alpha_ann": result.rebalancing_alpha_annualized,
                "dgt_trades": len(result.dgt_trades),
            })

    return results


def _print_table(results: list[dict], title: str) -> None:
    """Print formatted comparison table."""
    print(f"\n{'=' * 100}")
    print(f"  {title}")
    print(f"{'=' * 100}")
    header = f"{'Ratio':<7} {'Mode':<15} {'Return%':<10} {'MDD%':<10} {'Sharpe':<8} {'Calmar':<8} {'Rebal':<6} {'Alpha%':<9} {'Trades':<7}"
    print(header)
    print("-" * 100)
    for r in results:
        print(
            f"{r['ratio']:<7} {r['mode']:<15} "
            f"{r['return_pct']:>8.2f}% "
            f"{r['mdd_pct']:>8.2f}% "
            f"{r['sharpe']:>7.3f} "
            f"{r['calmar']:>7.3f} "
            f"{r['rebalances']:>5} "
            f"{r['alpha_ann']:>7.2f}% "
            f"{r['dgt_trades']:>6}"
        )
    print("-" * 100)

    # Find best by Calmar
    best = max(results, key=lambda x: x["calmar"])
    print(f"  Best Calmar: {best['ratio']} / {best['mode']} → Calmar={best['calmar']:.3f}")


def _load_ohlcv_pykrx(ticker: str, start: str, end: str) -> tuple[Asset, list[OHLCV]]:
    """Load OHLCV from pykrx (lazy import)."""
    try:
        from pykrx import stock as pykrx_stock  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: pykrx not installed. Run: pip install pykrx", file=sys.stderr)
        sys.exit(1)

    df = pykrx_stock.get_market_ohlcv_by_date(start, end, ticker)
    if df.empty:
        print(f"ERROR: No data for {ticker} ({start}~{end})", file=sys.stderr)
        sys.exit(1)

    name = pykrx_stock.get_market_ticker_name(ticker) or ticker
    asset = Asset(
        code=ticker,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name=name,
        tick_size=Decimal("1"),
        listed_at=date(2000, 1, 1),
    )

    bars: list[OHLCV] = []
    for idx, row in df.iterrows():
        o = Decimal(str(row["시가"]))
        h = Decimal(str(row["고가"]))
        low_val = Decimal(str(row["저가"]))
        c = Decimal(str(row["종가"]))
        # Skip bars with zero values (trading halts)
        if o <= 0 or h <= 0 or low_val <= 0 or c <= 0:
            continue
        # pykrx data can have minor rounding inconsistencies
        h = max(h, o, c)
        low_val = min(low_val, o, c)
        bars.append(OHLCV(
            asset=asset,
            trade_date=idx.date(),  # type: ignore[union-attr]
            open=o,
            high=h,
            low=low_val,
            close=c,
            volume=Decimal(str(row["거래량"])),
        ))

    return asset, bars


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 0.11.g.2 — Core-Satellite ratio sweep")
    parser.add_argument("--ticker", default="005930", help="KRX ticker code")
    parser.add_argument("--period", choices=["bull", "bear", "full", "all"], default="all")
    parser.add_argument("--capital", type=int, default=100_000_000, help="Initial capital (KRW)")
    parser.add_argument("--multi4", action="store_true", help="Run 4-stock portfolio")
    args = parser.parse_args()

    capital = Decimal(str(args.capital))
    tickers = ["005930", "005380", "035720", "241560"] if args.multi4 else [args.ticker]
    per_stock_capital = capital / Decimal(len(tickers))

    periods = list(_PERIODS.keys()) if args.period == "all" else [args.period]

    for period in periods:
        start_str, end_str = _PERIODS[period]
        all_results: list[dict] = []

        for ticker in tickers:
            asset, ohlcv = _load_ohlcv_pykrx(ticker, start_str, end_str)
            results = _run_sweep_single(asset, ohlcv, per_stock_capital, period)

            if len(tickers) == 1:
                all_results = results
            else:
                # Aggregate: sum returns weighted by equal allocation
                if not all_results:
                    all_results = [dict(r) for r in results]
                    for r in all_results:
                        r["_count"] = 1
                else:
                    for i, r in enumerate(results):
                        all_results[i]["return_pct"] += r["return_pct"]
                        all_results[i]["mdd_pct"] = min(all_results[i]["mdd_pct"], r["mdd_pct"])
                        all_results[i]["rebalances"] += r["rebalances"]
                        all_results[i]["alpha_ann"] += r["alpha_ann"]
                        all_results[i]["dgt_trades"] += r["dgt_trades"]
                        all_results[i]["_count"] = all_results[i].get("_count", 1) + 1

        # Average for multi-stock
        if len(tickers) > 1:
            for r in all_results:
                cnt = r.pop("_count", 1)
                r["return_pct"] /= Decimal(cnt)
                r["alpha_ann"] /= Decimal(cnt)
                r["sharpe"] = Decimal("0")  # recompute would need combined snapshots
                r["calmar"] = Decimal("0")

        title = f"Core-Satellite Sweep — {'+'.join(tickers)} — {period} ({_PERIODS[period][0]}~{_PERIODS[period][1]})"
        _print_table(all_results, title)


if __name__ == "__main__":
    main()
