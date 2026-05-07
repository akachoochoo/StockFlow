"""Download KR asset (ETF + KR_STOCK) OHLCV history via pykrx.

Phase 0.9 (sub-step 0.9.e — ADR 0005 §1.7 / §1.12 + §3 합병 박제). 박제
이전 ``scripts/download_kr_etf.py`` 를 일반화 — Phase 0.9 부터 ETF 외에
KR_STOCK (개별 주식) 도 지원.

핵심 변경:
- 이름: ``download_kr_etf.py`` → ``download_kr_assets.py`` (ADR 0005 §1.12 박제)
- ``--code`` (registry 통합) — `composition.asset_from_code(code)` 활용:
  Asset 메타데이터 (listed_at) 자동 검증 + 출력 경로 자동 산정.
  단순 ad-hoc 용도는 ``--ticker`` 그대로 사용 가능.
- ``adjusted=True`` 명시 (ADR 0005 §1.7.4 박제 — 액면분할 = 수정 종가).
  도메인 처리 zero (pykrx 가 자동 조정).

Pykrx wraps the public KRX disclosures endpoints — no API key, no auth,
only network. Output CSV matches the exact schema
``src.infrastructure.csv_market_data_loader`` expects so the file is
drop-in for ``trading backtest --csv``.

Phase 1 will swap this for the KIS API adapter; pykrx then becomes the
offline-replay / regression-fixture data source. Until that swap, this
script is the single point of network dependency in the project.

Usage::

    # registry 모드 (추천) — listed_at 자동 검증 + 출력 경로 자동 산정.
    uv run python scripts/download_kr_assets.py \\
        --code 069500 --start 2019-01-02 --end 2024-12-30
    uv run python scripts/download_kr_assets.py \\
        --code 005930 --start 2019-01-02 --end 2024-12-30
    uv run python scripts/download_kr_assets.py \\
        --code 005380 --start 2019-01-02 --end 2024-12-30

    # ad-hoc ticker 모드 (registry 미등록 종목 / one-shot 도구).
    uv run python scripts/download_kr_assets.py \\
        --ticker 069500 --start 2020-01-02 --end 2024-12-30 \\
        --out data/historical/KRX_069500_2020-2024.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from pykrx import stock

from src.infrastructure.asset_csv import (
    derive_csv_path,
    validate_asset_for_window,
)

if TYPE_CHECKING:
    from src.domain.models import Asset


def _parse_iso_date(s: str) -> date:
    """YYYY-MM-DD → date. argparse 시점 검증."""
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid YYYY-MM-DD date: {s!r} ({exc})"
        ) from exc


def resolve_target(
    *,
    code: str | None,
    ticker: str | None,
    out: Path | None,
    start: date,
    end: date,
) -> tuple[str, Path, Asset | None]:
    """Resolve (ticker, out_path, asset_or_none) from CLI args.

    Registry 모드 (`--code`): Asset 조회 + listed_at 검증 + 출력 경로
    자동 산정 (--out 미지정 시).
    Ad-hoc 모드 (`--ticker`): 검증 zero. --out 필수.

    Raises ValueError on invalid combinations or window violations.
    """
    if code is not None and ticker is not None:
        raise ValueError("--code 와 --ticker 동시 지정 불가; 하나만 사용")
    if code is None and ticker is None:
        raise ValueError("--code 또는 --ticker 중 하나는 필수")

    if code is not None:
        # Registry 모드 — 검증 + 자동 경로.
        from src.cli.composition import asset_from_code

        try:
            asset = asset_from_code(code)
        except KeyError as exc:
            raise ValueError(
                f"--code {code!r} 가 registry 미등록. "
                f"src/cli/composition.py 갱신 필요. ({exc})"
            ) from exc
        validate_asset_for_window(asset, start, end)
        out_path = out or derive_csv_path(code, start, end)
        return code, out_path, asset

    # Ad-hoc ticker 모드.
    assert ticker is not None  # narrow for type checker
    if out is None:
        raise ValueError("--ticker 모드에서는 --out 필수")
    return ticker, out, None


def download(
    start: date, end: date, ticker: str, out_path: Path,
) -> int:
    """Fetch [start, end] daily bars (수정 종가) and write the CSV.

    ``adjusted=True`` 명시 — 액면분할 자동 처리 (ADR 0005 §1.7.4 박제).

    Returns row count.
    """
    start_yyyymmdd = start.strftime("%Y%m%d")
    end_yyyymmdd = end.strftime("%Y%m%d")

    df = stock.get_market_ohlcv(
        start_yyyymmdd, end_yyyymmdd, ticker, adjusted=True,
    )
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
    parser.add_argument(
        "--start", required=True, type=_parse_iso_date,
        help="YYYY-MM-DD inclusive",
    )
    parser.add_argument(
        "--end", required=True, type=_parse_iso_date,
        help="YYYY-MM-DD inclusive",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--code",
        help=(
            "Registry-resolved KRX code (e.g. 069500 / 005930). Looks up "
            "Asset via composition.asset_from_code; validates listed_at; "
            "auto-derives --out path when not given."
        ),
    )
    group.add_argument(
        "--ticker",
        help=(
            "Ad-hoc KRX ticker — no registry validation. --out required. "
            "Use for one-shot tooling or codes not yet registered."
        ),
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help=(
            "Output CSV path; parent dirs are created. Required for "
            "--ticker; optional for --code (auto-derived if omitted)."
        ),
    )
    args = parser.parse_args()

    try:
        ticker, out_path, asset = resolve_target(
            code=args.code,
            ticker=args.ticker,
            out=args.out,
            start=args.start,
            end=args.end,
        )
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if asset is not None:
        sys.stderr.write(
            f"Resolved {asset.fqn} ({asset.name}, {asset.asset_class.value}, "
            f"listed_at={asset.listed_at}) → {out_path}\n"
        )

    n = download(args.start, args.end, ticker, out_path)
    print(f"Wrote {n} rows to {out_path}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
