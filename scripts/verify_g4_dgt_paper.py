#!/usr/bin/env python
"""G4 검증 — DGT(GridRunner) vs Buy&Hold MDD 방어 실증 (ADR 0022 G4).

live 주문 배선이 별도 승인 게이트로 연기됨에 따라, G4 의 backtest 프록시.
승격된 도메인 엔진(`GridRunner`)을 여러 종목 x 국면(강세/약세/횡보/전체)에서
구동해 DGT 와 Buy&Hold 의 return / MDD / CAGR / Sharpe / Calmar 를 정량 비교한다.

판정 가설 (D2 / Q4): DGT 는 **MDD 를 B&H 대비 유의하게 방어**하고 risk-adjusted
(Calmar) 가 크게 열위가 아니어야 한다. 강세장 절대수익 B&H 미달은 수용된 trade-off.

1-회 검증 도구 (verify_phase_0_9_assets.py 패턴). Decimal=money, float=비율 통계.

Usage::
    uv run python scripts/verify_g4_dgt_paper.py
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.cli.composition import asset_from_code  # noqa: E402
from src.domain.models import OHLCV, Currency, Money  # noqa: E402
from src.domain.strategies.grid import GridConfig  # noqa: E402
from src.infrastructure.csv_market_data_loader import load_ohlcv_csv  # noqa: E402
from src.use_cases.grid_runner import GridRunner  # noqa: E402

_CAPITAL = Money(amount=Decimal("25000000"), currency=Currency.KRW)  # D8 ~2,500만원
_TRADING_DAYS = 252

# 종목: ETF 우선(D8 = 저가 ETF). 주식 일부 포함(breadth).
_ASSETS = {
    "069500": "data/historical/KRX_069500_2019-2024.csv",  # KODEX 200 (ETF)
    "132030": "data/historical/KRX_132030_2019-2024.csv",  # KODEX 골드 (ETF)
    "005930": "data/historical/KRX_005930_2019-2024.csv",  # 삼성전자 (STOCK)
}

# 국면 윈도우 (KOSPI 200 기준 근사).
_WINDOWS = {
    "전체(19-24)": (date(2019, 1, 2), date(2024, 12, 30)),
    "강세(20.3-21.6)": (date(2020, 3, 19), date(2021, 6, 30)),
    "약세(2022)": (date(2022, 1, 1), date(2022, 12, 30)),
    "횡보(23-24)": (date(2023, 1, 1), date(2024, 12, 30)),
}


def _optimal_config() -> GridConfig:
    return GridConfig(
        grid_count=11,
        fallback_k=Decimal("0.05"),
        rebalance_mode="daily",
        volatility_measure="adr",
        atr_period=14,
        multiplier=Decimal("1.0"),
        k_min=Decimal("0.005"),
        k_max=Decimal("0.05"),
        volume_gate=True,
        volume_gate_period=10,
        volume_gate_multiplier=Decimal("1.5"),
    )


@dataclass
class _Metrics:
    total_return_pct: float
    cagr_pct: float
    mdd_pct: float
    sharpe: float
    calmar: float
    trades: int


def _metrics(values: list[Decimal], init: Decimal, days: int, trades: int) -> _Metrics:
    fv = float(values[-1])
    iv = float(init)
    total_return = (fv - iv) / iv
    years = max(days / _TRADING_DAYS, 1e-9)
    cagr = (fv / iv) ** (1 / years) - 1 if fv > 0 else -1.0
    # MDD
    peak = float(values[0])
    mdd = 0.0
    for v in values:
        fvv = float(v)
        peak = max(peak, fvv)
        if peak > 0:
            mdd = min(mdd, (fvv - peak) / peak)
    # Sharpe (일간 수익률, 무위험 0 가정)
    rets = [
        float(values[i]) / float(values[i - 1]) - 1
        for i in range(1, len(values))
        if float(values[i - 1]) > 0
    ]
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std) * math.sqrt(_TRADING_DAYS) if std > 0 else 0.0
    else:
        sharpe = 0.0
    calmar = cagr / abs(mdd) if mdd < 0 else float("inf")
    return _Metrics(total_return * 100, cagr * 100, mdd * 100, sharpe, calmar, trades)


def _bh_values(window: list[OHLCV], init: Decimal) -> list[Decimal]:
    first = window[0].close
    shares = (init / first).to_integral_value(rounding="ROUND_DOWN")
    cash = init - shares * first
    return [cash + shares * b.close for b in window]


def _run(code: str, csv: str) -> None:
    asset = asset_from_code(code)
    bars = load_ohlcv_csv(_REPO_ROOT / csv, asset)
    print(f"\n{'=' * 78}\n{asset.fqn} ({asset.name})\n{'=' * 78}")
    header = (
        f"{'국면':16}{'엔진':8}{'수익%':>9}{'CAGR%':>9}"
        f"{'MDD%':>9}{'Sharpe':>8}{'Calmar':>8}{'거래':>6}"
    )
    print(header)
    print("-" * 78)
    for label, (start, end) in _WINDOWS.items():
        window = [b for b in bars if start <= b.trade_date <= end]
        if len(window) < 30:
            print(f"{label:16}(데이터 부족: {len(window)})")
            continue
        result = GridRunner(cost_model=None).run(
            asset=asset, bars=window, config=_optimal_config(), initial_capital=_CAPITAL
        )
        dgt_vals = [d.total_value for d in result.daily_values]
        dgt = _metrics(dgt_vals, _CAPITAL.amount, len(window), len(result.trades))
        bh_vals = _bh_values(window, _CAPITAL.amount)
        bh = _metrics(bh_vals, _CAPITAL.amount, len(window), 0)
        _print_row(label, "DGT", dgt)
        _print_row("", "B&H", bh)
        verdict = "✅ MDD 방어" if dgt.mdd_pct > bh.mdd_pct else "❌ MDD 열위"
        print(f"{'':16}→ {verdict} (DGT {dgt.mdd_pct:.1f}% vs B&H {bh.mdd_pct:.1f}%)")
        print("-" * 78)


def _print_row(label: str, engine: str, m: _Metrics) -> None:
    print(
        f"{label:16}{engine:8}{m.total_return_pct:>9.2f}{m.cagr_pct:>9.2f}"
        f"{m.mdd_pct:>9.2f}{m.sharpe:>8.2f}{m.calmar:>8.2f}{m.trades:>6}"
    )


def main() -> int:
    print("G4 검증 — DGT(GridRunner) vs Buy&Hold (자본 25,000,000 KRW/종목, 최적 구성)")
    print("판정: DGT 는 MDD 를 B&H 대비 방어하는가? (강세장 절대수익 미달은 D2 수용)")
    for code, csv in _ASSETS.items():
        _run(code, csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
