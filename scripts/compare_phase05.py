"""Compare two Phase 0.5 backtest JSON outputs (Policy D-2 vs Policy F).

ADR 0002 §8 D-vs-F retrospective tooling. Reads two
``trading backtest --json`` outputs and prints a side-by-side comparison
of the §8.1 metrics (the four standard return/risk metrics plus the
three Phase 0.5 capital-rotation metrics).

Usage::

    trading backtest --config config/strategies-D.yaml \\
        --csv data/historical/KRX_069500_2020-2024.csv \\
        --start 2020-01-02 --end 2024-12-30 --json > /tmp/D.json

    trading backtest --config config/strategies-F.yaml \\
        --csv data/historical/KRX_069500_2020-2024.csv \\
        --start 2020-01-02 --end 2024-12-30 --json > /tmp/F.json

    uv run python scripts/compare_phase05.py /tmp/D.json /tmp/F.json

The new metrics (ADR §8.1):
- Capital turnover = cumulative_buy_amount / initial_capital * (252 / N_days)
- Cumulative sells = count(SellActionRecord across all decisions)
- Avg capital utilization = mean(committed_capital_t / initial_capital)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Summary:
    """Per-policy summary computed from one ``--json`` payload."""

    label: str
    n_trading_days: int
    total_return_pct: Decimal
    cagr_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal
    calmar_ratio: Decimal
    capital_turnover: Decimal
    sell_count: int
    avg_capital_utilization: Decimal


def _cumulative_buy_amount(decisions: list[dict[str, Any]]) -> Decimal:
    total = Decimal(0)
    for d in decisions:
        ba = d.get("buy_action")
        if ba is None:
            continue
        total += Decimal(ba["filled_quantity"]) * Decimal(ba["filled_price"])
    return total


def _total_sell_count(decisions: list[dict[str, Any]]) -> int:
    return sum(len(d.get("sell_actions", [])) for d in decisions)


def _avg_capital_utilization(snapshots: list[dict[str, Any]]) -> Decimal:
    """Mean of committed_capital / initial_capital across the daily series."""
    if not snapshots:
        return Decimal(0)
    initial = Decimal(snapshots[0]["initial_capital"]["amount"])
    if initial == 0:
        return Decimal(0)
    util_sum = Decimal(0)
    for s in snapshots:
        committed = Decimal(s["total_market_value"]["amount"])
        util_sum += committed / initial
    return util_sum / Decimal(len(snapshots))


def _capital_turnover(
    decisions: list[dict[str, Any]], snapshots: list[dict[str, Any]]
) -> Decimal:
    """Cumulative buy spend * annualization factor / initial capital."""
    if not snapshots:
        return Decimal(0)
    initial = Decimal(snapshots[0]["initial_capital"]["amount"])
    n = len(snapshots)
    if initial == 0 or n == 0:
        return Decimal(0)
    cumulative = _cumulative_buy_amount(decisions)
    return (cumulative / initial) * (Decimal(252) / Decimal(n))


def summarize(label: str, payload: dict[str, Any]) -> Summary:
    decisions = payload.get("decisions", [])
    snapshots = payload.get("snapshots", [])
    return Summary(
        label=label,
        n_trading_days=int(payload.get("n_trading_days", 0)),
        total_return_pct=Decimal(payload.get("total_return_pct", "0")),
        cagr_pct=Decimal(payload.get("cagr_pct", "0")),
        max_drawdown_pct=Decimal(payload.get("max_drawdown_pct", "0")),
        sharpe_ratio=Decimal(payload.get("sharpe_ratio", "0")),
        calmar_ratio=Decimal(payload.get("calmar_ratio", "0")),
        capital_turnover=_capital_turnover(decisions, snapshots),
        sell_count=_total_sell_count(decisions),
        avg_capital_utilization=_avg_capital_utilization(snapshots),
    )


def render(d: Summary, f: Summary) -> str:
    """Render a side-by-side comparison table (text)."""
    rows: list[tuple[str, str, str, str]] = []

    def _fmt_decimal(v: Decimal, places: int = 4) -> str:
        # Quantize to fixed places for stable column widths; preserve sign.
        return f"{v:.{places}f}"

    def _row_decimal(label: str, d_val: Decimal, f_val: Decimal) -> None:
        delta = f_val - d_val
        rows.append((
            label,
            _fmt_decimal(d_val),
            _fmt_decimal(f_val),
            _fmt_decimal(delta),
        ))

    def _row_int(label: str, d_val: int, f_val: int) -> None:
        rows.append((label, str(d_val), str(f_val), str(f_val - d_val)))

    _row_int("Trading days", d.n_trading_days, f.n_trading_days)
    _row_decimal("Total return %", d.total_return_pct, f.total_return_pct)
    _row_decimal("CAGR %", d.cagr_pct, f.cagr_pct)
    _row_decimal("Max drawdown %", d.max_drawdown_pct, f.max_drawdown_pct)
    _row_decimal("Sharpe ratio", d.sharpe_ratio, f.sharpe_ratio)
    _row_decimal("Calmar ratio", d.calmar_ratio, f.calmar_ratio)
    _row_decimal("Capital turnover", d.capital_turnover, f.capital_turnover)
    _row_int("Cumulative sells", d.sell_count, f.sell_count)
    _row_decimal(
        "Avg capital util",
        d.avg_capital_utilization,
        f.avg_capital_utilization,
    )

    metric_w = max(len(r[0]) for r in rows)
    val_w = max(
        len(s)
        for r in rows
        for s in (r[1], r[2], r[3], d.label, f.label, "F-D")
    )
    val_w = max(val_w, 12)

    out: list[str] = []
    out.append("=" * (metric_w + (val_w + 2) * 3))
    out.append("Phase 0.5 Policy comparison (ADR 0002 §8)")
    out.append("=" * (metric_w + (val_w + 2) * 3))
    out.append(
        f"{'Metric':<{metric_w}}  "
        f"{d.label:>{val_w}}  {f.label:>{val_w}}  {'F - D':>{val_w}}"
    )
    out.append("-" * (metric_w + (val_w + 2) * 3))
    for label, d_str, f_str, delta_str in rows:
        out.append(
            f"{label:<{metric_w}}  "
            f"{d_str:>{val_w}}  {f_str:>{val_w}}  {delta_str:>{val_w}}"
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Policy D-2 vs Policy F backtest JSON outputs "
            "(ADR 0002 §8 D-vs-F retrospective)."
        )
    )
    parser.add_argument(
        "d_json",
        type=Path,
        help="Policy D-2 'trading backtest --json' output file.",
    )
    parser.add_argument(
        "f_json",
        type=Path,
        help="Policy F 'trading backtest --json' output file.",
    )
    parser.add_argument(
        "--d-label",
        default="Policy D-2",
        help="Label for the first policy column (default: 'Policy D-2').",
    )
    parser.add_argument(
        "--f-label",
        default="Policy F",
        help="Label for the second policy column (default: 'Policy F').",
    )
    args = parser.parse_args(argv)

    d_payload = json.loads(args.d_json.read_text(encoding="utf-8"))
    f_payload = json.loads(args.f_json.read_text(encoding="utf-8"))

    d_summary = summarize(args.d_label, d_payload)
    f_summary = summarize(args.f_label, f_payload)

    print(render(d_summary, f_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
