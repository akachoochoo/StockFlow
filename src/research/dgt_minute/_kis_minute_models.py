"""KIS `inquire-time-itemchartprice` (FHKST03010200) 응답 Pydantic strict model.

ADR 0023 §10.1 / 세그먼트 1.2.1.b.1 산출. 응답 schema 정본 =
`docs/research/phase-1.x-minute/schema.md` (실증 박제, 2026-05-31).

본 모델은 **5th ring 격리** — production `src/adapters/kis/models.py` 의
`KISDailyPriceResponse` 와 별도. 분봉이 inner ring production 진입하는 시점
(ADR 0023 §10.4 / 1.2.4 직전)에 별도 ADR 박제 후 production 모델 신규.

설계 invariant (CLAUDE.md 정합):
- `extra='forbid'` (§5.1 외부 데이터 strict, KIS schema drift 즉시 발견)
- `frozen=True` (도메인 모델 불변성)
- 모든 numeric str→Decimal/int (§2.3 — float 경유 zero, KIS string 표준)
- 시계 주입 zero (§3.2) — `stck_bsop_date` / `stck_cntg_hour` 는 raw str 보존,
  변환은 downloader (`_to_trade_datetime`) 에서.

본 모델은 raw KIS 응답만 검증 + 형변환. 도메인 `_MinuteBar` (CSV 저장 모델)
는 downloader 가 별도 구축 (1.2.1.b.2 산출).
"""
from __future__ import annotations

from decimal import Decimal  # noqa: TC003  -- pydantic field annotation needs runtime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _KISMinuteBar(BaseModel):
    """`output2[]` element — 1분봉 1봉.

    Sample (069500 15:30 봉):
        stck_bsop_date="20260529", stck_cntg_hour="153000",
        stck_oprc=stck_hgpr=stck_lwpr=stck_prpr=Decimal("134815"),
        cntg_vol=165274, acml_tr_pbmn=2324598621492
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stck_bsop_date: str = Field(
        min_length=8,
        max_length=8,
        description="거래일 YYYYMMDD (str, KIS 표준)",
    )
    stck_cntg_hour: str = Field(
        min_length=6,
        max_length=6,
        description="체결 시각 HHMMSS (str, KIS 표준). 1분봉은 SS='00'.",
    )
    stck_oprc: Decimal = Field(description="open (≥0, KIS string → Decimal)")
    stck_hgpr: Decimal = Field(description="high")
    stck_lwpr: Decimal = Field(description="low")
    stck_prpr: Decimal = Field(description="close")
    cntg_vol: int = Field(ge=0, description="해당 분 체결 거래량 (1분, ≥0)")
    acml_tr_pbmn: int = Field(
        ge=0, description="누적 거래대금 KRW (해당 분까지 누적, ≥0)"
    )

    @field_validator("stck_bsop_date")
    @classmethod
    def _validate_date_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError(f"stck_bsop_date must be 8 digits, got {v!r}")
        return v

    @field_validator("stck_cntg_hour")
    @classmethod
    def _validate_hour_digits(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError(f"stck_cntg_hour must be 6 digits, got {v!r}")
        return v

    @field_validator("stck_oprc", "stck_hgpr", "stck_lwpr", "stck_prpr")
    @classmethod
    def _validate_price_non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"price must be ≥0, got {v}")
        return v


class _KISMinuteOutput1(BaseModel):
    """`output1` — 종목 메타 + 현재가.

    분봉 backtest/dry-run 의사결정 로직에는 직접 사용 zero (output2 의
    bar 시계열로 충분). production cron 알림 / 디버깅 용도 (e.g. 종목명
    한글 표시).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    hts_kor_isnm: str = Field(description="종목명 (한글)")
    stck_prpr: Decimal = Field(description="현재가")
    stck_prdy_clpr: Decimal = Field(description="전일 종가")
    prdy_vrss: Decimal = Field(description="전일대비 절대값")
    prdy_vrss_sign: str = Field(
        min_length=1,
        max_length=1,
        description="부호: 1=상한 / 2=상승 / 3=보합 / 4=하한 / 5=하락",
    )
    prdy_ctrt: Decimal = Field(description="전일대비율 %")
    acml_vol: int = Field(ge=0, description="누적 거래량")
    acml_tr_pbmn: int = Field(ge=0, description="누적 거래대금 KRW")

    @field_validator("prdy_vrss_sign")
    @classmethod
    def _validate_sign_range(cls, v: str) -> str:
        if v not in {"1", "2", "3", "4", "5"}:
            raise ValueError(
                f"prdy_vrss_sign must be one of 1..5, got {v!r}"
            )
        return v


class _KISMinuteResponse(BaseModel):
    """`inquire-time-itemchartprice` 전체 응답.

    Top-level: rt_cd / msg_cd / msg1 + output1 + output2[].
    `rt_cd != "0"` 처리 = downloader 책임 (본 model 은 schema 검증만).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rt_cd: str = Field(description="상태 코드 ('0' = 성공)")
    msg_cd: str = Field(description="메시지 코드 (예: MCA00000)")
    msg1: str = Field(description="메시지 (한글)")
    output1: _KISMinuteOutput1
    output2: tuple[_KISMinuteBar, ...] = Field(
        description="분봉 배열 (descending — output2[0] = 가장 최근)",
    )
