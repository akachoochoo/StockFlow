"""Phase 1.1 Stage 1 작업 1.2 — 손절(추가매수 차단) 임계 비교 backtest.

ADR 0012 D2 (b') 의미 = **평가손 ≤ -X% 도달 종목은 그날 추가 매수만
차단** (매도 / ProfitTargetSell 은 정상 작동 — 자동매도 zero). 손절 정책은
Phase 1 진입 전 작성 금지 (CLAUDE.md §14) 이므로 도메인 변경 zero —
research-scope 래퍼로만 실험한다.

구현 = research-scope 래퍼 (도메인 변경 zero):
- ``_StopLossBuyWrapper`` 가 ``PriceDropStrategy`` 를 감싸고 동일한
  ``evaluate`` 시그니처를 구현. 보유 포지션의 평가손이 임계 이하면 추가
  매수만 차단 (``SkipReason.STRATEGY_NO_BUY`` 반환), 그 외 내부
  ``PriceDropStrategy.evaluate`` 그대로 위임.
- 루프 = ``BacktestRunner`` 내부 루프 (backtest_runner.py:254-360) 를
  스크립트에 미러링하되 ``AssetContext.strategy`` 만 래퍼로 교체.
  MockBroker / MockMarketData / DailyOrchestrator / DailySnapshotBuilder /
  clock_holder / create_buy_strategy / create_reentry_strategy /
  ProfitTargetSell 동일 구성 (BacktestRunner 수정 zero — 구성만 복제).

Faithfulness gate (필수):
- no-SL 미러 루프 결과 (최종가치 + 4 지표) 가 ``BacktestRunner(...).run()``
  baseline (동일 파라미터) 과 **정확히 일치** 함을 assert. 불일치 시 미러
  루프 버그 → 보고. 통과해야 SL 변형 결과 신뢰.

규칙 (CLAUDE.md §1.1 / §2 / §13.3):
- production ring (src/) 변경 zero. 모든 가격/수량/금액 Decimal. 결정론.
- 윈도우 = 가용 전 구간 교집합 (2019-01-02 ~ 2024-12-30) 고정.
- profit_target 등 = 작업 1.1 baseline (=10) 과 동일 고정.

Usage::

    uv run python scripts/run_phase_1_1_b_stop_loss.py \\
        --config config/strategies-0.7.3.yaml \\
        --csv 069500=data/historical/KRX_069500_2019-2024.csv \\
        --csv 132030=data/historical/KRX_132030_2019-2024.csv \\
        --start 2019-01-02 --end 2024-12-30 --capital 100000000 \\
        --out-dir docs/research/phase-1.1.b
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.adapters.mock.market_data import MockMarketData
from src.adapters.mock.signals import NullSignal
from src.application.backtest_runner import BacktestResult, BacktestRunner
from src.application.snapshot_builder import DailySnapshotBuilder
from src.cli.composition import (
    asset_from_code,
    create_buy_strategy,
    slot_model_for_buy_strategy,
)
from src.domain.constants import KST
from src.domain.models import (
    OHLCV,
    Asset,
    Balance,
    Currency,
    Money,
    Position,
    Price,
    SkipReason,
)
from src.domain.strategies.price_drop import (
    BuyEvaluationResult,
    PriceDropStrategy,
    SplitStrategyConfig,
)
from src.domain.strategies.profit_target import (
    ProfitTargetSell,
    SellStrategyConfig,
)
from src.domain.strategies.reentry import create_reentry_strategy
from src.infrastructure.yaml_strategy_config_loader import load_strategy_config
from src.use_cases.asset_context import AssetContext
from src.use_cases.daily_orchestrator import DailyOrchestrator

# Phase 1.1 작업 1.2 — 손절(추가매수 차단) 임계 (percent, 양수 = 손실폭).
STOP_LOSS_THRESHOLDS_PCT: tuple[Decimal, ...] = (
    Decimal("15"),
    Decimal("20"),
    Decimal("25"),
)
# 작업 1.1 baseline profit_target (고정).
BASELINE_PROFIT_TARGET_PCT = Decimal("10")
_DECISION_KST = time(9, 0)
_SNAPSHOT_KST = time(16, 0)


class _StopLossBuyWrapper:
    """research-scope wrapper: blocks additional buys on deep unrealized loss.

    ADR 0012 D2 (b') — 평가손 ≤ -stop_loss_pct 도달 시 추가 매수만 차단.
    매도 (ProfitTargetSell) 는 orchestrator 의 SELL loop 가 담당하므로 본
    래퍼는 BUY 만 다룬다 (자동매도 zero). 도메인 변경 zero —
    ``PriceDropStrategy.evaluate`` 와 동일 시그니처로 위임.

    포지션 없음 (첫 매수) 은 차단하지 않는다 — 손절은 보유 포지션의 평가손
    개념이므로 holdings 가 있어야 적용. 차단 발생 시 ``_block_count`` 증가
    (집계용).
    """

    def __init__(
        self, inner: PriceDropStrategy, stop_loss_pct: Decimal
    ) -> None:
        self._inner = inner
        self._stop_loss_pct = stop_loss_pct
        # block_count: every time the loss condition tripped and we returned
        # a skip. effective_block_count: subset where the inner strategy
        # WOULD have emitted a buy (i.e. blocks that actually changed the
        # outcome). When effective == 0 the SL variant is inert vs no-SL.
        self.block_count = 0
        self.effective_block_count = 0

    def evaluate(
        self,
        *,
        position: Position | None,
        current_price: Price,
        balance: Balance,
        config: SplitStrategyConfig,
        today: date,
        excluded_slot_numbers: set[int] | None = None,
    ) -> BuyEvaluationResult:
        has_holding = (
            position is not None
            and position.quantity > 0
            and position.split_level > 0
            and position.avg_price > 0
        )
        if has_holding:
            assert position is not None  # narrow for type checker
            loss_pct = (
                (current_price.value - position.avg_price)
                / position.avg_price
                * Decimal(100)
            )
            if loss_pct <= -self._stop_loss_pct:
                self.block_count += 1
                # Probe whether the inner strategy would actually have bought
                # — only then does the block change the run outcome. Pure
                # read (inner.evaluate is stateless), no side effects.
                inner_res = self._inner.evaluate(
                    position=position,
                    current_price=current_price,
                    balance=balance,
                    config=config,
                    today=today,
                    excluded_slot_numbers=excluded_slot_numbers,
                )
                if inner_res.buy is not None:
                    self.effective_block_count += 1
                return BuyEvaluationResult(
                    buy=None,
                    skip_reason=SkipReason.STRATEGY_NO_BUY,
                    reasoning={
                        "today": today.isoformat(),
                        "asset": current_price.asset.fqn,
                        "current_price": str(current_price.value),
                        "avg_price": str(position.avg_price),
                        "loss_pct": str(loss_pct),
                        "stop_loss_pct": str(self._stop_loss_pct),
                        "stop_loss_block": "True",
                    },
                )
        return self._inner.evaluate(
            position=position,
            current_price=current_price,
            balance=balance,
            config=config,
            today=today,
            excluded_slot_numbers=excluded_slot_numbers,
        )


def _parse_csv_arg(values: list[str]) -> dict[str, Path]:
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


def _count_sells(result: BacktestResult) -> int:
    return sum(len(d.sell_actions) for d in result.decisions)


def _utc_for(d: date, t: time) -> datetime:
    """KST date+time → UTC datetime (mirrors BacktestRunner._utc_for)."""
    return datetime.combine(d, t, tzinfo=KST).astimezone(UTC)


def _run_mirror(
    *,
    assets_list: list[Asset],
    buy_config: SplitStrategyConfig,
    sell_config: SellStrategyConfig,
    reentry_strategy_name: str,
    reentry_parameters: dict[str, object],
    total_capital: Decimal,
    ohlcv_by_asset: dict[Asset, list[OHLCV]],
    start: date,
    end: date,
    stop_loss_pct: Decimal | None,
) -> tuple[BacktestResult, int, int]:
    """Mirror BacktestRunner.run() but swap AssetContext.strategy.

    backtest_runner.py:233-360 을 그대로 미러링. ``stop_loss_pct`` 가 None
    이면 vanilla PriceDropStrategy (faithfulness baseline). 값이 있으면
    ``_StopLossBuyWrapper`` 로 감싼다.

    Returns (result, block_count, effective_block_count). block_count 는
    손실 임계 발동 횟수 합, effective_block_count 는 그 중 inner 가 실제로
    매수했을 (= 결과를 바꾼) 횟수 합 (None 시 둘 다 0).
    """
    if start > end:
        raise ValueError(f"start ({start}) > end ({end})")

    initial_capital = Money(amount=total_capital, currency=Currency.KRW)

    # Trading dates = intersection of each asset's bars within [start, end].
    date_sets = [
        {b.trade_date for b in ohlcv_by_asset.get(asset, [])
         if start <= b.trade_date <= end}
        for asset in assets_list
    ]
    if date_sets:
        common_dates = date_sets[0]
        for ds in date_sets[1:]:
            common_dates = common_dates & ds
    else:
        common_dates = set()
    trading_dates = sorted(common_dates)

    clock_holder: list[datetime | None] = [None]

    def clock() -> datetime:
        value = clock_holder[0]
        assert value is not None, "mirror loop did not set the clock"
        return value

    broker = MockBroker(
        initial_balance=Balance(cash=initial_capital),
        clock=clock,
        slot_model=slot_model_for_buy_strategy("price_drop"),
    )
    market_data = MockMarketData(ohlcv_by_asset=ohlcv_by_asset)
    signal = NullSignal()

    reentry = create_reentry_strategy(
        reentry_strategy_name,
        market_data=market_data,
        **reentry_parameters,  # type: ignore[arg-type]
    )
    base_strategy = create_buy_strategy("price_drop", reentry=reentry)
    assert isinstance(base_strategy, PriceDropStrategy)

    # Swap seam: vanilla PriceDropStrategy (None) vs _StopLossBuyWrapper.
    # A single strategy instance is shared across all AssetContexts —
    # matches BacktestRunner (broadcast). The wrapper accumulates a single
    # shared block_count across assets.
    wrappers: list[_StopLossBuyWrapper] = []
    if stop_loss_pct is None:
        strategy: object = base_strategy
    else:
        wrapper = _StopLossBuyWrapper(base_strategy, stop_loss_pct)
        wrappers.append(wrapper)
        strategy = wrapper

    shared_uow = InMemoryUnitOfWork()
    asset_contexts = [
        AssetContext(
            asset=asset,
            strategy=strategy,  # type: ignore[arg-type]
            config=buy_config,
            sell_strategy=ProfitTargetSell(),
            sell_config=sell_config,
        )
        for asset in assets_list
    ]
    orchestrator = DailyOrchestrator(
        broker=broker,
        market_data=market_data,
        signal=signal,
        asset_contexts=asset_contexts,
        clock=clock,
        uow_factory=lambda: shared_uow,
    )
    snapshot_builder = DailySnapshotBuilder(
        broker=broker,
        market_data=market_data,
        uow_factory=lambda: shared_uow,
        clock=clock,
        initial_capital=initial_capital,
    )

    decisions = []
    snapshots = []
    for d in trading_dates:
        clock_holder[0] = _utc_for(d, _DECISION_KST)
        decisions.extend(orchestrator.run_for_date(d))
        clock_holder[0] = _utc_for(d, _SNAPSHOT_KST)
        snapshots.append(snapshot_builder.build_and_save(d))

    final_positions = broker.get_positions()
    result = BacktestResult.from_run(
        start_date=start,
        end_date=end,
        initial_capital=initial_capital,
        decisions=decisions,
        snapshots=snapshots,
        final_positions=final_positions,
    )
    block_count = sum(w.block_count for w in wrappers)
    effective_block_count = sum(w.effective_block_count for w in wrappers)
    return result, block_count, effective_block_count


def _metrics_tuple(result: BacktestResult) -> tuple[str, str, str, str, str]:
    """The 5 load-bearing comparison values as exact strings (Decimal)."""
    return (
        str(result.final_value.amount),
        str(result.cagr_pct),
        str(result.max_drawdown_pct),
        str(result.sharpe_ratio),
        str(result.calmar_ratio),
    )


def _result_row(
    result: BacktestResult,
    *,
    label: str,
    stop_loss_pct: Decimal | None,
    block_count: int,
    effective_block_count: int,
) -> dict[str, object]:
    return {
        "label": label,
        "stop_loss_pct": str(stop_loss_pct) if stop_loss_pct is not None else None,
        "final_value": str(result.final_value.amount),
        "currency": result.final_value.currency.value,
        "total_return_pct": str(result.total_return_pct),
        "cagr_pct": str(result.cagr_pct),
        "max_drawdown_pct": str(result.max_drawdown_pct),
        "sharpe_ratio": str(result.sharpe_ratio),
        "calmar_ratio": str(result.calmar_ratio),
        "total_sells": _count_sells(result),
        "block_count": block_count,
        "effective_block_count": effective_block_count,
        "n_trading_days": result.n_trading_days,
    }


def _format_md(
    rows: list[dict[str, object]],
    *,
    faithful: bool,
    faithful_detail: str,
    start: date,
    end: date,
    total_capital: Decimal,
    config_path: Path,
    csv_paths: dict[str, Path],
) -> str:
    lines: list[str] = []
    lines.append("# Phase 1.1 Stage 1 — 작업 1.2: 손절(추가매수 차단) 임계 비교 결과")
    lines.append("")
    lines.append("> ADR 0012 D2 (b') = 평가손 ≤ -X% 도달 종목은 그날 **추가 매수만**")
    lines.append("> 차단 (매도 / ProfitTargetSell 정상, 자동매도 zero).")
    lines.append("> 구현 = research-scope ``_StopLossBuyWrapper`` (도메인 변경 zero).")
    lines.append("> production ring (src/) 변경 zero — BacktestRunner 내부 루프 미러링.")
    lines.append("> **권고: pending 사용자 확정** (-20% 가 ADR 0012 D2 기본값이나 "
                 "backtest 결과로 정정 가능).")
    lines.append("")
    lines.append("## Faithfulness gate")
    lines.append("")
    status = "PASS ✅" if faithful else "FAIL ❌"
    lines.append(f"- no-SL 미러 루프 vs `BacktestRunner(...).run()` baseline: **{status}**")
    lines.append(f"- 상세: {faithful_detail}")
    lines.append("")
    lines.append("## 고정 조건")
    lines.append("")
    lines.append(f"- 윈도우: `{start}` ~ `{end}` (가용 전 구간 교집합)")
    lines.append(f"- 초기자본: `{total_capital:,}` KRW (0.7.3 baseline 동일)")
    lines.append("- 자산: 069500 (KODEX 200) + 132030 (KODEX 골드선물(H)), EQUAL allocation")
    lines.append("- 고정 파라미터 (0.7.3 baseline + 작업 1.1 baseline): "
                 "drop_threshold_pct=5 / max_split_count=7 / "
                 "per_split_amount=5,000,000 / max_split_per_day=1 / "
                 f"profit_target_pct={BASELINE_PROFIT_TARGET_PCT} / "
                 "reentry=hybrid cooldown=60")
    lines.append("- 변수: `stop_loss_pct ∈ {no-SL, 15, 20, 25}` (추가매수 차단 임계)")
    lines.append("")
    lines.append("## 컬럼 정의")
    lines.append("")
    lines.append("- **차단 횟수**: 평가손 ≤ -X% 조건이 발동해 래퍼가 매수를 short-circuit 한 횟수.")
    lines.append("- **유효 차단**: 그 중 inner `PriceDropStrategy` 가 실제로 매수를 "
                 "냈을(= 결과를 바꾼) 횟수. **유효 차단 = 0 이면 해당 SL 임계는 본 "
                 "윈도우 / 정책에서 inert** (no-SL 과 결과 동일).")
    lines.append("")
    lines.append("## 비교 표")
    lines.append("")
    lines.append(
        "| 손절 임계 | 최종가치 (KRW) | Total Return % | CAGR % | MDD % | "
        "Sharpe | Calmar | 총 매도 | 차단 횟수 | 유효 차단 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        fv = Decimal(str(r["final_value"]))
        label = r["label"]
        lines.append(
            f"| {label} "
            f"| {fv:,.0f} "
            f"| {Decimal(str(r['total_return_pct'])):.4f} "
            f"| {Decimal(str(r['cagr_pct'])):.4f} "
            f"| {Decimal(str(r['max_drawdown_pct'])):.4f} "
            f"| {Decimal(str(r['sharpe_ratio'])):.4f} "
            f"| {Decimal(str(r['calmar_ratio'])):.4f} "
            f"| {r['total_sells']} "
            f"| {r['block_count']} "
            f"| {r['effective_block_count']} |"
        )
    lines.append("")
    lines.append("## 재현 커맨드")
    lines.append("")
    lines.append("```bash")
    lines.append("uv run python scripts/run_phase_1_1_b_stop_loss.py \\")
    lines.append(f"    --config {config_path} \\")
    for code, p in csv_paths.items():
        lines.append(f"    --csv {code}={p} \\")
    lines.append(f"    --start {start} --end {end} --capital {total_capital} \\")
    lines.append("    --out-dir docs/research/phase-1.1.b")
    lines.append("```")
    lines.append("")
    lines.append("## 권고")
    lines.append("")
    lines.append("- **pending 사용자 확정**. -20% 가 ADR 0012 D2 기본값이나 위 "
                 "backtest 수치로 정정 가능.")
    lines.append("- **이상치 주의**: 0.7.3 baseline (drop=5% / max_split_per_day=1 / "
                 "hybrid cooldown=60) 에서는 모든 SL 임계의 **유효 차단 = 0** — "
                 "즉 손실이 임계에 도달한 날에는 strategy 가 이미 매수하지 않는다 "
                 "(일일 1회 매수 cap + cooldown + drop trigger 가 선행 억제). 따라서 "
                 "본 정책에서 SL 추가매수 차단은 결과를 바꾸지 못함 (모든 지표 no-SL "
                 "동일). SL 의 효용 검증은 더 공격적인 매수 정책 (큰 max_split_per_day "
                 "/ 짧은 cooldown / 작은 drop) 에서 재평가 필요 — 사용자 결정 항목.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1.1 작업 1.2 — 손절(추가매수 차단) 임계 비교.",
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--csv", action="append", required=True,
                        dest="csv_values", default=[],
                        help="OHLCV CSV per asset: CODE=PATH.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--capital", required=True, type=int)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

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

    # 작업 1.1 baseline profit_target (=10) 고정.
    sell_config = SellStrategyConfig(
        profit_target_pct=BASELINE_PROFIT_TARGET_PCT,
        max_sells_per_day=7,
    )

    # ------------------------------------------------------------------
    # Faithfulness gate: no-SL mirror == BacktestRunner(...).run()
    # ------------------------------------------------------------------
    runner = BacktestRunner(
        assets=assets_list,
        strategy_config=first_bundle.buy_config,
        sell_strategy_config=sell_config,
        reentry_strategy_name=first_bundle.reentry_strategy_name,
        reentry_parameters=first_bundle.reentry_parameters,
        initial_capital=Money(amount=total_capital, currency=Currency.KRW),
        ohlcv_by_asset=ohlcv_by_asset,
    )
    canonical = runner.run(start, end)

    mirror_baseline, _, _ = _run_mirror(
        assets_list=assets_list,
        buy_config=first_bundle.buy_config,
        sell_config=sell_config,
        reentry_strategy_name=first_bundle.reentry_strategy_name,
        reentry_parameters=first_bundle.reentry_parameters,
        total_capital=total_capital,
        ohlcv_by_asset=ohlcv_by_asset,
        start=start,
        end=end,
        stop_loss_pct=None,
    )

    canon_t = _metrics_tuple(canonical)
    mirror_t = _metrics_tuple(mirror_baseline)
    faithful = canon_t == mirror_t
    faithful_detail = (
        f"canonical=(fv={canon_t[0]}, cagr={canon_t[1]}, mdd={canon_t[2]}, "
        f"sharpe={canon_t[3]}, calmar={canon_t[4]}) "
        f"mirror=(fv={mirror_t[0]}, cagr={mirror_t[1]}, mdd={mirror_t[2]}, "
        f"sharpe={mirror_t[3]}, calmar={mirror_t[4]})"
    )

    # ------------------------------------------------------------------
    # Rows: no-SL baseline (mirror) + SL variants.
    # ------------------------------------------------------------------
    rows: list[dict[str, object]] = [
        _result_row(
            mirror_baseline,
            label="no-SL",
            stop_loss_pct=None,
            block_count=0,
            effective_block_count=0,
        )
    ]
    for sl in STOP_LOSS_THRESHOLDS_PCT:
        res, blocks, effective = _run_mirror(
            assets_list=assets_list,
            buy_config=first_bundle.buy_config,
            sell_config=sell_config,
            reentry_strategy_name=first_bundle.reentry_strategy_name,
            reentry_parameters=first_bundle.reentry_parameters,
            total_capital=total_capital,
            ohlcv_by_asset=ohlcv_by_asset,
            start=start,
            end=end,
            stop_loss_pct=sl,
        )
        rows.append(
            _result_row(
                res,
                label=f"-{sl}%",
                stop_loss_pct=sl,
                block_count=blocks,
                effective_block_count=effective,
            )
        )

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_payload = {
        "phase": "1.1.b",
        "task": "손절(추가매수 차단) 임계 비교 (ADR 0012 D2 b')",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "initial_capital": str(total_capital),
        "currency": "KRW",
        "assets": sorted(enabled_bundles.keys()),
        "allocation_policy": "EQUAL",
        "baseline_profit_target_pct": str(BASELINE_PROFIT_TARGET_PCT),
        "fixed_parameters": {
            "drop_threshold_pct": str(first_bundle.buy_config.drop_threshold_pct),
            "max_split_count": first_bundle.buy_config.max_split_count,
            "per_split_amount": str(first_bundle.buy_config.per_split_amount.amount),
            "max_split_per_day": first_bundle.buy_config.max_split_per_day,
            "reentry_strategy": first_bundle.reentry_strategy_name,
            "reentry_parameters": first_bundle.reentry_parameters,
        },
        "faithfulness_gate": {
            "pass": faithful,
            "detail": faithful_detail,
            "canonical": {
                "final_value": canon_t[0],
                "cagr_pct": canon_t[1],
                "max_drawdown_pct": canon_t[2],
                "sharpe_ratio": canon_t[3],
                "calmar_ratio": canon_t[4],
            },
            "mirror": {
                "final_value": mirror_t[0],
                "cagr_pct": mirror_t[1],
                "max_drawdown_pct": mirror_t[2],
                "sharpe_ratio": mirror_t[3],
                "calmar_ratio": mirror_t[4],
            },
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
        faithful=faithful,
        faithful_detail=faithful_detail,
        start=start,
        end=end,
        total_capital=total_capital,
        config_path=args.config,
        csv_paths=csv_paths,
    )
    (out_dir / "results.md").write_text(md + "\n", encoding="utf-8")

    print(md)
    print("\n--- Faithfulness gate ---")
    print(f"PASS={faithful}")
    print(faithful_detail)

    # Faithfulness 불일치 시 SL 변형 결과 신뢰 불가 → non-zero exit (보고용).
    if not faithful:
        print(
            "\nERROR: mirror loop diverged from BacktestRunner baseline. "
            "SL variant numbers are NOT trustworthy.",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
