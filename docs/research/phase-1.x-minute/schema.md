# KIS 분봉 API 응답 schema (ADR 0023 §10.1 / 세그먼트 1.2.1.a)

> **박제 일자**: 2026-05-31
> **본질**: `inquire-time-itemchartprice` 실 KIS 서버 응답 4종 cross-verify schema 박제. 1.2.1.b KIS 분봉 다운로더 구현 root.
> **Sample**: `sample-{069500,132030,005930,035900}.json` (본 디렉토리). probe = `scripts/probe_kis_minute.py`.
> **Cross-reference**: ADR 0020 §2.2 (KIS 매핑 표 분봉 row) + §5.2 (실증 박제) / ADR 0023 §10.1 (세그먼트 1.2.1) / CLAUDE.md §2.3 (Decimal) / §3.2 (시계 주입) / §5.1 (외부 데이터 검증).

---

## 1. Endpoint

| 항목 | 값 |
|------|---|
| Method | `GET` |
| Path | `/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice` |
| TR_ID | `FHKST03010200` (실/모의 공통 — 시세, `FH...`) |
| Throttle | KIS real 20/s, paper 2/s (ADR 0020 §2.3) |
| Auth | OAuth2 Bearer token (KISAuth, 23h TTL) |

### Params

| Name | Value | 비고 |
|------|-------|------|
| `FID_ETC_CLS_CODE` | `""` (빈 문자열) | 기본값 |
| `FID_COND_MRKT_DIV_CODE` | `"J"` | 일봉과 동일 (시장 구분 — 주식) |
| `FID_INPUT_ISCD` | 6자리 숫자 문자열 | 종목 코드 (예: `069500`) |
| `FID_INPUT_HOUR_1` | `HHMMSS` (6자리) | 조회 종료 시각 — 이 시각 직전 30봉 반환 |
| `FID_PW_DATA_INCU_YN` | `"Y"` / `"N"` | 과거 데이터 포함 여부 |

---

## 2. Response (top-level)

```json
{
  "rt_cd": "0",
  "msg_cd": "MCA00000",
  "msg1": "정상처리 되었습니다.",
  "output1": { ... },
  "output2": [ ... ]
}
```

- `rt_cd != "0"` → 실패 (KIS 공통 컨벤션, `KISApiError` 처리).
- 4종 모두 `rt_cd="0"` 확인.

---

## 3. `output1` (단일 객체 — 종목 메타 + 현재가)

| Field | Sample (069500) | Dtype | 의미 |
|-------|------------------|-------|------|
| `hts_kor_isnm` | `"KODEX 200"` | str | 종목명 (한글) |
| `stck_prpr` | `"134815"` | str→Decimal | 현재가 |
| `stck_prdy_clpr` | `"129990"` | str→Decimal | 전일 종가 |
| `prdy_vrss` | `"4825"` | str→Decimal | 전일대비 (절대값) |
| `prdy_vrss_sign` | `"2"` | str (enum) | 부호: 1=상한 / 2=상승 / 3=보합 / 4=하한 / 5=하락 |
| `prdy_ctrt` | `"3.71"` | str→Decimal | 전일대비율 (%) |
| `acml_vol` | `"18852382"` | str→int | 누적 거래량 |
| `acml_tr_pbmn` | `"2525014806132"` | str→int (KRW) | 누적 거래대금 |

**`output1` 의 의도**: 호출 시점 현재가 + 메타. 분봉 backtest/dry-run 로직에는 직접 사용 zero (output2 의 bar 데이터로 충분). production 에서 cron 알림 / 디버깅 용도.

---

## 4. `output2[]` (분봉 배열 — descending order, 직전 30봉)

| Field | Sample (069500 15:30 봉) | Dtype | 의미 |
|-------|---------------------------|-------|------|
| `stck_bsop_date` | `"20260529"` | str YYYYMMDD | 거래일 |
| `stck_cntg_hour` | `"153000"` | str HHMMSS | 체결 시각 (분 단위 박제 — 초 자리 = `00`) |
| `stck_oprc` | `"134815"` | str→Decimal | open |
| `stck_hgpr` | `"134815"` | str→Decimal | high |
| `stck_lwpr` | `"134815"` | str→Decimal | low |
| `stck_prpr` | `"134815"` | str→Decimal | close |
| `cntg_vol` | `"165274"` | str→int | 해당 분 체결 거래량 (1분 단위) |
| `acml_tr_pbmn` | `"2324598621492"` | str→int (KRW) | 누적 거래대금 (해당 분까지) |

### 4.1 Order

- **Descending by `stck_cntg_hour`**. `output2[0]` = 가장 최근 = 호출 시각 직전 봉.
- 4종 sample 모두 `output2[0]` = `153000` (15:30 봉), `output2[29]` = `150100` (15:01 봉).

### 4.2 1봉 정의

- `stck_cntg_hour="HHMM00"` 의 분봉 = `[HH:MM-1:00, HH:MM:00)` 구간 거래.
  - 예: `stck_cntg_hour="150100"` = 15:00:00 ~ 15:01:00 구간 1분.
  - 예: `stck_cntg_hour="153000"` = 15:29:00 ~ 15:30:00 구간 1분 (동시호가 단일가 체결).

### 4.3 Zero-volume 봉

- 장중 거래 없는 분도 `cntg_vol=0` 으로 1봉 잡힘 — OHLC 는 직전 거래 가격 그대로 (가격 변화 zero).
- 069500 sample 의 15:20~15:29 = 모두 `cntg_vol=0`, `stck_oprc=stck_hgpr=stck_lwpr=stck_prpr=134310` (15:19 마지막 거래 가격).
- 일봉의 zero-volume 행 skip (KISMarketData `_fetch_ohlcv_page` `stck_clpr == 0` 행 skip) 와 달리, **분봉은 zero-volume 보존** — timeline 연속성 + grid level pass 감지 (volume 없어도 price drift 가능).

### 4.4 동시호가

- 09:00 (시가) 와 15:30 (종가) 의 단일가 체결도 1분봉으로 잡힘.
- 069500 15:30 봉: `cntg_vol=165274` = 동시호가 단일가 체결 거래량.
- **OHLC 4가 동일** 빈도 ↑ (069500 = `O=H=L=C=134815`).

---

## 5. Paging 전략 (하루 390봉 확보)

KIS 분봉 API = 단발 호출 ≤ 30봉. 하루 390봉 = **13 호출** / 종목.

### 5.1 시간 후퇴 paging

호출 1 → `FID_INPUT_HOUR_1=153000` → 15:01 ~ 15:30 (30봉).
호출 2 → `FID_INPUT_HOUR_1=150000` → 14:31 ~ 15:00 (30봉).
…
호출 13 → `FID_INPUT_HOUR_1=093000` → 09:01 ~ 09:30 (30봉, 시가 09:01 포함).

추가 호출 → `FID_INPUT_HOUR_1=090100` → 09:00 단봉 (시가 동시호가 단일가).

→ **호출 14회 / 종목 / 거래일** = 14 × 4종 = 56 호출 / 일. KIS real 20/s 의 0.7% — 부담 zero.

### 5.2 Dedup

`output2[]` 의 인접 호출 간 경계 봉 중복 (예: 호출 1 의 15:01 = 호출 2 의 15:00 직후 봉) 가능 — `(stck_bsop_date, stck_cntg_hour)` 키로 dedup.

### 5.3 휴장일 처리

- 휴장일 (예: 5/30 부처님오신날) 호출 시 KIS 가 **직전 거래일 (5/29) 데이터** 반환.
- cron 이 휴장일에 호출 = 동일 데이터 중복 → manifest dedup (`new_dates ⊂ already-recorded` → no-op).
- 안전한 cron 시점 = KRX 마감 후 16:00 KST (장중 1분봉 호출은 backtest 데이터 수집과 무관, dry-run/live runner 별도 경로).

### 5.4 Quota 계산

| 시나리오 | 호출 수 | KIS quota 사용 |
|----------|---------|----------------|
| 4종 × 1일 분봉 다운로드 | 56 | 16 sec (real 20/s 기준 0.05% / 일) |
| 4종 × 6개월 (125영업일) 초기 backfill | 7,000 | ~6분 (1회성) |
| 4종 × 5년 (1,250영업일) bulk | 70,000 | ~1시간 (OQ2 외부 vendor 검토) |

---

## 6. Pydantic strict model (1.2.1.b 산출 — 본 § 6 = 설계 spec)

`src/research/dgt_minute/_kis_minute_models.py` (5th ring 격리 — production `KISTimePriceResponse` 와 별도, 분봉 production 통합 시 별도 ADR).

```python
# 설계 sketch — 1.2.1.b 산출
class _KISMinuteBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stck_bsop_date: str  # YYYYMMDD
    stck_cntg_hour: str  # HHMMSS (분 단위)
    stck_oprc: Decimal
    stck_hgpr: Decimal
    stck_lwpr: Decimal
    stck_prpr: Decimal  # close
    cntg_vol: int
    acml_tr_pbmn: int

class _KISMinuteOutput1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hts_kor_isnm: str
    stck_prpr: Decimal
    stck_prdy_clpr: Decimal
    prdy_vrss: Decimal
    prdy_vrss_sign: str
    prdy_ctrt: Decimal
    acml_vol: int
    acml_tr_pbmn: int

class _KISMinuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rt_cd: str
    msg_cd: str
    msg1: str
    output1: _KISMinuteOutput1
    output2: tuple[_KISMinuteBar, ...]
```

- `extra="forbid"`: KIS schema drift 즉시 발견 (CLAUDE.md §5.1).
- `Decimal` 자동 변환: pydantic 가 `str` → `Decimal` (float 경유 zero).
- `frozen=True`: 도메인 모델 invariant.

---

## 7. CSV 저장 형식 (1.2.1.b 산출 — 본 § 7 = 설계 spec)

`data/historical/minute/{code}/{YYYY-MM-DD}.csv` (ADR 0023 §8.2 amendment — parquet → csv).

```csv
trade_date,trade_time,open,high,low,close,volume
2026-05-29,09:01:00,129500,129700,129450,129600,12345
2026-05-29,09:02:00,129600,129650,129500,129550,8901
...
2026-05-29,15:30:00,134810,134815,134810,134815,165274
```

- `trade_date` = `YYYY-MM-DD` (CSV human-readable, KIS `stck_bsop_date` 변환).
- `trade_time` = `HH:MM:SS` (3-digit human-readable, KIS `stck_cntg_hour` 변환).
- 모든 가격 = Decimal (CSV string round-trip 안전).
- **Ascending order** (KIS descending → 저장 ascending). backtest iteration 자연.

---

## 8. 1.2.1.b 진입 산출 plan

본 § 8 = 다음 commit (1.2.1.b) 의 산출 plan (구현 진입 직전).

| 파일 | 본질 | 의존 |
|------|------|------|
| `src/research/dgt_minute/_kis_minute_models.py` | Pydantic strict response model (§6) | pydantic / Decimal |
| `src/research/dgt_minute/_kis_minute_downloader.py` | KISClient 호출 + paging (§5) + dedup (§5.2) + 휴장일 무시 (§5.3) + CSV write (§7) + manifest update | _kis_minute_models / _manifest / KISClient |
| `scripts/fetch_kis_minute_daily.py` | cron 진입점 (argparse: `--codes`, `--date`, `--lookback-days`, `--data-root`) | downloader / 알림 (선택) |
| `tests/research/test_minute_downloader.py` | 응답 model parse / paging dedup / CSV round-trip / manifest update | fixtures: sample-*.json |

게이트: G1 회귀 zero / AC7 manifest 가용성 / R3 KIS quota / R8 cron 실패 알림.

---

*세그먼트 1.2.1.a 박제 완료 (2026-05-31). 1.2.1.b 구현 진입 ready.*
