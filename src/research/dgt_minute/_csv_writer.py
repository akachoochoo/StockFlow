"""분봉 CSV writer/reader — `_MinuteBar` ↔ CSV file.

ADR 0023 §10.1 / 세그먼트 1.2.1.b.3 산출. schema.md §7 (CSV 저장 형식) spec
정합.

저장 형식:
- 헤더: `trade_date,trade_time,open,high,low,close,volume`
- 행: `YYYY-MM-DD,HH:MM:SS,<Decimal str>,<Decimal str>,<Decimal str>,<Decimal str>,<int>`
- Ascending order by `(trade_date, trade_time)` (KIS descending → 저장 ascending).
- Decimal `str(v)` round-trip 안전 (CLAUDE.md §2.3 float 경유 zero).

원자성 (CLAUDE.md §10 정신):
- `_write_minute_csv` = atomic `tmp + rename` (manifest 와 동일 패턴, §_manifest).
- 부분 쓰기 시 기존 파일 보존, 다음 cron 에서 재시도.
"""
from __future__ import annotations

import csv
from datetime import date, time
from decimal import Decimal
from pathlib import Path  # noqa: TC003  -- runtime use in _write_/_read_

from src.research.dgt_minute._kis_minute_downloader import _MinuteBar

_CSV_HEADER: tuple[str, ...] = (
    "trade_date",
    "trade_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


def _write_minute_csv(bars: list[_MinuteBar], path: Path) -> None:
    """ascending `_MinuteBar` 시계열 → CSV (atomic).

    - Empty `bars` → 파일 미작성 (no-op). 호출자 (storage) 가 휴장일/실패
      처리. 빈 CSV 박제는 manifest 와 충돌 (`total_bars` 0 vs 파일 존재).
    - 비어 있지 않으면 parent dir 자동 생성 + tmp 파일 rename 으로 원자성.
    - `bars` 가 ascending order 라는 invariant 는 caller (downloader) 가 보장
      — 본 함수는 그대로 직렬화. 정렬 zero (입력 신뢰).
    """
    if not bars:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(_CSV_HEADER)
        for bar in bars:
            writer.writerow(
                [
                    bar.trade_date.isoformat(),  # YYYY-MM-DD
                    bar.trade_time.isoformat(timespec="seconds"),  # HH:MM:SS
                    str(bar.open),
                    str(bar.high),
                    str(bar.low),
                    str(bar.close),
                    str(bar.volume),
                ]
            )
    tmp.replace(path)


def _read_minute_csv(path: Path, asset_code: str) -> list[_MinuteBar]:
    """CSV → `_MinuteBar` 시계열 (round-trip — _write_minute_csv 역).

    Args:
        path: CSV 파일.
        asset_code: dataclass 의 `asset_code` 필드는 CSV 에 없으므로 caller 가
            (디렉토리 path 에서 추론 or context 에서) 명시 주입.

    Returns:
        Ascending 시퀀스 (저장된 그대로). 파일 부재 → 빈 리스트.

    Raises:
        ValueError: 헤더 불일치 (schema drift 알람).
        decimal.InvalidOperation / ValueError: 행 dtype 위반.
    """
    if not path.exists():
        return []
    bars: list[_MinuteBar] = []
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.reader(fp)
        header = next(reader, None)
        if header is None or tuple(header) != _CSV_HEADER:
            raise ValueError(
                f"CSV header mismatch at {path}: "
                f"expected {_CSV_HEADER}, got {tuple(header) if header else ()}"
            )
        for row in reader:
            (
                d_str,
                t_str,
                open_str,
                high_str,
                low_str,
                close_str,
                vol_str,
            ) = row
            bars.append(
                _MinuteBar(
                    asset_code=asset_code,
                    trade_date=date.fromisoformat(d_str),
                    trade_time=time.fromisoformat(t_str),
                    open=Decimal(open_str),
                    high=Decimal(high_str),
                    low=Decimal(low_str),
                    close=Decimal(close_str),
                    volume=int(vol_str),
                )
            )
    return bars


def _csv_path_for(
    *, data_root: Path, asset_code: str, trade_date: date
) -> Path:
    """`{data_root}/minute/{code}/{YYYY-MM-DD}.csv` (schema.md §7)."""
    return (
        data_root / "minute" / asset_code / f"{trade_date.isoformat()}.csv"
    )
