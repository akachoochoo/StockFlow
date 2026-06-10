"""KIS 분봉 다운로더 — paging + dedup + 휴장일 필터 + 도메인 변환.

ADR 0023 §10.1 / 세그먼트 1.2.1.b.2 산출. schema.md §5 (paging) + §6 (model) +
§7 (CSV) spec 정합.

본 모듈의 본질:
1. KIS `inquire-time-itemchartprice` 단발 호출 = 직전 30봉. 하루 390봉은
   `FID_INPUT_HOUR_1` 30분씩 후퇴 14회 호출 (15:30 → 09:00) + dedup.
2. 휴장일 호출 시 KIS 가 직전 거래일 데이터 반환 → `target_date` 와 다른
   `stck_bsop_date` 행은 필터 (조용히 drop).
3. 반환 = 도메인 `_MinuteBar` (asset_code/trade_date/trade_time/OHLCV) 시계열
   ascending order — backtest/dry-run runner iteration 자연.

5th ring 격리 (ADR 0023 §5.1): production `KISMarketData.get_ohlcv` (일봉)
와 별도 경로. KISClient 자체는 inner ring (`src.adapters.kis._client`) 의
재사용 — 5th ring 의 outer→inner read 정합 (ADR 0007 §1.6).

CSV/manifest 통합은 1.2.1.b.3 산출 (별도 commit) — 본 모듈은 *raw KIS →
도메인 bar 시계열* 변환만 책임.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal  # noqa: TC003  -- dataclass field annotation runtime
from typing import TYPE_CHECKING, Protocol

from src.research.dgt_minute._kis_minute_models import _KISMinuteResponse

if TYPE_CHECKING:
    from collections.abc import Callable

# KIS endpoint constants (ADR 0020 §2.2 분봉 row 박제, 2026-05-31).
_MINUTE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
_MINUTE_TR_ID = "FHKST03010200"

# Paging anchors: HHMMSS strings, descending. 호출 N+1 의 anchor 는 호출 N
# 의 응답에 포함된 가장 이른 봉보다 ≤ 30분 전 — 30분씩 후퇴로 직전 30봉
# 윈도 겹침 zero (단일 호출 = 직전 30봉 fully covers 윈도).
#
# 14 anchors → 14 호출 → 단순화: 모든 호출 동일 params 형식, 응답 dedup.
# 09:00 시가 단봉은 anchor "090000" 호출 (08:31~09:00 윈도) 응답에 포함.
_DEFAULT_PAGING_ANCHORS: tuple[str, ...] = (
    "153000",  # 15:01~15:30 (장마감 + 동시호가)
    "150000",  # 14:31~15:00
    "143000",  # 14:01~14:30
    "140000",  # 13:31~14:00
    "133000",  # 13:01~13:30
    "130000",  # 12:31~13:00
    "123000",  # 12:01~12:30
    "120000",  # 11:31~12:00
    "113000",  # 11:01~11:30
    "110000",  # 10:31~11:00
    "103000",  # 10:01~10:30
    "100000",  # 09:31~10:00
    "093000",  # 09:01~09:30 (시가 직후)
    "090000",  # 08:31~09:00 (시가 단봉)
)


class _MinuteApiError(Exception):
    """KIS 분봉 API non-zero `rt_cd` — caller 가 종목/anchor 추적."""


class _KISClientLike(Protocol):
    """Minimal KISClient surface — adapter import 의존 회피.

    Production: `src.adapters.kis._client.KISClient` (Stage 2.3).
    Tests: fake implementing only `request(...)`.
    """

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
        ...


@dataclass(frozen=True, slots=True)
class _MinuteBar:
    """도메인 1분봉 — `(asset_code, trade_date, trade_time)` 단위.

    Ascending order 키 = `(trade_date, trade_time)`.
    backtest/dry-run runner 가 그대로 iteration 가능. CSV 저장 시
    `volume` int 그대로, OHLC Decimal `str(v)` round-trip 안전 (§7).
    """

    asset_code: str
    trade_date: date
    trade_time: time
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


def _parse_kis_response(
    body: dict[str, object],
    *,
    asset_code: str,
    expected_date: date,
) -> tuple[list[_MinuteBar], frozenset[date]]:
    """KIS raw body → (도메인 bar 시계열, dropped dates).

    - `rt_cd != "0"` → `_MinuteApiError` (msg1 surface).
    - `stck_bsop_date != expected_date` 행 → drop. KIS 가 휴장일 호출 시
      직전 거래일 반환 (ADR 0023 §16 D16 + schema.md §5.3). 운영 관찰성
      확보를 위해 (ADR 0023 R-신규, 2026-06-11 박제) dropped dates 를
      frozenset 으로 반환 — caller 가 stderr WARN 등 디버깅 활용 가능.
    - schema 위반 → `pydantic.ValidationError` (caller 가 KIS schema drift
      알람용으로 catch 가능).

    Returns:
        (bars, dropped_dates) — bars 는 expected_date 일치 행만 포함.
        dropped_dates = KIS 응답에 있었지만 expected_date 와 다른 일자 set.
        휴장일 호출 = dropped_dates 가 직전 거래일 (1개 또는 그 이상).
    """
    response = _KISMinuteResponse.model_validate(body)
    if response.rt_cd != "0":
        raise _MinuteApiError(
            f"KIS minute API rt_cd={response.rt_cd!r} "
            f"(msg_cd={response.msg_cd!r}): {response.msg1}"
        )

    expected_str = expected_date.strftime("%Y%m%d")
    bars: list[_MinuteBar] = []
    dropped_strs: set[str] = set()
    for raw in response.output2:
        if raw.stck_bsop_date != expected_str:
            dropped_strs.add(raw.stck_bsop_date)
            continue
        hh = int(raw.stck_cntg_hour[0:2])
        mm = int(raw.stck_cntg_hour[2:4])
        ss = int(raw.stck_cntg_hour[4:6])
        bars.append(
            _MinuteBar(
                asset_code=asset_code,
                trade_date=expected_date,
                trade_time=time(hh, mm, ss),
                open=raw.stck_oprc,
                high=raw.stck_hgpr,
                low=raw.stck_lwpr,
                close=raw.stck_prpr,
                volume=raw.cntg_vol,
            )
        )
    dropped: frozenset[date] = frozenset(
        date(int(s[0:4]), int(s[4:6]), int(s[6:8])) for s in dropped_strs
    )
    return bars, dropped


def _download_minute_bars(
    client: _KISClientLike,
    *,
    asset_code: str,
    target_date: date,
    paging_anchors: tuple[str, ...] = _DEFAULT_PAGING_ANCHORS,
    include_past: bool = False,
    inter_anchor_sleep_sec: float = 0.1,
    sleep_fn: Callable[[float], None] = _time.sleep,
) -> tuple[list[_MinuteBar], frozenset[date]]:
    """`target_date` 의 1분봉 시계열 다운로드.

    Args:
        client: KISClient (production) 또는 fake (tests).
        asset_code: 6자리 숫자 문자열 (예: "069500").
        target_date: 다운로드할 거래일 (KST date).
        paging_anchors: HHMMSS anchor 시퀀스. 기본 14 anchor (15:30~09:00).
        include_past: `FID_PW_DATA_INCU_YN` ("Y"/"N"). 기본 "N".
        inter_anchor_sleep_sec: anchor 호출 간 sleep 초 (ADR 0023 R3 mitigation,
            EGW00201 burst 회피). 첫 호출 후부터 적용. 기본 100ms — KISClient
            throttle 50ms (real) 위에 추가 50ms 안전 마진. 0 = 비활성.
        sleep_fn: injectable for tests (noop 으로 빠른 검증).

    Returns:
        (bars, dropped_dates) — bars 는 `(trade_date, trade_time)` ascending.
        dropped_dates = 전체 anchor 호출에서 발견된, target_date 외의 모든
        일자 union (ADR 0023 R-신규 — 운영 관찰성). 휴장일 호출 시 bars=[]
        + dropped_dates 가 KIS 가 반환한 직전 거래일 정보.

    Raises:
        _MinuteApiError: KIS rt_cd != "0".
        pydantic.ValidationError: 응답 schema 위반 (KIS drift 알람).
    """
    seen: dict[tuple[date, time], _MinuteBar] = {}
    all_dropped: set[date] = set()
    for i, anchor in enumerate(paging_anchors):
        if i > 0 and inter_anchor_sleep_sec > 0:
            sleep_fn(inter_anchor_sleep_sec)
        body = client.request(
            "GET",
            _MINUTE_PATH,
            tr_id=_MINUTE_TR_ID,
            params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": asset_code,
                "FID_INPUT_HOUR_1": anchor,
                "FID_PW_DATA_INCU_YN": "Y" if include_past else "N",
            },
        )
        page, dropped = _parse_kis_response(
            body, asset_code=asset_code, expected_date=target_date
        )
        all_dropped.update(dropped)
        for bar in page:
            # setdefault = 첫 발견 유지 (보통 최신 anchor 가 최신 데이터).
            seen.setdefault((bar.trade_date, bar.trade_time), bar)
    sorted_bars = sorted(seen.values(), key=lambda b: (b.trade_date, b.trade_time))
    return sorted_bars, frozenset(all_dropped)
