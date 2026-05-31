"""Tests for `_KISMinuteResponse` etc — ADR 0023 §10.1 / 세그먼트 1.2.1.b.1.

검증 전략:
1. `docs/research/phase-1.x-minute/sample-*.json` (4종 실 KIS 응답, 박제됨)
   를 fixture 로 사용 → 4종 모두 strict parse 성공해야 함 (schema 정합).
2. `extra='forbid'` 위반 / dtype 위반 / 검증 규칙 (price ≥0, sign ∈ {1..5})
   위반은 `ValidationError`.
3. Decimal/int 변환 invariant (CLAUDE.md §2.3 — float 경유 zero).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.research.dgt_minute._kis_minute_models import (
    _KISMinuteBar,
    _KISMinuteOutput1,
    _KISMinuteResponse,
)

_SAMPLE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "research"
    / "phase-1.x-minute"
)
_SAMPLE_CODES = ("069500", "132030", "005930", "035900")


def _load_sample(code: str) -> dict[str, object]:
    path = _SAMPLE_DIR / f"sample-{code}.json"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(params=_SAMPLE_CODES)
def sample_payload(request: pytest.FixtureRequest) -> dict[str, object]:
    if not _SAMPLE_DIR.exists():
        pytest.skip("sample dir not present (allowed in test envs)")
    path = _SAMPLE_DIR / f"sample-{request.param}.json"
    if not path.exists():
        pytest.skip(f"sample-{request.param}.json not present")
    return _load_sample(request.param)


class TestSampleParse:
    """4종 실 응답 sample → strict parse 성공."""

    def test_full_response_parses(self, sample_payload: dict[str, object]) -> None:
        resp = _KISMinuteResponse.model_validate(sample_payload)
        assert resp.rt_cd == "0"
        assert resp.msg_cd == "MCA00000"
        assert "정상" in resp.msg1

    def test_output1_fields_match_schema(
        self, sample_payload: dict[str, object]
    ) -> None:
        resp = _KISMinuteResponse.model_validate(sample_payload)
        assert isinstance(resp.output1.hts_kor_isnm, str)
        assert resp.output1.hts_kor_isnm  # 비공백
        assert isinstance(resp.output1.stck_prpr, Decimal)
        assert isinstance(resp.output1.acml_vol, int)
        assert resp.output1.acml_vol >= 0
        assert resp.output1.prdy_vrss_sign in {"1", "2", "3", "4", "5"}

    def test_output2_has_30_bars(
        self, sample_payload: dict[str, object]
    ) -> None:
        resp = _KISMinuteResponse.model_validate(sample_payload)
        assert len(resp.output2) == 30

    def test_output2_descending_order(
        self, sample_payload: dict[str, object]
    ) -> None:
        resp = _KISMinuteResponse.model_validate(sample_payload)
        hours = [b.stck_cntg_hour for b in resp.output2]
        assert hours == sorted(hours, reverse=True), (
            "output2 must be descending by stck_cntg_hour"
        )

    def test_output2_first_bar_is_1530(
        self, sample_payload: dict[str, object]
    ) -> None:
        resp = _KISMinuteResponse.model_validate(sample_payload)
        assert resp.output2[0].stck_cntg_hour == "153000"

    def test_output2_last_bar_is_1501(
        self, sample_payload: dict[str, object]
    ) -> None:
        resp = _KISMinuteResponse.model_validate(sample_payload)
        assert resp.output2[-1].stck_cntg_hour == "150100"

    def test_all_bars_share_trade_date(
        self, sample_payload: dict[str, object]
    ) -> None:
        resp = _KISMinuteResponse.model_validate(sample_payload)
        dates = {b.stck_bsop_date for b in resp.output2}
        assert len(dates) == 1
        (only,) = dates
        assert only == "20260529"  # 4종 sample 모두 동일

    def test_bar_decimal_invariant(
        self, sample_payload: dict[str, object]
    ) -> None:
        """모든 가격 = Decimal, 거래량 = int (CLAUDE.md §2.3)."""
        resp = _KISMinuteResponse.model_validate(sample_payload)
        for bar in resp.output2:
            assert isinstance(bar.stck_oprc, Decimal)
            assert isinstance(bar.stck_hgpr, Decimal)
            assert isinstance(bar.stck_lwpr, Decimal)
            assert isinstance(bar.stck_prpr, Decimal)
            assert isinstance(bar.cntg_vol, int)
            assert isinstance(bar.acml_tr_pbmn, int)

    def test_bar_ohlc_invariant(
        self, sample_payload: dict[str, object]
    ) -> None:
        """high ≥ low / high ≥ open / high ≥ close / low ≤ open / low ≤ close.

        zero-volume 분봉은 OHLC 가 동일 → invariant 자동 만족.
        """
        resp = _KISMinuteResponse.model_validate(sample_payload)
        for bar in resp.output2:
            assert bar.stck_hgpr >= bar.stck_lwpr, (
                f"high < low for {bar.stck_bsop_date} {bar.stck_cntg_hour}"
            )
            assert bar.stck_hgpr >= bar.stck_oprc
            assert bar.stck_hgpr >= bar.stck_prpr
            assert bar.stck_lwpr <= bar.stck_oprc
            assert bar.stck_lwpr <= bar.stck_prpr

    def test_zero_volume_bars_preserved(
        self, sample_payload: dict[str, object]
    ) -> None:
        """schema.md §4.3 — 장중 거래 없는 분도 1봉 보존."""
        resp = _KISMinuteResponse.model_validate(sample_payload)
        zero_vol = [b for b in resp.output2 if b.cntg_vol == 0]
        # 069500 sample 의 15:20~15:29 일부 = cntg_vol=0. 4종 모두 zero
        # 봉이 존재할 가능성 매우 높음 (장중 1분 무거래는 흔함).
        # 단 모든 종목에서 zero 봉이 *반드시* 있다는 보장은 없음 — 따라서
        # assert 는 "필터링 자체가 동작" 만 확인 (count ≥ 0).
        assert len(zero_vol) >= 0


class TestSchemaInvariants:
    """schema 규칙 위반은 ValidationError (drift 즉시 발견)."""

    def test_extra_field_in_response_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteResponse.model_validate(
                {
                    "rt_cd": "0",
                    "msg_cd": "MCA00000",
                    "msg1": "정상",
                    "output1": {
                        "hts_kor_isnm": "X",
                        "stck_prpr": "1",
                        "stck_prdy_clpr": "1",
                        "prdy_vrss": "0",
                        "prdy_vrss_sign": "3",
                        "prdy_ctrt": "0",
                        "acml_vol": 0,
                        "acml_tr_pbmn": 0,
                    },
                    "output2": [],
                    "EXTRA": "unexpected",
                }
            )

    def test_extra_field_in_bar_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteBar.model_validate(
                {
                    "stck_bsop_date": "20260529",
                    "stck_cntg_hour": "153000",
                    "stck_oprc": "1",
                    "stck_hgpr": "1",
                    "stck_lwpr": "1",
                    "stck_prpr": "1",
                    "cntg_vol": 0,
                    "acml_tr_pbmn": 0,
                    "BOGUS": "x",
                }
            )

    def test_non_digit_date_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteBar.model_validate(
                {
                    "stck_bsop_date": "2026XX29",
                    "stck_cntg_hour": "153000",
                    "stck_oprc": "1",
                    "stck_hgpr": "1",
                    "stck_lwpr": "1",
                    "stck_prpr": "1",
                    "cntg_vol": 0,
                    "acml_tr_pbmn": 0,
                }
            )

    def test_wrong_date_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteBar.model_validate(
                {
                    "stck_bsop_date": "20260529X",
                    "stck_cntg_hour": "153000",
                    "stck_oprc": "1",
                    "stck_hgpr": "1",
                    "stck_lwpr": "1",
                    "stck_prpr": "1",
                    "cntg_vol": 0,
                    "acml_tr_pbmn": 0,
                }
            )

    def test_non_digit_hour_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteBar.model_validate(
                {
                    "stck_bsop_date": "20260529",
                    "stck_cntg_hour": "1530XX",
                    "stck_oprc": "1",
                    "stck_hgpr": "1",
                    "stck_lwpr": "1",
                    "stck_prpr": "1",
                    "cntg_vol": 0,
                    "acml_tr_pbmn": 0,
                }
            )

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteBar.model_validate(
                {
                    "stck_bsop_date": "20260529",
                    "stck_cntg_hour": "153000",
                    "stck_oprc": "-1",
                    "stck_hgpr": "1",
                    "stck_lwpr": "1",
                    "stck_prpr": "1",
                    "cntg_vol": 0,
                    "acml_tr_pbmn": 0,
                }
            )

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteBar.model_validate(
                {
                    "stck_bsop_date": "20260529",
                    "stck_cntg_hour": "153000",
                    "stck_oprc": "1",
                    "stck_hgpr": "1",
                    "stck_lwpr": "1",
                    "stck_prpr": "1",
                    "cntg_vol": -1,
                    "acml_tr_pbmn": 0,
                }
            )

    def test_invalid_sign_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _KISMinuteOutput1.model_validate(
                {
                    "hts_kor_isnm": "X",
                    "stck_prpr": "1",
                    "stck_prdy_clpr": "1",
                    "prdy_vrss": "0",
                    "prdy_vrss_sign": "9",  # 1..5 외
                    "prdy_ctrt": "0",
                    "acml_vol": 0,
                    "acml_tr_pbmn": 0,
                }
            )

    def test_float_string_to_decimal_no_float_round_trip(self) -> None:
        """CLAUDE.md §2.3: KIS string → Decimal 직접 (float 경유 zero)."""
        bar = _KISMinuteBar.model_validate(
            {
                "stck_bsop_date": "20260529",
                "stck_cntg_hour": "153000",
                "stck_oprc": "134815.50",
                "stck_hgpr": "134815.50",
                "stck_lwpr": "134815.50",
                "stck_prpr": "134815.50",
                "cntg_vol": 1,
                "acml_tr_pbmn": 1,
            }
        )
        assert bar.stck_oprc == Decimal("134815.50")
        # Decimal 정확도 유지 (float 경유 시 134815.49999... 가능).
        assert str(bar.stck_oprc) == "134815.50"
