"""Phase 0.7.3.b.1 데이터 가용성 검증 — ADR 0003 §18.6 / §18.8 박제.

종목 다양화 (3 종) lookback + 백테스트 데이터 가용성 검증. Phase 0.7.2.b.1
패턴 정합 (`verify_phase_0_7_2_data.py`). 본 스크립트는 1-회 검증 도구.

검증 대상:
1. **069500** (KODEX 200) — Phase 0.7.1 / 0.7.2 그대로. 데이터 보존 확인.
2. **132030** (KODEX 골드선물(H)) — Phase 0.7.3 신규. pykrx 가용성 확인.
3. **329200** (TIGER 부동산인프라고배당) — Phase 0.7.3 신규. pykrx 가용성
   확인.

각 자산 검증 윈도우: 2019-01-02 ~ 2024-12-30 (lookback 246 거래일 +
백테스트 1231 거래일 = 1477 거래일 예상).

Usage::

    uv run python scripts/verify_phase_0_7_3_data.py

Exit code:
    0 — 모든 자산 lookback + 백테스트 데이터 충족 → 0.7.3.b.2 skip,
        b.3 진입 가능
    1 — 일부 자산 데이터 부족 → b.2 fallback 결정 라운드 진입
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import NamedTuple

# ADR §16.5 — KRX 1 거래년 표준 (NYSE 252 → KRX 246, 2026-05-04 갱신).
LOOKBACK_DAYS = 246

# ADR §18.2 종목 3 종 (Phase 0.7.3 채택).
ASSETS = {
    "069500": "KODEX 200",
    "132030": "KODEX 골드선물(H)",
    "329200": "TIGER 부동산인프라고배당",
}

# 백테스트 + lookback 윈도우 (Phase 0.7.2 와 동일).
WINDOW_START = date(2019, 1, 1)
WINDOW_END = date(2024, 12, 30)
BACKTEST_START = date(2020, 1, 2)

# 로컬 CSV 위치 (069500 만 기존 보유).
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"


class CsvAvailability(NamedTuple):
    code: str
    name: str
    csv_path: Path
    csv_exists: bool
    first_date: date | None
    last_date: date | None
    trading_days: int


class PykrxAvailability(NamedTuple):
    code: str
    name: str
    fetch_ok: bool
    error: str | None
    trading_days: int
    first_date: date | None
    last_date: date | None
    pre_backtest_days: int  # 2020-01-02 직전까지 거래일 수


def measure_csv(code: str, name: str) -> CsvAvailability:
    csv_path = DATA_DIR / f"KRX_{code}_2019-2024.csv"
    if not csv_path.exists():
        return CsvAvailability(code, name, csv_path, False, None, None, 0)
    dates: list[date] = []
    with csv_path.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            dates.append(date.fromisoformat(row["date"]))
    dates.sort()
    return CsvAvailability(
        code, name, csv_path, True,
        dates[0] if dates else None,
        dates[-1] if dates else None,
        len(dates),
    )


def measure_pykrx(code: str, name: str) -> PykrxAvailability:
    """pykrx 2019-01-01 ~ 2024-12-30 OHLCV 가용성 + 백테스트 직전 거래일 수."""
    try:
        from pykrx import stock
    except ImportError as e:
        return PykrxAvailability(
            code, name, False, f"pykrx import 실패: {e}", 0, None, None, 0,
        )

    start_yyyymmdd = WINDOW_START.strftime("%Y%m%d")
    end_yyyymmdd = WINDOW_END.strftime("%Y%m%d")

    try:
        df = stock.get_market_ohlcv(start_yyyymmdd, end_yyyymmdd, code)
    except Exception as e:
        return PykrxAvailability(
            code, name, False,
            f"pykrx fetch 실패: {type(e).__name__}: {e}",
            0, None, None, 0,
        )

    if df is None or df.empty:
        return PykrxAvailability(
            code, name, False,
            "pykrx 빈 결과 (해당 종목 미상장 또는 데이터 없음)",
            0, None, None, 0,
        )

    dates = sorted(d.date() for d in df.index)
    pre_backtest = sum(1 for d in dates if d < BACKTEST_START)
    return PykrxAvailability(
        code, name, True, None,
        len(dates), dates[0], dates[-1], pre_backtest,
    )


def print_csv_table(measurements: list[CsvAvailability]) -> None:
    header = ("Asset", "CSV exists", "First date", "Last date", "Total days")
    rows = [header]
    for m in measurements:
        rows.append((
            f"{m.code} ({m.name})",
            "✓" if m.csv_exists else "✗",
            str(m.first_date) if m.first_date else "—",
            str(m.last_date) if m.last_date else "—",
            str(m.trading_days),
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    print("로컬 CSV 가용성 (data/historical/KRX_{code}_2019-2024.csv)")
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    for ri, r in enumerate(rows):
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
        if ri == 0:
            print("-" * (sum(widths) + 3 * len(widths) - 1))


def print_pykrx_table(measurements: list[PykrxAvailability]) -> None:
    header = (
        "Asset", "Fetch OK", "Total days", "First date", "Last date",
        "Pre-backtest", "Error",
    )
    rows = [header]
    for m in measurements:
        rows.append((
            f"{m.code} ({m.name})",
            "✓" if m.fetch_ok else "✗",
            str(m.trading_days),
            str(m.first_date) if m.first_date else "—",
            str(m.last_date) if m.last_date else "—",
            str(m.pre_backtest_days),
            m.error or "",
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    print()
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    print(f"pykrx 가용성 ({WINDOW_START} ~ {WINDOW_END})")
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    for ri, r in enumerate(rows):
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
        if ri == 0:
            print("-" * (sum(widths) + 3 * len(widths) - 1))


def determine_verdict(pykrx: list[PykrxAvailability]) -> tuple[int, str]:
    all_fetch_ok = all(m.fetch_ok for m in pykrx)
    if not all_fetch_ok:
        failed = [m.code for m in pykrx if not m.fetch_ok]
        return 1, (
            f"FAIL — pykrx fetch 실패 자산: {failed}. "
            "0.7.3.b.2 fallback 결정 라운드 진입."
        )
    all_lookback_ok = all(
        m.pre_backtest_days >= LOOKBACK_DAYS for m in pykrx
    )
    if not all_lookback_ok:
        insufficient = [
            (m.code, m.pre_backtest_days)
            for m in pykrx if m.pre_backtest_days < LOOKBACK_DAYS
        ]
        return 1, (
            f"FAIL — lookback {LOOKBACK_DAYS} 미충족: {insufficient}. "
            "0.7.3.b.2 fallback 결정 라운드 진입."
        )
    return 0, (
        f"PASS — 모든 자산 lookback {LOOKBACK_DAYS} + 백테스트 데이터 "
        "충족. 0.7.3.b.2 skip + 0.7.3.b.3 다운로드 진입 가능."
    )


def main() -> int:
    print(
        f"Phase 0.7.3.b.1 데이터 가용성 검증 — ADR 0003 §18.6 / §18.8 박제\n"
        f"백테스트 시작일: {BACKTEST_START} | lookback: {LOOKBACK_DAYS} 거래일"
    )
    print()

    csv_results = [measure_csv(code, name) for code, name in ASSETS.items()]
    print_csv_table(csv_results)

    pykrx_results = [
        measure_pykrx(code, name) for code, name in ASSETS.items()
    ]
    print_pykrx_table(pykrx_results)

    code, verdict = determine_verdict(pykrx_results)
    print()
    print("=" * 70)
    print(f"VERDICT (exit={code}): {verdict}")
    print("=" * 70)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
