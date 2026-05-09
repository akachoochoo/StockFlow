"""Phase 0.9.2 백테스트 → drawdown episode 리포트 생성 (sub-step 0.10.e).

ADR 0006 §11 박제 — Step D end-to-end 통합. ``run_phase_0_8_1_backtest.py``
패턴 정합 (yaml + csv → BacktestRunner → BacktestResult) + reporting
pipeline (generate_episode_report) 결합.

Usage::

    uv run python scripts/generate_phase_0_9_2_report.py \\
        --output-dir reports/backtest/strategies-0.9.2_20200102_20241230 \\
        [--threshold -5]

기본값으로 strategies-0.9.2.yaml + 5 종 csv (data/historical/) +
2020-01-02~2024-12-30 + 100M 자본 사용. CLI 명령 통합 (``trading
report``) 은 Phase 0.10.x 또는 Phase 1+ 검토.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.adapters.reporting.renderer_registry import StrategyRendererRegistry
from src.application.backtest_runner import BacktestRunner
from src.application.reporting.report import generate_episode_report
from src.application.reporting.strategy_info import from_strategy_bundle
from src.cli.composition import asset_from_code
from src.domain.models import OHLCV, Asset, Currency, Money
from src.infrastructure.yaml_strategy_config_loader import load_strategy_config


def _load_csv_bars(asset: Asset, path: Path) -> list[OHLCV]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--config", default="config/strategies-0.9.2.yaml", type=Path,
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path,
        help="Reports 출력 디렉토리 (예: reports/backtest/...)",
    )
    parser.add_argument(
        "--threshold", default=Decimal("-5"),
        type=lambda s: Decimal(s),
        help="Drawdown 임계 (음수, default -5%)",
    )
    parser.add_argument(
        "--start", default="2020-01-02",
        help="Backtest start (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end", default="2024-12-30",
        help="Backtest end (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--capital", default=100_000_000, type=int,
        help="Initial capital (KRW int, default 100M)",
    )
    parser.add_argument(
        "--chart-symbol", default=None,
        help="Chart 그릴 symbol (default = first asset)",
    )
    parser.add_argument(
        "--csv-dir", default="data/historical", type=Path,
    )
    args = parser.parse_args()

    bundles = load_strategy_config(args.config)
    enabled = {code: b for code, b in bundles.items() if b.enabled}
    if not enabled:
        raise SystemExit(f"No enabled assets in {args.config}")

    # Resolve assets + load bars (filename pattern: KRX_<code>_<years>.csv)
    assets_by_code: dict[str, Asset] = {
        code: asset_from_code(code) for code in enabled
    }
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    bars_by_code: dict[str, list[OHLCV]] = {}
    for code in enabled:
        # Try CSV with start.year (e.g. KRX_<code>_2020-2024.csv) first;
        # fall back to start.year - 1 (lookback included, e.g. 2019-2024).
        candidates = [
            f"KRX_{code}_{start.year}-{end.year}.csv",
            f"KRX_{code}_{start.year - 1}-{end.year}.csv",
        ]
        csv_path = next(
            (args.csv_dir / name for name in candidates
             if (args.csv_dir / name).exists()),
            None,
        )
        if csv_path is None:
            raise SystemExit(
                f"CSV not found for {code} (tried {candidates}). "
                "Run scripts/download_kr_assets.py first."
            )
        bars_by_code[code] = _load_csv_bars(assets_by_code[code], csv_path)

    # Filter bars to [start, end] for backtest (price_drop strategy)
    bars_by_asset: dict[Asset, list[OHLCV]] = {
        assets_by_code[code]: [
            b for b in bars_by_code[code]
            if start <= b.trade_date <= end
        ]
        for code in enabled
    }
    assets_list = [assets_by_code[code] for code in enabled]
    first_bundle = next(iter(enabled.values()))

    # Run backtest
    runner = BacktestRunner(
        assets=assets_list,
        strategy_config=first_bundle.buy_config,
        sell_strategy_config=first_bundle.sell_config,
        reentry_strategy_name=first_bundle.reentry_strategy_name,
        reentry_parameters=first_bundle.reentry_parameters,
        initial_capital=Money(
            amount=Decimal(args.capital), currency=Currency.KRW,
        ),
        ohlcv_by_asset=bars_by_asset,
        buy_strategy_name=first_bundle.buy_strategy_name,
    )
    result = runner.run(start, end)
    print(
        f"백테스트 완료: H1 cumulative_buy / H2 return / H3 sharpe — "
        f"return={result.total_return_pct:.4f}%, "
        f"MDD={result.max_drawdown_pct:.4f}%, "
        f"sharpe={result.sharpe_ratio:.6f}, "
        f"snapshots={result.n_trading_days}"
    )

    # Generate report
    bars_by_symbol = {code: bars_by_code[code] for code in enabled}
    registry = StrategyRendererRegistry()
    # Phase 0.10.y §15.5 — surface strategy info in HTML output.
    strategy_info = from_strategy_bundle(
        first_bundle, args.config, asset_codes=enabled,
    )
    report = generate_episode_report(
        backtest_result=result,
        strategy_id=first_bundle.buy_strategy_name,
        output_dir=args.output_dir,
        bars_by_asset=bars_by_symbol,
        registry=registry,
        threshold_pct=args.threshold,
        scope="portfolio",
        chart_symbol=args.chart_symbol,
        title=f"Phase 0.9.2 — {args.start}~{args.end}",
        strategy_info=strategy_info,
    )

    print()
    print("=" * 70)
    print(f"리포트 생성 완료 — {len(report.episodes)} episodes")
    print("=" * 70)
    print(f"  Index:  {report.index_html_path}")
    for path in report.episode_html_paths:
        idx = report.episode_html_paths.index(path) + 1
        ep = report.episodes[idx - 1]
        print(
            f"  Ep {idx}: {path}  ({ep.peak_date} → "
            f"{ep.trough_date}, dd={ep.drawdown_pct:+.4f}%, "
            f"recovered={'yes' if ep.recovered else 'no'})"
        )
    print(f"  Trades: {report.trade_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
