"""Phase 0.11.a — DGT prototype CLI.

ADR 0007 §1.10 AC8 oracle. Run via:
    python -m src.research.dgt.cli --asset 069500 --start ... --end ... \
        --initial-capital 10000000 --grid-levels 7 --grid-spacing-pct 5 \
        --output tests/fixtures/golden/dgt_069500_2021_2025.json

ADR 0007 §1.6 — `python -m` CLI 진입은 ring boundary 위반 아님 (terminal
진입점). 본 CLI 는 outer (5th ring) 에서 inner ring (`src/domain/`) 만 read.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
    OHLCV,
)
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.results import _DGTBacktestResult
from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner


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


def _load_ohlcv_csv(path: Path, asset: Asset, start: date, end: date) -> list[OHLCV]:
    """CSV 로더 (5th ring 내부 — Phase 0.10.bb csv_market_data_loader 회귀 invariant 보존).

    Format: date,open,high,low,close,volume (data/historical/KRX_*_*.csv).
    """
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


def _compute_metrics(result: _DGTBacktestResult) -> dict[str, Decimal]:
    """4 informational metrics: CAGR / MDD / Sharpe / Calmar (G2 informational).

    Self-contained Decimal (ln/exp 패턴, 28-digit precision). src/application/
    metrics.py 호출 zero (5th ring isolation + informational only — AC9 비교
    informational).
    """
    snapshots = result.daily_snapshots
    if len(snapshots) < 2:
        return {
            "cagr_pct": Decimal("0"),
            "mdd_pct": Decimal("0"),
            "sharpe": Decimal("0"),
            "calmar": Decimal("0"),
        }

    values = [s.total_value for s in snapshots]
    initial = values[0]
    final = values[-1]
    n = len(values)

    # CAGR — exp(ln(final/initial) / years) - 1, percent
    years = Decimal(n - 1) / Decimal(252)
    if initial > 0 and final > 0 and years > 0:
        ratio = final / initial
        cagr_pct = ((ratio.ln() / years).exp() - Decimal(1)) * Decimal(100)
    else:
        cagr_pct = Decimal("0")

    # MDD — max drawdown over peak
    peak = values[0]
    max_dd = Decimal("0")
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
    mdd_pct = max_dd * Decimal(100)

    # Daily returns (simple, prev>0 only)
    daily_rets: list[Decimal] = []
    for prev, curr in zip(values[:-1], values[1:]):
        if prev > 0:
            daily_rets.append((curr - prev) / prev)

    # Sharpe — rf=0, annualized 252 (sample stdev, n-1)
    sharpe = Decimal("0")
    if len(daily_rets) >= 2:
        mean_r = sum(daily_rets, Decimal("0")) / Decimal(len(daily_rets))
        var = sum(((r - mean_r) ** 2 for r in daily_rets), Decimal("0")) / Decimal(
            len(daily_rets) - 1
        )
        std_r = var.sqrt()
        if std_r > 0:
            sharpe = mean_r / std_r * Decimal(252).sqrt()

    # Calmar — CAGR / |MDD|
    abs_mdd = abs(mdd_pct)
    calmar = cagr_pct / abs_mdd if abs_mdd > 0 else Decimal("0")

    return {
        "cagr_pct": cagr_pct,
        "mdd_pct": mdd_pct,
        "sharpe": sharpe,
        "calmar": calmar,
    }


def _serialize_result(result: _DGTBacktestResult) -> dict[str, object]:
    """Deterministic JSON serialization (AC15 reproducibility + AC9 metrics)."""
    metrics = _compute_metrics(result)
    return {
        "asset_fqn": result.asset.fqn,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "initial_capital": str(result.initial_capital.amount),
        "currency": result.initial_capital.currency.value,
        "final_cash": str(result.final_cash),
        "final_holdings": str(result.final_holdings),
        "final_close_price": str(result.final_close_price),
        "final_balance": str(result.final_balance.amount),
        "wallet_total": str(result.wallet_total),
        "reference_price": str(result.reference_price),
        "grid_levels": [str(level) for level in result.grid_levels],
        "trades_count": len(result.trades),
        "snapshots_count": len(result.daily_snapshots),
        "config_grid_count": (
            len(result.grid_levels) - 1 if result.grid_levels else 0
        ),
        "metrics": {
            "cagr_pct": str(metrics["cagr_pct"]),
            "mdd_pct": str(metrics["mdd_pct"]),
            "sharpe": str(metrics["sharpe"]),
            "calmar": str(metrics["calmar"]),
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="src.research.dgt.cli",
        description="Phase 0.11.a DGT informational backtest (ADR 0007 §1.10 AC8).",
    )
    parser.add_argument("--asset", required=True, help="Asset code (D3 default = 069500)")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--initial-capital",
        required=True,
        type=str,
        help="KRW amount (Decimal-safe str)",
    )
    parser.add_argument("--grid-levels", required=True, type=int, help="n (grid_count)")
    parser.add_argument(
        "--grid-spacing-pct",
        required=True,
        type=str,
        help="k as percent (Decimal-safe str, e.g. 5)",
    )
    parser.add_argument("--levels-above", type=int, default=0, help="m (default 0)")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data/historical/KRX_069500_2019-2024.csv"),
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.asset != "069500":
        raise SystemExit(
            f"D3 default = 069500 단독. Got '{args.asset}'. "
            "Override gated until ADR 0007 §1.3 D3 변경 박제."
        )

    asset = _build_asset_069500()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    bars = _load_ohlcv_csv(args.csv, asset, start, end)
    if not bars:
        raise SystemExit(f"No bars loaded from {args.csv} in [{start}, {end}]")

    config = _DGTConfig(
        grid_count=args.grid_levels,
        grid_spacing_pct=Decimal(args.grid_spacing_pct),
        levels_above=args.levels_above,
    )
    runner = _DGTPrototypeRunner(cost_model=_KoreanMarketCostModel(), config=config)
    result = runner.run(
        asset=asset,
        start=start,
        end=end,
        initial_capital=Money(amount=Decimal(args.initial_capital), currency=Currency.KRW),
        ohlcv=bars,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(_serialize_result(result), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
