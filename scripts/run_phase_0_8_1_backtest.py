"""Phase 0.8.1 백테스트 — SupportLevelStrategy 패러다임 검증.

ADR 0004 §5 / §6 박제. Phase 0.7.2 script (run_phase_0_7_2_backtest.py)
패턴 정합 — main.py / runner / composition 변경 zero. 차이점:

1. yaml ``buy_strategy`` 필드를 BacktestRunner 에 전달 (Phase 0.8.1 =
   "support_level"). 회귀 invariant: yaml ``"price_drop"`` 시 Phase
   0.7.x baseline 동일 동작.
2. ``ohlcv_by_asset`` 에 lookback 데이터 포함 — SupportLevelStrategy 의
   indicator 계산 (slot 5 = recent_high(60), slot 4 = MA20 등) 위해
   2019 데이터 필요. CSV 전체 범위 사용 (필터 없음).
3. Phase 0.7.2 script 의 INV_VOL/VOL 정책 분기는 그대로 유지 — Phase
   0.8.1 baseline = EQUAL 이므로 미사용 경로.

Usage::

    uv run python scripts/run_phase_0_8_1_backtest.py \\
        --config config/strategies-0.8.1.yaml \\
        --csv 069500=data/historical/KRX_069500_2019-2024.csv \\
        --csv 132030=data/historical/KRX_132030_2019-2024.csv \\
        --start 2020-01-02 --end 2024-12-30 --capital 100000000 \\
        --json > /tmp/phase081/support_level.json
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.application.backtest_runner import BacktestRunner
from src.cli.allocation import (
    _calculate_volatility,
    compute_per_asset_budgets,
)
from src.cli.composition import asset_from_code
from src.cli.output_formatter import format_backtest_result
from src.domain.models import (
    OHLCV,
    AllocationPolicy,
    Asset,
    Currency,
    Money,
)
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.infrastructure.yaml_strategy_config_loader import (
    AssetStrategyBundle,
    load_allocation_policy,
    load_strategy_config,
)

# ADR 0003 §16.5 — KRX 1 거래년 표준.
LOOKBACK_DAYS = 246


def _parse_csv_arg(values: tuple[str, ...]) -> dict[str, Path]:
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


def _lookback_closes(bars: list[OHLCV], before: date, n: int) -> list[Decimal]:
    eligible = [b.close for b in bars if b.trade_date < before]
    if len(eligible) < n:
        raise SystemExit(
            f"Insufficient lookback for {bars[0].asset.fqn if bars else '?'}: "
            f"need {n} bars before {before}, got {len(eligible)}"
        )
    return eligible[-n:]


def _compute_overrides(
    policy: AllocationPolicy,
    enabled_bundles: dict[str, AssetStrategyBundle],
    bars_by_code: dict[str, list[OHLCV]],
    assets_by_code: dict[str, Asset],
    start: date,
    total_capital: Decimal,
) -> dict[str, SplitStrategyConfig] | None:
    if policy is AllocationPolicy.EQUAL:
        return None
    vols: dict[str, Decimal] = {}
    yaml_per_splits: dict[str, int] = {}
    max_splits: dict[str, int] = {}
    for code, bundle in enabled_bundles.items():
        closes = _lookback_closes(bars_by_code[code], start, LOOKBACK_DAYS)
        vols[code] = _calculate_volatility(closes)
        yaml_per_splits[code] = int(bundle.buy_config.per_split_amount.amount)
        max_splits[code] = bundle.buy_config.max_split_count
    per_split_by_code = compute_per_asset_budgets(
        policy=policy,
        total_capital=total_capital,
        asset_volatilities=vols,
        yaml_per_split_amounts=yaml_per_splits,
        max_split_counts=max_splits,
    )
    overrides: dict[str, SplitStrategyConfig] = {}
    for code, bundle in enabled_bundles.items():
        cfg = bundle.buy_config
        overrides[assets_by_code[code].fqn] = SplitStrategyConfig(
            drop_threshold_pct=cfg.drop_threshold_pct,
            max_split_count=cfg.max_split_count,
            per_split_amount=Money(
                amount=Decimal(per_split_by_code[code]),
                currency=Currency.KRW,
            ),
            max_split_per_day=cfg.max_split_per_day,
            max_loss_pct=cfg.max_loss_pct,
        )
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 0.8.1 SupportLevelStrategy 백테스트 (ADR 0004 §6).",
    )
    parser.add_argument("--config", required=True, type=Path,
                        help="YAML strategy config (Phase 0.8.1 = strategies-0.8.1.yaml).")
    parser.add_argument("--csv", action="append", required=True,
                        dest="csv_values", default=[],
                        help="OHLCV CSV per asset: CODE=PATH. 2019 lookback "
                             "포함 필수 (SupportLevelStrategy slot 5 = 60 bars).")
    parser.add_argument("--start", required=True,
                        help="Backtest start date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True,
                        help="Backtest end date (YYYY-MM-DD).")
    parser.add_argument("--capital", required=True, type=int,
                        help="Initial capital (KRW int).")
    parser.add_argument("--policy", default=None,
                        choices=[p.value for p in AllocationPolicy],
                        help="Override yaml allocation_policy (optional).")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Emit JSON instead of human-readable text.")
    args = parser.parse_args()

    bundles = load_strategy_config(args.config)
    yaml_policy = load_allocation_policy(args.config)
    policy = (
        AllocationPolicy(args.policy) if args.policy is not None else yaml_policy
    )

    enabled_bundles = {
        code: b for code, b in bundles.items() if b.enabled
    }
    if not enabled_bundles:
        raise SystemExit(
            f"No enabled assets in {args.config}. Set enabled: true."
        )

    csv_paths = _parse_csv_arg(tuple(args.csv_values))
    expected = set(enabled_bundles.keys())
    actual = set(csv_paths.keys())
    if actual != expected:
        missing = expected - actual
        extra = actual - expected
        raise SystemExit(
            f"--csv codes must match enabled yaml codes. "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )

    assets_by_code: dict[str, Asset] = {
        code: asset_from_code(code) for code in enabled_bundles
    }
    bars_by_code: dict[str, list[OHLCV]] = {
        code: _load_csv_bars(assets_by_code[code], csv_paths[code])
        for code in enabled_bundles
    }

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    total_capital = Decimal(args.capital)

    # ohlcv_by_asset: buy_strategy 별 분기.
    #   - support_level: 2019 lookback 포함 (slot 5 recent_high(60) 등 indicator)
    #   - price_drop: [start, end] 필터 (Phase 0.7.x baseline 회귀 invariant)
    # ADR 0004 §2.5.4 (lookback 처리 패턴) + ADR 0003 §16.13 (Phase 0.7.2
    # 회귀 invariant) 양쪽 박제 정합.
    first_bundle = next(iter(enabled_bundles.values()))
    needs_lookback = first_bundle.buy_strategy_name == "support_level"
    if needs_lookback:
        ohlcv_by_asset: dict[Asset, list[OHLCV]] = {
            assets_by_code[code]: bars_by_code[code]
            for code in enabled_bundles
        }
    else:
        ohlcv_by_asset = {
            assets_by_code[code]: [
                b for b in bars_by_code[code]
                if start <= b.trade_date <= end
            ]
            for code in enabled_bundles
        }
    assets_list = [assets_by_code[code] for code in enabled_bundles]

    overrides = _compute_overrides(
        policy=policy,
        enabled_bundles=enabled_bundles,
        bars_by_code=bars_by_code,
        assets_by_code=assets_by_code,
        start=start,
        total_capital=total_capital,
    )

    runner = BacktestRunner(
        assets=assets_list,
        strategy_config=first_bundle.buy_config,
        sell_strategy_config=first_bundle.sell_config,
        reentry_strategy_name=first_bundle.reentry_strategy_name,
        reentry_parameters=first_bundle.reentry_parameters,
        initial_capital=Money(amount=total_capital, currency=Currency.KRW),
        ohlcv_by_asset=ohlcv_by_asset,
        per_asset_strategy_overrides=overrides,
        # ADR 0004 §5.7: yaml buy_strategy 필드 → BacktestRunner factory dispatch.
        buy_strategy_name=first_bundle.buy_strategy_name,
    )

    result = runner.run(start, end)
    sys.stdout.write(format_backtest_result(result, as_json=args.as_json) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
