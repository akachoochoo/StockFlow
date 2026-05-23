"""Phase 1.1 Stage 1 작업 1.1 — 매도 임계 비교 backtest.

ADR 0012 (Phase 1 가칭) 진입 전 정량 근거 박제. profit_target_pct ∈
{10, 15, 20} 3 run 을 동일 윈도우 / 자본 / 데이터 / 정책 (0.7.3 baseline)
으로 실행, 최종가치 + 4 지표 (CAGR / MDD / Sharpe / Calmar) + 총 매도
횟수를 비교 산출.

규칙 (CLAUDE.md §1.1 / §2 / §13.3):
- production ring (src/) 변경 zero — 본 스크립트는 ``BacktestRunner`` 를
  그대로 사용 (옵션 C 정신, scripts/run_phase_0_7_2_backtest.py 본뜸).
- 모든 가격/수량/금액 Decimal. 결정론 (MockBroker / MockMarketData /
  NullSignal / InMemoryUnitOfWork — BacktestRunner 가 fresh adapter 와이어).
- 윈도우 = 가용 전 구간 교집합 (2019-01-02 ~ 2024-12-30) 고정.
  EQUAL allocation 은 lookback 불필요하므로 full data range 를 그대로 backtest
  구간으로 사용 (canonical 0.7.3 reproduce 는 start=2020-01-02 — 본 비교는
  더 긴 윈도우, profit_target 만 다른 동일 조건 비교라 절대값 ≠ 0.7.3 회고).

profit_target 외 모든 파라미터 = 0.7.3 baseline yaml 고정
(drop_threshold_pct=5 / max_split_count=7 / per_split_amount=5,000,000 /
max_split_per_day=1 / reentry=hybrid cooldown=60 / EQUAL).

Usage::

    uv run python scripts/run_phase_1_1_a_sell_threshold.py \\
        --config config/strategies-0.7.3.yaml \\
        --csv 069500=data/historical/KRX_069500_2019-2024.csv \\
        --csv 132030=data/historical/KRX_132030_2019-2024.csv \\
        --start 2019-01-02 --end 2024-12-30 --capital 100000000 \\
        --out-dir docs/research/phase-1.1.a
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.application.backtest_runner import BacktestResult, BacktestRunner
from src.cli.composition import asset_from_code
from src.domain.models import OHLCV, Asset, Currency, Money
from src.domain.strategies.profit_target import SellStrategyConfig
from src.infrastructure.yaml_strategy_config_loader import (
    load_strategy_config,
)

# Phase 1.1 작업 1.1 — 비교 대상 매도 임계 (profit_target_pct, percent).
SELL_THRESHOLDS_PCT: tuple[Decimal, ...] = (
    Decimal("10"),
    Decimal("15"),
    Decimal("20"),
)


def _parse_csv_arg(values: list[str]) -> dict[str, Path]:
    """Parse 'CODE=PATH' format; return code-keyed dict."""
    out: dict[str, Path] = {}
    for v in values:
        code, _, path_str = v.partition("=")
        if not code or not path_str:
            raise SystemExit(
                f"Invalid --csv format: {v!r}. Expected CODE=PATH."
            )
        out[code] = Path(path_str)
    return out


def _load_csv_bars(asset: Asset, path: Path) -> list[OHLCV]:
    """Read CSV and produce OHLCV list. Sorted by date asc.

    scripts/run_phase_0_7_2_backtest.py:_load_csv_bars 를 그대로 본뜸.
    """
    rows: list[OHLCV] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(
                OHLCV(
                    asset=asset,
                    trade_date=date.fromisoformat(row["date"]),
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row["volume"]),
                )
            )
    return sorted(rows, key=lambda b: b.trade_date)


def _count_sells(result: BacktestResult) -> int:
    """Total filled SELL actions across all decisions."""
    return sum(len(d.sell_actions) for d in result.decisions)


def _run_one(
    *,
    profit_target_pct: Decimal,
    assets_list: list[Asset],
    first_bundle_buy_config: object,
    reentry_strategy_name: str,
    reentry_parameters: dict[str, object],
    total_capital: Decimal,
    ohlcv_by_asset: dict[Asset, list[OHLCV]],
    start: date,
    end: date,
) -> BacktestResult:
    """One BacktestRunner.run() with a given profit_target_pct.

    profit_target 외 모든 파라미터 = 0.7.3 baseline 고정.
    """
    sell_config = SellStrategyConfig(
        profit_target_pct=profit_target_pct,
        max_sells_per_day=7,
    )
    runner = BacktestRunner(
        assets=assets_list,
        strategy_config=first_bundle_buy_config,  # type: ignore[arg-type]
        sell_strategy_config=sell_config,
        reentry_strategy_name=reentry_strategy_name,
        reentry_parameters=reentry_parameters,  # type: ignore[arg-type]
        initial_capital=Money(amount=total_capital, currency=Currency.KRW),
        ohlcv_by_asset=ohlcv_by_asset,
    )
    return runner.run(start, end)


def _result_row(result: BacktestResult, threshold: Decimal) -> dict[str, object]:
    """JSON-safe summary row for one run (Decimal → str)."""
    return {
        "profit_target_pct": str(threshold),
        "final_value": str(result.final_value.amount),
        "currency": result.final_value.currency.value,
        "total_return_pct": str(result.total_return_pct),
        "cagr_pct": str(result.cagr_pct),
        "max_drawdown_pct": str(result.max_drawdown_pct),
        "sharpe_ratio": str(result.sharpe_ratio),
        "calmar_ratio": str(result.calmar_ratio),
        "total_sells": _count_sells(result),
        "n_trading_days": result.n_trading_days,
    }


def _format_md(
    rows: list[dict[str, object]],
    *,
    start: date,
    end: date,
    total_capital: Decimal,
    config_path: Path,
    csv_paths: dict[str, Path],
) -> str:
    """Human-readable comparison markdown (3-row table)."""
    lines: list[str] = []
    lines.append("# Phase 1.1 Stage 1 — 작업 1.1: 매도 임계 비교 결과")
    lines.append("")
    lines.append("> Phase 1 (ADR 0012 가칭) 진입 전 정량 근거 박제.")
    lines.append("> production ring (src/) 변경 zero — BacktestRunner 직접 사용.")
    lines.append("> **권고: pending 사용자 확정** (default 미선정 — 수치만 박제).")
    lines.append("")
    lines.append("## 고정 조건")
    lines.append("")
    lines.append(f"- 윈도우: `{start}` ~ `{end}` (가용 전 구간 교집합, EQUAL lookback 불필요)")
    lines.append(f"- 초기자본: `{total_capital:,}` KRW (0.7.3 baseline 동일)")
    lines.append("- 자산: 069500 (KODEX 200) + 132030 (KODEX 골드선물(H)), EQUAL allocation")
    lines.append("- 고정 파라미터 (0.7.3 baseline): drop_threshold_pct=5 / "
                 "max_split_count=7 / per_split_amount=5,000,000 / "
                 "max_split_per_day=1 / reentry=hybrid cooldown=60")
    lines.append("- 변수: `profit_target_pct ∈ {10, 15, 20}` 만 변경")
    lines.append("")
    lines.append("## 비교 표")
    lines.append("")
    lines.append(
        "| profit_target_pct | 최종가치 (KRW) | Total Return % | CAGR % | "
        "MDD % | Sharpe | Calmar | 총 매도 |"
    )
    lines.append(
        "|---|---|---|---|---|---|---|---|"
    )
    for r in rows:
        fv = Decimal(str(r["final_value"]))
        lines.append(
            f"| {r['profit_target_pct']} "
            f"| {fv:,.0f} "
            f"| {Decimal(str(r['total_return_pct'])):.4f} "
            f"| {Decimal(str(r['cagr_pct'])):.4f} "
            f"| {Decimal(str(r['max_drawdown_pct'])):.4f} "
            f"| {Decimal(str(r['sharpe_ratio'])):.4f} "
            f"| {Decimal(str(r['calmar_ratio'])):.4f} "
            f"| {r['total_sells']} |"
        )
    lines.append("")
    lines.append("## 재현 커맨드")
    lines.append("")
    lines.append("```bash")
    lines.append("uv run python scripts/run_phase_1_1_a_sell_threshold.py \\")
    lines.append(f"    --config {config_path} \\")
    for code, p in csv_paths.items():
        lines.append(f"    --csv {code}={p} \\")
    lines.append(f"    --start {start} --end {end} --capital {total_capital} \\")
    lines.append("    --out-dir docs/research/phase-1.1.a")
    lines.append("```")
    lines.append("")
    lines.append("## 권고")
    lines.append("")
    lines.append("- **pending 사용자 확정**. default 미선정 — 위 수치를 근거로 "
                 "사용자가 채택. (ADR 0002 §12.4.1 +15/+20% 비교 보류 항목 처리.)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1.1 작업 1.1 — 매도 임계 비교 backtest.",
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--csv", action="append", required=True,
                        dest="csv_values", default=[],
                        help="OHLCV CSV per asset: CODE=PATH.")
    parser.add_argument("--start", required=True,
                        help="Backtest start date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True,
                        help="Backtest end date (YYYY-MM-DD).")
    parser.add_argument("--capital", required=True, type=int,
                        help="Initial capital (KRW int).")
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="Output directory for results.md + results.json.")
    args = parser.parse_args()

    # 1. yaml 로드 (정책 baseline). 매도 임계만 override 한다.
    bundles = load_strategy_config(args.config)
    enabled_bundles = {c: b for c, b in bundles.items() if b.enabled}
    if not enabled_bundles:
        raise SystemExit(f"No enabled assets in {args.config}.")

    csv_paths = _parse_csv_arg(args.csv_values)
    expected = set(enabled_bundles.keys())
    actual = set(csv_paths.keys())
    if actual != expected:
        raise SystemExit(
            f"--csv codes must match enabled yaml codes. "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )

    # 2. assets + OHLCV (윈도우 필터 — start <= trade_date <= end).
    assets_by_code = {c: asset_from_code(c) for c in enabled_bundles}
    bars_by_code = {
        c: _load_csv_bars(assets_by_code[c], csv_paths[c])
        for c in enabled_bundles
    }
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    total_capital = Decimal(args.capital)
    ohlcv_by_asset: dict[Asset, list[OHLCV]] = {
        assets_by_code[c]: [
            b for b in bars_by_code[c] if start <= b.trade_date <= end
        ]
        for c in enabled_bundles
    }
    assets_list = [assets_by_code[c] for c in enabled_bundles]
    first_bundle = next(iter(enabled_bundles.values()))

    # 3. 매도 임계별 run.
    rows: list[dict[str, object]] = []
    for threshold in SELL_THRESHOLDS_PCT:
        result = _run_one(
            profit_target_pct=threshold,
            assets_list=assets_list,
            first_bundle_buy_config=first_bundle.buy_config,
            reentry_strategy_name=first_bundle.reentry_strategy_name,
            reentry_parameters=first_bundle.reentry_parameters,
            total_capital=total_capital,
            ohlcv_by_asset=ohlcv_by_asset,
            start=start,
            end=end,
        )
        rows.append(_result_row(result, threshold))

    # 4. 산출 — results.json + results.md.
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_payload = {
        "phase": "1.1.a",
        "task": "매도 임계 비교 (profit_target_pct)",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "initial_capital": str(total_capital),
        "currency": "KRW",
        "assets": sorted(enabled_bundles.keys()),
        "allocation_policy": "EQUAL",
        "fixed_parameters": {
            "drop_threshold_pct": str(first_bundle.buy_config.drop_threshold_pct),
            "max_split_count": first_bundle.buy_config.max_split_count,
            "per_split_amount": str(first_bundle.buy_config.per_split_amount.amount),
            "max_split_per_day": first_bundle.buy_config.max_split_per_day,
            "reentry_strategy": first_bundle.reentry_strategy_name,
            "reentry_parameters": first_bundle.reentry_parameters,
        },
        "default_recommendation": "pending 사용자 확정",
        "runs": rows,
    }
    (out_dir / "results.json").write_text(
        json.dumps(json_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md = _format_md(
        rows,
        start=start,
        end=end,
        total_capital=total_capital,
        config_path=args.config,
        csv_paths=csv_paths,
    )
    (out_dir / "results.md").write_text(md + "\n", encoding="utf-8")

    # 5. stdout 비교 표 (사람이 읽는 + JSON 동시).
    print(md)
    print("\n--- JSON (results.json) ---")
    print(json.dumps(json_payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
