"""Phase 0.7.1 3-way comparison + gate verdict.

ADR 0003 §13.6.4 D / §2.2.5 / §2.2.6 박제 기반 분석 도구.

Compares:
  1. Phase 0 baseline     -- hard-coded citation from phase-0.md §3.2
  2. Phase 0.5 F (single) -- live JSON (invariant verification vs §13.6.4 G)
  3. Phase 0.7.1 multi    -- live JSON (069500 + 214980)

Invariant check: Phase 0.5 F re-run values must match phase-0.5-results.md
within 1e-4 tolerance.  Mismatch -> non-zero exit before gate evaluation.

Capital-utilization definition (ADR §2.2.6):
  per_asset_budget = initial_capital / N_assets
  per_asset_committed_t = quantity x avg_price  (cost-basis from valuation)
  per_asset_util_t = committed_t / per_asset_budget
  per_asset_avg_util = time-mean over trading days
  portfolio_avg_util = arithmetic mean over assets

Gate (ADR §2.2.5):
  H1  avg_capital_util >= 48.5 %
  H2  total_return_pct >= 25.96 %
  H3  sharpe_ratio     >=  0.39
  Pass >= 2 of 3 -> exit 0   (Phase 1 entry recommended)
  Pass < 2       -> exit 1   (user decision round #5)

Usage::

    uv run python scripts/analyze_phase_0_7_1.py \\
        /tmp/phase071/phase05_F.json \\
        /tmp/phase071/phase071_multi.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Phase 0 baseline -- hard-coded citation from docs/retrospectives/phase-0.md §3.2
# 100,000,000 KRW initial capital, 5-year KOSPI 200 (2020-01-02 ~ 2024-12-30).
# ---------------------------------------------------------------------------
PHASE_0_TOTAL_RETURN_PCT: Decimal = Decimal("25.96")
PHASE_0_CAGR_PCT: Decimal = Decimal("4.84")
PHASE_0_MAX_DRAWDOWN_PCT: Decimal = Decimal("-27.57")
PHASE_0_SHARPE: Decimal = Decimal("0.39")
PHASE_0_CALMAR: Decimal = Decimal("0.18")
# Estimated from 7 splits x 10M / 100M x (252 / 1231)
PHASE_0_CAPITAL_TURNOVER: Decimal = Decimal("0.143")
PHASE_0_CUMULATIVE_SELLS: int = 0
# Phase 0 §3.2: 자본 활용 69.92 % (7 splits x 10M = 70M committed / 100M)
# For per-asset-budget comparison: single asset, budget = 100M -> avg util 69.92 %
# (4.7-year dormancy after split_7: mostly fully committed during that period)
PHASE_0_AVG_CAPITAL_UTIL: Decimal = Decimal("0.6992")

# ---------------------------------------------------------------------------
# Phase 0.5 F invariant targets -- citation from phase-0.5-results.md
# ADR §13.6.4 G: difference < 1e-4 required
# ---------------------------------------------------------------------------
INVARIANT_TOTAL_RETURN_PCT: Decimal = Decimal("9.4229")
INVARIANT_CAGR_PCT: Decimal = Decimal("1.8620")
INVARIANT_MAX_DRAWDOWN_PCT: Decimal = Decimal("-15.9017")
INVARIANT_SHARPE: Decimal = Decimal("0.2977")
INVARIANT_CALMAR: Decimal = Decimal("0.1171")
INVARIANT_CAPITAL_TURNOVER: Decimal = Decimal("0.2862")
INVARIANT_CUMULATIVE_SELLS: int = 12
INVARIANT_AVG_CAPITAL_UTIL: Decimal = Decimal("0.1940")

# Gate thresholds -- ADR §2.2.5
# H1: avg capital utilization >= 48.5 % (= Phase 0.5 F 19.4 % x 2.5)
GATE_H1_AVG_UTIL_PCT: Decimal = Decimal("48.5")
GATE_H2_TOTAL_RETURN_PCT: Decimal = Decimal("25.96")
GATE_H3_SHARPE: Decimal = Decimal("0.39")

INVARIANT_TOLERANCE: Decimal = Decimal("1e-4")


@dataclass(frozen=True)
class Summary:
    label: str
    n_trading_days: int
    total_return_pct: Decimal
    cagr_pct: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal
    calmar_ratio: Decimal
    capital_turnover: Decimal
    cumulative_sells: int
    avg_capital_util: Decimal  # fraction (0-1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _capital_turnover(
    decisions: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    initial: Decimal,
) -> Decimal:
    n = len(snapshots)
    if initial == 0 or n == 0:
        return Decimal(0)
    cumulative = _cumulative_buy_amount(decisions)
    return (cumulative / initial) * (Decimal(252) / Decimal(n))


def _avg_util_single(
    snapshots: list[dict[str, Any]],
    initial: Decimal,
) -> Decimal:
    """Single-asset avg capital utilization (Phase 0.5 F style).

    committed_t = total_market_value / initial (same as compare_phase05.py).
    """
    if not snapshots or initial == 0:
        return Decimal(0)
    util_sum = Decimal(0)
    for s in snapshots:
        committed = Decimal(s["total_market_value"]["amount"])
        util_sum += committed / initial
    return util_sum / Decimal(len(snapshots))


def _avg_util_multi(
    snapshots: list[dict[str, Any]],
    initial: Decimal,
    n_assets: int,
) -> Decimal:
    """Multi-asset avg capital utilization per ADR §2.2.6.

    per_asset_budget = initial / n_assets
    per_asset_committed_t = sum of cost_basis for that asset's valuations
      = quantity x avg_price  (valuation.quantity x valuation.avg_price)
    per_asset_util_t = per_asset_committed_t / per_asset_budget
    portfolio_avg_util = mean over assets of time-mean(per_asset_util_t)

    Iterates once, building per-asset util series in order.
    """
    if not snapshots or initial == 0 or n_assets == 0:
        return Decimal(0)
    per_asset_budget = initial / Decimal(n_assets)

    # asset_code -> list of util (one entry per snapshot)
    asset_util: dict[str, list[Decimal]] = {}

    for s in snapshots:
        seen_in_snap: set[str] = set()
        for v in s.get("valuations", []):
            code = v["asset"]["code"]
            cost_basis = Decimal(v["quantity"]) * Decimal(v["avg_price"])
            util_t = cost_basis / per_asset_budget
            if code not in asset_util:
                # Back-fill with zeros for snapshots before first appearance
                idx = snapshots.index(s)
                asset_util[code] = [Decimal(0)] * idx
            asset_util[code].append(util_t)
            seen_in_snap.add(code)

        # Assets tracked but absent in this snapshot -> 0
        for code in asset_util:
            if code not in seen_in_snap:
                asset_util[code].append(Decimal(0))

    n_snaps = len(snapshots)
    per_asset_avgs: list[Decimal] = []
    for _code, series in asset_util.items():
        # Pad trailing zeros if needed
        while len(series) < n_snaps:
            series.append(Decimal(0))
        avg = sum(series) / Decimal(n_snaps)
        per_asset_avgs.append(avg)

    if not per_asset_avgs:
        return Decimal(0)
    return sum(per_asset_avgs) / Decimal(len(per_asset_avgs))


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------

def summarize_single(label: str, payload: dict[str, Any]) -> Summary:
    """Summarize a single-asset backtest JSON payload."""
    decisions = payload.get("decisions", [])
    snapshots = payload.get("snapshots", [])
    initial = Decimal(payload["initial_capital"]["amount"])
    return Summary(
        label=label,
        n_trading_days=int(payload.get("n_trading_days", 0)),
        total_return_pct=Decimal(str(payload.get("total_return_pct", "0"))),
        cagr_pct=Decimal(str(payload.get("cagr_pct", "0"))),
        max_drawdown_pct=Decimal(str(payload.get("max_drawdown_pct", "0"))),
        sharpe_ratio=Decimal(str(payload.get("sharpe_ratio", "0"))),
        calmar_ratio=Decimal(str(payload.get("calmar_ratio", "0"))),
        capital_turnover=_capital_turnover(decisions, snapshots, initial),
        cumulative_sells=_total_sell_count(decisions),
        avg_capital_util=_avg_util_single(snapshots, initial),
    )


def summarize_multi(label: str, payload: dict[str, Any], n_assets: int) -> Summary:
    """Summarize a multi-asset backtest JSON payload."""
    decisions = payload.get("decisions", [])
    snapshots = payload.get("snapshots", [])
    initial = Decimal(payload["initial_capital"]["amount"])
    return Summary(
        label=label,
        n_trading_days=int(payload.get("n_trading_days", 0)),
        total_return_pct=Decimal(str(payload.get("total_return_pct", "0"))),
        cagr_pct=Decimal(str(payload.get("cagr_pct", "0"))),
        max_drawdown_pct=Decimal(str(payload.get("max_drawdown_pct", "0"))),
        sharpe_ratio=Decimal(str(payload.get("sharpe_ratio", "0"))),
        calmar_ratio=Decimal(str(payload.get("calmar_ratio", "0"))),
        capital_turnover=_capital_turnover(decisions, snapshots, initial),
        cumulative_sells=_total_sell_count(decisions),
        avg_capital_util=_avg_util_multi(snapshots, initial, n_assets),
    )


# ---------------------------------------------------------------------------
# Phase 0 citation summary (no JSON needed)
# ---------------------------------------------------------------------------

def phase0_summary() -> Summary:
    return Summary(
        label="Phase 0 (baseline)",
        n_trading_days=1231,
        total_return_pct=PHASE_0_TOTAL_RETURN_PCT,
        cagr_pct=PHASE_0_CAGR_PCT,
        max_drawdown_pct=PHASE_0_MAX_DRAWDOWN_PCT,
        sharpe_ratio=PHASE_0_SHARPE,
        calmar_ratio=PHASE_0_CALMAR,
        capital_turnover=PHASE_0_CAPITAL_TURNOVER,
        cumulative_sells=PHASE_0_CUMULATIVE_SELLS,
        avg_capital_util=PHASE_0_AVG_CAPITAL_UTIL,
    )


# ---------------------------------------------------------------------------
# Invariant check (ADR §13.6.4 G)
# ---------------------------------------------------------------------------

def check_invariant(f05: Summary) -> list[str]:
    """Return list of failure messages; empty list = PASS."""
    failures: list[str] = []

    def _chk(name: str, actual: Decimal, expected: Decimal) -> None:
        diff = abs(actual - expected)
        if diff >= INVARIANT_TOLERANCE:
            failures.append(
                f"  {name}: actual={actual:.4f} expected={expected:.4f} diff={diff:.6f}"
            )

    _chk("Total return %", f05.total_return_pct, INVARIANT_TOTAL_RETURN_PCT)
    _chk("CAGR %", f05.cagr_pct, INVARIANT_CAGR_PCT)
    _chk("Max drawdown %", f05.max_drawdown_pct, INVARIANT_MAX_DRAWDOWN_PCT)
    _chk("Sharpe ratio", f05.sharpe_ratio, INVARIANT_SHARPE)
    _chk("Calmar ratio", f05.calmar_ratio, INVARIANT_CALMAR)
    _chk("Capital turnover", f05.capital_turnover, INVARIANT_CAPITAL_TURNOVER)
    _chk("Avg capital util", f05.avg_capital_util, INVARIANT_AVG_CAPITAL_UTIL)
    if f05.cumulative_sells != INVARIANT_CUMULATIVE_SELLS:
        failures.append(
            f"  Cumulative sells: actual={f05.cumulative_sells} "
            f"expected={INVARIANT_CUMULATIVE_SELLS}"
        )
    return failures


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fmt(v: Decimal, places: int = 4) -> str:
    return f"{v:.{places}f}"


def render_comparison(p0: Summary, f05: Summary, multi: Summary) -> str:
    width_m = 22  # metric column
    width_v = 15  # value column

    def row(metric: str, p0v: str, f05v: str, mv: str, delta: str) -> str:
        return (
            f"{metric:<{width_m}}  "
            f"{p0v:>{width_v}}  "
            f"{f05v:>{width_v}}  "
            f"{mv:>{width_v}}  "
            f"{delta:>{width_v}}"
        )

    sep = "=" * (width_m + (width_v + 2) * 4)
    thin = "-" * (width_m + (width_v + 2) * 4)

    lines: list[str] = [
        sep,
        "Phase 0.7.1.h 3-way comparison (ADR §2.2.5)",
        sep,
        row(
            "Metric",
            "Phase 0",
            "Phase 0.5 F",
            "Phase 0.7.1",
            "Delta vs 0.5 F",
        ),
        row("", "(baseline)", "(single, F)", "(multi, F)", ""),
        thin,
    ]

    def add_row(
        metric: str,
        p0v: Decimal,
        f05v: Decimal,
        mv: Decimal,
        places: int = 4,
    ) -> None:
        delta = mv - f05v
        lines.append(
            row(
                metric,
                _fmt(p0v, places),
                _fmt(f05v, places),
                _fmt(mv, places),
                ("+" if delta >= 0 else "") + _fmt(delta, places),
            )
        )

    add_row("Total return %", p0.total_return_pct, f05.total_return_pct, multi.total_return_pct)
    add_row("CAGR %", p0.cagr_pct, f05.cagr_pct, multi.cagr_pct)
    add_row("Max drawdown %", p0.max_drawdown_pct, f05.max_drawdown_pct, multi.max_drawdown_pct)
    add_row("Sharpe ratio", p0.sharpe_ratio, f05.sharpe_ratio, multi.sharpe_ratio)
    add_row("Calmar ratio", p0.calmar_ratio, f05.calmar_ratio, multi.calmar_ratio)
    add_row("Capital turnover", p0.capital_turnover, f05.capital_turnover, multi.capital_turnover)
    # Avg util rendered as % for readability
    add_row(
        "Avg capital util %",
        p0.avg_capital_util * 100,
        f05.avg_capital_util * 100,
        multi.avg_capital_util * 100,
        places=1,
    )

    # Sells row (int)
    delta_sells = multi.cumulative_sells - f05.cumulative_sells
    lines.append(
        row(
            "Cumulative sells",
            str(p0.cumulative_sells),
            str(f05.cumulative_sells),
            str(multi.cumulative_sells),
            ("+" if delta_sells >= 0 else "") + str(delta_sells),
        )
    )

    lines.append(sep)
    return "\n".join(lines)


def render_gate(multi: Summary) -> tuple[str, bool]:
    util_pct = multi.avg_capital_util * 100
    h1_pass = util_pct >= GATE_H1_AVG_UTIL_PCT
    h2_pass = multi.total_return_pct >= GATE_H2_TOTAL_RETURN_PCT
    h3_pass = multi.sharpe_ratio >= GATE_H3_SHARPE

    n_pass = sum([h1_pass, h2_pass, h3_pass])
    overall_pass = n_pass >= 2

    def verdict(p: bool) -> str:
        return "PASS" if p else "FAIL"

    sep = "=" * 61
    thin = "-" * 61
    lines = [
        sep,
        "Phase 0.7.1 게이트 판정 (ADR §2.2.5)",
        sep,
        f"H1 자본 활용률 >= 48.5%:   {verdict(h1_pass):<6}  ({util_pct:.1f}%)",
        f"H2 total return >= +25.96%: {verdict(h2_pass):<6}  (+{multi.total_return_pct:.4f}%)",
        f"H3 Sharpe >= 0.39:          {verdict(h3_pass):<6}  ({multi.sharpe_ratio:.4f})",
        thin,
        f"통과 기준 (>= 2 참):        {verdict(overall_pass):<6}  ({n_pass} / 3 참)",
        thin,
        "다음 단계 권고:",
    ]
    if overall_pass:
        lines.append("  -> PASS: Phase 1 진입 가능 (KIS API + 손절 ADR 라운드)")
    else:
        lines.append("  -> FAIL: 사용자 결정 라운드 #5 (Phase 0.7.2 / 옵션 검토)")
    lines.append(sep)
    return "\n".join(lines), overall_pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 0.7.1.h 3-way comparison + gate verdict "
            "(ADR 0003 §13.6.4 / §2.2.5)."
        )
    )
    parser.add_argument(
        "phase05_f_json",
        type=Path,
        help="Phase 0.5 F single-asset 'trading backtest --json' output.",
    )
    parser.add_argument(
        "phase071_multi_json",
        type=Path,
        help="Phase 0.7.1 multi-asset 'trading backtest --json' output.",
    )
    args = parser.parse_args(argv)

    f05_payload = json.loads(args.phase05_f_json.read_text(encoding="utf-8"))
    multi_payload = json.loads(args.phase071_multi_json.read_text(encoding="utf-8"))

    p0 = phase0_summary()
    f05 = summarize_single("Phase 0.5 F", f05_payload)
    multi = summarize_multi("Phase 0.7.1", multi_payload, n_assets=2)

    # --- Invariant check (ADR §13.6.4 G) ------------------------------------
    print()
    print("=" * 61)
    print("Phase 0.5 F invariant 검증 (ADR §13.6.4 G)")
    print("=" * 61)
    failures = check_invariant(f05)
    if failures:
        print("FAIL — 0.7.1 refactor regression 의심:")
        for msg in failures:
            print(msg)
        print("=" * 61)
        print("0.7.1.h 중단. 디버깅 라운드 진입 필요.")
        return 2
    print("PASS — 8 지표 모두 박제값 +-1e-4 이내 일치.")
    print(f"  Total return %  : actual={f05.total_return_pct:.4f}  expected={INVARIANT_TOTAL_RETURN_PCT}")
    print(f"  CAGR %          : actual={f05.cagr_pct:.4f}  expected={INVARIANT_CAGR_PCT}")
    print(f"  Max drawdown %  : actual={f05.max_drawdown_pct:.4f}  expected={INVARIANT_MAX_DRAWDOWN_PCT}")
    print(f"  Sharpe ratio    : actual={f05.sharpe_ratio:.4f}  expected={INVARIANT_SHARPE}")
    print(f"  Calmar ratio    : actual={f05.calmar_ratio:.4f}  expected={INVARIANT_CALMAR}")
    print(f"  Capital turnover: actual={f05.capital_turnover:.4f}  expected={INVARIANT_CAPITAL_TURNOVER}")
    print(f"  Cumul. sells    : actual={f05.cumulative_sells}  expected={INVARIANT_CUMULATIVE_SELLS}")
    print(f"  Avg capital util: actual={f05.avg_capital_util:.4f}  expected={INVARIANT_AVG_CAPITAL_UTIL}")
    print("=" * 61)

    # --- 3-way comparison table ---------------------------------------------
    print()
    print(render_comparison(p0, f05, multi))

    # --- Gate verdict -------------------------------------------------------
    print()
    gate_text, overall_pass = render_gate(multi)
    print(gate_text)

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
