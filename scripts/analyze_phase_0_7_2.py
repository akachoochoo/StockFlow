"""Phase 0.7.2 3-policy comparison + gate verdict — ADR 0003 §16.2 / §16.14.

Compares EQUAL / INV_VOL / VOL backtest results against Phase 0.7.1 baseline
(invariant target for EQUAL) and Phase 0.7.2 게이트 (§16.2):

  H1 avg_capital_util  >= 15.6 %
  H2 total_return_pct  >= +5.25 %
  H3 sharpe_ratio      >= 0.33
  Pass >= 2 of 3 -> policy 게이트 통과

Capital-utilization definition (ADR §2.2.6 그대로 — 옵션 A 채택, 2026-05-05):
  per_asset_budget = initial_capital / N_assets
  per_asset_committed_t = quantity * avg_price (cost-basis from valuation)
  per_asset_util_t = committed_t / per_asset_budget
  portfolio_avg_util = mean over assets of time-mean(per_asset_util_t)

INV_VOL 시 채권 commit > 50M / 분모 50M -> util > 100% 가능. ADR §16.2
baseline 일관 보존 (정책-aware 산정 거부 — 사용자 결정 2026-05-05).

Usage::

    uv run python scripts/analyze_phase_0_7_2.py \\
        /tmp/phase072/equal.json \\
        /tmp/phase072/inv_vol.json \\
        /tmp/phase072/vol.json

Exit code:
    0 — invariant pass + 적어도 1 정책 게이트 통과
    1 — invariant fail (EQUAL != Phase 0.7.1 baseline)
    2 — invariant pass but 0 policies passed gate
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Phase 0.7.1 baseline — phase-0.7.1-results.md 박제값 (§14.3 인용)
# 100,000,000 KRW initial capital, 2 자산 (069500 + 214980), 5-year 백테스트.
# ---------------------------------------------------------------------------
PHASE_0_7_1_TOTAL_RETURN_PCT: Decimal = Decimal("5.2514")
PHASE_0_7_1_CAGR_PCT: Decimal = Decimal("1.0541")
PHASE_0_7_1_MAX_DRAWDOWN_PCT: Decimal = Decimal("-7.9487")
PHASE_0_7_1_SHARPE: Decimal = Decimal("0.3258")
PHASE_0_7_1_CALMAR: Decimal = Decimal("0.1326")
PHASE_0_7_1_CAPITAL_TURNOVER: Decimal = Decimal("0.1633")
PHASE_0_7_1_CUMULATIVE_SELLS: int = 13
PHASE_0_7_1_AVG_CAPITAL_UTIL: Decimal = Decimal("0.156")

# Gate thresholds — ADR §16.2 (Phase 0.7.1 baseline).
GATE_H1_AVG_UTIL_PCT: Decimal = Decimal("15.6")
GATE_H2_TOTAL_RETURN_PCT: Decimal = Decimal("5.25")
GATE_H3_SHARPE: Decimal = Decimal("0.33")
GATE_PASS_COUNT: int = 2  # >= 2 of 3

INVARIANT_TOLERANCE: Decimal = Decimal("1e-4")


@dataclass
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
    avg_capital_util: Decimal  # fraction (0-1+)


# ---------------------------------------------------------------------------
# Helpers (차용 from analyze_phase_0_7_1.py)
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


def _avg_util_multi(
    snapshots: list[dict[str, Any]],
    initial: Decimal,
    n_assets: int,
) -> Decimal:
    """Multi-asset avg capital utilization per ADR §2.2.6 (옵션 A 그대로).

    per_asset_budget = initial / n_assets (균등 분모)
    per_asset_committed_t = sum cost_basis (quantity x avg_price)
    per_asset_util_t = committed / budget
    portfolio_avg_util = mean over assets of time-mean
    """
    if not snapshots or initial == 0 or n_assets == 0:
        return Decimal(0)
    per_asset_budget = initial / Decimal(n_assets)

    asset_util: dict[str, list[Decimal]] = {}

    for s in snapshots:
        seen: set[str] = set()
        for v in s.get("valuations", []):
            code = v["asset"]["code"]
            cost_basis = Decimal(v["quantity"]) * Decimal(v["avg_price"])
            util_t = cost_basis / per_asset_budget
            if code not in asset_util:
                idx = snapshots.index(s)
                asset_util[code] = [Decimal(0)] * idx
            asset_util[code].append(util_t)
            seen.add(code)

        for code in asset_util:
            if code not in seen:
                asset_util[code].append(Decimal(0))

    n_snaps = len(snapshots)
    per_asset_avgs: list[Decimal] = []
    for series in asset_util.values():
        while len(series) < n_snaps:
            series.append(Decimal(0))
        per_asset_avgs.append(sum(series) / Decimal(n_snaps))

    if not per_asset_avgs:
        return Decimal(0)
    return sum(per_asset_avgs) / Decimal(len(per_asset_avgs))


def summarize(label: str, payload: dict[str, Any], n_assets: int) -> Summary:
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


def phase_0_7_1_baseline() -> Summary:
    return Summary(
        label="Phase 0.7.1 baseline",
        n_trading_days=1231,
        total_return_pct=PHASE_0_7_1_TOTAL_RETURN_PCT,
        cagr_pct=PHASE_0_7_1_CAGR_PCT,
        max_drawdown_pct=PHASE_0_7_1_MAX_DRAWDOWN_PCT,
        sharpe_ratio=PHASE_0_7_1_SHARPE,
        calmar_ratio=PHASE_0_7_1_CALMAR,
        capital_turnover=PHASE_0_7_1_CAPITAL_TURNOVER,
        cumulative_sells=PHASE_0_7_1_CUMULATIVE_SELLS,
        avg_capital_util=PHASE_0_7_1_AVG_CAPITAL_UTIL,
    )


# ---------------------------------------------------------------------------
# Invariant check (EQUAL → Phase 0.7.1 baseline)
# ---------------------------------------------------------------------------
def check_invariant(equal: Summary) -> list[str]:
    """Verify EQUAL policy 결과가 Phase 0.7.1 baseline 일치 (오차 < 1e-4).

    Returns list of failure messages — empty list = PASS.
    """
    failures: list[str] = []

    def chk(name: str, got: Decimal, expected: Decimal) -> None:
        diff = abs(got - expected)
        if diff > INVARIANT_TOLERANCE:
            failures.append(
                f"{name}: got {got}, expected {expected} (diff {diff})"
            )

    chk("Total return %", equal.total_return_pct, PHASE_0_7_1_TOTAL_RETURN_PCT)
    chk("CAGR %", equal.cagr_pct, PHASE_0_7_1_CAGR_PCT)
    chk("Max drawdown %", equal.max_drawdown_pct, PHASE_0_7_1_MAX_DRAWDOWN_PCT)
    chk("Sharpe ratio", equal.sharpe_ratio, PHASE_0_7_1_SHARPE)
    chk("Calmar ratio", equal.calmar_ratio, PHASE_0_7_1_CALMAR)
    return failures


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------
@dataclass
class GateVerdict:
    label: str
    h1_pass: bool
    h1_value: Decimal
    h2_pass: bool
    h2_value: Decimal
    h3_pass: bool
    h3_value: Decimal
    n_pass: int
    overall_pass: bool


def evaluate_gate(s: Summary) -> GateVerdict:
    h1_value = s.avg_capital_util * Decimal(100)  # to %
    h1_pass = h1_value >= GATE_H1_AVG_UTIL_PCT
    h2_pass = s.total_return_pct >= GATE_H2_TOTAL_RETURN_PCT
    h3_pass = s.sharpe_ratio >= GATE_H3_SHARPE
    n_pass = sum([h1_pass, h2_pass, h3_pass])
    return GateVerdict(
        label=s.label,
        h1_pass=h1_pass, h1_value=h1_value,
        h2_pass=h2_pass, h2_value=s.total_return_pct,
        h3_pass=h3_pass, h3_value=s.sharpe_ratio,
        n_pass=n_pass,
        overall_pass=(n_pass >= GATE_PASS_COUNT),
    )


# ---------------------------------------------------------------------------
# Output (table)
# ---------------------------------------------------------------------------
def _fmt(v: Decimal, places: int = 4) -> str:
    return f"{v:.{places}f}"


def print_4way_table(
    baseline: Summary, equal: Summary, inv_vol: Summary, vol: Summary,
) -> None:
    rows = [
        ("Metric", "Phase 0.7.1", "EQUAL", "INV_VOL", "VOL"),
        ("Total return %",
         _fmt(baseline.total_return_pct),
         _fmt(equal.total_return_pct),
         _fmt(inv_vol.total_return_pct),
         _fmt(vol.total_return_pct)),
        ("CAGR %",
         _fmt(baseline.cagr_pct),
         _fmt(equal.cagr_pct),
         _fmt(inv_vol.cagr_pct),
         _fmt(vol.cagr_pct)),
        ("Max drawdown %",
         _fmt(baseline.max_drawdown_pct),
         _fmt(equal.max_drawdown_pct),
         _fmt(inv_vol.max_drawdown_pct),
         _fmt(vol.max_drawdown_pct)),
        ("Sharpe ratio",
         _fmt(baseline.sharpe_ratio),
         _fmt(equal.sharpe_ratio),
         _fmt(inv_vol.sharpe_ratio),
         _fmt(vol.sharpe_ratio)),
        ("Calmar ratio",
         _fmt(baseline.calmar_ratio),
         _fmt(equal.calmar_ratio),
         _fmt(inv_vol.calmar_ratio),
         _fmt(vol.calmar_ratio)),
        ("Capital turnover",
         _fmt(baseline.capital_turnover),
         _fmt(equal.capital_turnover),
         _fmt(inv_vol.capital_turnover),
         _fmt(vol.capital_turnover)),
        ("Avg capital util %",
         _fmt(baseline.avg_capital_util * 100, 2),
         _fmt(equal.avg_capital_util * 100, 2),
         _fmt(inv_vol.avg_capital_util * 100, 2),
         _fmt(vol.avg_capital_util * 100, 2)),
        ("Cumulative sells",
         str(baseline.cumulative_sells),
         str(equal.cumulative_sells),
         str(inv_vol.cumulative_sells),
         str(vol.cumulative_sells)),
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    sep_width = sum(widths) + 2 * (len(widths) - 1)
    print("=" * sep_width)
    print("Phase 0.7.2 4-way comparison (ADR §16.14)")
    print("=" * sep_width)
    for i, r in enumerate(rows):
        line = "  ".join(c.rjust(widths[j]) if j > 0 else c.ljust(widths[j])
                          for j, c in enumerate(r))
        print(line)
        if i == 0:
            print("-" * sep_width)


def print_gate_table(verdicts: list[GateVerdict]) -> None:
    print()
    print("=" * 80)
    print(
        f"Gate evaluation (ADR §16.2: H1 >= {GATE_H1_AVG_UTIL_PCT}% / "
        f"H2 >= {GATE_H2_TOTAL_RETURN_PCT}% / H3 >= {GATE_H3_SHARPE}, "
        f">= {GATE_PASS_COUNT} of 3)"
    )
    print("=" * 80)
    print(f"{'Policy':<10}  {'H1 util':>10}  {'H2 ret':>10}  {'H3 Sharpe':>10}  {'Pass':>5}  Verdict")
    print("-" * 80)
    for v in verdicts:
        h1_str = f"{_fmt(v.h1_value, 2)}{'✓' if v.h1_pass else '✗'}"
        h2_str = f"{_fmt(v.h2_value, 2)}{'✓' if v.h2_pass else '✗'}"
        h3_str = f"{_fmt(v.h3_value, 4)}{'✓' if v.h3_pass else '✗'}"
        verdict = "PASS" if v.overall_pass else "FAIL"
        print(
            f"{v.label:<10}  {h1_str:>10}  {h2_str:>10}  {h3_str:>10}  "
            f"{v.n_pass}/3  {verdict}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0] if __doc__ else "",
    )
    parser.add_argument("equal_json", type=Path, help="EQUAL policy 결과 JSON.")
    parser.add_argument("inv_vol_json", type=Path, help="INV_VOL 결과 JSON.")
    parser.add_argument("vol_json", type=Path, help="VOL 결과 JSON.")
    parser.add_argument(
        "--n-assets", type=int, default=2,
        help="자산 수 (default 2 — 069500 + 214980).",
    )
    args = parser.parse_args()

    equal = summarize(
        "EQUAL", json.loads(args.equal_json.read_text()), args.n_assets,
    )
    inv_vol = summarize(
        "INV_VOL", json.loads(args.inv_vol_json.read_text()), args.n_assets,
    )
    vol = summarize(
        "VOL", json.loads(args.vol_json.read_text()), args.n_assets,
    )
    baseline = phase_0_7_1_baseline()

    # 1. Invariant check (EQUAL → Phase 0.7.1 baseline)
    print("=" * 80)
    print(
        "Phase 0.7.1 invariant check (EQUAL = Phase 0.7.1 baseline, "
        f"tolerance < {INVARIANT_TOLERANCE})"
    )
    print("=" * 80)
    failures = check_invariant(equal)
    if failures:
        print("INVARIANT FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("INVARIANT PASS — 5 지표 1e-4 오차 이내 일치.")

    # 2. 4-way comparison
    print()
    print_4way_table(baseline, equal, inv_vol, vol)

    # 3. Gate evaluation
    verdicts = [evaluate_gate(s) for s in (equal, inv_vol, vol)]
    print_gate_table(verdicts)

    # 4. Verdict
    print()
    print("=" * 80)
    n_passing_policies = sum(1 for v in verdicts if v.overall_pass)
    if n_passing_policies == 0:
        print(
            f"FINAL VERDICT: NO policy 게이트 통과 (>= {GATE_PASS_COUNT} 참 "
            "필요). 라운드 #7 진입."
        )
        return 2
    passing = [v.label for v in verdicts if v.overall_pass]
    print(
        f"FINAL VERDICT: {n_passing_policies} policy 게이트 통과: "
        f"{passing}. 0.7.2.e 결과 박제 + 0.7.2.f 회고."
    )
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
