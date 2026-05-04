"""Phase 0.7.2 자본 배분 정책 백테스트 — ADR 0003 §16.13.9 4b.4 박제.

옵션 C (별도 스크립트) 정신 정합 — main.py / runner / composition 변경 zero.
스크립트가 sigma 산출 + per_asset_budget 계산 + SplitStrategyConfig
override 주입 + BacktestRunner 직접 호출.

Phase 0.7.2 검증 흐름:
1. yaml 로드 → bundles, allocation_policy
2. CLI ``--policy`` 인자가 있으면 yaml 의 allocation_policy override
3. 자산별 OHLCV CSV 로드 (2019-2024 전체 — lookback + backtest 동시)
4. ``allocation_policy != EQUAL`` 시:
   - 백테스트 시작일 직전 ``LOOKBACK_DAYS=246`` 거래일 closes 추출
   - ``_calculate_volatility`` (per asset)
   - ``compute_per_asset_budgets`` → 자산별 per_split_amount
   - ``SplitStrategyConfig`` override dict 생성 (asset.fqn 키)
5. ``BacktestRunner`` 인스턴스화 (override 주입) + ``run``
6. ``output_formatter.format_backtest_result(result, as_json)`` 출력

Usage::

    # EQUAL 정책 (Phase 0.7.1 회귀 invariant 검증 — 0.7.1 결과 8 지표 일치)
    uv run python scripts/run_phase_0_7_2_backtest.py \\
        --config config/strategies-0.7.1-F.yaml \\
        --csv 069500=data/historical/KRX_069500_2019-2024.csv \\
        --csv 214980=data/historical/KRX_214980_2019-2024.csv \\
        --start 2020-01-02 --end 2024-12-30 --capital 100000000 \\
        --json > /tmp/phase072/equal.json

    # INV_VOL 정책
    uv run python scripts/run_phase_0_7_2_backtest.py \\
        --policy INV_VOL \\
        --config config/strategies-0.7.1-F.yaml \\
        --csv 069500=data/historical/KRX_069500_2019-2024.csv \\
        --csv 214980=data/historical/KRX_214980_2019-2024.csv \\
        --start 2020-01-02 --end 2024-12-30 --capital 100000000 \\
        --json > /tmp/phase072/inv_vol.json
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

# ADR 0003 §16.5 — KRX 1 거래년 표준 (2026-05-04 갱신).
LOOKBACK_DAYS = 246


def _parse_csv_arg(values: tuple[str, ...]) -> dict[str, Path]:
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
    """Read CSV and produce OHLCV list. Sorted by date asc."""
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
    """Return last `n` closes from bars strictly before `before` date."""
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
    """Build per-asset SplitStrategyConfig override dict.

    Returns ``None`` for EQUAL (회귀 invariant — runner uses single
    fallback). For INV_VOL/VOL: keys = ``asset.fqn``.
    """
    if policy is AllocationPolicy.EQUAL:
        return None

    # Per-asset volatilities + yaml per_split_amount + max_split.
    vols: dict[str, Decimal] = {}
    yaml_per_splits: dict[str, int] = {}
    max_splits: dict[str, int] = {}
    for code, bundle in enabled_bundles.items():
        closes = _lookback_closes(bars_by_code[code], start, LOOKBACK_DAYS)
        vols[code] = _calculate_volatility(closes)
        # AssetStrategyBundle.buy_config.per_split_amount is Money; pull amount.
        yaml_per_splits[code] = int(bundle.buy_config.per_split_amount.amount)
        max_splits[code] = bundle.buy_config.max_split_count

    per_split_by_code = compute_per_asset_budgets(
        policy=policy,
        total_capital=total_capital,
        asset_volatilities=vols,
        yaml_per_split_amounts=yaml_per_splits,
        max_split_counts=max_splits,
    )

    # Build SplitStrategyConfig per asset (per_split_amount only differs).
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
        description=__doc__.split("\n\n")[0] if __doc__ else "",
    )
    parser.add_argument("--config", required=True, type=Path,
                        help="YAML strategy config (Phase 0.7.1 yaml 재사용 권고).")
    parser.add_argument("--csv", action="append", required=True,
                        dest="csv_values", default=[],
                        help="OHLCV CSV per asset: CODE=PATH. 권고: 2019-2024 "
                             "전체 (lookback + backtest 동시).")
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

    # 1. yaml 로드
    bundles = load_strategy_config(args.config)
    yaml_policy = load_allocation_policy(args.config)

    # 2. policy override
    policy = (
        AllocationPolicy(args.policy) if args.policy is not None else yaml_policy
    )

    # 3. enabled assets
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

    # 4. assets + OHLCV 로드
    assets_by_code: dict[str, Asset] = {
        code: asset_from_code(code) for code in enabled_bundles
    }
    # Load full CSV (may include 2019 lookback data for INV_VOL/VOL).
    bars_by_code: dict[str, list[OHLCV]] = {
        code: _load_csv_bars(assets_by_code[code], csv_paths[code])
        for code in enabled_bundles
    }

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    total_capital = Decimal(args.capital)

    # Backtest OHLCV — [start, end] 범위만. Lookback 데이터 (start 이전)
    # 가 백테스트에 들어가면 strategy 의 T-1 close 평가에 영향
    # (Phase 0.7.1 baseline 은 2020-2024 CSV 만 사용 — start 이전 데이터
    # 없음). 회귀 invariant 보존을 위해 명시적 필터.
    ohlcv_by_asset: dict[Asset, list[OHLCV]] = {
        assets_by_code[code]: [
            b for b in bars_by_code[code] if start <= b.trade_date <= end
        ]
        for code in enabled_bundles
    }
    assets_list = [assets_by_code[code] for code in enabled_bundles]

    # 5. SplitStrategyConfig override (정책별)
    overrides = _compute_overrides(
        policy=policy,
        enabled_bundles=enabled_bundles,
        bars_by_code=bars_by_code,
        assets_by_code=assets_by_code,
        start=start,
        total_capital=total_capital,
    )

    # 6. BacktestRunner — 정책 동일성 (yaml 의 첫 enabled bundle 사용).
    first_bundle = next(iter(enabled_bundles.values()))

    runner = BacktestRunner(
        assets=assets_list,
        strategy_config=first_bundle.buy_config,  # fallback (None override 시)
        sell_strategy_config=first_bundle.sell_config,
        reentry_strategy_name=first_bundle.reentry_strategy_name,
        reentry_parameters=first_bundle.reentry_parameters,
        initial_capital=Money(amount=total_capital, currency=Currency.KRW),
        ohlcv_by_asset=ohlcv_by_asset,
        per_asset_strategy_overrides=overrides,
    )

    result = runner.run(start, end)

    # 7. 출력 — main.py 와 동일 format.
    sys.stdout.write(format_backtest_result(result, as_json=args.as_json) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
