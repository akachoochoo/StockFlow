"""Phase 0.7.1.d 사전 검증 — ADR 0003 §13.4 박제.

KOSEF 미국 S&P500 (139260) 의 5 년 OHLCV pykrx 가용성 + KODEX 200
(069500) 와의 일별 close-to-close return Pearson 상관계수 측정.

본 스크립트는 1-회 검증 도구. CSV 저장 / 데이터 파일 생성 안 함 —
실제 다운로드는 0.7.1.f 책임.

Usage::

    uv run python scripts/verify_phase_0_7_1_assets.py
    uv run python scripts/verify_phase_0_7_1_assets.py --start 2020-01-02 --end 2024-12-30

Output: 사람-읽기 표 (ADR §13.4 결과 박제용).
Exit code:
    0 — pearson_r < threshold → PASS, 0.7.1.e 진입 가능
    1 — pearson_r >= threshold → FALLBACK (사용자 결정 라운드)
"""
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from pykrx import stock

if TYPE_CHECKING:
    import pandas as pd


# ADR 0003 §13.2 fallback threshold (근거는 §13.4 결과 항목에 박제).
CORRELATION_THRESHOLD = 0.5

# ADR 0003 §13.1 박제 종목.
ASSET_KODEX_200 = "069500"
ASSET_KOSEF_SP500 = "139260"

# CLAUDE.md §5.2 — 전일 대비 ±30 % 변동 의심.
PRICE_OUTLIER_THRESHOLD_PCT = 30.0

# Phase 0 / 0.5 백테스트 윈도우 (동일 비교 가능 보장).
DEFAULT_START = "2020-01-02"
DEFAULT_END = "2024-12-30"


def fetch_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """pykrx 일별 OHLCV. 빈 결과는 RuntimeError 로 즉시 fail-fast."""
    start_yyyymmdd = start.replace("-", "")
    end_yyyymmdd = end.replace("-", "")
    df = stock.get_market_ohlcv(start_yyyymmdd, end_yyyymmdd, ticker)
    if df is None or df.empty:
        raise RuntimeError(
            f"pykrx returned no rows for {ticker} in [{start}, {end}]"
        )
    return df


def trading_day_alignment(
    df_a: pd.DataFrame, df_b: pd.DataFrame,
) -> tuple[set, set, set]:
    """(only_in_a, only_in_b, in_both)."""
    days_a = set(df_a.index)
    days_b = set(df_b.index)
    return (days_a - days_b, days_b - days_a, days_a & days_b)


def detect_price_outliers(
    df: pd.DataFrame, threshold_pct: float,
) -> list[tuple[str, float]]:
    """전일 대비 |close pct change| > threshold 일자 (CLAUDE.md §5.2)."""
    closes = df["종가"].astype(float)
    pct_change = closes.pct_change().dropna() * 100.0
    return [
        (ts.strftime("%Y-%m-%d"), float(p))
        for ts, p in pct_change.items()
        if abs(float(p)) > threshold_pct
    ]


def pearson_correlation_close_returns(
    df_a: pd.DataFrame, df_b: pd.DataFrame,
) -> tuple[float, int]:
    """일별 close-to-close return Pearson 상관계수 + N (양 종목 모두 있는 일자만)."""
    closes_a = df_a["종가"].astype(float)
    closes_b = df_b["종가"].astype(float)
    common_dates = closes_a.index.intersection(closes_b.index)
    a_common = closes_a.loc[common_dates].sort_index()
    b_common = closes_b.loc[common_dates].sort_index()
    returns_a = a_common.pct_change().dropna()
    returns_b = b_common.pct_change().dropna()
    common_returns = returns_a.index.intersection(returns_b.index)
    return (
        float(returns_a.loc[common_returns].corr(returns_b.loc[common_returns])),
        len(common_returns),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", default=DEFAULT_START, help="YYYY-MM-DD inclusive")
    parser.add_argument("--end", default=DEFAULT_END, help="YYYY-MM-DD inclusive")
    args = parser.parse_args()

    print("=== Phase 0.7.1.d 사전 검증 — ADR 0003 §13.4 ===")
    print(f"Window: {args.start} ~ {args.end}")
    print()

    # [1] OHLCV fetch
    print("[1/4] pykrx OHLCV fetch")
    df_kodex = fetch_ohlcv(ASSET_KODEX_200, args.start, args.end)
    df_kosef = fetch_ohlcv(ASSET_KOSEF_SP500, args.start, args.end)
    print(f"  069500 (KODEX 200):          {len(df_kodex):>5} trading days")
    print(f"  139260 (KOSEF 미국 S&P500):  {len(df_kosef):>5} trading days")
    print()

    # [2] Trading day alignment
    print("[2/4] Trading day alignment (KR 거래소 동일 calendar 검증)")
    only_kodex, only_kosef, in_both = trading_day_alignment(df_kodex, df_kosef)
    print(f"  Only in 069500: {len(only_kodex):>5}")
    print(f"  Only in 139260: {len(only_kosef):>5}")
    print(f"  In both:        {len(in_both):>5}")
    if only_kodex:
        sample = sorted(only_kodex)[:5]
        print(f"    sample only-069500: {[d.strftime('%Y-%m-%d') for d in sample]}")
    if only_kosef:
        sample = sorted(only_kosef)[:5]
        print(f"    sample only-139260: {[d.strftime('%Y-%m-%d') for d in sample]}")
    print()

    # [3] Price outlier detection
    print(f"[3/4] Price outlier (CLAUDE.md §5.2 — |%Δclose| > {PRICE_OUTLIER_THRESHOLD_PCT}%)")
    outliers_kodex = detect_price_outliers(df_kodex, PRICE_OUTLIER_THRESHOLD_PCT)
    outliers_kosef = detect_price_outliers(df_kosef, PRICE_OUTLIER_THRESHOLD_PCT)
    print(f"  069500 outliers: {len(outliers_kodex)}")
    for date, pct in outliers_kodex:
        print(f"    {date}: {pct:+.2f}%")
    print(f"  139260 outliers: {len(outliers_kosef)}")
    for date, pct in outliers_kosef:
        print(f"    {date}: {pct:+.2f}%")
    print()

    # [4] Pearson correlation
    print("[4/4] Pearson correlation (close-to-close return)")
    corr, n_obs = pearson_correlation_close_returns(df_kodex, df_kosef)
    print(f"  pearson_r(069500, 139260) = {corr:.4f}")
    print(f"  N observations:           {n_obs}")
    print()

    # Verdict
    print(f"=== Verdict (ADR §13.2 — threshold = {CORRELATION_THRESHOLD}) ===")
    if corr < CORRELATION_THRESHOLD:
        print(f"  pearson_r = {corr:.4f} < {CORRELATION_THRESHOLD} — PASS, 0.7.1.e 진입 가능")
        return 0
    print(f"  pearson_r = {corr:.4f} >= {CORRELATION_THRESHOLD} — FALLBACK")
    print("  사용자 결정 라운드 #3 트리거 (ADR §13.6 박제 필요)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
