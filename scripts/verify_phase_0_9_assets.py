"""Phase 0.9.c 사전 검증 — ADR 0005 §1.7.2 / §1.7.4 박제.

개별 주식 5 종 (Phase 0.9.1 = 2 종 + Phase 0.9.2 = 3 종 추가) 의
백테스트 데이터 가용성 + 거래 정지 일수 + 가격 이상치 (액면분할 후보
포함) 검증. Phase 0.7.3 패턴 (`verify_phase_0_7_3_data.py`) 정합. 본
스크립트는 1-회 검증 도구.

검증 대상 (ADR 0005 §1.6.2):
- Phase 0.9.1 : 005930 삼성전자 (반도체) + 005380 현대차 (자동차)
- Phase 0.9.2 : + 055550 신한지주 (금융) + 097950 CJ제일제당 (소비재)
                + 015760 한국전력 (에너지)

검증 윈도우: 2019-01-01 ~ 2024-12-30 (Phase 0.7.3 baseline 정합).
백테스트 시작: 2020-01-02. lookback: 246 거래일 (KRX 1 거래년).
KRX 영업일 표준: 069500 (KODEX 200) 거래일 (Phase 0.7 시리즈 일관).

본 스크립트는 1-회 검증 도구. CSV 저장 / 데이터 파일 생성 안 함 —
실제 다운로드는 0.9.g 책임. `listed_at` 절대 일자 박제는 0.9.d (Asset
모델 확장) 시점에 수동 박제 (DART / KRX 공식 자료) — 본 검증은
lookback 246 거래일 충족 여부만 확인.

Usage::

    uv run python scripts/verify_phase_0_9_assets.py

Output: 사람-읽기 표 (ADR 0005 §2 사전 검증 결과 박제용).
Exit code:
    0 — 5 종 모두 lookback 246 + 백테스트 데이터 충족 → 0.9.c PASS
    1 — 일부 자산 데이터 부족 → 사용자 결정 라운드 진입
"""
from __future__ import annotations

import sys
from datetime import date
from typing import NamedTuple

# ADR 0003 §16.5 — KRX 1 거래년 표준 (2026-05-04 갱신).
LOOKBACK_DAYS = 246

# Phase 0.7.3 baseline 윈도우 정합 (ADR 0005 §1.11).
WINDOW_START = date(2019, 1, 1)
WINDOW_END = date(2024, 12, 30)
BACKTEST_START = date(2020, 1, 2)

# KRX 영업일 표준 (Phase 0.7 시리즈 일관). 069500 가 5-year 가용 확인됨.
BENCHMARK_TICKER = "069500"
BENCHMARK_NAME = "KODEX 200"

# CLAUDE.md §5.2 — 전일 대비 ±30% 변동 의심 (액면분할 후보 포함).
PRICE_OUTLIER_THRESHOLD_PCT = 30.0

# 액면분할 후보 임계 (±40% 이상 = 분할 강한 추정).
SPLIT_CANDIDATE_THRESHOLD_PCT = 40.0

# ADR 0005 §1.6.2 박제 종목.
ASSETS: dict[str, tuple[str, str, str]] = {
    "005930": ("삼성전자", "반도체", "Phase 0.9.1"),
    "005380": ("현대차", "자동차", "Phase 0.9.1"),
    "055550": ("신한지주", "금융", "Phase 0.9.2"),
    "097950": ("CJ제일제당", "소비재", "Phase 0.9.2"),
    "015760": ("한국전력", "에너지", "Phase 0.9.2"),
}


class AssetMeasurement(NamedTuple):
    code: str
    name: str
    sector: str
    phase: str
    fetch_ok: bool
    error: str | None
    trading_days: int
    first_date: date | None
    last_date: date | None
    pre_backtest_days: int  # 2020-01-02 직전 거래일 수
    halts: list[date]  # benchmark 에 있고 asset 에 없는 일자
    outliers: list[tuple[date, float]]  # ±30% 변동


def fetch_benchmark_days() -> list[date]:
    """069500 거래일 = KRX 영업일 표준 (Phase 0.7 시리즈 일관)."""
    from pykrx import stock
    df = stock.get_market_ohlcv(
        WINDOW_START.strftime("%Y%m%d"),
        WINDOW_END.strftime("%Y%m%d"),
        BENCHMARK_TICKER,
    )
    if df is None or df.empty:
        raise RuntimeError(
            f"pykrx benchmark fetch 실패: {BENCHMARK_TICKER} ({BENCHMARK_NAME})"
        )
    return sorted(d.date() for d in df.index)


def measure_asset(
    code: str, name: str, sector: str, phase: str,
    benchmark_dates: set[date],
) -> AssetMeasurement:
    """1 종목 가용성 + 거래 정지 + outlier 측정."""
    try:
        from pykrx import stock
    except ImportError as e:
        return AssetMeasurement(
            code, name, sector, phase, False,
            f"pykrx import 실패: {e}",
            0, None, None, 0, [], [],
        )

    try:
        df = stock.get_market_ohlcv(
            WINDOW_START.strftime("%Y%m%d"),
            WINDOW_END.strftime("%Y%m%d"),
            code,
        )
    except Exception as e:
        return AssetMeasurement(
            code, name, sector, phase, False,
            f"pykrx fetch 실패: {type(e).__name__}: {e}",
            0, None, None, 0, [], [],
        )

    if df is None or df.empty:
        return AssetMeasurement(
            code, name, sector, phase, False,
            "pykrx 빈 결과 (해당 종목 미상장 또는 데이터 없음)",
            0, None, None, 0, [], [],
        )

    asset_dates_list = sorted(d.date() for d in df.index)
    asset_dates_set = set(asset_dates_list)
    pre_backtest = sum(1 for d in asset_dates_list if d < BACKTEST_START)

    # 거래 정지: benchmark 에 있고 asset 에 없는 일자 (단순화 — 거래 정지
    # 또는 데이터 누락 가능성 모두 포함).
    halts = sorted(benchmark_dates - asset_dates_set)

    # 가격 outlier: 종가 전일 대비 ±30% 변동 (액면분할 후보 포함).
    closes = df["종가"].astype(float)
    pct_change = closes.pct_change().dropna() * 100.0
    outliers = [
        (ts.date(), float(p))
        for ts, p in pct_change.items()
        if abs(float(p)) > PRICE_OUTLIER_THRESHOLD_PCT
    ]

    return AssetMeasurement(
        code, name, sector, phase, True, None,
        len(asset_dates_list), asset_dates_list[0], asset_dates_list[-1],
        pre_backtest, halts, outliers,
    )


def print_summary_table(measurements: list[AssetMeasurement]) -> None:
    """5 종 가용성 + lookback + 거래 정지 + outlier 요약 표."""
    header = (
        "Asset", "Sector", "Phase",
        "Fetch", "Total", "First", "Last", "Pre-BT",
        "Halts", "Outliers",
    )
    rows: list[tuple[str, ...]] = [header]
    for m in measurements:
        rows.append((
            f"{m.code} ({m.name})",
            m.sector, m.phase,
            "✓" if m.fetch_ok else "✗",
            str(m.trading_days),
            str(m.first_date) if m.first_date else "—",
            str(m.last_date) if m.last_date else "—",
            str(m.pre_backtest_days),
            str(len(m.halts)),
            str(len(m.outliers)),
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    sep_len = sum(widths) + 3 * len(widths) - 1
    print("=" * sep_len)
    print(f"개별 주식 5 종 가용성 ({WINDOW_START} ~ {WINDOW_END})")
    print("=" * sep_len)
    for ri, r in enumerate(rows):
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
        if ri == 0:
            print("-" * sep_len)


def print_detail_halts_outliers(measurements: list[AssetMeasurement]) -> None:
    """거래 정지 + outlier 상세 (액면분할 후보 표기)."""
    print()
    print("=" * 70)
    print(f"거래 정지 — benchmark {BENCHMARK_TICKER} ({BENCHMARK_NAME}) 에 있고 종목에 없는 일자")
    print("=" * 70)
    for m in measurements:
        if not m.fetch_ok:
            continue
        print(f"\n  {m.code} ({m.name}) — 정지 {len(m.halts)} 일")
        for d in m.halts[:10]:
            print(f"    {d}")
        if len(m.halts) > 10:
            print(f"    ... +{len(m.halts) - 10} more")

    print()
    print("=" * 70)
    print(
        f"가격 이상치 (CLAUDE.md §5.2 — |%Δclose| > {PRICE_OUTLIER_THRESHOLD_PCT}%) "
        f"+ 액면분할 후보 (|%Δclose| > {SPLIT_CANDIDATE_THRESHOLD_PCT}%)"
    )
    print("=" * 70)
    for m in measurements:
        if not m.fetch_ok:
            continue
        print(f"\n  {m.code} ({m.name}) — outlier {len(m.outliers)} 일")
        for d, p in m.outliers:
            tag = " ← 액면분할 후보" if abs(p) > SPLIT_CANDIDATE_THRESHOLD_PCT else ""
            print(f"    {d}: {p:+.2f}%{tag}")


def determine_verdict(measurements: list[AssetMeasurement]) -> tuple[int, str]:
    """exit code + 사람-읽기 verdict."""
    failed = [m.code for m in measurements if not m.fetch_ok]
    if failed:
        return 1, (
            f"FAIL — pykrx fetch 실패 자산: {failed}. "
            "사용자 결정 라운드 진입 (종목 교체 또는 Phase 0.9.2 종목 축소)."
        )
    insufficient = [
        (m.code, m.pre_backtest_days)
        for m in measurements if m.pre_backtest_days < LOOKBACK_DAYS
    ]
    if insufficient:
        return 1, (
            f"FAIL — lookback {LOOKBACK_DAYS} 미충족: {insufficient}. "
            "사용자 결정 라운드 진입."
        )
    return 0, (
        f"PASS — 5 종 모두 lookback {LOOKBACK_DAYS} + 백테스트 데이터 "
        "충족. ADR 0005 §2 박제 + sub-step 0.9.d 진입 가능."
    )


def main() -> int:
    print(
        f"Phase 0.9.c 사전 검증 — ADR 0005 §1.7.2 / §1.7.4 박제\n"
        f"검증 윈도우: {WINDOW_START} ~ {WINDOW_END} | "
        f"백테스트 시작: {BACKTEST_START}\n"
        f"lookback: {LOOKBACK_DAYS} 거래일 | "
        f"benchmark: {BENCHMARK_TICKER} ({BENCHMARK_NAME})"
    )
    print()

    print("[1/3] KRX 영업일 표준 (069500) 가져오기 ...")
    benchmark_days = fetch_benchmark_days()
    benchmark_set = set(benchmark_days)
    print(
        f"  069500 거래일: {len(benchmark_days)} 일 "
        f"({benchmark_days[0]} ~ {benchmark_days[-1]})"
    )
    print()

    print("[2/3] 5 종 OHLCV fetch + 거래 정지 + outlier 측정 ...")
    measurements = [
        measure_asset(code, *meta, benchmark_set)
        for code, meta in ASSETS.items()
    ]
    print()

    print("[3/3] 결과 요약")
    print()
    print_summary_table(measurements)
    print_detail_halts_outliers(measurements)

    code, verdict = determine_verdict(measurements)
    print()
    print("=" * 70)
    print(f"VERDICT (exit={code}): {verdict}")
    print("=" * 70)
    return code


if __name__ == "__main__":
    sys.exit(main())
