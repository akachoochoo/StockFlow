"""KRX DGT 백테스트 비교 스크립트.

pykrx로 OHLCV 데이터를 받아 DGT 백테스트 + 리포트(JSON + HTML) 생성.
4-way 비교: Paper (논문 충실) vs Static vs Adaptive vs Adp-Narrow.

Usage:
    python3 -m src.research.dgt.kakao_dgt_backtest \
        --code 035720 \
        --start 2025-07-25 --end 2026-05-13 \
        --initial-capital 10000000 \
        --grid-levels 11 --grid-spacing-pct 3 --levels-above 1 \
        --output-dir report/kakao-dgt/

Best parameter (Phase 0.11.b): n=11, k=3%, m=1.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from datetime import date
from decimal import ROUND_DOWN, Decimal
from html import escape
from pathlib import Path

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
    OHLCV,
)
from src.research.dgt.cli import _compute_metrics, _serialize_result
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.adaptive_runner import _AdaptiveConfig, _DGTAdaptiveRunner
from src.research.dgt.dynamic_runner import _DGTDynamicRunner
from src.research.dgt.paper_adaptive_runner import _DGTPaperAdaptiveRunner
from src.research.dgt.paper_runner import _DGTPaperRunner
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot, _DGTTrade
from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner


def _build_asset(code: str) -> Asset:
    """pykrx에서 종목명을 조회하여 Asset 생성."""
    from pykrx import stock as pykrx_stock  # lazy import (research-only dep)

    name = pykrx_stock.get_market_ticker_name(code)
    if not name:
        name = code
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name=name,
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2000, 1, 1),
    )


def _fetch_ohlcv(code: str, start: date, end: date, asset: Asset) -> list[OHLCV]:
    """pykrx로 일봉 OHLCV를 받아 도메인 모델로 변환."""
    from pykrx import stock as pykrx_stock  # lazy import (research-only dep)

    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")
    df = pykrx_stock.get_market_ohlcv_by_date(start_str, end_str, code)
    if df.empty:
        raise SystemExit(f"No data from pykrx for {code} [{start}, {end}]")

    bars: list[OHLCV] = []
    for idx, row in df.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else idx
        o = int(row["시가"])
        h = int(row["고가"])
        l = int(row["저가"])
        c = int(row["종가"])
        # pykrx rounding can produce close outside [low, high] by 1
        h = max(h, o, c)
        l = min(l, o, c)
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=trade_date,
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(l)),
                close=Decimal(str(c)),
                volume=Decimal(str(int(row["거래량"]))),
            )
        )
    return bars


# ---------------------------------------------------------------------------
# Run 3-way comparison
# ---------------------------------------------------------------------------

def _run_static(
    asset: Asset, config: _DGTConfig, capital: Money, bars: list[OHLCV],
    start: date, end: date,
) -> _DGTBacktestResult:
    runner = _DGTPrototypeRunner(cost_model=_KoreanMarketCostModel(), config=config)
    return runner.run(asset=asset, start=start, end=end,
                      initial_capital=capital, ohlcv=bars)


def _run_paper(
    asset: Asset, config: _DGTConfig, capital: Money, bars: list[OHLCV],
    start: date, end: date,
) -> _DGTBacktestResult:
    runner = _DGTPaperRunner(cost_model=_KoreanMarketCostModel(), config=config)
    return runner.run(asset=asset, start=start, end=end,
                      initial_capital=capital, ohlcv=bars)


def _run_paper_adaptive(
    asset: Asset, config: _DGTConfig, capital: Money, bars: list[OHLCV],
    start: date, end: date,
    *,
    multiplier: Decimal = Decimal("1.5"),
    k_min: Decimal = Decimal("0.02"),
    k_max: Decimal = Decimal("0.10"),
    rebalance_mode: str = "on_breach",
    volatility_measure: str = "atr",
    slope_gate: bool = False,
    slope_gate_period: int = 5,
    slope_gate_threshold: Decimal = Decimal("0.05"),
    volume_gate: bool = False,
    volume_gate_period: int = 20,
    volume_gate_multiplier: Decimal = Decimal("2.0"),
    use_trend: bool = False,
    trend_period: int = 20,
    trend_sensitivity: Decimal = Decimal("10"),
) -> _DGTBacktestResult:
    runner = _DGTPaperAdaptiveRunner(
        cost_model=_KoreanMarketCostModel(),
        config=config,
        adaptive=_AdaptiveConfig(
            atr_period=14, multiplier=multiplier, k_min=k_min, k_max=k_max,
        ),
        rebalance_mode=rebalance_mode,
        volatility_measure=volatility_measure,
        slope_gate=slope_gate,
        slope_gate_period=slope_gate_period,
        slope_gate_threshold=slope_gate_threshold,
        volume_gate=volume_gate,
        volume_gate_period=volume_gate_period,
        volume_gate_multiplier=volume_gate_multiplier,
        use_trend=use_trend,
        trend_period=trend_period,
        trend_sensitivity=trend_sensitivity,
    )
    return runner.run(asset=asset, start=start, end=end,
                      initial_capital=capital, ohlcv=bars)


def _run_buy_and_hold(
    asset: Asset, capital: Money, bars: list[OHLCV],
    start: date, end: date, allocation_pct: Decimal = Decimal("30"),
) -> _DGTBacktestResult:
    """Buy & Hold: buy once on day 1 with allocation_pct% of capital, hold to end."""
    cost_model = _KoreanMarketCostModel()
    invest = capital.amount * allocation_pct / Decimal("100")
    first_close = bars[0].close
    quantity = (invest / first_close).quantize(Decimal("1"), rounding=ROUND_DOWN)
    trades: list[_DGTTrade] = []
    if quantity > 0:
        cost = cost_model.compute_buy_cost(price=first_close, quantity=quantity, asset=asset)
        cash = capital.amount - cost.total_cost
        holdings = quantity
        trades.append(_DGTTrade(
            trade_date=bars[0].trade_date, side="BUY",
            grid_level_price=first_close, quantity=quantity,
            rounded_price=cost.rounded_price, gross=cost.gross,
            tax=cost.tax, commission=cost.commission,
            cash_delta=-cost.total_cost,
        ))
    else:
        # Price too high for allocation — hold cash
        cash = capital.amount
        holdings = Decimal("0")
    snapshots = [
        _DGTSnapshot(
            trade_date=b.trade_date, cash=cash, holdings=holdings,
            close_price=b.close, total_value=cash + holdings * b.close,
        )
        for b in bars
    ]
    final_close = bars[-1].close
    final_amount = cash + holdings * final_close
    return _DGTBacktestResult(
        asset=asset, start=start, end=end, initial_capital=capital,
        final_cash=cash, final_holdings=holdings,
        final_close_price=final_close,
        final_balance=Money(amount=final_amount, currency=capital.currency),
        wallet_total=Decimal("0"), reference_price=first_close,
        grid_levels=[], trades=trades, daily_snapshots=snapshots,
    )


def _merge_multi_results(
    per_stock: list[_DGTBacktestResult],
    capital: Money,
    start: date,
    end: date,
) -> _DGTBacktestResult:
    """Merge results from multiple stocks into a combined portfolio result."""
    # Combine trades (tag by asset)
    all_trades: list[_DGTTrade] = []
    for r in per_stock:
        all_trades.extend(r.trades)
    all_trades.sort(key=lambda t: t.trade_date)

    # Combine daily snapshots by date
    date_map: dict[date, list[_DGTSnapshot]] = {}
    for r in per_stock:
        for s in r.daily_snapshots:
            date_map.setdefault(s.trade_date, []).append(s)

    combined_snaps: list[_DGTSnapshot] = []
    for d in sorted(date_map.keys()):
        snaps = date_map[d]
        combined_snaps.append(_DGTSnapshot(
            trade_date=d,
            cash=sum(s.cash for s in snaps),
            holdings=Decimal("0"),  # not meaningful for multi-asset
            close_price=Decimal("0"),
            total_value=sum(s.total_value for s in snaps),
        ))

    final_cash = sum(r.final_cash for r in per_stock)
    final_value = sum(r.final_cash + r.final_holdings * r.final_close_price for r in per_stock)
    return _DGTBacktestResult(
        asset=per_stock[0].asset,  # placeholder
        start=start, end=end, initial_capital=capital,
        final_cash=final_cash, final_holdings=Decimal("0"),
        final_close_price=Decimal("0"),
        final_balance=Money(amount=final_value, currency=capital.currency),
        wallet_total=sum(r.wallet_total for r in per_stock),
        reference_price=Decimal("0"),
        grid_levels=[], trades=all_trades, daily_snapshots=combined_snaps,
    )


def _run_dynamic(
    asset: Asset, config: _DGTConfig, capital: Money, bars: list[OHLCV],
    start: date, end: date, mode: str,
) -> _DGTBacktestResult:
    runner = _DGTDynamicRunner(
        cost_model=_KoreanMarketCostModel(), config=config,
        rebalance_mode=mode,  # type: ignore[arg-type]
    )
    return runner.run(asset=asset, start=start, end=end,
                      initial_capital=capital, ohlcv=bars)


def _run_adaptive(
    asset: Asset, config: _DGTConfig, capital: Money, bars: list[OHLCV],
    start: date, end: date,
    *,
    multiplier: Decimal = Decimal("1.5"),
    k_min: Decimal = Decimal("0.02"),
    k_max: Decimal = Decimal("0.10"),
) -> _DGTBacktestResult:
    runner = _DGTAdaptiveRunner(
        cost_model=_KoreanMarketCostModel(),
        base_config=config,
        adaptive=_AdaptiveConfig(
            atr_period=14,
            multiplier=multiplier,
            k_min=k_min,
            k_max=k_max,
        ),
        rebalance_mode="daily",
    )
    return runner.run(asset=asset, start=start, end=end,
                      initial_capital=capital, ohlcv=bars)


def _result_summary(
    label: str, result: _DGTBacktestResult, capital: Money,
) -> dict[str, str]:
    metrics = _compute_metrics(result)
    initial = capital.amount
    final = result.final_balance.amount
    pnl = final - initial
    pnl_pct = pnl / initial * Decimal(100) if initial else Decimal(0)
    n_buys = sum(1 for t in result.trades if t.side == "BUY")
    n_sells = sum(1 for t in result.trades if t.side == "SELL")
    return {
        "label": label,
        "final": str(final),
        "pnl": str(pnl),
        "pnl_pct": f"{pnl_pct:.2f}",
        "trades": str(len(result.trades)),
        "buys": str(n_buys),
        "sells": str(n_sells),
        "cagr": f"{metrics['cagr_pct']:.2f}",
        "mdd": f"{metrics['mdd_pct']:.2f}",
        "sharpe": f"{metrics['sharpe']:.4f}",
        "calmar": f"{metrics['calmar']:.4f}",
    }


# ---------------------------------------------------------------------------
# Chart rendering (matplotlib)
# ---------------------------------------------------------------------------

def _render_comparison_chart(
    results: list[tuple[str, _DGTBacktestResult]],
    bars: list[OHLCV],
    config: _DGTConfig,
    configs_per_result: list[_DGTConfig] | None = None,
) -> bytes:
    """Per-strategy price+grid+markers panels + equity overlay → PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    dates = [b.trade_date for b in bars]
    closes = [float(b.close) for b in bars]

    colors = {"Paper-3%": "#e74c3c", "Paper-1%": "#8e44ad",
              "Hyb-Daily": "#27ae60", "Hyb-ATR": "#27ae60", "Hyb-ADR": "#2980b9",
              "ADR-Base": "#95a5a6", "ADR+Slope": "#e74c3c",
              "ADR+Vol": "#8e44ad", "ADR+Both": "#2980b9",
              "Base": "#95a5a6", "Vol-1.5x": "#e74c3c", "Vol-2.0x": "#27ae60",
              "Vol-2.5x": "#8e44ad", "Vol-3.0x": "#2980b9",
              "V-P5": "#e74c3c", "V-P10": "#27ae60", "V-P15": "#8e44ad",
              "V-P20": "#2980b9", "V-P30": "#d35400",
              "B&H-30%": "#f39c12", "B&H-100%": "#f39c12", "B&H-50/50": "#f39c12",
              "Paper": "#1abc9c", "Static": "#95a5a6"}
    n_strategies = len(results)

    fig, axes = plt.subplots(
        n_strategies + 1, 1, figsize=(14, 4 * (n_strategies + 1)),
        sharex=True,
        gridspec_kw={"height_ratios": [1] * n_strategies + [1]},
    )
    asset = results[0][1].asset
    fig.suptitle(
        f"{asset.name} ({asset.code}) DGT 4-Way Comparison\n"
        f"n={config.grid_count}, k={config.grid_spacing_pct}%, "
        f"m={config.levels_above}  |  {bars[0].trade_date} ~ {bars[-1].trade_date}",
        fontsize=13, fontweight="bold",
    )

    # --- Per-strategy panels: Price + grid levels + trade markers ---
    def _mode_for(lbl: str) -> str:
        if lbl.startswith("B&H"):
            return "bh"
        if (lbl.startswith("Trend") or lbl.startswith("Hyb-D") or lbl.startswith("ADR")
                or lbl in ("Hyb-Daily", "Hyb-ATR", "Hyb-ADR")):
            return "paper_adaptive_daily"
        if lbl.startswith("Hyb"):
            return "paper_adaptive"
        if lbl.startswith("Paper"):
            return "paper"
        return {"Static": "static", "On-Breach": "on_breach",
                "Daily": "daily", "Adaptive": "adaptive",
                "Adp-Narrow": "adaptive"}.get(lbl, "static")

    _best_acfg = _AdaptiveConfig(
        atr_period=14, multiplier=Decimal("1.0"),
        k_min=Decimal("0.005"), k_max=Decimal("0.05"),
    )
    adaptive_cfgs: dict[str, _AdaptiveConfig | None] = {
        "Hyb-Daily": _best_acfg,
    }
    for i, (label, result) in enumerate(results):
        ax = axes[i]
        color = colors.get(label, "#555")

        # Price line
        ax.plot(dates, closes, color="#2c3e50", linewidth=0.8, alpha=0.6)

        # Grid levels as Bollinger-band style envelope
        acfg = adaptive_cfgs.get(label)
        rc = configs_per_result[i] if configs_per_result else config
        _draw_grid_levels(ax, result, dates, rc,
                          mode=_mode_for(label),
                          ohlcv_bars=bars, adaptive_cfg=acfg,
                          band_color=color)

        # Trade markers
        buy_dates = [t.trade_date for t in result.trades if t.side == "BUY"]
        buy_prices = [float(t.rounded_price) for t in result.trades if t.side == "BUY"]
        sell_dates = [t.trade_date for t in result.trades if t.side == "SELL"]
        sell_prices = [float(t.rounded_price) for t in result.trades if t.side == "SELL"]

        ax.scatter(buy_dates, buy_prices, marker="^", color="#27ae60",
                   s=50, zorder=5, label=f"BUY ({len(buy_dates)})",
                   edgecolors="white", linewidths=0.5)
        ax.scatter(sell_dates, sell_prices, marker="v", color="#c0392b",
                   s=50, zorder=5, label=f"SELL ({len(sell_dates)})",
                   edgecolors="white", linewidths=0.5)

        n_trades = len(result.trades)
        final_v = float(result.final_balance.amount)
        initial_v = float(result.initial_capital.amount)
        pnl_pct = (final_v - initial_v) / initial_v * 100
        ax.set_ylabel("Price (KRW)", fontsize=9)
        ax.set_title(f"{label}  —  {n_trades} trades, PnL {pnl_pct:+.1f}%",
                     fontsize=11, fontweight="bold", color=color, loc="left")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)

    # --- Bottom panel: Equity curve overlay ---
    ax_eq = axes[-1]
    initial = float(results[0][1].initial_capital.amount)
    ax_eq.axhline(initial, color="#95a5a6", linewidth=0.8, linestyle="--",
                  label=f"Initial ({initial:,.0f})", alpha=0.7)
    for label, result in results:
        eq = [float(s.total_value) for s in result.daily_snapshots]
        eq_dates = [s.trade_date for s in result.daily_snapshots]
        color = colors.get(label, "#555")
        n_trades = len(result.trades)
        final_v = eq[-1] if eq else 0
        pnl_pct = (final_v - initial) / initial * 100
        ax_eq.plot(eq_dates, eq, color=color, linewidth=1.3,
                   label=f"{label} ({n_trades}t, {pnl_pct:+.1f}%)")
    ax_eq.set_ylabel("Portfolio Value (KRW)", fontsize=9)
    ax_eq.set_title("Equity Curve Comparison", fontsize=11,
                    fontweight="bold", loc="left")
    ax_eq.legend(loc="upper right", fontsize=9)
    ax_eq.grid(True, alpha=0.3)
    ax_eq.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _draw_grid_levels(
    ax: object,
    result: _DGTBacktestResult,
    dates: list[date],
    config: _DGTConfig,
    mode: str = "static",
    ohlcv_bars: list[OHLCV] | None = None,
    adaptive_cfg: _AdaptiveConfig | None = None,
    band_color: str = "#bdc3c7",
) -> None:
    """Draw grid levels as Bollinger-band style envelope.

    Per-bar grid bounds (min/max) are reconstructed by replaying the
    rebalancing logic, then drawn as filled band + boundary lines.
    Intermediate grid levels are drawn as thin lines within the band.
    ohlcv_bars + adaptive_cfg required for adaptive mode (ATR computation).
    """
    from src.research.dgt.formulas import grid_levels_table1

    snapshots = result.daily_snapshots
    if not snapshots or mode == "bh":
        return

    # Reconstruct per-bar grid state
    ref = snapshots[0].close_price
    k = config.k_ratio
    # Paper mode: m = n//2 (symmetric), others: config.levels_above
    m = config.grid_count // 2 if mode in ("paper", "paper_adaptive") else config.levels_above
    levels = grid_levels_table1(
        n=config.grid_count, reference_price=ref,
        k=k, levels_above=m,
    )

    per_bar_levels: list[list[float]] = []
    for bar_idx, snap in enumerate(snapshots):
        close = snap.close_price
        should_rebalance = False
        if mode in ("on_breach", "paper", "paper_adaptive"):
            should_rebalance = close < levels[0] or close > levels[-1]
        elif mode in ("daily", "adaptive", "paper_adaptive_daily"):
            should_rebalance = True

        if should_rebalance:
            ref = close
            if mode in ("paper", "paper_adaptive", "paper_adaptive_daily"):
                m = config.grid_count // 2  # re-symmetrize on reset
            if mode in ("adaptive", "paper_adaptive", "paper_adaptive_daily") and ohlcv_bars and adaptive_cfg:
                from src.research.dgt.adaptive_runner import _compute_atr
                atr = _compute_atr(ohlcv_bars, adaptive_cfg.atr_period, bar_idx)
                if atr > 0 and close > 0:
                    atr_pct = atr / close
                    k = max(adaptive_cfg.k_min, min(adaptive_cfg.k_max,
                            atr_pct * adaptive_cfg.multiplier))
            levels = grid_levels_table1(
                n=config.grid_count, reference_price=ref,
                k=k, levels_above=m,
            )
        per_bar_levels.append([float(lv) for lv in levels])

    bar_dates = [s.trade_date for s in snapshots]
    band_min = [lvls[0] for lvls in per_bar_levels]
    band_max = [lvls[-1] for lvls in per_bar_levels]

    # Outer band fill
    ax.fill_between(bar_dates, band_min, band_max, color=band_color, alpha=0.12,
                    label="Grid range")
    # Band boundary lines
    ax.plot(bar_dates, band_min, color=band_color, linewidth=1.0, alpha=0.6)
    ax.plot(bar_dates, band_max, color=band_color, linewidth=1.0, alpha=0.6)

    # Intermediate grid levels as thin lines
    n_levels = len(per_bar_levels[0])
    for li in range(1, n_levels - 1):
        level_series = [lvls[li] for lvls in per_bar_levels]
        ax.plot(bar_dates, level_series, color=band_color, linewidth=0.3, alpha=0.4)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def _fmt_krw(v: Decimal) -> str:
    return f"{v:,.0f}"


def _fmt_pct(v: Decimal) -> str:
    return f"{v:.2f}%"


def _render_html_report(
    results: list[tuple[str, _DGTBacktestResult]],
    config: _DGTConfig,
    chart_png: bytes,
    output_path: Path,
    per_stock_charts: dict[str, bytes] | None = None,
    assets: list[Asset] | None = None,
) -> None:
    asset = results[0][1].asset
    capital = results[0][1].initial_capital
    chart_b64 = base64.b64encode(chart_png).decode("ascii")

    # Title
    if assets and len(assets) > 1:
        title_str = " + ".join(f"{a.name}({a.code})" for a in assets)
    else:
        title_str = f"{escape(asset.name)} ({escape(asset.code)})"

    # Comparison table
    summaries = [_result_summary(label, r, capital) for label, r in results]
    comparison_rows = ""
    for s in summaries:
        comparison_rows += (
            f"<tr>"
            f"<td><b>{escape(s['label'])}</b></td>"
            f"<td>{_fmt_krw(Decimal(s['final']))}</td>"
            f"<td>{_fmt_krw(Decimal(s['pnl']))}</td>"
            f"<td>{s['pnl_pct']}%</td>"
            f"<td>{s['trades']} (B{s['buys']}/S{s['sells']})</td>"
            f"<td>{s['cagr']}%</td>"
            f"<td>{s['mdd']}%</td>"
            f"<td>{s['sharpe']}</td>"
            f"<td>{s['calmar']}</td>"
            f"</tr>\n"
        )

    # Per-stock chart sections
    per_stock_html = ""
    if per_stock_charts and assets:
        for a in assets:
            if a.code in per_stock_charts:
                b64 = base64.b64encode(per_stock_charts[a.code]).decode("ascii")
                per_stock_html += f"""
<h2>{escape(a.name)} ({escape(a.code)}) — Per-Strategy Detail</h2>
<div class="chart">
<img src="data:image/png;base64,{b64}" alt="{escape(a.name)} detail">
</div>
"""

    # Per-strategy trade logs
    trade_sections = ""
    for label, result in results:
        trade_rows = "\n".join(_trade_row(t) for t in result.trades)
        if not trade_rows:
            trade_rows = '<tr><td colspan="8"><em>(no trades)</em></td></tr>'
        trade_sections += f"""
<details>
<summary>{escape(label)} — Trade Log ({len(result.trades)})</summary>
<table>
<thead>
<tr><th>Date</th><th>Side</th><th>Grid Level</th><th>Price</th>
<th>Qty</th><th>Gross</th><th>Tax+Comm</th><th>Cash Delta</th></tr>
</thead>
<tbody>
{trade_rows}
</tbody>
</table>
</details>
"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>DGT Comparison — {title_str}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                     "Apple SD Gothic Neo", sans-serif;
        margin: 20px; max-width: 1400px; color: #2c3e50; }}
h1 {{ color: #2c3e50; }}
h2 {{ color: #34495e; border-bottom: 2px solid #ecf0f1;
      padding-bottom: 5px; margin-top: 25px; }}
table {{ border-collapse: collapse; margin: 10px 0; width: 100%; }}
th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: right;
          font-size: 14px; }}
th {{ background: #f8f9fa; font-weight: 600; text-align: center; }}
td:first-child {{ text-align: left; }}
.chart img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
.side-buy  {{ color: #27ae60; font-weight: 600; }}
.side-sell {{ color: #c0392b; font-weight: 600; }}
.params {{ background: #fafbfc; border: 1px solid #e1e6ec;
           border-radius: 6px; padding: 12px 16px; margin: 12px 0; }}
.params span {{ margin-right: 24px; }}
.winner {{ background: #eafaf1; font-weight: 700; }}
details {{ margin: 14px 0; }}
summary {{ cursor: pointer; padding: 8px 12px; background: #f8f9fa;
           border: 1px solid #ddd; border-radius: 4px; font-weight: 600; }}
summary:hover {{ background: #ecf0f1; }}
</style>
</head>
<body>
<h1>DGT Comparison — {title_str}</h1>

<div class="params">
  <span><b>Period:</b> {results[0][1].start} ~ {results[0][1].end}</span>
  <span><b>Params:</b> n={config.grid_count}</span>
  <span><b>Initial Capital:</b> {_fmt_krw(capital.amount)} KRW</span>
</div>

<h2>Comparison</h2>
<table>
<thead>
<tr><th>Strategy</th><th>Final Balance</th><th>PnL</th><th>PnL %</th>
<th>Trades</th><th>CAGR</th><th>MDD</th><th>Sharpe</th><th>Calmar</th></tr>
</thead>
<tbody>
{comparison_rows}
</tbody>
</table>

<h2>Equity Curve Comparison</h2>
<div class="chart">
<img src="data:image/png;base64,{chart_b64}" alt="DGT Comparison Chart">
</div>

{per_stock_html}

<h2>Trade Logs</h2>
{trade_sections}

</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def _trade_row(t: _DGTTrade) -> str:
    side_cls = "side-buy" if t.side == "BUY" else "side-sell"
    tax_comm = t.tax + t.commission
    return (
        f"<tr>"
        f"<td style='text-align:left'>{t.trade_date}</td>"
        f'<td class="{side_cls}" style="text-align:center">{t.side}</td>'
        f"<td>{_fmt_krw(t.grid_level_price)}</td>"
        f"<td>{_fmt_krw(t.rounded_price)}</td>"
        f"<td style='text-align:center'>{t.quantity}</td>"
        f"<td>{_fmt_krw(t.gross)}</td>"
        f"<td>{_fmt_krw(tax_comm)}</td>"
        f"<td>{_fmt_krw(t.cash_delta)}</td>"
        f"</tr>"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dgt_backtest",
        description="KRX DGT adaptive comparison backtest via pykrx.",
    )
    parser.add_argument("--code", default="035720",
                        help="KRX ticker code(s), comma-separated for multi-asset (e.g. 005930,005380)")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--initial-capital", type=str, default="10000000",
        help="KRW amount (default: 10000000)",
    )
    parser.add_argument("--grid-levels", type=int, default=11, help="n (default: 11)")
    parser.add_argument(
        "--grid-spacing-pct", type=str, default="3",
        help="k as percent (default: 3)",
    )
    parser.add_argument("--levels-above", type=int, default=1, help="m (default: 1)")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("report/kakao-dgt/"),
        help="Output directory",
    )
    return parser


def _run_multi_asset_strategy(
    label: str,
    assets: list[Asset],
    bars_map: dict[str, list[OHLCV]],
    config: _DGTConfig,
    capital: Money,
    start: date,
    end: date,
    adp_params: dict[str, object] | None,
) -> tuple[_DGTBacktestResult, list[_DGTBacktestResult]]:
    """Run a strategy on multiple stocks with equal capital split.

    Returns (merged_result, per_stock_results).
    """
    n_stocks = len(assets)
    per_stock_capital = Money(
        amount=capital.amount / Decimal(n_stocks), currency=capital.currency,
    )
    per_stock_results: list[_DGTBacktestResult] = []
    for asset in assets:
        bars = bars_map[asset.code]
        if adp_params is None:
            r = _run_paper(asset, config, per_stock_capital, bars, start, end)
        else:
            r = _run_paper_adaptive(asset, config, per_stock_capital, bars, start, end, **adp_params)
        per_stock_results.append(r)
    merged = _merge_multi_results(per_stock_results, capital, start, end)
    return merged, per_stock_results


def _run_multi_asset_bh(
    assets: list[Asset],
    bars_map: dict[str, list[OHLCV]],
    capital: Money,
    start: date,
    end: date,
) -> tuple[_DGTBacktestResult, list[_DGTBacktestResult]]:
    """B&H with equal split across stocks (100% of each allocation).

    Returns (merged_result, per_stock_results).
    """
    n_stocks = len(assets)
    per_stock_capital = Money(
        amount=capital.amount / Decimal(n_stocks), currency=capital.currency,
    )
    per_stock_results: list[_DGTBacktestResult] = []
    for asset in assets:
        bars = bars_map[asset.code]
        r = _run_buy_and_hold(asset, per_stock_capital, bars, start, end, Decimal("100"))
        per_stock_results.append(r)
    merged = _merge_multi_results(per_stock_results, capital, start, end)
    return merged, per_stock_results


def _render_per_stock_charts(
    assets: list[Asset],
    bars_map: dict[str, list[OHLCV]],
    strategy_per_stock: dict[str, list[_DGTBacktestResult]],
    config: _DGTConfig,
    adaptive_cfg: _AdaptiveConfig | None = None,
) -> dict[str, bytes]:
    """Render per-stock chart: price + grid (Hyb-Daily) + trade markers for all strategies."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    colors_list = {"Paper-3%": "#e74c3c", "Paper-1%": "#8e44ad",
                   "Hyb-Daily": "#27ae60", "B&H-25%": "#f39c12"}
    result_pngs: dict[str, bytes] = {}

    for stock_idx, asset in enumerate(assets):
        bars = bars_map[asset.code]
        dates = [b.trade_date for b in bars]
        closes = [float(b.close) for b in bars]

        strategy_labels = list(strategy_per_stock.keys())
        n_strats = len(strategy_labels)

        fig, axes = plt.subplots(n_strats, 1, figsize=(14, 3.5 * n_strats),
                                 sharex=True)
        if n_strats == 1:
            axes = [axes]
        fig.suptitle(f"{asset.name} ({asset.code})  —  Per-Strategy Detail",
                     fontsize=13, fontweight="bold")

        for si, label in enumerate(strategy_labels):
            ax = axes[si]
            result = strategy_per_stock[label][stock_idx]
            color = colors_list.get(label, "#555")

            # Price line
            ax.plot(dates, closes, color="#2c3e50", linewidth=0.8, alpha=0.6)

            # Grid levels (skip for B&H)
            if not label.startswith("B&H"):
                mode = "paper_adaptive_daily" if label == "Hyb-Daily" else "paper"
                acfg = adaptive_cfg if label == "Hyb-Daily" else None
                rc = config
                if label == "Paper-3%":
                    rc = _DGTConfig(config.grid_count, Decimal("3"), config.grid_count // 2)
                elif label == "Paper-1%":
                    rc = _DGTConfig(config.grid_count, Decimal("1"), config.grid_count // 2)
                _draw_grid_levels(ax, result, dates, rc,
                                  mode=mode, ohlcv_bars=bars,
                                  adaptive_cfg=acfg, band_color=color)

            # Trade markers
            buy_dates = [t.trade_date for t in result.trades if t.side == "BUY"]
            buy_prices = [float(t.rounded_price) for t in result.trades if t.side == "BUY"]
            sell_dates = [t.trade_date for t in result.trades if t.side == "SELL"]
            sell_prices = [float(t.rounded_price) for t in result.trades if t.side == "SELL"]

            ax.scatter(buy_dates, buy_prices, marker="^", color="#27ae60",
                       s=40, zorder=5, label=f"BUY ({len(buy_dates)})",
                       edgecolors="white", linewidths=0.5)
            ax.scatter(sell_dates, sell_prices, marker="v", color="#c0392b",
                       s=40, zorder=5, label=f"SELL ({len(sell_dates)})",
                       edgecolors="white", linewidths=0.5)

            n_trades = len(result.trades)
            initial_v = float(result.initial_capital.amount)
            final_v = float(result.final_balance.amount)
            pnl_pct = (final_v - initial_v) / initial_v * 100 if initial_v else 0
            ax.set_title(f"{label}  —  {n_trades} trades, PnL {pnl_pct:+.1f}%",
                         fontsize=10, fontweight="bold", color=color, loc="left")
            ax.legend(loc="upper right", fontsize=7)
            ax.grid(True, alpha=0.3)
            ax.set_ylabel("Price", fontsize=8)

        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate()
        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)
        result_pngs[asset.code] = buf.getvalue()

    return result_pngs


def _compute_cumulative_realized_single(result: _DGTBacktestResult) -> dict[date, Decimal]:
    """Compute cumulative realized P&L for a single-stock result (weighted avg cost)."""
    avg_cost = Decimal("0")
    total_holdings = Decimal("0")
    cum_realized = Decimal("0")
    realized_by_date: dict[date, Decimal] = {}

    for trade in result.trades:
        if trade.side == "BUY":
            cost_per_share = trade.rounded_price
            if total_holdings + trade.quantity > 0:
                avg_cost = (
                    (avg_cost * total_holdings + cost_per_share * trade.quantity)
                    / (total_holdings + trade.quantity)
                )
            total_holdings += trade.quantity
        elif trade.side == "SELL":
            profit = (trade.rounded_price - avg_cost) * trade.quantity
            fees = trade.tax + trade.commission
            cum_realized += profit - fees
            total_holdings -= trade.quantity
        realized_by_date[trade.trade_date] = cum_realized
    return realized_by_date


def _compute_cumulative_realized(
    result: _DGTBacktestResult,
    per_stock: list[_DGTBacktestResult] | None = None,
) -> dict[date, float]:
    """Compute cumulative realized P&L, summing per-stock when available."""
    if per_stock and len(per_stock) > 1:
        # Compute per stock, then sum by date
        all_by_date: dict[date, Decimal] = {}
        for stock_result in per_stock:
            stock_realized = _compute_cumulative_realized_single(stock_result)
            for d, val in stock_realized.items():
                all_by_date[d] = all_by_date.get(d, Decimal("0")) + val
        # For dates with partial updates, forward-fill each stock independently
        per_stock_last: list[Decimal] = [Decimal("0")] * len(per_stock)
        snapshot_dates = [s.trade_date for s in result.daily_snapshots]
        stock_by_date: list[dict[date, Decimal]] = [
            _compute_cumulative_realized_single(sr) for sr in per_stock
        ]
        filled: dict[date, float] = {}
        for d in snapshot_dates:
            total = Decimal("0")
            for i, sbd in enumerate(stock_by_date):
                if d in sbd:
                    per_stock_last[i] = sbd[d]
                total += per_stock_last[i]
            filled[d] = float(total)
        return filled
    else:
        realized_by_date = _compute_cumulative_realized_single(result)
        snapshot_dates = [s.trade_date for s in result.daily_snapshots]
        filled: dict[date, float] = {}
        last_val = 0.0
        for d in snapshot_dates:
            if d in realized_by_date:
                last_val = float(realized_by_date[d])
            filled[d] = last_val
        return filled


def _render_equity_only_chart(
    results: list[tuple[str, _DGTBacktestResult]],
    title: str,
    show_realized: bool = False,
    per_stock_map: dict[str, list[_DGTBacktestResult]] | None = None,
) -> bytes:
    """Equity curve overlay chart (no grid panels, for multi-asset)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    colors_list = ["#e74c3c", "#8e44ad", "#27ae60", "#f39c12", "#2980b9"]

    n_panels = 2 if show_realized else 1
    fig, axes = plt.subplots(
        n_panels, 1, figsize=(14, 6 * n_panels),
        sharex=True,
        gridspec_kw={"height_ratios": [1] * n_panels},
    )
    if n_panels == 1:
        axes = [axes]
    fig.suptitle(title, fontsize=13, fontweight="bold")

    ax = axes[0]
    initial = float(results[0][1].initial_capital.amount)
    ax.axhline(initial, color="#95a5a6", linewidth=0.8, linestyle="--",
               label=f"Initial ({initial:,.0f})", alpha=0.7)

    for i, (label, result) in enumerate(results):
        eq = [float(s.total_value) for s in result.daily_snapshots]
        eq_dates = [s.trade_date for s in result.daily_snapshots]
        color = colors_list[i % len(colors_list)]
        n_trades = len(result.trades)
        final_v = eq[-1] if eq else 0
        pnl_pct = (final_v - initial) / initial * 100
        ax.plot(eq_dates, eq, color=color, linewidth=1.5,
                label=f"{label} ({n_trades}t, {pnl_pct:+.1f}%)")

    ax.set_ylabel("Portfolio Value (KRW)", fontsize=10)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    if show_realized:
        ax_r = axes[1]
        ax_r.axhline(0, color="#95a5a6", linewidth=0.8, linestyle="--", alpha=0.5)
        for i, (label, result) in enumerate(results):
            ps = per_stock_map.get(label) if per_stock_map else None
            realized = _compute_cumulative_realized(result, per_stock=ps)
            if not realized:
                continue
            r_dates = list(realized.keys())
            r_vals = list(realized.values())
            color = colors_list[i % len(colors_list)]
            final_r = r_vals[-1] if r_vals else 0
            ax_r.plot(r_dates, r_vals, color=color, linewidth=1.5,
                      label=f"{label} (realized {final_r:+,.0f})")
        ax_r.set_ylabel("Cumulative Realized P&L (KRW)", fontsize=10)
        ax_r.set_title("Realized Profit (weighted avg cost)", fontsize=11,
                       fontweight="bold", loc="left")
        ax_r.legend(loc="upper left", fontsize=9)
        ax_r.grid(True, alpha=0.3)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    codes = [c.strip() for c in args.code.split(",")]
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    config = _DGTConfig(
        grid_count=args.grid_levels,
        grid_spacing_pct=Decimal(args.grid_spacing_pct),
        levels_above=args.levels_above,
    )
    capital = Money(amount=Decimal(args.initial_capital), currency=Currency.KRW)
    m_sym = config.grid_count // 2
    base_cfg = _DGTConfig(
        grid_count=config.grid_count,
        grid_spacing_pct=config.grid_spacing_pct,
        levels_above=m_sym,
    )

    # Fetch OHLCV for all stocks
    assets: list[Asset] = []
    bars_map: dict[str, list[OHLCV]] = {}
    for code in codes:
        asset = _build_asset(code)
        assets.append(asset)
        print(f"Fetching OHLCV for {asset.name} ({asset.code}) [{start} ~ {end}] ...")
        bars = _fetch_ohlcv(code, start, end, asset)
        bars_map[code] = bars
        print(f"  loaded {len(bars)} bars")

    is_multi = len(codes) > 1
    asset_names = " + ".join(f"{a.name}({a.code})" for a in assets)

    _adp_base = {"multiplier": Decimal("1.0"), "k_min": Decimal("0.005"), "k_max": Decimal("0.05"),
                 "rebalance_mode": "daily", "volatility_measure": "adr"}
    def _vol(period: int = 20, mult: str = "2.0") -> dict[str, object]:
        return {**_adp_base, "volume_gate": True, "volume_gate_period": period,
                "volume_gate_multiplier": Decimal(mult)}
    run_specs: list[tuple[str, _DGTConfig, dict[str, object] | None]] = [
        ("ADR-Base", base_cfg, {**_adp_base}),
        ("ADR+Vol", base_cfg, _vol(10, "1.5")),
    ]

    n_variants = len(run_specs)
    mode_str = f"Multi-Asset ({len(codes)} stocks)" if is_multi else "Single"
    print(f"\nRunning {n_variants}-way comparison [{mode_str}] (n={config.grid_count}):")

    results: list[tuple[str, _DGTBacktestResult]] = []
    variant_configs: list[_DGTConfig] = []

    # per-stock results: {strategy_label: [result_per_stock]}
    strategy_per_stock: dict[str, list[_DGTBacktestResult]] = {}

    if is_multi:
        pct = 100 // len(codes)
        bh_label = f"B&H-{pct}%"
        for idx, (label, vcfg, adp_params) in enumerate(run_specs, 1):
            print(f"  [{idx}/{n_variants}] {label} (equal split across {len(codes)} stocks) ...")
            merged, per_stock = _run_multi_asset_strategy(
                label, assets, bars_map, vcfg, capital, start, end, adp_params)
            results.append((label, merged))
            variant_configs.append(vcfg)
            strategy_per_stock[label] = per_stock

        print(f"  [+] {bh_label} (buy once, hold, equal split) ...")
        bh_merged, bh_per_stock = _run_multi_asset_bh(assets, bars_map, capital, start, end)
        results.append((bh_label, bh_merged))
        variant_configs.append(base_cfg)
        strategy_per_stock[bh_label] = bh_per_stock
    else:
        asset = assets[0]
        bars = bars_map[codes[0]]
        for idx, (label, vcfg, adp_params) in enumerate(run_specs, 1):
            if adp_params is None:
                print(f"  [{idx}/{n_variants}] {label} (fixed k, m=n//2) ...")
                r = _run_paper(asset, vcfg, capital, bars, start, end)
            else:
                print(f"  [{idx}/{n_variants}] {label} (ATR-adaptive k, m=n//2) ...")
                r = _run_paper_adaptive(asset, vcfg, capital, bars, start, end, **adp_params)
            results.append((label, r))
            variant_configs.append(vcfg)

        print(f"  [+] B&H-100% (buy once, hold) ...")
        bh = _run_buy_and_hold(asset, capital, bars, start, end, Decimal("100"))
        results.append(("B&H-100%", bh))
        variant_configs.append(base_cfg)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON summaries
    comparison_data = {}
    for label, result in results:
        s = _result_summary(label, result, capital)
        comparison_data[label] = s

    (output_dir / "comparison.json").write_text(
        json.dumps(comparison_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Charts
    print("\nRendering charts ...")
    per_stock_pngs: dict[str, bytes] = {}
    if is_multi:
        chart_title = (f"{asset_names}\nMulti-Asset DGT Comparison  |  "
                       f"n={config.grid_count}, equal split  |  {start} ~ {end}")
        chart_png = _render_equity_only_chart(
            results, chart_title, show_realized=True, per_stock_map=strategy_per_stock,
        )
        # Per-stock detail charts
        print("  Rendering per-stock detail charts ...")
        per_stock_pngs = _render_per_stock_charts(
            assets, bars_map, strategy_per_stock, config,
            adaptive_cfg=_AdaptiveConfig(
                atr_period=14, multiplier=Decimal("1.0"),
                k_min=Decimal("0.005"), k_max=Decimal("0.05"),
            ),
        )
        for code, png in per_stock_pngs.items():
            (output_dir / f"chart_{code}.png").write_bytes(png)
    else:
        chart_png = _render_comparison_chart(results, bars_map[codes[0]], config,
                                             configs_per_result=variant_configs)
    (output_dir / "comparison_chart.png").write_bytes(chart_png)

    # HTML report
    print("Generating HTML report ...")
    _render_html_report(results, config, chart_png, output_dir / "report.html",
                        per_stock_charts=per_stock_pngs, assets=assets if is_multi else None)

    # Print comparison table
    print(f"\n{'='*80}")
    print(f"  DGT Comparison — {asset_names}")
    print(f"  Period: {start} ~ {end}")
    print(f"  Params: n={config.grid_count}, capital={_fmt_krw(capital.amount)} KRW")
    if is_multi:
        print(f"  Mode: Multi-Asset (equal split across {len(codes)} stocks)")
    print(f"{'='*80}")
    print(f"  {'Strategy':<12} {'Final':>14} {'PnL':>14} {'PnL%':>8} "
          f"{'Trades':>8} {'CAGR':>8} {'MDD':>8} {'Sharpe':>8} {'Calmar':>8}")
    print(f"  {'-'*12} {'-'*14} {'-'*14} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for label, result in results:
        s = comparison_data[label]
        final = Decimal(s["final"])
        pnl = Decimal(s["pnl"])
        print(f"  {label:<12} {_fmt_krw(final):>14} {_fmt_krw(pnl):>14} "
              f"{s['pnl_pct']:>7}% {s['trades']:>8} {s['cagr']:>7}% "
              f"{s['mdd']:>7}% {s['sharpe']:>8} {s['calmar']:>8}")
    print(f"\n  Output: {output_dir.resolve()}/")
    print(f"  HTML:   {(output_dir / 'report.html').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
