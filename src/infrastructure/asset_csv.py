"""Helpers for asset OHLCV CSV path derivation + window validation.

Phase 0.9 (sub-step 0.9.e — ADR 0005 §1.7 / §1.12 박제). 데이터 다운로드
스크립트 (`scripts/download_kr_assets.py`) 와 백테스트 러너 양쪽에서
재사용. Asset 메타데이터 (`listed_at`) 와 윈도우 일관성을 강제.

CLAUDE.md §1.1 — 본 모듈은 infrastructure 계층 (file path + 외부 데이터
검증). domain 모델은 Asset 만 import (Protocol 외 import 없음).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

    from src.domain.models import Asset


CSV_DIR_DEFAULT = "data/historical"


def derive_csv_path(
    code: str, start: date, end: date, *, base_dir: str = CSV_DIR_DEFAULT
) -> Path:
    """Build the canonical OHLCV CSV path for a KRX asset window.

    Pattern: ``{base_dir}/KRX_{code}_{start_year}-{end_year}.csv``

    Examples:
        >>> derive_csv_path("069500", date(2019, 1, 2), date(2024, 12, 30))
        PosixPath('data/historical/KRX_069500_2019-2024.csv')

    Phase 0.7.x convention; preserved verbatim for round-trip with
    existing fixtures (``KRX_069500_2019-2024.csv`` etc).
    """
    from pathlib import Path

    return Path(base_dir) / f"KRX_{code}_{start.year}-{end.year}.csv"


def validate_asset_for_window(asset: Asset, start: date, end: date) -> None:
    """Raise if ``asset`` cannot cover ``[start, end]`` per its listing dates.

    Phase 0.9 (ADR 0005 §1.7.2 박제). ``Asset.listed_at`` must be ≤ ``start``;
    if ``Asset.delisted_at`` is set it must be > ``end``. ``start`` must be
    ≤ ``end``. Caller (download script / backtest) catches the ValueError
    and surfaces a user-readable message.

    Raises:
        ValueError: window inversion / pre-listing / post-delisting.
    """
    if start > end:
        raise ValueError(
            f"start ({start}) must be <= end ({end})"
        )
    if asset.listed_at > start:
        raise ValueError(
            f"{asset.fqn} listed_at {asset.listed_at} > start {start} — "
            "window precedes listing date"
        )
    if asset.delisted_at is not None and asset.delisted_at <= end:
        raise ValueError(
            f"{asset.fqn} delisted_at {asset.delisted_at} <= end {end} — "
            "window extends past delisting date"
        )
