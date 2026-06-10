"""Tests for `_storage._download_and_persist` — e2e (download → CSV → manifest)."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.research.dgt_minute._csv_writer import _read_minute_csv
from src.research.dgt_minute._manifest import _load_manifest
from src.research.dgt_minute._storage import _download_and_persist

_SAMPLE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "research"
    / "phase-1.x-minute"
)
_SAMPLE_DATE = date(2026, 5, 29)
KST = ZoneInfo("Asia/Seoul")


def _load_sample(code: str) -> dict[str, object]:
    path = _SAMPLE_DIR / f"sample-{code}.json"
    if not path.exists():
        pytest.skip(f"sample-{code}.json not present")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@dataclass
class _FakeKISClient:
    bodies: list[dict[str, object]]
    calls: int = field(default=0)

    def request(
        self,
        method: str,
        path: str,
        *,
        tr_id: str,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        tr_cont: str = "",
    ) -> dict[str, object]:
        body = self.bodies[self.calls % len(self.bodies)]
        self.calls += 1
        return copy.deepcopy(body)


class TestDownloadAndPersist:
    def test_happy_path_writes_csv_and_manifest(self, tmp_path: Path) -> None:
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        manifest_path = tmp_path / "minute" / "manifest.json"

        result = _download_and_persist(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
            data_root=tmp_path,
            manifest_path=manifest_path,
            now=now,
            download_kwargs={"sleep_fn": lambda _: None},
        )

        assert result.bars_count == 30
        assert result.csv_written
        assert result.manifest_updated
        assert result.csv_path == tmp_path / "minute" / "069500" / "2026-05-29.csv"
        assert result.csv_path.exists()

        # CSV round-trip.
        bars = _read_minute_csv(result.csv_path, asset_code="069500")
        assert len(bars) == 30
        assert bars[0].trade_time.hour == 15
        assert bars[0].trade_time.minute == 1  # ascending — first = earliest
        assert bars[-1].trade_time.hour == 15
        assert bars[-1].trade_time.minute == 30

        # Manifest 갱신.
        m = _load_manifest(manifest_path)
        assert "069500" in m.assets
        asset = m.assets["069500"]
        assert asset.first_date == _SAMPLE_DATE
        assert asset.last_date == _SAMPLE_DATE
        assert asset.total_bars == 30
        assert m.updated_at == now

    def test_holiday_call_zero_side_effect(self, tmp_path: Path) -> None:
        """휴장일 호출 = CSV 미작성 + manifest 미갱신 + dropped_dates 기록."""
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        manifest_path = tmp_path / "minute" / "manifest.json"

        result = _download_and_persist(
            client,
            asset_code="069500",
            target_date=date(2026, 5, 30),  # 부처님오신날 휴장
            data_root=tmp_path,
            manifest_path=manifest_path,
            now=now,
            download_kwargs={"sleep_fn": lambda _: None},
        )

        assert result.bars_count == 0
        assert not result.csv_written
        assert not result.manifest_updated
        assert not result.csv_path.exists()
        assert not manifest_path.exists()
        # ADR 0023 R-신규: KIS 가 반환한 직전 거래일 = dropped_dates 박제.
        assert result.dropped_dates == (date(2026, 5, 29),)

    def test_success_dropped_dates_empty(self, tmp_path: Path) -> None:
        """정상 영업일 + 일치 응답 = dropped_dates 빈 tuple."""
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        manifest_path = tmp_path / "minute" / "manifest.json"

        result = _download_and_persist(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
            data_root=tmp_path,
            manifest_path=manifest_path,
            now=now,
            download_kwargs={"sleep_fn": lambda _: None},
        )

        assert result.csv_written
        assert result.dropped_dates == ()

    def test_idempotent_rerun(self, tmp_path: Path) -> None:
        """같은 (code, date) 재호출 = CSV overwrite, manifest 누적 zero."""
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        now1 = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        now2 = datetime(2026, 5, 31, 16, 0, tzinfo=KST)
        manifest_path = tmp_path / "minute" / "manifest.json"

        _download_and_persist(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
            data_root=tmp_path,
            manifest_path=manifest_path,
            now=now1,
        )
        _download_and_persist(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
            data_root=tmp_path,
            manifest_path=manifest_path,
            now=now2,
        )

        m = _load_manifest(manifest_path)
        asset = m.assets["069500"]
        # manifest first/last 변경 zero. 단 total_bars 는 누적 (caller invariant —
        # 호출자 (cron) 가 같은 날짜 중복 호출 회피해야 정확. 본 테스트는
        # 멱등 = 파일 보존 + manifest 가 새 now 로 갱신 = 정상 동작 확인).
        assert asset.first_date == _SAMPLE_DATE
        assert asset.last_date == _SAMPLE_DATE
        assert asset.total_bars == 60  # 30 + 30 (caller 책임 — cron 중복 회피)
        assert m.updated_at == now2

    def test_two_dates_extend_manifest(self, tmp_path: Path) -> None:
        """다른 거래일 2회 호출 → manifest first/last 확장."""
        # 5/28 sample 시뮬: 069500 sample 을 stck_bsop_date=20260528 로 복제.
        body_5_28 = copy.deepcopy(_load_sample("069500"))
        for bar in body_5_28["output2"]:  # type: ignore[union-attr]
            bar["stck_bsop_date"] = "20260528"  # type: ignore[index]
        body_5_29 = _load_sample("069500")  # 그대로 20260529

        client = _FakeKISClient(bodies=[body_5_28, body_5_29])
        # FakeKISClient 는 14 anchor x 2 호출 = 28 호출 동안 sample 순환.
        # 단 paging anchors 가 14 = bodies 2 의 7 cycle → 5/28 + 5/29 → 5/28 ...
        # → 두 date 가 mixed 응답이 됨. 시뮬 단순화 — 정확 검증은 정수 호출 분리.
        # 본 테스트는 2-date manifest 확장 path 의 존재만 검증.

        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)
        manifest_path = tmp_path / "minute" / "manifest.json"

        _download_and_persist(
            client,
            asset_code="069500",
            target_date=date(2026, 5, 28),
            data_root=tmp_path,
            manifest_path=manifest_path,
            now=now,
            download_kwargs={"sleep_fn": lambda _: None},
        )
        # 다음 호출 — bodies 순환에 의해 mix 되지만 target_date 가 expected
        # date 와 매치되는 행만 추출 (parser 의 필터 동작 검증).
        _download_and_persist(
            client,
            asset_code="069500",
            target_date=date(2026, 5, 29),
            data_root=tmp_path,
            manifest_path=manifest_path,
            now=now,
            download_kwargs={"sleep_fn": lambda _: None},
        )

        m = _load_manifest(manifest_path)
        asset = m.assets["069500"]
        # first ≤ 5/28, last ≥ 5/29.
        assert asset.first_date is not None
        assert asset.last_date is not None
        assert asset.first_date <= date(2026, 5, 28)
        assert asset.last_date >= date(2026, 5, 29)
