# Phase 0.9.1 회고 — 개별 주식 인프라 검증 (005930 + 005380)

> Phase 0.9.1 narrative 회고. 작성일: 2026-05-07. sub-step 0.9.k.
> 정량 결과 + 분석은 ADR 0005 §6 박제 (sub-step 0.9.j). 결정 박제: ADR
> 0005 §1 (라운드 #12 — Phase 0.9 진입) + §3 (라운드 #13 — sub-step
> 0.9.d ↔ 0.9.f 합병) + §6 (Phase 0.9.1 결과 분석). 선행 회고:
> `phase-0.8.1.md` + `phase-0.8.md` (Phase 0.8 시리즈). 패턴 정합 (Phase
> 0.7.x / 0.8.x narrative 패턴).
>
> 본 회고 시점에 sub-step 0.9.l (게이트 판정 박제) + 0.9.m (Phase 0.9.2
> 진입 결정 라운드 #14) 미진행 — 후속 sub-step 에서 별도 박제.

---

## 1. 마일스톤

Phase 0.9 진입 (2026-05-07 ADR §1 라운드 #12) → 동일 일자 Phase 0.9.1
sub-step 시리즈 13 step 진행 + 백테스트 결과 분석 박제. **1 일 완료** —
Phase 0.7.x / 0.8.x 인프라 (BacktestRunner / AssetContext / yaml loader
/ MockBroker) 재사용 + Asset 모델 확장 (Market enum / listed_at) +
tick_size helper 도입 + 5 KR_STOCK 신규 종목 인프라 + 변수 1 차원 통제
(자산 종류 ETF → 개별 주식 만 변경).

### 1.1 sub-step 흐름

| sub-step | 내용 | commit |
|---|---|---|
| 0.9.a | ADR §1 라운드 #12 박제 (Phase 0.9 진입, 개별 주식 검증) | d83a89b |
| 0.9.b | CLAUDE.md §14 / §16 본문 갱신 (Phase 1 호환성 의식) | 8049535 |
| 0.9.c | 사전 검증 (`scripts/verify_phase_0_9_assets.py`) — 5 종 lookback 246 PASS | cb18d6a |
| 0.9.d Step 0 | ADR §3 박제 (라운드 #13 — sub-step 0.9.d ↔ 0.9.f 합병) | 6f0be8e |
| 0.9.d Step 1 | Asset 모델 확장 (Market / listed_at / delisted_at) + `src/domain/tick_size.py` helper + 도메인 단위 테스트 | 5574784 |
| 0.9.d Step 2 | 개별 주식 5 종 factory 신규 + composition 단위 테스트 | 4276a31 |
| 0.9.e | 다운로드 스크립트 일반화 (`scripts/download_kr_assets.py` rename + `--code` registry 통합 + `adjusted=True` 명시) | aaae13d |
| ~~0.9.f~~ | 폐기 (§3 박제로 0.9.d 와 합병) | — |
| 0.9.g | 8 종 데이터 다운로드 + 회귀 byte-identical PASS (3 ETF) + 5 KR_STOCK 신규 (ADR §4) | 03f7334 |
| 0.9.h | BacktestRunner 통합 + Phase 0.7.3 회귀 invariant 재실행 (H1/H2/H3 PASS, ADR §5) | d495fcb |
| 0.9.i | Phase 0.9.1 백테스트 실행 — 시나리오 C 게이트 2/3 (config 추가) | cdbb920 |
| 0.9.j | 결과 분석 + ADR §6 박제 (분산 효과 약화 본질) | 98f0b84 |
| **0.9.k** | **본 회고 + 후속 sub-step 미리보기** | (현재) |
| 0.9.l | 게이트 판정 박제 (시나리오 C / 게이트 2/3 PASS 정식 박제) | 다음 |
| 0.9.m | Phase 0.9.2 진입 결정 라운드 #14 | 후속 |

---

## 2. 완료 기준 충족 검증

ADR §1 (라운드 #12 진입 결정) + §1.11 (비교 baseline) + §1.2.3 (게이트
시나리오 A/B/C/D) 박제 그대로:

| 완료 기준 | 충족 | 근거 |
|---|---|---|
| 변수 1 차원 통제 (자산 종류 ETF → 개별 주식 만 변경) | ✅ | `strategies-0.9.1.yaml` = `strategies-0.7.3.yaml` + 종목 (069500/132030 → 005930/005380), 다른 모든 필드 동일 (drop=5.0 / max_split=7 / target=10 / cooldown=60 / EQUAL) |
| 회귀 invariant (Phase 0.7.x baseline 변경 zero) | ✅ | sub-step 0.9.h 에서 H1=0.3270 / H2=13.2280 / H3=0.5255 모두 정합 PASS (ADR §5) |
| CSV byte-identical 회귀 (3 ETF) | ✅ | sub-step 0.9.g 에서 069500 / 214980 / 132030 모두 `diff` exit=0 (ADR §4.2) |
| 5-year 백테스트 실행 | ✅ | 2020-01-02 ~ 2024-12-30 (1231 거래일) |
| 게이트 strict 평가 | ✅ | H1/H2/H3 strict 비교, ADR §6.1 박제 |
| 단위 테스트 + 통합 테스트 통과 | ✅ | 825 passed (797 → 825, +28 신규 — `test_tick_size.py` + `test_asset_csv.py` + composition Phase 0.9 추가) |
| ruff / mypy 통과 | ✅ | Phase 0.9.d / 0.9.e 도입 파일 모두 clean |
| Asset 모델 확장 무부작용 검증 | ✅ | sub-step 0.9.h 회귀 invariant 재실행 결과 = ADR §1.11 baseline 정합 (ADR §5) |

---

## 3. 5-year 결과 요약 (Phase 0.7.3 baseline 비교)

ADR §6.1 박제 표 인용:

| 지표 | Phase 0.7.3 baseline | Phase 0.9.1 | diff |
|---|---:|---:|---:|
| Total return % | 13.2280 | **18.8266** | **+5.5986** |
| CAGR % | 2.5779 | 3.5972 | +1.0193 |
| Max drawdown % | -8.2737 | **-22.6639** | **-14.3902** |
| Sharpe ratio | 0.5255 | **0.4139** | **-0.1116** |
| Calmar ratio | 0.3116 | 0.1587 | -0.1529 |
| Capital turnover | 0.3270 | **0.6173** | **+0.2903** |
| Cumulative buy KRW | 159,736,940 | 301,562,500 | +88.8% |
| Cumulative sells | 28 | 50 | +22 |
| Decisions: buys | (참고) | 61 | (참고) |
| Decisions: skips | (참고) | 2375 | (참고) |

**개선 4 (return / CAGR / turnover / sells) vs 악화 3 (MDD / Sharpe /
Calmar)** — Phase 0.8.1 동일 패턴 (자본 회전 ↑ + 절대 수익 ↑ vs 위험
분산 약화 + 위험조정 수익 미달).

---

## 4. 가설 검증 (ADR §1.2.3 게이트 strict)

| 가설 | 임계 | Phase 0.9.1 | 판정 | 학습 |
|---|---|---:|---|---|
| **H1** Capital turnover ≥ 0.3270 | strict | 0.6173 | ✅ PASS (+0.2903) | 개별 주식 변동성 ↑ → drop=5.0% trigger 자주 발생 |
| **H2** Total return % ≥ 13.2280 | strict | 18.8266 | ✅ PASS (+5.5986pp) | 5-year 추세 양호 (특히 005380 +86%) |
| **H3** Sharpe ratio ≥ 0.5255 | strict | 0.4139 | ❌ **FAIL** (-0.1116) | MDD 큰 폭 악화로 위험조정 수익 미달 |
| **통과** | ≥ 2/3 | **2/3** | **✅ PASS (시나리오 C)** | Phase 0.8.1 패턴 정확히 반복 |

**Final verdict — 시나리오 C (게이트 2/3 PASS)**:

- H1 + H2 통과 = 개별 주식 환경 (변동성 ↑) 의 trigger 빈도 + 절대 수익
  은 ETF baseline 보다 양호
- H3 미달 = MDD -8.27% → -22.66% (-14.39pp) 악화. **분산 효과 약화** 가
  본질 (ADR §6.6 박제)

**시나리오 분류 매칭** (ADR §1.2.3):

| 시나리오 | 예측 결과 | 매칭? |
|---|---|---|
| A: 3/3 PASS | Phase 1 직진 후보 | — |
| B: H1+H3 ✅, H2 ❌ | 수익률 trade-off | — |
| **C: H1+H2 ✅, H3 ❌** | **Phase 0.8.1 패턴 반복, H3 본질적 한계** | **매칭** |
| D: 1/3 PASS | 시스템 한계 | — |

---

## 5. 학습

### 5.1 분산 효과의 결정적 영향 — Phase 0.7.3 vs Phase 0.9.1

ADR §6.4 / §6.5 박제 인용:

| 차원 | Phase 0.7.3 (3/3 PASS) | Phase 0.9.1 (시나리오 C) |
|---|---|---|
| 종목 | 069500 (KODEX 200) + 132030 (KODEX 골드) | 005930 (삼성전자) + 005380 (현대차) |
| 자산군 분산 | **주식 + 골드** (낮은 상관성) | **KOSPI 대형주 2 종** (높은 상관성) |
| MDD | -8.27% | -22.66% |
| H3 | 0.5255 ✅ | 0.4139 ❌ |

→ **종목 자체 (ETF vs 개별 주식) 보다 분산 효과 (자산군 vs 단일 시장)
가 결정적**. Phase 0.7.3 의 골드 hedge 효과가 MDD 제한의 결정타였다는
가설 (ADR 0003 §18 박제) 이 Phase 0.9.1 결과로 **반대 방향** 에서 검증
됨 (분산 약화 시 H3 ❌).

### 5.2 Phase 0.8.1 패턴 정확히 반복 — H3 본질적 한계 가설 검증

ADR §6.5 박제:

| 지표 | Phase 0.7.3 baseline | Phase 0.8.1 (전략 변경) | Phase 0.9.1 (종목 변경) |
|---|---|---|---|
| H1 turnover | 0.3270 | 0.4188 | **0.6173** |
| H2 return | 13.23% | 14.06% | **18.83%** |
| H3 sharpe | **0.5255 ✅** | **0.2679 ❌** | **0.4139 ❌** |
| MDD | -8.27% | -21.28% | -22.66% |
| 게이트 결과 | 3/3 PASS | 2/3 (시나리오 C) | 2/3 (시나리오 C) |

→ **trade-off 패턴이 변경 차원 무관하게 동일하게 발현**:
- Phase 0.8.1 (전략 차원 — SupportLevelStrategy whipsaw): trigger ↑ →
  return ↑ vs MDD ↑ → Sharpe ↓
- Phase 0.9.1 (종목 차원 — 개별 주식 + 분산 약화): trigger ↑ → return
  ↑ vs MDD ↑ → Sharpe ↓

**ADR 0004 §7 박제 가설 ("PriceDropStrategy + 분산이 본질") 의 검증**:
- PriceDropStrategy 자체가 변하지 않아도 (Phase 0.9.1) 분산이 약하면
  H3 미달
- 분산 효과 약화 = H3 미달의 **충분 조건** (필요 조건 아님 — 다른
  경로 있음)

### 5.3 Lock-in loss 패턴 — 005930 split_level=7 가득찬 상태

ADR §6.3 박제:

- 005930 평단가 68,586 KRW vs 종료 시점 시장가 53,200 KRW (-22.4%) →
  unrealized_pnl = -7,801,100 KRW
- split_level=7 (가득찬 상태) → 추가 매수 차단 + 매도 trigger (+10%)
  도달 불가능 → 끝까지 보유
- realized_pnl 30M KRW vs unrealized_pnl -11M KRW → 수익 잠금
  (locked-in loss) 패턴

**시사점**:
- 강한 추세 하락 종목에서 max_split 가득찬 상태로 종료 = 손실 잠금
- 손절 정책 미도입 (ADR §1.9 박제) 의 직접적 영향
- Phase 1 ADR §1 에서 손절 정책 본격 검토 시 본 패턴 데이터 인용 가능
  (ADR 0002 §12.4.2 H3 거짓 대응 정합)

### 5.4 종목별 기여도 균등 — 시장 동조성 강함

ADR §6.2 박제: 005930 / 005380 buys 31/30, sells 24/26, realized_pnl
14M / 16M (47/53 split). **두 종목 거의 동등** — 둘 다 KOSPI 대형주
(반도체 + 자동차) 라 시장 동조성 강함.

→ 분산 효과는 종목 수가 아니라 **자산군 차이** 가 핵심. 5 종 (Phase
0.9.2) 으로 확장해도 모두 KOSPI 대형주이면 분산 효과 회복은 제한적
가능성 (ADR §6.6.3 박제 가설).

### 5.5 변수 통제의 가치 — 1 차원 변경 검증

Phase 0.9.1 = 자산 종류 (ETF → 개별 주식) **만 변경**. 다른 모든 변수
(자본 배분 / 매수 / 매도 / 재진입 / 기간) Phase 0.7.3 baseline 동일.
→ **단일 변수 변경의 효과를 정확히 측정** (ADR 0001 §1.3 / CLAUDE.md
§13 변수 통제 원칙 정합):
- Phase 0.5: 매도 + 재진입 1 차원 (3/3 → 1/4 미달, H2/H3 약화)
- Phase 0.7.1: 종목 수 1 차원 (단일 → 2 종, 0/3)
- Phase 0.7.2: 자본 배분 1 차원 (EQUAL/INV_VOL/VOL, 게이트 분리)
- Phase 0.7.3: 종목 조성 1 차원 (채권 → 골드, 3/3 PASS)
- Phase 0.8.1: 매수 패러다임 1 차원 (PriceDrop → SupportLevel, 시나리오 C)
- **Phase 0.9.1**: 자산 종류 1 차원 (ETF → 개별 주식, **시나리오 C**)

각 단계 변수 1 차원 변경의 효과를 누적 → 다음 단계 결정의 데이터 근거.

### 5.6 회귀 invariant 보존의 패턴 — Asset 확장 + tick_size 분기

sub-step 0.9.d / 0.9.e / 0.9.g / 0.9.h 종합 박제 (ADR §3 / §4 / §5):

- Asset 모델 확장 (`market` / `listed_at` / `delisted_at`) — 기존
  `tick_size` / `lot_size` 그대로 사용, 분기 분기 zero
- `tick_size` 의 `asset_class` 분기 — KR_ETF 는 단일값 그대로 (회귀
  invariant 보존), KR_STOCK 만 helper 호출
- `adjusted=True` 명시 갱신 — pykrx 기본값과 byte-identical (env 의존
  pykrx 버전 + 환경에서)
- Asset registry 8 종 확장 — 기존 3 ETF factory 동작 영향 zero (분기
  zero, 호출자 그대로)
- BacktestRunner / DailyOrchestrator / MockBroker — 신규 필드 사용 zero
  (필드 추가만, 동작 그대로)

→ Phase 0.7.3 회귀 invariant 결과 (H1=0.3270 / H2=13.23% / H3=0.5255)
정합 PASS (sub-step 0.9.h, ADR §5) 로 정량 입증.

### 5.7 sub-step 합병 박제의 가치 (ADR §3 라운드 #13)

원래 ADR §1.12 박제 = 0.9.d (Asset 확장) + 0.9.f (tick_size helper)
별도 sub-step. sub-step 0.9.c PASS 직후 0.9.d 진입 시점에 사용자 제안
으로 **합병 박제** (라운드 #13).

근거 (ADR §3.3.1 박제):
1. placeholder 의사결정 회피 — KR_STOCK factory 의 `tick_size` placeholder
   가 helper 도입 후 dead code 됨
2. 차원 분리 합리성 약함 — 둘 다 KR_STOCK 지원 본질의 일부
3. 회귀 invariant 위험 zero — KR_ETF 분기 보존
4. commit 양 적절 — Step 1 + Step 2 분리로 충분
5. 0.9.h~0.9.i 시점 helper 도입 보장

→ **박제된 결정도 변경 가능** — 단 ADR § 신규 박제 + 영향 범위 (CLAUDE.md
/ roadmap) 명시 갱신 후 진행. 데이터 근거 (placeholder = dead code 증거)
로 결정 변경 정당성 확보.

---

## 6. 발견된 이슈 / 제약

### 6.1 lock-in loss — split_level 가득찬 상태 종료

ADR §6.3 박제. 005930 split_level=7 으로 종료 → 추가 매수 차단 + 매도
trigger 미도달 → 끝까지 보유. 손절 정책 미도입 (ADR §1.9) 의 직접적
영향. Phase 1 ADR §1 에서 본격 검토.

### 6.2 분산 효과 약화 — KOSPI 대형주 2 종 한계

ADR §6.4 박제. 005930 (반도체) + 005380 (자동차) 둘 다 KOSPI 대형주 →
시장 동조성 강함. Phase 0.7.3 의 주식+골드 분산 효과 (자산군 차이) 와
는 다른 차원.

→ Phase 0.9.2 (5 종 업종 다양화) 가설로 검증 — 업종 다양화로 H3 회복
가능 여부가 핵심.

### 6.3 KRX_ID / KRX_PW 경고 (정보)

다운로드 시 `KRX 로그인 실패: KRX_ID 또는 KRX_PW 환경 변수가 설정되지
않았습니다.` 경고 출력. 일별 OHLCV fetch 는 무관 (KRX 로그인 없이 정상
동작). 일중 데이터 사용 시에만 KRX 로그인 필요 (Phase 0.9 미사용).

### 6.4 손절 정책 미도입의 trade-off (ADR §1.9 박제)

Phase 0.9 본질 = 인프라 검증, 변수 통제 strict. 손절 정책 도입 시 변수
추가 → 변수 통제 위반. 005930 lock-in loss (§6.1) 가 직접적 영향이지만
Phase 0.9 동안 처방 거부 박제. Phase 1 ADR §1 본격 검토 (ADR 0002
§12.4.2 H3 거짓 대응 정합).

### 6.5 후행 편향 단순화 (ADR §1.6.3 / §1.10 박제)

5 종 모두 2026-05-07 시점 살아있는 종목 (상장 폐지 X) — 백테스트 결과
는 **낙관적 추정**. Phase 1+ 정교화 (상장 폐지 종목 포함) 보류. 본 회고
시점에 실거래 결과는 본 백테스트 결과보다 낮을 수 있음 인지.

---

## 7. ADR §6 박제 결과 (sub-step 0.9.j)

ADR 0005 §6 박제 그대로 — 본 회고는 narrative 보강 + 시각화. 결정 박제
요약:

### 7.1 결과 박제

- H1=0.6173 ✅ / H2=18.8266% ✅ / H3=0.4139 ❌ → **시나리오 C**
- 게이트 2/3 PASS (ADR §1.2.3 박제 시나리오 매칭)
- 종목별 기여도 47/53 split (시장 동조성 강함)
- Final snapshot lock-in loss 패턴 (005930 split_level=7)

### 7.2 분석 박제

- Phase 0.7.3 baseline 차이의 본질 = 분산 효과 (자산군 vs 단일 시장)
- Phase 0.8.1 패턴 정확히 반복 (변경 차원 무관)
- "PriceDropStrategy + 분산이 본질" 가설 (ADR 0004 §7) 데이터 검증

### 7.3 후속 sub-step 미박제

- **0.9.l (게이트 판정 박제)** — 시나리오 C / 게이트 2/3 PASS 정식 박제
  (본 회고 §4 의 분석 결과를 ADR §7 (가칭) 으로 박제)
- **0.9.m (Phase 0.9.2 진입 결정 라운드 #14)** — 후속 trajectory:
  - 옵션 1: Phase 0.9.2 진입 (5 종 분산 효과 검증)
  - 옵션 2: Phase 0.9 종료 + Phase 1 직진 (게이트 2/3 = 진입 자격 충족)
  - 옵션 3: 기타 (사용자 결정)

→ **0.9.m 라운드 #14 결정 후 Phase 0.9.2 또는 Phase 1 진입**.

---

## 8. 후속 권고 (Phase 0.9.2 / Phase 1)

### 8.1 Phase 0.9.2 진입 시 (ADR §1.6.2 박제)

| 항목 | Phase 0.9.2 default |
|---|---|
| **종목** | **5 종**: 005930 + 005380 + 055550 신한지주 + 097950 CJ제일제당 + 015760 한국전력 |
| **업종 분산** | 반도체 / 자동차 / 금융 / 소비재 / 에너지 |
| 자본 배분 | EQUAL (Phase 0.9.1 동일) |
| 매수 / 매도 / 재진입 | Phase 0.9.1 동일 (drop=5.0 / target=10 / cooldown=60) |
| 게이트 | Phase 0.7.3 baseline strict (Phase 0.9.1 동일) |

**가설 (ADR §6.6.3 박제)**: 업종 다양화 → 분산 효과 회복 시 시나리오
C → A / B 변경 가능. 다만 모두 KOSPI 대형주 → 자산군 분산 (Phase 0.7.3
골드) 만큼 강하지 않을 가능성.

### 8.2 Phase 1 직진 시 (Phase 0.9 종료 결정)

게이트 2/3 PASS = 진입 자격 충족. Phase 1 ADR 0007 (가칭, 기존 ADR 0006 명명 변경 — ADR 0005 §11.5) 박제 항목
(CLAUDE.md §16.5 박제):
1. KIS API 어댑터 (BrokerPort / MarketDataPort 구현)
2. 손절 정책 — H3 거짓 대응 + lock-in loss 처방 (ADR §6.3 인용)
3. 텔레그램 알림
4. 종목별 vs 전체 kill switch / 자산 격리 정지
5. partial fill 처리 ADR
6. 거래세 / 수수료 모델링 (`OrderResult.tax` / `commission` 필드)
7. 모의투자 → 실거래 전환 게이트
8. SupportLevelStrategy + cooldown 도입 검토 (ADR 0004 §7.3.2 인용)

### 8.3 Phase 0.9.x 가능성

ADR 0005 §1.13 박제 그대로:
- SupportLevelStrategy + 개별 주식 결합 (Phase 0.8 보존, ADR 0004 §1.10)
- Phase 0.7.4 (부동산 분산) — ADR 0003 §18.12.4 placeholder
- 박영옥 가치주 스타일 자동 식별 — Phase 0.9.x 또는 Phase 1+
- 그리드 트레이딩 — Phase 0.10+ placeholder

---

## 9. 지표 요약

| 지표 | Phase 0.7.3 | Phase 0.8.1 | Phase 0.9.1 | gate (vs 0.7.3) |
|---|---:|---:|---:|---|
| Total return % | 13.2280 | 14.0586 | **18.8266** | **H2 ✅ +5.60pp** |
| CAGR % | 2.5779 | 2.7392 | 3.5972 | |
| Max drawdown % | -8.2737 | -21.2815 | **-22.6639** | (H3 동반) |
| Sharpe ratio | 0.5255 | 0.2679 | **0.4139** | **H3 ❌ -0.1116** |
| Calmar ratio | 0.3116 | 0.1287 | 0.1587 | (H3 동반) |
| Capital turnover | 0.3270 | 0.4188 | **0.6173** | **H1 ✅ +0.2903** |
| Cumulative buy KRW | 159,736,940 | (참고) | 301,562,500 | |
| Cumulative sells | 28 | 33 | 50 | |
| **Gate verdict** | **3/3 strict PASS** | **2/3 (시나리오 C)** | **2/3 (시나리오 C)** | |

→ Phase 0.8.1 + Phase 0.9.1 모두 시나리오 C — H3 본질적 한계 가설
검증 (ADR §6.5 박제).

---

## 10. Phase 0.9.1 → Phase 0.9.2 (또는 Phase 1) 진입 체크포인트

- [x] ADR 0005 §1 (라운드 #12 — Phase 0.9 진입) 박제
- [x] CLAUDE.md §14 / §16 본문 갱신 (Phase 1 호환성 의식)
- [x] 사전 검증 (`scripts/verify_phase_0_9_assets.py`) 5 종 PASS
- [x] ADR 0005 §3 박제 (라운드 #13 — sub-step 0.9.d ↔ 0.9.f 합병)
- [x] Asset 모델 확장 (Market / listed_at / delisted_at) + `src/domain/tick_size.py` helper
- [x] 개별 주식 5 종 factory 신규 + composition 단위 테스트
- [x] 다운로드 스크립트 일반화 (`scripts/download_kr_assets.py`)
- [x] 8 종 5-year 데이터 다운로드 + 회귀 byte-identical PASS (3 ETF) + ADR §4
- [x] BacktestRunner Phase 0.7.3 회귀 invariant 재실행 (H1/H2/H3 PASS) + ADR §5
- [x] config/strategies-0.9.1.yaml + Phase 0.9.1 백테스트 실행
- [x] ADR §6 박제 (결과 분석 + 시나리오 C + 분산 효과 본질)
- [x] 본 narrative 회고 (`phase-0.9.1.md`)
- [ ] sub-step 0.9.l — 게이트 판정 박제 (ADR §7 가칭, 시나리오 C / 게이트 2/3 PASS 정식 박제) — 다음
- [ ] sub-step 0.9.m — Phase 0.9.2 진입 결정 라운드 #14 (Phase 0.9.2 vs Phase 1 vs 기타) — 후속

---

> Phase 0.9.1 narrative 회고 완료. 다음 단계 = sub-step 0.9.l (게이트
> 판정 박제) → 0.9.m (Phase 0.9.2 진입 결정 라운드 #14) — 사용자 명시
> 결정 후 박제.
