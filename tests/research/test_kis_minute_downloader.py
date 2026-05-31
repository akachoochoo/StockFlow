"""Tests for `_kis_minute_downloader` — ADR 0023 §10.1 / 세그먼트 1.2.1.b.2.

검증 전략:
- 4종 실 KIS sample (`docs/research/phase-1.x-minute/sample-*.json`) fixture
  를 fake `KISClient` 가 반환 → parser/dedup/ordering 동작 검증.
- KIS 의존성 zero (fake client) — 네트워크 호출 zero, 결정론적.
- 휴장일 시뮬: target_date 가 sample 의 stck_bsop_date 와 다르면 모두 drop.
- rt_cd != "0" → `_MinuteApiError`.
- paging dedup: 동일 sample 을 N anchor 마다 반환 → dedup 후 30봉.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.research.dgt_minute._kis_minute_downloader import (
    _DEFAULT_PAGING_ANCHORS,
    _MINUTE_PATH,
    _MINUTE_TR_ID,
    _download_minute_bars,
    _MinuteApiError,
    _MinuteBar,
    _parse_kis_response,
)

_SAMPLE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "research"
    / "phase-1.x-minute"
)
_SAMPLE_DATE = date(2026, 5, 29)  # 4종 sample 모두 stck_bsop_date="20260529"


def _load_sample(code: str) -> dict[str, object]:
    path = _SAMPLE_DIR / f"sample-{code}.json"
    if not path.exists():
        pytest.skip(f"sample-{code}.json not present")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@dataclass
class _RecordedCall:
    method: str
    path: str
    tr_id: str
    params: dict[str, str]


@dataclass
class _FakeKISClient:
    """Test double — records calls + returns scripted bodies."""

    bodies: list[dict[str, object]]
    calls: list[_RecordedCall] = field(default_factory=list)
    _index: int = 0

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
        self.calls.append(
            _RecordedCall(
                method=method, path=path, tr_id=tr_id, params=dict(params or {})
            )
        )
        body = self.bodies[self._index % len(self.bodies)]
        self._index += 1
        return copy.deepcopy(body)


# --------------------------------------------------------------------- #
# _parse_kis_response
# --------------------------------------------------------------------- #
class TestParse:
    def test_parses_069500_sample_into_30_bars(self) -> None:
        body = _load_sample("069500")
        bars = _parse_kis_response(
            body, asset_code="069500", expected_date=_SAMPLE_DATE
        )
        assert len(bars) == 30

    def test_bar_fields_filled_from_sample(self) -> None:
        body = _load_sample("069500")
        bars = _parse_kis_response(
            body, asset_code="069500", expected_date=_SAMPLE_DATE
        )
        # First bar in returned list mirrors KIS output2[0] = 15:30.
        first = next(b for b in bars if b.trade_time.hour == 15 and b.trade_time.minute == 30)
        assert first.asset_code == "069500"
        assert first.trade_date == _SAMPLE_DATE
        assert first.open == Decimal("134815")
        assert first.high == Decimal("134815")
        assert first.low == Decimal("134815")
        assert first.close == Decimal("134815")
        assert first.volume == 165274

    def test_target_date_mismatch_drops_all(self) -> None:
        """휴장일 호출 시뮬 — KIS 가 직전 거래일 데이터 반환."""
        body = _load_sample("069500")
        bars = _parse_kis_response(
            body,
            asset_code="069500",
            expected_date=date(2026, 5, 30),  # 부처님오신날 휴장
        )
        assert bars == []

    def test_rt_cd_non_zero_raises(self) -> None:
        body = _load_sample("069500")
        body["rt_cd"] = "1"
        body["msg_cd"] = "EGW00201"
        body["msg1"] = "유량 초과"
        with pytest.raises(_MinuteApiError, match="rt_cd='1'"):
            _parse_kis_response(
                body, asset_code="069500", expected_date=_SAMPLE_DATE
            )

    def test_schema_drift_raises_validation_error(self) -> None:
        body = _load_sample("069500")
        body["UNEXPECTED"] = "drift"
        with pytest.raises(ValidationError):
            _parse_kis_response(
                body, asset_code="069500", expected_date=_SAMPLE_DATE
            )


# --------------------------------------------------------------------- #
# _download_minute_bars
# --------------------------------------------------------------------- #
class TestDownload:
    def test_single_anchor_returns_30_bars_ascending(self) -> None:
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        bars = _download_minute_bars(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
            paging_anchors=("153000",),
        )
        assert len(bars) == 30
        times = [(b.trade_time.hour, b.trade_time.minute) for b in bars]
        assert times == sorted(times), "result must be ascending by trade_time"

    def test_multiple_anchors_dedup_to_30(self) -> None:
        """같은 sample 을 14 anchor 모두 반환 → dedup 후 30봉."""
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        bars = _download_minute_bars(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
        )  # default 14 anchors
        assert len(bars) == 30
        assert len(client.calls) == 14
        # 모든 호출 = 동일 endpoint / TR_ID / asset code.
        for call, anchor in zip(client.calls, _DEFAULT_PAGING_ANCHORS, strict=True):
            assert call.method == "GET"
            assert call.path == _MINUTE_PATH
            assert call.tr_id == _MINUTE_TR_ID
            assert call.params["FID_INPUT_ISCD"] == "069500"
            assert call.params["FID_INPUT_HOUR_1"] == anchor
            assert call.params["FID_COND_MRKT_DIV_CODE"] == "J"
            assert call.params["FID_PW_DATA_INCU_YN"] == "N"

    def test_include_past_flag_propagates(self) -> None:
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        _download_minute_bars(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
            paging_anchors=("153000",),
            include_past=True,
        )
        assert client.calls[0].params["FID_PW_DATA_INCU_YN"] == "Y"

    def test_holiday_call_returns_empty(self) -> None:
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        bars = _download_minute_bars(
            client,
            asset_code="069500",
            target_date=date(2026, 5, 30),  # 휴장일
        )
        assert bars == []
        # 호출은 정상 14회 (parser 가 행을 drop, 다운로더는 호출 자체는 skip 안 함).
        assert len(client.calls) == 14

    def test_rt_cd_error_propagates(self) -> None:
        body = _load_sample("069500")
        body["rt_cd"] = "1"
        body["msg1"] = "유량 초과"
        client = _FakeKISClient(bodies=[body])
        with pytest.raises(_MinuteApiError):
            _download_minute_bars(
                client,
                asset_code="069500",
                target_date=_SAMPLE_DATE,
                paging_anchors=("153000",),
            )

    @pytest.mark.parametrize("code", ["069500", "132030", "005930", "035900"])
    def test_4_assets_all_parse(self, code: str) -> None:
        """4종 모두 동일 schema → 30봉 ascending 반환."""
        client = _FakeKISClient(bodies=[_load_sample(code)])
        bars = _download_minute_bars(
            client,
            asset_code=code,
            target_date=_SAMPLE_DATE,
            paging_anchors=("153000",),
        )
        assert len(bars) == 30
        assert {b.asset_code for b in bars} == {code}

    def test_bar_ascending_invariant(self) -> None:
        client = _FakeKISClient(bodies=[_load_sample("069500")])
        bars = _download_minute_bars(
            client,
            asset_code="069500",
            target_date=_SAMPLE_DATE,
            paging_anchors=("153000",),
        )
        # First in ascending = 15:01, last = 15:30.
        assert bars[0].trade_time.hour == 15
        assert bars[0].trade_time.minute == 1
        assert bars[-1].trade_time.hour == 15
        assert bars[-1].trade_time.minute == 30


# --------------------------------------------------------------------- #
# _MinuteBar dataclass invariants
# --------------------------------------------------------------------- #
class TestMinuteBarDataclass:
    def test_frozen(self) -> None:
        bar = _MinuteBar(
            asset_code="069500",
            trade_date=_SAMPLE_DATE,
            trade_time=__import__("datetime").time(15, 30, 0),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=1000,
        )
        with pytest.raises((AttributeError, Exception)):
            bar.asset_code = "X"  # type: ignore[misc]

    def test_equality(self) -> None:
        from datetime import time as t

        a = _MinuteBar(
            asset_code="069500",
            trade_date=_SAMPLE_DATE,
            trade_time=t(15, 30),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=0,
        )
        b = _MinuteBar(
            asset_code="069500",
            trade_date=_SAMPLE_DATE,
            trade_time=t(15, 30),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            volume=0,
        )
        assert a == b
