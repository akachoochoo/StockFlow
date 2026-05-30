"""Tests for `src.research.dgt_minute._manifest` (ADR 0023 AC7).

스키마 검증 (extra forbid / version / tz-aware) + load/save round-trip +
update_asset 누적 + missing_dates 재계산.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from src.research.dgt_minute._manifest import (
    _AssetManifest,
    _load_manifest,
    _Manifest,
    _save_manifest,
    _update_asset,
)

KST = ZoneInfo("Asia/Seoul")


class TestSchema:
    def test_empty_manifest_defaults(self) -> None:
        m = _Manifest()
        assert m.version == "1.0"
        assert m.updated_at is None
        assert m.assets == {}

    def test_unsupported_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _Manifest(version="2.0")

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _Manifest.model_validate({"version": "1.0", "assets": {}, "extra": "x"})

    def test_naive_updated_at_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _Manifest(updated_at=datetime(2026, 5, 30, 16, 0))

    def test_tz_aware_updated_at_accepted(self) -> None:
        m = _Manifest(updated_at=datetime(2026, 5, 30, 16, 0, tzinfo=KST))
        assert m.updated_at is not None
        assert m.updated_at.tzinfo is not None


class TestAssetManifest:
    def test_default_empty(self) -> None:
        a = _AssetManifest()
        assert a.first_date is None
        assert a.last_date is None
        assert a.missing_dates == ()
        assert a.total_bars == 0

    def test_unsorted_missing_dates_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _AssetManifest(
                first_date=date(2026, 5, 1),
                last_date=date(2026, 5, 31),
                missing_dates=(date(2026, 5, 10), date(2026, 5, 5)),
            )

    def test_duplicate_missing_dates_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _AssetManifest(
                first_date=date(2026, 5, 1),
                last_date=date(2026, 5, 31),
                missing_dates=(date(2026, 5, 5), date(2026, 5, 5)),
            )

    def test_negative_total_bars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _AssetManifest(total_bars=-1)


class TestLoadSave:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        m = _load_manifest(tmp_path / "no-such.json")
        assert m == _Manifest()

    def test_round_trip(self, tmp_path: Path) -> None:
        original = _Manifest(
            updated_at=datetime(2026, 5, 30, 16, 0, tzinfo=KST),
            assets={
                "069500": _AssetManifest(
                    first_date=date(2026, 5, 1),
                    last_date=date(2026, 5, 30),
                    missing_dates=(date(2026, 5, 15),),
                    total_bars=11310,
                ),
            },
        )
        path = tmp_path / "manifest.json"
        _save_manifest(original, path)
        loaded = _load_manifest(path)
        assert loaded == original

    def test_save_is_atomic_via_tmp_rename(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        m = _Manifest(updated_at=datetime(2026, 5, 30, 16, 0, tzinfo=KST))
        _save_manifest(m, path)
        assert path.exists()
        # tmp 파일은 rename 후 삭제됨.
        assert not (tmp_path / "manifest.json.tmp").exists()

    def test_save_creates_parent_dir(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "deep" / "manifest.json"
        _save_manifest(_Manifest(), path)
        assert path.exists()


class TestUpdateAsset:
    def test_first_insert(self) -> None:
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        m = _update_asset(
            _Manifest(),
            "069500",
            new_dates=[date(2026, 5, 28), date(2026, 5, 29), date(2026, 5, 30)],
            bars_added=1170,
            now=now,
        )
        asset = m.assets["069500"]
        assert asset.first_date == date(2026, 5, 28)
        assert asset.last_date == date(2026, 5, 30)
        assert asset.missing_dates == ()
        assert asset.total_bars == 1170
        assert m.updated_at == now

    def test_incremental_extend_no_gap(self) -> None:
        now1 = datetime(2026, 5, 29, 16, 0, tzinfo=KST)
        now2 = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        m1 = _update_asset(
            _Manifest(),
            "069500",
            new_dates=[date(2026, 5, 28), date(2026, 5, 29)],
            bars_added=780,
            now=now1,
        )
        m2 = _update_asset(
            m1,
            "069500",
            new_dates=[date(2026, 5, 30)],
            bars_added=390,
            now=now2,
        )
        asset = m2.assets["069500"]
        assert asset.first_date == date(2026, 5, 28)
        assert asset.last_date == date(2026, 5, 30)
        assert asset.missing_dates == ()
        assert asset.total_bars == 1170

    def test_gap_recorded_in_missing_dates(self) -> None:
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        m = _update_asset(
            _Manifest(),
            "069500",
            new_dates=[date(2026, 5, 28), date(2026, 5, 30)],  # 5/29 누락
            bars_added=780,
            now=now,
        )
        asset = m.assets["069500"]
        assert asset.first_date == date(2026, 5, 28)
        assert asset.last_date == date(2026, 5, 30)
        assert asset.missing_dates == (date(2026, 5, 29),)

    def test_holiday_excluded_from_missing(self) -> None:
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        # 5/29 = 휴장일 가정 — 거래일 누락 아님.
        m = _update_asset(
            _Manifest(),
            "069500",
            new_dates=[date(2026, 5, 28), date(2026, 5, 30)],
            bars_added=780,
            holidays=frozenset({date(2026, 5, 29)}),
            now=now,
        )
        asset = m.assets["069500"]
        assert asset.missing_dates == ()

    def test_independent_assets(self) -> None:
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        m = _Manifest()
        m = _update_asset(
            m, "069500", new_dates=[date(2026, 5, 30)], bars_added=390, now=now
        )
        m = _update_asset(
            m, "005930", new_dates=[date(2026, 5, 30)], bars_added=390, now=now
        )
        assert set(m.assets.keys()) == {"069500", "005930"}
        assert m.assets["069500"].total_bars == 390
        assert m.assets["005930"].total_bars == 390


class TestRepositoryManifest:
    """`data/historical/minute/manifest.json` (박제된 초기 manifest) 검증."""

    def test_repo_manifest_loads(self) -> None:
        repo_path = (
            Path(__file__).resolve().parent.parent.parent
            / "data"
            / "historical"
            / "minute"
            / "manifest.json"
        )
        if not repo_path.exists():
            pytest.skip("repo manifest not present (allowed in test envs)")
        m = _load_manifest(repo_path)
        assert m.version == "1.0"
        # 초기 박제 = 빈 manifest.
        assert m.assets == {}
        assert m.updated_at is None
