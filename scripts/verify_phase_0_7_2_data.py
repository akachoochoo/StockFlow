"""Phase 0.7.2.b.1 데이터 가용성 검증 — ADR 0003 §16.5.2 / §16.6 박제.

자본 배분 정책 비교 (균등 / 역변동성 / 정변동성) 의 σ 산출에 필요한
백테스트 시작일 (2020-01-02) 직전 252 거래일 lookback 데이터 가용성을
검증한다. look-ahead bias 회피용 (§16.5 default).

검증 대상:
1. 로컬 CSV (`data/historical/KRX_{069500,214980}_2020-2024.csv`) — 백테스트
   기간 데이터 (Phase 0.7.1 그대로 회귀 invariant 유지).
2. pykrx 2019-01-01 ~ 2019-12-30 데이터 — fallback 옵션 (a) "CSV 확장"
   채택 시 가용성 확인.

본 스크립트는 1-회 검증 도구. CSV 저장 / 데이터 파일 생성 안 함 —
실제 확장 다운로드는 §16.5.2 fallback (a) 채택 후 0.7.2.b.2 (또는
별도 0.7.2.b.3 선행 작업) 책임.

Usage::

    uv run python scripts/verify_phase_0_7_2_data.py

Exit code:
    0 — lookback 252 거래일 가용 (로컬 CSV 만으로 충족) → b.2 skip,
        b.3 진입 가능
    1 — 로컬 CSV 부족 + pykrx 2019 데이터 가용 → b.2 진입 (fallback
        (a) CSV 확장 추천)
    2 — 로컬 CSV 부족 + pykrx 2019 데이터 미가용 → b.2 진입 (fallback
        (b) σ 기간 단축 또는 (c) 시작일 조정)
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import pandas as pd


# ADR 0003 §16.5 default σ 산출 기간 — 1 거래년 표준.
LOOKBACK_DAYS = 252

# ADR 0003 §13.6.1 종목 (Phase 0.7.1 / 0.7.2 동일 — §16.3 종목 유지).
ASSETS = {
    "069500": "KODEX 200",
    "214980": "KODEX 단기채권 PLUS",
}

# Phase 0 / 0.5 / 0.7.1 백테스트 윈도우 (회귀 invariant 보존 — §16.5).
BACKTEST_START = date(2020, 1, 2)

# 로컬 CSV 위치 (data/historical/KRX_{code}_2020-2024.csv).
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"

# σ lookback 검증용 사전 윈도우 (백테스트 시작일 직전 약 1 거래년).
LOOKBACK_WINDOW_START = date(2019, 1, 1)
LOOKBACK_WINDOW_END = date(2019, 12, 30)


class CsvAvailability(NamedTuple):
    """로컬 CSV 가용성 측정 결과."""

    code: str
    name: str
    csv_path: Path
    csv_exists: bool
    first_date: date | None
    last_date: date | None
    trading_days: int
    has_2019_data: bool
    pre_backtest_days: int  # 2020-01-02 직전까지 가용 거래일 수


class PykrxAvailability(NamedTuple):
    """pykrx 2019 데이터 가용성 측정 결과."""

    code: str
    name: str
    fetch_ok: bool
    error: str | None
    trading_days_2019: int
    first_date_2019: date | None
    last_date_2019: date | None


def load_csv(path: Path) -> list[date]:
    """CSV 의 date 컬럼만 읽어 list[date] 반환. 첫 row 는 header 가정."""
    if not path.exists():
        return []
    dates: list[date] = []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            dates.append(date.fromisoformat(row["date"]))
    return sorted(dates)


def measure_csv(code: str, name: str) -> CsvAvailability:
    """로컬 CSV 가용성 측정."""
    csv_path = DATA_DIR / f"KRX_{code}_2020-2024.csv"
    if not csv_path.exists():
        return CsvAvailability(
            code=code,
            name=name,
            csv_path=csv_path,
            csv_exists=False,
            first_date=None,
            last_date=None,
            trading_days=0,
            has_2019_data=False,
            pre_backtest_days=0,
        )
    dates = load_csv(csv_path)
    if not dates:
        return CsvAvailability(
            code=code,
            name=name,
            csv_path=csv_path,
            csv_exists=True,
            first_date=None,
            last_date=None,
            trading_days=0,
            has_2019_data=False,
            pre_backtest_days=0,
        )
    pre_backtest_days = sum(1 for d in dates if d < BACKTEST_START)
    has_2019_data = any(d.year == 2019 for d in dates)
    return CsvAvailability(
        code=code,
        name=name,
        csv_path=csv_path,
        csv_exists=True,
        first_date=dates[0],
        last_date=dates[-1],
        trading_days=len(dates),
        has_2019_data=has_2019_data,
        pre_backtest_days=pre_backtest_days,
    )


def measure_pykrx(code: str, name: str) -> PykrxAvailability:
    """pykrx 2019-01-01 ~ 2019-12-30 OHLCV 가용성 측정.

    네트워크 의존이라 graceful 실패 처리. 실패 시 b.2 fallback 결정 시
    수동 검증 권고.
    """
    try:
        from pykrx import stock  # noqa: PLC0415 (graceful import)
    except ImportError as e:
        return PykrxAvailability(
            code=code,
            name=name,
            fetch_ok=False,
            error=f"pykrx import 실패: {e}",
            trading_days_2019=0,
            first_date_2019=None,
            last_date_2019=None,
        )

    start_yyyymmdd = LOOKBACK_WINDOW_START.strftime("%Y%m%d")
    end_yyyymmdd = LOOKBACK_WINDOW_END.strftime("%Y%m%d")

    try:
        df = stock.get_market_ohlcv(start_yyyymmdd, end_yyyymmdd, code)
    except Exception as e:  # noqa: BLE001 (네트워크 실패 graceful)
        return PykrxAvailability(
            code=code,
            name=name,
            fetch_ok=False,
            error=f"pykrx fetch 실패: {type(e).__name__}: {e}",
            trading_days_2019=0,
            first_date_2019=None,
            last_date_2019=None,
        )

    if df is None or df.empty:
        return PykrxAvailability(
            code=code,
            name=name,
            fetch_ok=False,
            error="pykrx 빈 결과 (해당 종목 2019년 미상장 또는 데이터 없음)",
            trading_days_2019=0,
            first_date_2019=None,
            last_date_2019=None,
        )

    dates = sorted(d.date() for d in df.index)
    return PykrxAvailability(
        code=code,
        name=name,
        fetch_ok=True,
        error=None,
        trading_days_2019=len(dates),
        first_date_2019=dates[0],
        last_date_2019=dates[-1],
    )


def print_csv_table(measurements: list[CsvAvailability]) -> None:
    """로컬 CSV 가용성 표."""
    header = (
        "Asset",
        "CSV exists",
        "First date",
        "Last date",
        "Total days",
        "2019 data?",
        "Pre-backtest days",
    )
    rows = [header]
    for m in measurements:
        rows.append(
            (
                f"{m.code} ({m.name})",
                "✓" if m.csv_exists else "✗",
                str(m.first_date) if m.first_date else "—",
                str(m.last_date) if m.last_date else "—",
                str(m.trading_days),
                "✓" if m.has_2019_data else "✗",
                str(m.pre_backtest_days),
            )
        )

    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    print("로컬 CSV 가용성 (data/historical/KRX_{code}_2020-2024.csv)")
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    for ri, r in enumerate(rows):
        line = "  ".join(c.ljust(widths[i]) for i, c in enumerate(r))
        print(line)
        if ri == 0:
            print("-" * (sum(widths) + 3 * len(widths) - 1))


def print_pykrx_table(measurements: list[PykrxAvailability]) -> None:
    """pykrx 2019 데이터 가용성 표."""
    header = (
        "Asset",
        "Fetch OK",
        "2019 trading days",
        "First date",
        "Last date",
        "Error",
    )
    rows = [header]
    for m in measurements:
        rows.append(
            (
                f"{m.code} ({m.name})",
                "✓" if m.fetch_ok else "✗",
                str(m.trading_days_2019),
                str(m.first_date_2019) if m.first_date_2019 else "—",
                str(m.last_date_2019) if m.last_date_2019 else "—",
                m.error or "",
            )
        )

    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    print()
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    print(
        f"pykrx 2019-01-01 ~ 2019-12-30 가용성 (fallback (a) CSV 확장 후보)"
    )
    print("=" * (sum(widths) + 3 * len(widths) - 1))
    for ri, r in enumerate(rows):
        line = "  ".join(c.ljust(widths[i]) for i, c in enumerate(r))
        print(line)
        if ri == 0:
            print("-" * (sum(widths) + 3 * len(widths) - 1))


def determine_verdict(
    csv_results: list[CsvAvailability],
    pykrx_results: list[PykrxAvailability],
) -> tuple[int, str]:
    """Exit code + 사람-읽기 verdict 판정.

    조건:
    - 모든 자산 lookback 252 거래일 충족 (pre_backtest_days >= 252) → 0
    - 로컬 부족 but 모든 자산 pykrx 2019 가용 (>= 252 거래일) → 1
    - 그 외 → 2
    """
    csv_ok = all(m.pre_backtest_days >= LOOKBACK_DAYS for m in csv_results)
    if csv_ok:
        return 0, (
            f"PASS — 로컬 CSV 만으로 lookback {LOOKBACK_DAYS} 거래일 충족. "
            "0.7.2.b.2 skip + 0.7.2.b.3 진입 가능."
        )

    pykrx_ok = all(
        m.fetch_ok and m.trading_days_2019 >= LOOKBACK_DAYS
        for m in pykrx_results
    )
    if pykrx_ok:
        return 1, (
            f"FALLBACK — 로컬 CSV 부족 (2019년 데이터 없음). pykrx 2019 "
            "데이터 모든 자산 가용. ADR §16.5.2 fallback (a) "
            "CSV 확장 추천 — 0.7.2.b.2 진입."
        )

    return 2, (
        "FALLBACK — 로컬 CSV 부족 + pykrx 2019 데이터 일부/전부 미가용. "
        "ADR §16.5.2 fallback (b) σ 기간 단축 또는 (c) 시작일 조정 "
        "사용자 명시 결정 필요 — 0.7.2.b.2 진입."
    )


def main() -> int:
    print(
        f"Phase 0.7.2.b.1 데이터 가용성 검증 — ADR 0003 §16.5.2 / §16.6 박제\n"
        f"백테스트 시작일: {BACKTEST_START} | lookback: {LOOKBACK_DAYS} 거래일"
    )
    print()

    csv_results = [measure_csv(code, name) for code, name in ASSETS.items()]
    print_csv_table(csv_results)

    pykrx_results = [
        measure_pykrx(code, name) for code, name in ASSETS.items()
    ]
    print_pykrx_table(pykrx_results)

    code, verdict = determine_verdict(csv_results, pykrx_results)
    print()
    print("=" * 70)
    print(f"VERDICT (exit={code}): {verdict}")
    print("=" * 70)

    return code


if __name__ == "__main__":
    raise SystemExit(main())
