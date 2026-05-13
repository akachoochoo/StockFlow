"""Phase 0.11.c.4 — visualization CLI (ADR 0009 §1.3 D7).

진입점:
    python -m src.research.visualization compare \\
        --asset 069500 --start 2020-01-02 --end 2024-12-30 \\
        --initial-capital 10000000 --n 7 --k 5 --m 3 \\
        --output-dir reports/visualization/

산출 (D5 PNG export, `--output-dir/`):
    - dgt_full_period.png      : DGT VisualizationRenderer 단일 차트
    - comparison_overlay_pnl.png      : 3-strategy overlay (누적 수익)
    - comparison_overlay_drawdown.png : 3-strategy overlay (drawdown)
    - comparison_grid.png             : 3-strategy grid (pnl + drawdown)
    - overlay_metrics.json            : 마지막 지점 metrics 박제

D7 정합: `python -m src.research.visualization.cli` — `src/cli/` 변경 zero
("production rings 변경 zero" invariant 보존).

ADR 0007 §1.6 — `python -m src.research.<...>` CLI 진입은 ring boundary
위반 아님. 본 CLI 는 outer (5th ring) → inner ring read 만 발생.

Lifecycle (ADR 0009 §1.7): permanent.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
)

if TYPE_CHECKING:
    from datetime import datetime as _dt

    from src.application.backtest_runner import BacktestResult
    from src.research.dgt.results import _DGTBacktestResult
    from src.research.dgt.runner import _DGTConfig
    from src.research.visualization._visualization_renderer import (
        _OverlayPayload,
    )


__all__: list[str] = []


_DEFAULT_INITIAL_CAPITAL = Decimal("10000000")  # 10M KRW (Phase 0.11.a 정합)


def _build_asset_069500() -> Asset:
    """Phase 0.11.a/b D3 default — 069500 (KODEX 200)."""
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
    path: Path, asset: Asset, start: date, end: date,
) -> list[OHLCV]:
    """5y CSV loader (Phase 0.11.a `dgt/cli.py` 패턴 재사용)."""
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


def _run_dgt(
    bars: list[OHLCV],
    asset: Asset,
    initial_capital: Money,
    n: int,
    k_pct: Decimal,
    m: int,
) -> tuple[_DGTBacktestResult, _DGTConfig]:
    """DGT runner 실행 → (`_DGTBacktestResult`, `_DGTConfig`)."""
    from src.research.dgt.cost_model import _KoreanMarketCostModel
    from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner

    config = _DGTConfig(
        grid_count=n,
        grid_spacing_pct=k_pct,
        levels_above=m,
    )
    runner = _DGTPrototypeRunner(
        cost_model=_KoreanMarketCostModel(),
        config=config,
    )
    result = runner.run(
        asset=asset,
        start=bars[0].trade_date,
        end=bars[-1].trade_date,
        initial_capital=initial_capital,
        ohlcv=bars,
    )
    return result, config


def _run_buy_and_hold(
    bars: list[OHLCV],
    asset: Asset,
    initial_capital: Money,
) -> BacktestResult:
    """Buy-and-Hold full-period — production BacktestRunner equivalent.

    Day-0 close 매수 → 마지막 day 평가. PortfolioSnapshot 시계열 산출
    (production layer 활용 — `src/application/snapshot_builder.py` 직접
    호출 비용 우회, 단순 wallet 회계).
    """
    from src.application.backtest_runner import BacktestResult
    from src.domain.models import (
        Decision,
        PortfolioSnapshot,
        Position,
        PositionValuation,
        SplitEntry,
        SplitSlot,
    )
    from src.research.dgt.cost_model import _KoreanMarketCostModel

    decisions: list[Decision] = []

    cost_model = _KoreanMarketCostModel()
    initial = initial_capital.amount
    day0_close = bars[0].close
    raw_qty = initial / day0_close
    quantity = raw_qty.quantize(Decimal("1"), rounding="ROUND_DOWN")
    if quantity <= 0:
        raise ValueError("insufficient capital for B&H")
    buy_cost = cost_model.compute_buy_cost(
        price=day0_close, quantity=quantity, asset=asset,
    )
    if buy_cost.total_cost > initial:
        quantity -= Decimal("1")
        if quantity <= 0:
            raise ValueError("insufficient capital after rounding")
        buy_cost = cost_model.compute_buy_cost(
            price=day0_close, quantity=quantity, asset=asset,
        )
    cash_after_buy = initial - buy_cost.total_cost

    # Build PortfolioSnapshot series — single Position throughout.
    snapshots: list[PortfolioSnapshot] = []
    for bar in bars:
        valuation = PositionValuation(
            asset=asset,
            quantity=quantity,
            avg_price=buy_cost.rounded_price,
            market_price=bar.close,
            market_value=Money(
                amount=quantity * bar.close,
                currency=initial_capital.currency,
            ),
            unrealized_pnl=Money(
                amount=(bar.close - buy_cost.rounded_price) * quantity,
                currency=initial_capital.currency,
            ),
            split_level=1,
        )
        snap = PortfolioSnapshot.build(
            snapshot_date=bar.trade_date,
            snapshot_at=_to_utc_noon(bar.trade_date),
            initial_capital=initial_capital,
            cash=Money(
                amount=cash_after_buy, currency=initial_capital.currency,
            ),
            valuations=[valuation],
        )
        snapshots.append(snap)

    # Minimal Decision + final Position (BacktestResult 시그니처 정합).
    # Reasoning 보존 일관 — empty dict allowed.
    entry = SplitEntry(
        split_number=1,
        entry_date=bars[0].trade_date,
        quantity=quantity,
        entry_price=buy_cost.rounded_price,
        idempotency_key="bh-001",
    )
    slot = SplitSlot.filled(entry)
    other_slots = [SplitSlot.empty(slot_number=i) for i in range(2, 8)]
    final_position = Position(
        asset=asset,
        quantity=quantity,
        avg_price=buy_cost.rounded_price,
        split_level=1,
        last_buy_at=_to_utc_noon(bars[0].trade_date),
        slots=[slot, *other_slots],
    )
    return BacktestResult.from_run(
        start_date=bars[0].trade_date,
        end_date=bars[-1].trade_date,
        initial_capital=initial_capital,
        decisions=decisions,
        snapshots=snapshots,
        final_positions=[final_position],
    )


def _to_utc_noon(d: date) -> _dt:
    """Date → UTC noon datetime (snapshot_at 시그니처 정합)."""
    from datetime import UTC, datetime

    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)


def _run_seven_split(
    bars: list[OHLCV],
    asset: Asset,
    initial_capital: Money,
) -> BacktestResult:
    """PriceDropStrategy 7-split full-period — `_baseline.py` 패턴 재사용.

    Phase 0.7.3 정합 config (drop=5% / target=10% / cooldown=60d).
    """
    from src.application.backtest_runner import BacktestRunner
    from src.domain.strategies.price_drop import SplitStrategyConfig
    from src.domain.strategies.profit_target import SellStrategyConfig

    per_split = (initial_capital.amount / Decimal("7")).quantize(Decimal("1"))
    strategy_config = SplitStrategyConfig(
        drop_threshold_pct=Decimal("5.0"),
        max_split_count=7,
        per_split_amount=Money(
            amount=per_split, currency=initial_capital.currency,
        ),
        max_split_per_day=1,
    )
    sell_config = SellStrategyConfig(
        profit_target_pct=Decimal("10.0"),
        max_sells_per_day=7,
    )
    runner = BacktestRunner(
        assets=[asset],
        strategy_config=strategy_config,
        initial_capital=initial_capital,
        ohlcv_by_asset={asset: bars},
        sell_strategy_config=sell_config,
        reentry_strategy_name="hybrid",
        reentry_parameters={"cooldown_days": 60},
    )
    return runner.run(bars[0].trade_date, bars[-1].trade_date)


def _final_overlay_metrics(payload: _OverlayPayload) -> dict[str, str]:
    """마지막 지점의 pnl + drawdown 요약 — JSON serializable."""
    if not payload.pnl_cumulative:
        return {"final_pnl": "0", "final_drawdown": "0"}
    return {
        "strategy_id": payload.strategy_id,
        "final_pnl": str(payload.pnl_cumulative[-1]),
        "final_drawdown": str(payload.drawdown[-1]),
        "n_points": str(len(payload.time_series)),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="src.research.visualization",
        description=(
            "Phase 0.11.c.4 strategy visualization comparison "
            "(ADR 0009 §1.3 D6 + D7)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    compare = sub.add_parser(
        "compare",
        help="Run B&H + 7split + DGT and emit comparison PNGs",
    )
    compare.add_argument(
        "--asset", default="069500",
        help="Asset code (default: 069500 — Phase 0.11.a/b D3 default)",
    )
    compare.add_argument(
        "--start", required=True, help="YYYY-MM-DD",
    )
    compare.add_argument(
        "--end", required=True, help="YYYY-MM-DD",
    )
    compare.add_argument(
        "--initial-capital",
        type=str,
        default=str(_DEFAULT_INITIAL_CAPITAL),
        help=f"KRW amount (default: {_DEFAULT_INITIAL_CAPITAL})",
    )
    compare.add_argument(
        "--n", type=int, default=7,
        help="DGT grid_count (Phase 0.11.a default = 7)",
    )
    compare.add_argument(
        "--k", type=str, default="5",
        help="DGT grid_spacing_pct as percent (Phase 0.11.a default = 5)",
    )
    compare.add_argument(
        "--m", type=int, default=3,
        help="DGT levels_above (Phase 0.11.a default = 3)",
    )
    compare.add_argument(
        "--csv",
        type=Path,
        default=Path("data/historical/KRX_069500_2019-2024.csv"),
        help="OHLCV CSV path",
    )
    compare.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for PNGs + metrics JSON",
    )
    compare.add_argument(
        "--skip-7split",
        action="store_true",
        help="Skip PriceDropStrategy 7-split (production BacktestRunner)",
    )
    return parser


def _run_compare(args: argparse.Namespace) -> int:
    if args.asset != "069500":
        raise SystemExit(
            f"D3 default = 069500 단독. Got '{args.asset}'. "
            "Multi-asset override = Phase 1 ADR 0012."
        )

    from src.research.visualization._align import _align_results_for_overlay
    from src.research.visualization._comparison import (
        _render_grid,
        _render_overlay_drawdown,
        _render_overlay_pnl,
    )
    from src.research.visualization._dgt_factory import (
        _build_dgt_visualization_artifacts,
        _dgt_trades_to_trade_views,
    )
    from src.research.visualization._dgt_renderer import (
        _DGTVisualizationRenderer,
    )

    asset = _build_asset_069500()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    bars = _load_ohlcv_csv(args.csv, asset, start, end)
    if not bars:
        raise SystemExit(f"No bars loaded from {args.csv} in [{start}, {end}]")

    initial_capital = Money(
        amount=Decimal(args.initial_capital), currency=Currency.KRW,
    )
    k_pct = Decimal(args.k)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # === DGT run + full-period chart ===
    dgt_result, dgt_config = _run_dgt(
        bars=bars,
        asset=asset,
        initial_capital=initial_capital,
        n=args.n,
        k_pct=k_pct,
        m=args.m,
    )
    dgt_artifacts = _build_dgt_visualization_artifacts(dgt_result, dgt_config)
    dgt_trade_views = _dgt_trades_to_trade_views(dgt_result, dgt_config)
    dgt_renderer = _DGTVisualizationRenderer()
    dgt_png = dgt_renderer.render_full_period(
        bars=bars,
        trades=dgt_trade_views,
        artifacts=dgt_artifacts,
    )
    (output_dir / "dgt_full_period.png").write_bytes(dgt_png)

    # === Overlay payloads ===
    payloads: list[_OverlayPayload] = [
        _align_results_for_overlay(dgt_result, strategy_id="dgt"),
    ]

    bh_result = _run_buy_and_hold(bars, asset, initial_capital)
    payloads.append(
        _align_results_for_overlay(bh_result, strategy_id="buy_and_hold"),
    )

    if not args.skip_7split:
        seven_result = _run_seven_split(bars, asset, initial_capital)
        payloads.append(
            _align_results_for_overlay(
                seven_result, strategy_id="price_drop_7split",
            ),
        )

    # === Comparison renders ===
    (output_dir / "comparison_overlay_pnl.png").write_bytes(
        _render_overlay_pnl(payloads),
    )
    (output_dir / "comparison_overlay_drawdown.png").write_bytes(
        _render_overlay_drawdown(payloads),
    )
    (output_dir / "comparison_grid.png").write_bytes(
        _render_grid(payloads),
    )

    metrics = {p.strategy_id: _final_overlay_metrics(p) for p in payloads}
    (output_dir / "overlay_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "compare":
        return _run_compare(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
