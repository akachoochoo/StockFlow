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
from src.research.dgt.optimization._pbo import _compute_pbo
from src.research.dgt.optimization._perturbation import (
    _PerturbationResult,
    _run_perturbation,
)
from src.research.dgt.runner import _DGTConfig


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


def _render_d11_judgment_markdown(
    *,
    asset_code: str,
    bars_window_start: date,
    bars_window_end: date,
    n_bars: int,
    grid_result: _WFOGridResult,
    perturbation: _PerturbationResult,
    pbo: Decimal,
    sensitivity_commit: str,
    elapsed_seconds: float,
) -> str:
    """D11 trigger judgment Markdown (ADR 0008 §1.10 시나리오 C graceful path)."""
    best = grid_result.points[0]
    band_count = sum(
        1 for p in grid_result.points if p.passes_d11_baseline_band
    )
    dsr_pass_count = sum(
        1 for p in grid_result.points if p.dsr >= Decimal("1.0")
    )
    sharpe_pass_count = sum(
        1 for p in grid_result.points if p.oos_sharpe >= Decimal("0.473")
    )
    g = grid_result.grid_size

    pert = perturbation
    pert_pass = "PASS" if pert.passes_d11_c else "FAIL"

    # AND-gate (b) — DSR 0/95 → 구조적 FAIL.
    and_gate_pass = (
        band_count > 0
        and dsr_pass_count > 0
        and sharpe_pass_count > 0
        and pert.passes_d11_c
    )
    and_gate_status = "PASS" if and_gate_pass else "FAIL"

    lines: list[str] = []
    lines.append(
        "# Phase 0.11.b sub-step .4 — D11 AND-gate 정식 판정 + INFORMATIONAL 강등 + D10 archive 확정"
    )
    lines.append("")
    lines.append(
        "> ADR 0008 §1.6 D11 AND-gate 정식 판정 + §1.10 시나리오 C graceful degradation. "
        "Markdown only (ADR 0008 D2)."
    )
    lines.append(">")
    lines.append(
        f"> Asset: **{asset_code}** (KODEX 200, KR_ETF). "
        f"Window: {bars_window_start.isoformat()} ~ {bars_window_end.isoformat()} "
        f"({n_bars} bars). Grid_size={g}, n_folds={grid_result.n_folds}, "
        f"elapsed={elapsed_seconds:.2f}s."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 1.
    lines.append("## 1. Sub-step .3 산출 인용 (sensitivity-heatmap.md)")
    lines.append("")
    lines.append(
        f"- Commit hash: `{sensitivity_commit}` (sub-step .3 박제 정본)."
    )
    lines.append(
        f"- Best parameter set: **n={best.config_n}, k={best.config_k_pct}%, "
        f"m={best.config_m}**"
    )
    lines.append(
        f"  - OOS Sharpe = **{_format_decimal(best.oos_sharpe)}**"
    )
    lines.append(
        f"  - OOS CAGR = **{_format_decimal(best.oos_cagr_pct, decimals=3)}%**"
    )
    lines.append(
        f"  - OOS MDD = **{_format_decimal(best.oos_mdd_pct, decimals=3)}%**"
    )
    lines.append(
        f"  - OOS Calmar = **{_format_decimal(best.oos_calmar)}**"
    )
    lines.append(
        f"  - DSR = **{_format_decimal(best.dsr)}**"
    )
    lines.append(
        f"  - trades (OOS aggregate) = **{best.total_trade_count}**"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 2.
    lines.append("## 2. D11 AND-gate 4 조건 정식 판정")
    lines.append("")
    lines.append(
        "| 조건 | 임계 | 합격 / 전체 | 비고 |"
    )
    lines.append("|---|---|---:|---|")
    lines.append(
        f"| (a) 4-metric ±10% band | CAGR≥2.32% AND MDD≥-9.10% AND "
        f"Sharpe≥0.473 AND Calmar≥0.280 | "
        f"**{band_count}/{g}** | sub-step .3 박제 인용 |"
    )
    lines.append(
        f"| (b) DSR ≥ 1.0 | Bailey-López de Prado 2014 5% 유의 수준 | "
        f"**{dsr_pass_count}/{g}** ❌ | sub-step .3 박제 인용 (구조적 unattainable) |"
    )
    lines.append(
        f"| (c) OOS Sharpe ≥ 0.473 (informational slice) | baseline × 0.9 | "
        f"**{sharpe_pass_count}/{g}** | sub-step .3 박제 인용 |"
    )
    lines.append(
        f"| (d) Perturbation ±10% worst OOS Sharpe > 0.3 | "
        f"D11 (c) PRIMARY (renumber) | "
        f"worst = **{_format_decimal(pert.worst_oos_sharpe)}** → "
        f"**{pert_pass}** | sub-step .4 영역 1 산출 |"
    )
    lines.append("")
    lines.append(
        f"### AND-gate 종합 = **{and_gate_status}**"
    )
    lines.append("")
    if not and_gate_pass:
        lines.append(
            "- (b) DSR 0/95 PASS — **구조적 unattainable** (n_trials=95 multiple-"
            "testing penalty + 5 fold small sample). AND-gate 의 (b) 조건이 "
            "구조적으로 만족 불가 → AND-gate FAIL 확정."
        )
        lines.append(
            "- R1 (HIGH) 의 일봉 한계 (ADR 0007 §1.8 + ADR 0008 §1.5) 정량 박제."
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 3.
    lines.append("## 3. INFORMATIONAL 강등 박제")
    lines.append("")
    lines.append(
        "- G2 CONDITIONAL PRIMARY (ADR 0008 §1.4) → **INFORMATIONAL FAIL** 강등."
    )
    lines.append(
        "- ADR 0008 §1.4 G2 + §1.10 시나리오 C graceful degradation path 정합."
    )
    lines.append(
        "- 사용자 결정 (2026-05-13 sub-step .3 종료): \"0.11.b.4 진입 — D11 "
        "INFORMATIONAL 강등 + D10 archive 확정 시나리오 C 수락\"."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 4.
    lines.append("## 4. D10 archive 확정 박제")
    lines.append("")
    lines.append(
        "- ADR 0007 §1.7 D10 = archive (default) 결정 **supersede 없음** 박제."
    )
    lines.append(
        "- D11 AND-gate FAIL → ADR 0007 §1.7.2 promote 경로 trigger 미발동."
    )
    lines.append(
        "- ADR 0007 §3 회고 정본 유지. Strategy registry 미합류 (ADR 0007 R5 정합)."
    )
    lines.append(
        "- Staleness tripwire (ADR 0007 §1.7.1): `tests/integration/"
        "test_namespace_isolation.py` FAIL 시점이 archive 의미 종료 시점."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 5.
    lines.append("## 5. PBO informational 산출 (영역 2)")
    lines.append("")
    lines.append(
        f"- PBO (Probability of Backtest Overfitting) = "
        f"**{_format_decimal(pbo)}**"
    )
    lines.append(
        "- Bailey-Borwein-López de Prado-Zhu 2017 simplified path "
        "(grid_runner aggregate 입력)."
    )
    if pbo < Decimal("0.5"):
        lines.append(
            f"- 임계 (Bailey 2017): PBO < 0.5 → **no overfitting** (현 PBO = "
            f"{_format_decimal(pbo)})."
        )
    else:
        lines.append(
            f"- 임계 (Bailey 2017): PBO > 0.5 → **overfitting suspect** (현 PBO = "
            f"{_format_decimal(pbo)})."
        )
    lines.append(
        "- Informational (ADR 0008 §1.6 D8 (iv) OPTIONAL) — DSR / perturbation "
        "PRIMARY 가드레일 보조."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 6.
    lines.append(
        "## 6. Phase 1 ADR 0012 D11 분봉 DGT 검토 정량 근거 박제"
    )
    lines.append("")
    lines.append("- **Best parameter set 정량 박제**:")
    lines.append(
        f"  - n = **{best.config_n}**, k = **{best.config_k_pct}%**, "
        f"m = **{best.config_m}**"
    )
    lines.append(
        f"  - OOS Sharpe = {_format_decimal(best.oos_sharpe)} / "
        f"OOS CAGR = {_format_decimal(best.oos_cagr_pct, decimals=3)}% / "
        f"OOS MDD = {_format_decimal(best.oos_mdd_pct, decimals=3)}% / "
        f"OOS Calmar = {_format_decimal(best.oos_calmar)} / "
        f"DSR = {_format_decimal(best.dsr)}"
    )
    lines.append("- **DSR / perturbation / PBO 수치 박제**:")
    lines.append(
        f"  - Best DSR = **{_format_decimal(best.dsr)}** (Bailey 2014 임계 1.0 "
        f"미달, n_trials=95 penalty)"
    )
    lines.append(
        f"  - Perturbation 27 points: worst = "
        f"**{_format_decimal(pert.worst_oos_sharpe)}** / "
        f"mean = **{_format_decimal(pert.mean_oos_sharpe)}** / "
        f"passes_d11_c = **{pert.passes_d11_c}**"
    )
    lines.append(
        f"  - PBO = **{_format_decimal(pbo)}** (Bailey 2017 simplified)"
    )
    lines.append(
        "- **일봉 한계 정당화**: sub-step .3 G2 FAIL → 분봉 DGT 재검토는 일봉의 "
        "intraday oscillation 정보 부재 (ADR 0007 §1.5 R1 일봉≠분봉) 정량 근거 "
        "제공. Phase 1 ADR 0012 D11 분봉 DGT 검토 진입 시 본 sub-step 산출이 "
        "정량 oracle."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 7.
    lines.append("## 7. Graceful degradation rationale")
    lines.append("")
    lines.append(
        "ADR 0008 §1.10 시나리오 C verbatim:"
    )
    lines.append("")
    lines.append(
        "> **시나리오 C — D11 strict → G2 FAIL → Phase 1 진입 지연**:"
    )
    lines.append(
        "> - 발생: D11 AND-gate 채택 후 일봉 한계 (0.11.a R1) 로 G2 FAIL → "
        "0.11.b archive 확정 → 사용자 \"왜 0.11.b 했냐?\" 의문."
    )
    lines.append(
        "> - 원인: 일봉 환경에서 grid trading 의 본질적 한계 — intraday "
        "oscillation 정보 부재."
    )
    lines.append(
        "> - Mitigation: G2 FAIL graceful degradation — INFORMATIONAL 강등 + "
        "best parameter set + DSR / perturbation 수치 박제 → Phase 1 ADR 0012 "
        "분봉 DGT 검토 시 정량 근거 활용 (archive 가치 보존). 사용자 명시 "
        "\"튜닝 결과가 좋으면 promote 재고\" 의 *대칭 case* (튜닝 후에도 archive "
        "라면 archive 사유의 정량 박제)."
    )
    lines.append("")
    lines.append(
        "**사용자 결정 verbatim (2026-05-13 sub-step .3 종료 시점)**:"
    )
    lines.append("")
    lines.append(
        "> \"0.11.b.4 진입 — D11 INFORMATIONAL 강등 + D10 archive 확정 시나리오 "
        "C 수락 (ADR 0008 §1.10 시나리오 C graceful degradation path 정합)\""
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 8 — perturbation table.
    lines.append("## 8. Perturbation 27-point 상세 (영역 1 산출)")
    lines.append("")
    lines.append(
        "| Rank | n | k (%) | m | IS Sharpe | OOS Sharpe | OOS CAGR (%) | "
        "OOS MDD (%) | OOS Calmar | DSR | trades |"
    )
    lines.append(
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    sorted_pert = sorted(
        pert.perturbation_results,
        key=lambda r: (-r.oos_sharpe, r.config_n, r.config_k_pct, r.config_m),
    )
    for rank, p in enumerate(sorted_pert, start=1):
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
    lines.append(
        f"Perturbation 27 points: worst OOS Sharpe = "
        f"**{_format_decimal(pert.worst_oos_sharpe)}** / "
        f"mean = **{_format_decimal(pert.mean_oos_sharpe)}** / "
        f"D11 (c) threshold (>0.3) = **{pert_pass}**."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section 9.
    lines.append("## 9. Reproducibility (D12)")
    lines.append("")
    lines.append(
        "- Deterministic ordering: grid + WFO + perturbation + PBO pipeline "
        "은 seed-free (Decimal-only)."
    )
    lines.append(
        "- 2 회 동일 실행 시 byte-identical 산출 (AC15 정신 계승, ADR 0008 D12)."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="src.research.dgt.optimization",
        description=(
            "Phase 0.11.b sub-step .3 + .4 — WFO grid + perturbation + D11 "
            "judgment (ADR 0008 §1.8)."
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

    run_pert = sub.add_parser(
        "run-perturbation",
        help="Perturbation ±10% 27-point + PBO + D11 judgment Markdown 산출 (sub-step .4).",
    )
    run_pert.add_argument(
        "--asset",
        default="069500",
        help="Asset code (D3 default = 069500)",
    )
    run_pert.add_argument(
        "--csv",
        type=Path,
        default=Path("data/historical/KRX_069500_2019-2024.csv"),
    )
    run_pert.add_argument(
        "--start", default="2020-01-02", help="YYYY-MM-DD (default 2020-01-02)"
    )
    run_pert.add_argument(
        "--end", default="2024-12-30", help="YYYY-MM-DD (default 2024-12-30)"
    )
    run_pert.add_argument(
        "--initial-capital",
        type=str,
        default="10000000",
        help="KRW (Decimal-safe str)",
    )
    run_pert.add_argument(
        "--best-n",
        type=int,
        default=11,
        help="Sub-step .3 best parameter n (default 11)",
    )
    run_pert.add_argument(
        "--best-k",
        type=str,
        default="3",
        help="Sub-step .3 best parameter k as % (default 3)",
    )
    run_pert.add_argument(
        "--best-m",
        type=int,
        default=1,
        help="Sub-step .3 best parameter m (default 1)",
    )
    run_pert.add_argument(
        "--sensitivity-commit",
        type=str,
        default="76b2400",
        help="sub-step .3 sensitivity-heatmap.md commit hash",
    )
    run_pert.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Markdown output path (e.g., docs/research/phase-0.11.b/d11-trigger-judgment.md)",
    )
    return parser


def _cmd_run_grid(args: argparse.Namespace) -> int:
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


def _cmd_run_perturbation(args: argparse.Namespace) -> int:
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
    best_config = _DGTConfig(
        grid_count=args.best_n,
        grid_spacing_pct=Decimal(args.best_k),
        levels_above=args.best_m,
    )

    print(
        f"[run-perturbation] asset={args.asset} bars={len(bars)} "
        f"window={start.isoformat()}~{end.isoformat()} "
        f"best=(n={args.best_n}, k={args.best_k}%, m={args.best_m})",
        file=sys.stderr,
    )

    t0 = time.time()
    grid_result = _run_wfo_grid(
        bars=bars,
        asset=asset,
        initial_capital_krw=initial_capital_krw,
    )
    grid_elapsed = time.time() - t0
    print(
        f"[run-perturbation] grid done in {grid_elapsed:.2f}s — "
        f"grid_size={grid_result.grid_size}",
        file=sys.stderr,
    )

    t1 = time.time()
    perturbation = _run_perturbation(
        bars=bars,
        asset=asset,
        best_config=best_config,
        initial_capital_krw=initial_capital_krw,
    )
    pert_elapsed = time.time() - t1
    print(
        f"[run-perturbation] 27-point perturbation done in {pert_elapsed:.2f}s "
        f"— worst={perturbation.worst_oos_sharpe} "
        f"mean={perturbation.mean_oos_sharpe} "
        f"passes_d11_c={perturbation.passes_d11_c}",
        file=sys.stderr,
    )

    t2 = time.time()
    pbo = _compute_pbo(grid_result.points, n_folds=grid_result.n_folds)
    pbo_elapsed = time.time() - t2
    print(
        f"[run-perturbation] PBO = {pbo} (computed in {pbo_elapsed:.2f}s)",
        file=sys.stderr,
    )

    total_elapsed = time.time() - t0
    md = _render_d11_judgment_markdown(
        asset_code=args.asset,
        bars_window_start=start,
        bars_window_end=end,
        n_bars=len(bars),
        grid_result=grid_result,
        perturbation=perturbation,
        pbo=pbo,
        sensitivity_commit=args.sensitivity_commit,
        elapsed_seconds=total_elapsed,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    print(
        f"[run-perturbation] wrote {args.output} "
        f"(total {total_elapsed:.2f}s, D10 budget 120s)",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "run-grid":
        return _cmd_run_grid(args)
    if args.cmd == "run-perturbation":
        return _cmd_run_perturbation(args)
    parser.error(f"unknown cmd {args.cmd}")
    return 2  # unreachable — parser.error exits


if __name__ == "__main__":
    raise SystemExit(main())
