"""CSV market data loader.

Per ADR §10.2, loads daily OHLCV bars from a standard CSV format:

    date,open,high,low,close,volume
    2026-01-05,35000,35100,34900,35050,1234567
    ...

Used by both the backtest and paper trading CLI commands so the same
deterministic data feed serves both flows. Numeric strings are passed
directly to ``Decimal`` (CLAUDE.md §2.3 — never via float). The OHLCV
domain model enforces OHLC consistency at construction.

A pykrx-based downloader lives separately in ``scripts/download_kr_assets.py``
(ADR 0005 §1.12 + §3 박제 — Phase 0.9 부터 ETF + KR_STOCK 양쪽 지원).
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from src.domain.models import OHLCV

if TYPE_CHECKING:
    from src.domain.models import Asset


_REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume")


def load_ohlcv_csv(path: Path | str, asset: Asset) -> list[OHLCV]:
    """Read OHLCV bars from ``path`` for ``asset``.

    Returns the bars sorted ascending by ``trade_date``. Empty file (header
    only or no header) returns ``[]`` — the caller decides whether an empty
    result is acceptable for its workflow.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ValueError: header missing, required columns missing, duplicate
            ``trade_date``, or unparsable numeric value.
        pydantic.ValidationError: OHLC integrity violated (high < low,
            close outside [low, high], etc.) — surfaced from the OHLCV
            model_validator.
    """
    csv_path = Path(path)
    bars: list[OHLCV] = []
    seen_dates: set[date] = set()
    with csv_path.open("r", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return []
        missing = [c for c in _REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ValueError(
                f"CSV {csv_path} missing required columns: {missing}"
            )
        # row_idx starts at 2 because line 1 is the header.
        for row_idx, row in enumerate(reader, start=2):
            try:
                trade_date = date.fromisoformat(row["date"])
            except ValueError as e:
                raise ValueError(
                    f"CSV {csv_path} line {row_idx}: bad date {row['date']!r}"
                ) from e
            if trade_date in seen_dates:
                raise ValueError(
                    f"CSV {csv_path} line {row_idx}: "
                    f"duplicate trade_date {trade_date}"
                )
            seen_dates.add(trade_date)
            try:
                bar = OHLCV(
                    asset=asset,
                    trade_date=trade_date,
                    open=Decimal(row["open"]),
                    high=Decimal(row["high"]),
                    low=Decimal(row["low"]),
                    close=Decimal(row["close"]),
                    volume=Decimal(row["volume"]),
                )
            except InvalidOperation as e:
                raise ValueError(
                    f"CSV {csv_path} line {row_idx}: bad numeric value ({e})"
                ) from e
            bars.append(bar)
    bars.sort(key=lambda b: b.trade_date)
    return bars
