"""Download a KR ETF OHLCV history via pykrx.

Phase 0 retrospective tooling. Pykrx wraps the public KRX disclosures
endpoints — no API key, no auth, only network. Output CSV matches the
exact schema ``src.infrastructure.csv_market_data_loader`` expects so
the file is drop-in for ``trading backtest --csv``.

Phase 1 will swap this for the KIS API adapter; pykrx then becomes the
offline-replay / regression-fixture data source. Until that swap, this
script is the single point of network dependency in the project.

Usage::

    uv run python scripts/download_kr_etf.py \\
        --ticker 069500 --start 2020-01-02 --end 2024-12-30 \\
        --out data/historical/KRX_069500_2020-2024.csv

    uv run python scripts/download_kr_etf.py \\
        --ticker 214980 --start 2020-01-02 --end 2024-12-30 \\
        --out data/historical/KRX_214980_2020-2024.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from pykrx import stock


def download(
    start: str, end: str, ticker: str, out_path: Path
) -> int:
    """Fetch [start, end] daily bars and write the CSV. Returns row count."""
    start_yyyymmdd = start.replace("-", "")
    end_yyyymmdd = end.replace("-", "")

    df = stock.get_market_ohlcv(start_yyyymmdd, end_yyyymmdd, ticker)
    if df is None or df.empty:
        sys.stderr.write(
            f"pykrx returned no rows for {ticker} in [{start}, {end}].\n"
        )
        return 0

    # pykrx column names are Korean: 시가/고가/저가/종가/거래량/등락률.
    # Coerce all numerics to int (KRX prices/volumes are whole units),
    # then validate OHLC consistency before writing — bad rows during a
    # corp-action cutover would otherwise cascade into the loader's
    # pydantic validator and abort the backtest much later.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for trade_date, row in df.iterrows():
            o = int(row["시가"])
            h = int(row["고가"])
            low_ = int(row["저가"])
            c = int(row["종가"])
            v = int(row["거래량"])
            if not (low_ <= o <= h and low_ <= c <= h):
                sys.stderr.write(
                    f"Skipping {trade_date}: OHLC inconsistency "
                    f"(o={o} h={h} l={low_} c={c}).\n"
                )
                continue
            writer.writerow([
                trade_date.strftime("%Y-%m-%d"), o, h, low_, c, v,
            ])
            rows_written += 1
    return rows_written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    parser.add_argument(
        "--ticker", required=True,
        help="KRX ticker (e.g. 069500 for KODEX 200, 214980 for KODEX 단기채권 PLUS).",
    )
    parser.add_argument(
        "--out", required=True, type=Path,
        help="Output CSV path; parent dirs are created.",
    )
    args = parser.parse_args()

    n = download(args.start, args.end, args.ticker, args.out)
    print(f"Wrote {n} rows to {args.out}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
