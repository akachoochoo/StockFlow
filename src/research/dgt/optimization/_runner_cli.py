"""Phase 0.11.b — sub-step .3 CLI entry (WFO + grid + diagnostics).

ADR 0008 §1.8 sub-step .3 산출 driver. Invoke:

    python -m src.research.dgt.optimization run-grid \\
        --asset 069500 --period 2019-2024 \\
        --output docs/research/phase-0.11.b/sensitivity-heatmap.md

Outputs sensitivity heatmap Markdown + D7 4-way baseline 비교 + B2 trade-level
diagnostics. Decimal-only (CLAUDE.md §2.1). Underscore-prefix private
(ADR 0007 §1.6.3).

`python -m` 진입은 ring boundary 위반 아님 (terminal 진입점, ADR 0007 §1.6.2).
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
)
from src.research.dgt.optimization._baseline import (
    _BaselineMetrics,
    _run_baselines,
)
from src.research.dgt.optimization._grid_runner import (
    _GridPointResult,
    _WFOGridResult,
    _run_wfo_grid,
)


def _build_asset_069500() -> Asset:
    """D3 default = 069500 단독 (KODEX 200)."""
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _load_ohlcv_csv(
    path: Path, asset: Asset, start: date, end: date
) -> list[OHLCV]:
    """CSV 로더 — phase-0.11.a-comparison.md 정합 (2020-01-02 ~ 2024-12-30)."""
    bars: list[OHLCV] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = date.fromisoformat(row["date"])
            if d < start or d > end:
                continue
            bars.append(
                OHLCV(
                    asset=asset,
                    trade_date=d,
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row["volume"]),
                )
            )
    return bars


def _format_decimal(value: Decimal, *, decimals: int = 4) -> str:
    """Decimal → fixed-precision string (Markdown 표 정합)."""
    q = Decimal("0.1") ** decimals
    return str(value.quantize(q))


def _render_heatmap_markdown(
    result: _WFOGridResult,
    baselines: dict[str, _BaselineMetrics],
    *,
    bars_window_start: date,
    bars_window_end: date,
    elapsed_seconds: float,
) -> str:
    """Sensitivity heatmap Markdown 생성 (ADR 0008 D2 = Markdown only)."""
    lines: list[str] = []
    lines.append(
        "# Phase 0.11.b sub-step .3 — Sensitivity Heatmap + D7 baseline + B2 diagnostics"
    )
    lines.append("")
    lines.append(
        "> ADR 0008 §1.8 sub-step .3 산출. WFO + grid search + D7 4-way "
        "baseline + B2 trade-level diagnostics. Markdown only (ADR 0008 D2)."
    )
    lines.append(">")
    lines.append(
        f"> Asset: **{result.asset_code}** (KODEX 200, KR_ETF). "
        f"Window: {bars_window_start.isoformat()} ~ {bars_window_end.isoformat()} "
        f"({result.n_bars} bars). WFO n_folds={result.n_folds}, "
        f"grid_size={result.grid_size}, elapsed={elapsed_seconds:.2f}s."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section: Top 10
    lines.append("## 1. Top 10 parameter sets (OOS Sharpe desc)")
    lines.append("")
    lines.append(
        "| Rank | n | k (%) | m | IS Sharpe | OOS Sharpe | OOS CAGR (%) | "
        "OOS MDD (%) | OOS Calmar | DSR | trades |"
    )
    lines.append(
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for rank, p in enumerate(result.points[:10], start=1):
        lines.append(
            f"| {rank} | {p.config_n} | {p.config_k_pct} | {p.config_m} | "
            f"{_format_decimal(p.is_sharpe)} | "
            f"{_format_decimal(p.oos_sharpe)} | "
            f"{_format_decimal(p.oos_cagr_pct, decimals=3)} | "
            f"{_format_decimal(p.oos_mdd_pct, decimals=3)} | "
            f"{_format_decimal(p.oos_calmar)} | "
            f"{_format_decimal(p.dsr)} | "
            f"{p.total_trade_count} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section: D11 trigger preview
    lines.append("## 2. D11 trigger preview (informational, sub-step .4 영역)")
    lines.append("")
    baseline_band_count = sum(
        1 for p in result.points if p.passes_d11_baseline_band
    )
    dsr_pass_count = sum(1 for p in result.points if p.dsr >= Decimal("1.0"))
    sharpe_pass_count = sum(
        1 for p in result.points if p.oos_sharpe >= Decimal("0.473")
    )
    lines.append(
        "Baselines from `phase-0.11.a-comparison.md` §1 (Phase 0.7.3): "
        "CAGR 2.5779% / MDD -8.2737% / Sharpe 0.5255 / Calmar 0.3116."
    )
    lines.append("")
    lines.append("| Criterion | Threshold | Grid points passing |")
    lines.append("|---|---|---:|")
    lines.append(
        f"| D11 (a) 4-metric ±10% band (AND) | "
        f"CAGR ≥ 2.32%, MDD ≥ -9.10%, Sharpe ≥ 0.473, Calmar ≥ 0.280 | "
        f"{baseline_band_count} / {result.grid_size} |"
    )
    lines.append(
        f"| D11 (b) DSR ≥ 1.0 | Bailey 2014 5% significance | "
        f"{dsr_pass_count} / {result.grid_size} |"
    )
    lines.append(
        f"| OOS Sharpe ≥ 0.473 (baseline × 0.9 slice) | informational | "
        f"{sharpe_pass_count} / {result.grid_size} |"
    )
    lines.append("")
    lines.append(
        "**D11 (c) parameter perturbation robustness** = sub-step .4 영역 "
        "(±10% 좌우 grid neighbor 평가 — 본 sub-step .3 informational skip)."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section: D7 baseline comparison
    lines.append("## 3. D7 4-way baseline 비교")
    lines.append("")
    lines.append(
        "| Baseline | CAGR (%) | MDD (%) | Sharpe | Calmar | trades | Note |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for key in [
        "(i) Phase 0.7.3 verbatim",
        "(ii) 069500 B&H",
        "(iii) 069500 SevenSplit",
        "(iv) 069500 DGT-best",
    ]:
        if key in baselines:
            b = baselines[key]
            lines.append(
                f"| {b.label} | {_format_decimal(b.cagr_pct, decimals=3)} | "
                f"{_format_decimal(b.mdd_pct, decimals=3)} | "
                f"{_format_decimal(b.sharpe)} | "
                f"{_format_decimal(b.calmar)} | "
                f"{b.trade_count} | {b.note} |"
            )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section: B2 diagnostics for best parameter set
    best_point = result.points[0] if result.points else None
    lines.append("## 4. B2 Trade-level diagnostics (best parameter set)")
    lines.append("")
    if best_point is not None:
        lines.append(
            f"Best parameter set: **n={best_point.config_n}, "
            f"k={best_point.config_k_pct}%, m={best_point.config_m}** "
            f"(OOS Sharpe = {_format_decimal(best_point.oos_sharpe)})."
        )
        lines.append("")
        lines.append(
            f"- Total trades (across all OOS folds): "
            f"**{best_point.total_trade_count}**"
        )
        lines.append(
            f"- Median holding period (days): "
            f"**{_format_decimal(best_point.median_holding_period_days, decimals=2)}**"
        )
        lines.append(
            f"- Mean holding period (days): "
            f"**{_format_decimal(best_point.mean_holding_period_days, decimals=2)}**"
        )
        lines.append("")
        lines.append("### Daily-return histogram (OOS concat, %)")
        lines.append("")
        lines.append("| Bin (low %) | Bin (high %) | Count | Bar |")
        lines.append("|---:|---:|---:|---|")
        max_count = max(
            (c for _, _, c in best_point.pnl_histogram), default=1
        )
        if max_count == 0:
            max_count = 1
        for low, high, count in best_point.pnl_histogram:
            bar_len = int(count * 40 / max_count)
            bar = "█" * bar_len if bar_len > 0 else ""
            lines.append(
                f"| {low} | {high} | {count} | {bar} |"
            )
    else:
        lines.append("_No grid points — empty result._")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section: full sensitivity heatmap
    lines.append("## 5. Full sensitivity heatmap (95 grid points, OOS Sharpe desc)")
    lines.append("")
    lines.append(
        "| Rank | n | k (%) | m | IS Sharpe | OOS Sharpe | OOS CAGR (%) | "
        "OOS MDD (%) | OOS Calmar | DSR | trades | D11(a) band |"
    )
    lines.append(
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:-:|"
    )
    for rank, p in enumerate(result.points, start=1):
        status = "PASS" if p.passes_d11_baseline_band else "FAIL"
        lines.append(
            f"| {rank} | {p.config_n} | {p.config_k_pct} | {p.config_m} | "
            f"{_format_decimal(p.is_sharpe)} | "
            f"{_format_decimal(p.oos_sharpe)} | "
            f"{_format_decimal(p.oos_cagr_pct, decimals=3)} | "
            f"{_format_decimal(p.oos_mdd_pct, decimals=3)} | "
            f"{_format_decimal(p.oos_calmar)} | "
            f"{_format_decimal(p.dsr)} | "
            f"{p.total_trade_count} | {status} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section: reproducibility notes
    lines.append("## 6. Reproducibility (D12)")
    lines.append("")
    lines.append(
        "- Deterministic ordering: grid generated via `itertools.product` "
        "with sorted keys (D12 invariant)."
    )
    lines.append(
        "- No random sampling — grid + WFO + DSR pipeline 은 seed-free "
        "(Decimal-only)."
    )
    lines.append(
        "- 2 회 동일 실행 시 byte-identical 산출 (AC15 정신 계승)."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="src.research.dgt.optimization",
        description=(
            "Phase 0.11.b sub-step .3 WFO + grid + sensitivity heatmap "
            "(ADR 0008 §1.8)."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_grid = sub.add_parser(
        "run-grid",
        help="WFO grid search + sensitivity heatmap Markdown 산출.",
    )
    run_grid.add_argument(
        "--asset",
        default="069500",
        help="Asset code (D3 default = 069500)",
    )
    run_grid.add_argument(
        "--csv",
        type=Path,
        default=Path("data/historical/KRX_069500_2019-2024.csv"),
    )
    run_grid.add_argument(
        "--start", default="2020-01-02", help="YYYY-MM-DD (default 2020-01-02)"
    )
    run_grid.add_argument(
        "--end", default="2024-12-30", help="YYYY-MM-DD (default 2024-12-30)"
    )
    run_grid.add_argument(
        "--initial-capital",
        type=str,
        default="10000000",
        help="KRW (Decimal-safe str)",
    )
    run_grid.add_argument(
        "--include-re-anchor",
        action="store_true",
        help="Enable 4-dim grid (re_anchor_period 포함).",
    )
    run_grid.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Markdown output path (e.g., docs/research/phase-0.11.b/sensitivity-heatmap.md)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd != "run-grid":
        parser.error(f"unknown cmd {args.cmd}")

    if args.asset != "069500":
        raise SystemExit(
            f"D3 default = 069500 단독. Got '{args.asset}'. "
            "Override gated until ADR 0008 §1.6 D3 변경 박제."
        )

    asset = _build_asset_069500()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    bars = _load_ohlcv_csv(args.csv, asset, start, end)
    if not bars:
        raise SystemExit(f"No bars loaded from {args.csv} in [{start}, {end}]")
    initial_capital_krw = Decimal(args.initial_capital)

    print(
        f"[run-grid] asset={args.asset} bars={len(bars)} "
        f"window={start.isoformat()}~{end.isoformat()} "
        f"include_re_anchor={args.include_re_anchor}",
        file=sys.stderr,
    )

    t0 = time.time()
    grid_result = _run_wfo_grid(
        bars=bars,
        asset=asset,
        include_re_anchor=args.include_re_anchor,
        initial_capital_krw=initial_capital_krw,
    )
    grid_elapsed = time.time() - t0
    print(
        f"[run-grid] grid done in {grid_elapsed:.2f}s — "
        f"grid_size={grid_result.grid_size} n_folds={grid_result.n_folds}",
        file=sys.stderr,
    )

    if not grid_result.points:
        raise SystemExit("Empty grid result — bug or empty filter")

    best_point = grid_result.points[0]
    t1 = time.time()
    baselines = _run_baselines(
        bars_069500=bars,
        asset_069500=asset,
        best_dgt_point=best_point,
        initial_capital_krw=initial_capital_krw,
    )
    baseline_elapsed = time.time() - t1
    print(
        f"[run-grid] baselines done in {baseline_elapsed:.2f}s",
        file=sys.stderr,
    )

    total_elapsed = time.time() - t0
    md = _render_heatmap_markdown(
        grid_result,
        baselines,
        bars_window_start=start,
        bars_window_end=end,
        elapsed_seconds=total_elapsed,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    print(
        f"[run-grid] wrote {args.output} "
        f"(total {total_elapsed:.2f}s, D10 budget 120s)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
