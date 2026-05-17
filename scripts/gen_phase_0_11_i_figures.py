"""Phase 0.11.i figure 박제 helper.

Bypasses pykrx by loading OHLCV from CSV and calling kakao_dgt_backtest
render functions directly. Produces:
  1. Static comparison PNG (박제 path proof via _render_comparison_chart)
  2. Interactive report.html (lightweight-charts default path)

Usage:
    uv run python scripts/gen_phase_0_11_i_figures.py
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
    OHLCV,
)
from src.research.dgt.kakao_dgt_backtest import (
    _run_paper,
    _run_paper_adaptive,
    _run_buy_and_hold,
    _render_comparison_chart,
    _render_html_report,
)
from src.research.dgt.runner import _DGTConfig

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CODE = "069500"
ASSET_NAME = "KODEX 200"
START = date(2020, 1, 2)
END = date(2024, 12, 30)
CSV_PATH = Path("data/historical/KRX_069500_2019-2024.csv")
OUTPUT_DIR = Path("reports/kakao-dgt/")
FIGURES_DIR = Path("docs/retrospectives/figures/phase-0.11.i/")
INITIAL_CAPITAL = Decimal("10000000")


def _build_asset_from_csv() -> Asset:
    return Asset(
        code=CODE,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name=ASSET_NAME,
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2000, 1, 1),
    )


def _load_ohlcv_csv(path: Path, asset: Asset, start: date, end: date) -> list[OHLCV]:
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


def main() -> int:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    asset = _build_asset_from_csv()
    capital = Money(amount=INITIAL_CAPITAL, currency=Currency.KRW)

    print(f"Loading OHLCV from {CSV_PATH} [{START} ~ {END}] ...")
    bars = _load_ohlcv_csv(CSV_PATH, asset, START, END)
    print(f"  loaded {len(bars)} bars")

    base_cfg = _DGTConfig(
        grid_count=11,
        grid_spacing_pct=Decimal("3"),
        levels_above=5,  # n//2 = 11//2 = 5
    )

    from decimal import Decimal as D
    _adp_base = {
        "multiplier": D("1.0"), "k_min": D("0.005"), "k_max": D("0.05"),
        "rebalance_mode": "daily", "volatility_measure": "adr",
    }
    _vol_cfg = {
        **_adp_base, "volume_gate": True,
        "volume_gate_period": 10, "volume_gate_multiplier": D("1.5"),
    }

    results = []
    variant_configs = []

    print("Running ADR-Base ...")
    r_base = _run_paper_adaptive(asset, base_cfg, capital, bars, START, END, **_adp_base)
    results.append(("ADR-Base", r_base))
    variant_configs.append(base_cfg)

    print("Running ADR+Vol ...")
    r_vol = _run_paper_adaptive(asset, base_cfg, capital, bars, START, END, **_vol_cfg)
    results.append(("ADR+Vol", r_vol))
    variant_configs.append(base_cfg)

    print("Running B&H-100% ...")
    r_bh = _run_buy_and_hold(asset, capital, bars, START, END, Decimal("100"))
    results.append(("B&H-100%", r_bh))
    variant_configs.append(base_cfg)

    bars_map = {CODE: bars}

    # 1. Static comparison chart PNG (박제 path proof)
    print("\nRendering static comparison chart PNG (박제 path) ...")
    chart_png = _render_comparison_chart(
        results, bars, base_cfg, configs_per_result=variant_configs,
    )
    static_png_path = FIGURES_DIR / "phase-0.11.i_static_comparison_069500.png"
    static_png_path.write_bytes(chart_png)
    print(f"  Saved: {static_png_path}")

    # 2. Interactive report.html (default lightweight-charts path)
    print("Generating interactive report.html ...")
    report_path = FIGURES_DIR / "phase-0.11.i_interactive_report_069500.html"
    _render_html_report(
        results, base_cfg, chart_png, report_path,
        per_stock_charts={},
        assets=None,
        bars_map=bars_map,
        static_charts=False,  # interactive (default)
    )
    print(f"  Saved: {report_path}")

    # Also write to reports/kakao-dgt/ for reference
    report_ref = OUTPUT_DIR / "report.html"
    _render_html_report(
        results, base_cfg, chart_png, report_ref,
        per_stock_charts={},
        assets=None,
        bars_map=bars_map,
        static_charts=False,
    )
    print(f"  Also saved: {report_ref}")

    print("\nFigures:")
    print(f"  1. Static PNG:           {static_png_path}")
    print(f"  2. Interactive HTML:     {report_path}")
    print("\nNote: Browser screenshot not possible in headless env.")
    print("      Interactive HTML saved directly as figure evidence per plan §6 fallback.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
