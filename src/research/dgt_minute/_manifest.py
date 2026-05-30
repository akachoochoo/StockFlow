"""Minute bar manifest — `data/historical/minute/manifest.json` 박제 스키마.

ADR 0023 §8.2 / AC7 — 분봉 데이터 가용성 박제. 일별 누적 cron
(`scripts/fetch_kis_minute_daily.py`, 1.2.1.b) 가 본 manifest 를 갱신.

스키마 design:
- `version` = 1.0 — 스키마 진화 시 bump.
- `updated_at` = ISO-8601 (KST 명시) — 마지막 cron 실행 시점.
- `assets` = code → `_AssetManifest` (가용 기간 + missing dates + bar count).

CLAUDE.md §5.1: 외부 입력(JSON) → pydantic strict (`extra='forbid'`) 검증.
CLAUDE.md §3.2: `updated_at` 은 외부 주입 — 본 모듈은 `datetime.now()` 호출
zero (`set_updated_at(now)` 형태).

CSV 채택 (ADR 0023 §8.2 amendment, 2026-05-30): parquet → csv 로 다운그레이드.
근거: pyarrow 의존성 회피 (`pyproject.toml` 변경 zero, CLAUDE.md §0 체크리스트
#3). 일별 ~390 rows x 250영업일 x 4종 = ~390K rows/년 = CSV 충분.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path  # noqa: TC003  -- runtime use in _save_manifest

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SCHEMA_VERSION = "1.0"


class _AssetManifest(BaseModel):
    """Per-asset 분봉 데이터 가용성 박제."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    first_date: date | None = Field(
        default=None,
        description="가장 이른 일자 (YYYY-MM-DD). 데이터 zero 면 None.",
    )
    last_date: date | None = Field(
        default=None,
        description="가장 늦은 일자. 데이터 zero 면 None.",
    )
    missing_dates: tuple[date, ...] = Field(
        default_factory=tuple,
        description="가용 범위 내부 결손 일자 (휴장일 제외 기준).",
    )
    total_bars: int = Field(
        default=0,
        ge=0,
        description="누적 분봉 행 수.",
    )

    @field_validator("missing_dates")
    @classmethod
    def _validate_missing_sorted(cls, v: tuple[date, ...]) -> tuple[date, ...]:
        if list(v) != sorted(v):
            raise ValueError("missing_dates must be sorted ascending")
        if len(set(v)) != len(v):
            raise ValueError("missing_dates must be unique")
        return v


class _Manifest(BaseModel):
    """분봉 데이터 manifest 정본."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(default=_SCHEMA_VERSION)
    updated_at: datetime | None = Field(
        default=None,
        description="마지막 갱신 시각 (timezone-aware). cron 외부 주입.",
    )
    assets: dict[str, _AssetManifest] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if v != _SCHEMA_VERSION:
            raise ValueError(
                f"unsupported manifest version: {v!r} "
                f"(expected {_SCHEMA_VERSION!r})"
            )
        return v

    @field_validator("updated_at")
    @classmethod
    def _validate_tz_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        return v


def _load_manifest(path: Path) -> _Manifest:
    """파일 → `_Manifest`. 파일 부재 → 빈 manifest (회귀 안전)."""
    if not path.exists():
        return _Manifest()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _Manifest.model_validate(raw)


def _save_manifest(manifest: _Manifest, path: Path) -> None:
    """`_Manifest` → 파일 (atomic write via tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = manifest.model_dump(mode="json")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def _update_asset(
    manifest: _Manifest,
    code: str,
    *,
    new_dates: list[date],
    bars_added: int,
    holidays: frozenset[date] = frozenset(),
    now: datetime,
) -> _Manifest:
    """가용 일자 + bar count 누적 + missing_dates 재계산.

    Args:
        manifest: 기존 manifest.
        code: 종목 코드.
        new_dates: 신규로 다운로드된 거래일 (이미 검증된 set, 중복 OK).
        bars_added: 이번 호출에서 추가된 bar 수.
        holidays: missing_dates 계산 시 제외할 휴장일.
        now: 현재 시각 (외부 주입, CLAUDE.md §3.2).

    Returns:
        새 `_Manifest` (frozen — 원본 미변경).
    """
    asset = manifest.assets.get(code, _AssetManifest())
    all_dates: set[date] = {*asset.missing_dates}
    if asset.first_date and asset.last_date:
        cur = asset.first_date
        while cur <= asset.last_date:
            if cur not in asset.missing_dates:
                all_dates.add(cur)
            cur = date.fromordinal(cur.toordinal() + 1)
    all_dates.update(new_dates)
    if not all_dates:
        new_asset = _AssetManifest(
            total_bars=asset.total_bars + bars_added,
        )
    else:
        sorted_dates = sorted(all_dates)
        first = sorted_dates[0]
        last = sorted_dates[-1]
        present = set(sorted_dates)
        missing: list[date] = []
        cur = first
        while cur <= last:
            if cur not in present and cur not in holidays:
                missing.append(cur)
            cur = date.fromordinal(cur.toordinal() + 1)
        new_asset = _AssetManifest(
            first_date=first,
            last_date=last,
            missing_dates=tuple(missing),
            total_bars=asset.total_bars + bars_added,
        )
    new_assets = dict(manifest.assets)
    new_assets[code] = new_asset
    return _Manifest(
        version=manifest.version,
        updated_at=now,
        assets=new_assets,
    )
