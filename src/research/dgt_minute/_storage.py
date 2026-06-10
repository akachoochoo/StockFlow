"""분봉 download → CSV → manifest 통합 — `_StorageResult` 반환.

ADR 0023 §10.1 / 세그먼트 1.2.1.b.3 산출. 1.2.1.b.1 (model) +
1.2.1.b.2 (downloader) + 1.2.1.b.3a (CSV writer) + 1.2.1.b (manifest 스키마)
조립.

본 모듈의 본질:
1. `_download_minute_bars` 호출.
2. 결과 bars 가 비어있지 않으면 CSV 저장 (`_write_minute_csv`).
3. manifest 갱신 (`_update_asset` — bars 가 있으면 `new_dates=[target_date]`,
   `bars_added=len(bars)`; 없으면 갱신 zero).
4. 원자성: CSV → manifest 순서. CSV 성공 + manifest 실패 시 다음 cron 호출에서
   CSV 가 이미 존재 (멱등) + manifest 가 다시 갱신 시도 (idempotent — 같은
   `new_dates` 재호출 = no-op).

호출자 = `scripts/fetch_kis_minute_daily.py` (1.2.1.b.4 cron 진입점).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime  # noqa: TC003  -- runtime use
from pathlib import Path  # noqa: TC003  -- runtime use

from src.research.dgt_minute._csv_writer import (
    _csv_path_for,
    _write_minute_csv,
)
from src.research.dgt_minute._kis_minute_downloader import (
    _download_minute_bars,
    _KISClientLike,
)
from src.research.dgt_minute._manifest import (
    _load_manifest,
    _save_manifest,
    _update_asset,
)


@dataclass(frozen=True, slots=True)
class _StorageResult:
    """단일 (code, date) download 결과."""

    asset_code: str
    trade_date: date
    bars_count: int
    csv_path: Path
    csv_written: bool
    manifest_updated: bool
    # KIS 가 응답에 포함했지만 target_date 와 mismatch 된 일자 union (ADR 0023
    # R-신규, 2026-06-11). 휴장일 호출 시 직전 거래일 일자 = 운영 디버깅 단서.
    # 정상 영업일 + 일치 응답 시 빈 tuple. caller 가 stderr WARN 등 활용.
    dropped_dates: tuple[date, ...] = ()


def _download_and_persist(
    client: _KISClientLike,
    *,
    asset_code: str,
    target_date: date,
    data_root: Path,
    manifest_path: Path,
    now: datetime,
    holidays: frozenset[date] = frozenset(),
    download_kwargs: dict[str, object] | None = None,
) -> _StorageResult:
    """단일 (asset_code, target_date) 다운로드 + CSV 저장 + manifest 갱신.

    Args:
        client: KISClient (production) 또는 fake (tests).
        asset_code: 6자리 코드.
        target_date: 거래일.
        data_root: 데이터 루트 (`data/historical/`). CSV 는
            `{data_root}/minute/{code}/{YYYY-MM-DD}.csv`.
        manifest_path: manifest JSON 경로 (`data/historical/minute/manifest.json`).
        now: 현재 시각 (timezone-aware, 외부 주입 — CLAUDE.md §3.2).
        holidays: missing_dates 계산 시 제외할 휴장일.
        download_kwargs: `_download_minute_bars` 추가 인자 (예:
            `inter_anchor_sleep_sec` / `sleep_fn`). 기본 None = downloader
            기본값 사용 (100ms anchor sleep + real time.sleep).

    Returns:
        `_StorageResult` — 호출자가 알림/로깅에 활용.

    Side effects:
        - CSV 파일 작성 (bars 가 비어있지 않은 경우).
        - manifest 파일 갱신 (bars 가 비어있지 않은 경우).
    """
    bars, dropped_set = _download_minute_bars(
        client,
        asset_code=asset_code,
        target_date=target_date,
        **(download_kwargs or {}),  # type: ignore[arg-type]
    )
    dropped_dates = tuple(sorted(dropped_set))
    csv_path = _csv_path_for(
        data_root=data_root, asset_code=asset_code, trade_date=target_date
    )

    if not bars:
        # 휴장일 호출 또는 데이터 zero — 부작용 zero (CSV/manifest 미갱신).
        return _StorageResult(
            asset_code=asset_code,
            trade_date=target_date,
            bars_count=0,
            csv_path=csv_path,
            csv_written=False,
            manifest_updated=False,
            dropped_dates=dropped_dates,
        )

    _write_minute_csv(bars, csv_path)

    manifest = _load_manifest(manifest_path)
    updated = _update_asset(
        manifest,
        asset_code,
        new_dates=[target_date],
        bars_added=len(bars),
        holidays=holidays,
        now=now,
    )
    _save_manifest(updated, manifest_path)

    return _StorageResult(
        asset_code=asset_code,
        trade_date=target_date,
        bars_count=len(bars),
        csv_path=csv_path,
        csv_written=True,
        manifest_updated=True,
        dropped_dates=dropped_dates,
    )
