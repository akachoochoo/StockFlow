# Phase 0.9 시리즈 회고 — 개별 주식 검증 (인프라 + 분산 효과)

> Phase 0.9 시리즈 (0.9.1 + 0.9.2) narrative 종합 회고. 작성일:
> 2026-05-08. sub-step 0.10.a (Phase 0.9 시리즈 종료 + Phase 0.10 진입
> commit 동시).
>
> 정량 결과: `phase-0.9.1.md` (인프라 검증) + `phase-0.9.2.md` (분산
> 효과). 결정 박제: ADR 0005 §1 (라운드 #12 — Phase 0.9 진입) + §3
> (라운드 #13 — sub-step 합병) + §6 / §9 (결과 분석) + §7 / §10 (게이트
> 정식 박제) + §11 (라운드 #15 — 시리즈 종료 + Phase 0.10 진입). 선행
> 회고: `phase-0.7.md` / `phase-0.8.md`. 패턴 정합 (Phase 0.7 / 0.8
> 시리즈 회고 패턴).

---

## 1. 마일스톤

Phase 0.9 진입 (2026-05-06) → ADR 0005 §1 라운드 #12 박제 (2026-05-07)
→ Phase 0.9.1 sub-step 0.9.a~0.9.m 진행 (2026-05-07) → Phase 0.9.2
sub-step 0.9.2.a~0.9.2.f 진행 (2026-05-07~2026-05-08) → 라운드 #15 박제
(2026-05-08 — Phase 0.9 시리즈 종료 + Phase 0.10 진입). **3 일 완료**
(인프라 모두 사전 준비됨 + sub-step 합병 박제 — 라운드 #13).

### 1.1 sub-step 흐름 종합

| Phase | sub-step | 내용 | commit |
|---|---|---|---|
| 0.9 진입 | 0.9.a | ADR §1 라운드 #12 박제 | d83a89b |
| | 0.9.b | CLAUDE.md §14 / §16 본문 갱신 | 8049535 |
| 0.9.1 인프라 | 0.9.c | 사전 검증 (5 종 PASS) — ADR §2 | cb18d6a |
| | 0.9.d Step 0 | ADR §3 박제 (라운드 #13 — 0.9.d ↔ 0.9.f 합병) | 6f0be8e |
| | 0.9.d Step 1 | Asset 모델 확장 + tick_size helper + 단위 테스트 | 5574784 |
| | 0.9.d Step 2 | 개별 주식 5 종 factory 신규 + composition 테스트 | 4276a31 |
| | 0.9.e | 다운로드 스크립트 일반화 (`download_kr_assets.py`) | aaae13d |
| | 0.9.g | 8 종 데이터 다운로드 + 회귀 byte-identical PASS — ADR §4 | 03f7334 |
| | 0.9.h | BacktestRunner + Phase 0.7.3 회귀 invariant — ADR §5 | d495fcb |
| | 0.9.i | Phase 0.9.1 백테스트 실행 (시나리오 C 게이트 2/3) | cdbb920 |
| | 0.9.j | 결과 분석 + ADR §6 박제 | 98f0b84 |
| | 0.9.k | 회고 (`phase-0.9.1.md`) | 55004d8 |
| | 0.9.l | 게이트 판정 박제 — ADR §7 | 5498fe2 |
| | 0.9.m | Phase 0.9.2 진입 결정 라운드 #14 — ADR §8 | e806ef7 |
| 0.9.2 분산 | 0.9.2.a | (0.9.m 동시 commit) | (e806ef7) |
| | 0.9.2.b | yaml + 5 종 백테스트 실행 (시나리오 C 또 발현) | e5d5f04 |
| | 0.9.2.c | 결과 분석 + ADR §9 박제 (자산군 분산 일반화) | 2e04dde |
| | 0.9.2.d | 회고 (`phase-0.9.2.md`) | 45d857c |
| | 0.9.2.e | 게이트 판정 박제 — ADR §10 | a7bd7b6 |
| 0.9 종료 | **0.9.2.f / 0.10.a** | **본 commit — Phase 0.9 종료 라운드 #15 (ADR §11) + Phase 0.10 진입 (ADR 0006 §1) + 본 회고 + CLAUDE.md §16 in-place 갱신 + ADR 0006/0007 명명 변경** | (현재) |

총 18 commits (sub-step 합병 박제 적용 후) — Phase 0.7 시리즈 (각 sub-step
별 약 5~7 commits, 총 약 25 commits) 보다 압축. 인프라 재사용 + 합병
박제의 효과.

---

## 2. 시리즈 변수 통제 (Phase 0.7 / 0.8 패턴 정합)

### 2.1 Phase 0.5 ~ Phase 0.9.2 누적 학습 (ADR 0001 §1.3 / CLAUDE.md §13)

| Phase | 변수 차원 | 게이트 | 시나리오 | 학습 |
|---|---|---|---|---|
| 0.5 | 매도 + 재진입 | 1/4 | (단일 종목) | F (Hybrid cooldown=60) > D-2 (MovingAverage) |
| 0.7.1 | 종목 수 (1→2, 채권) | 0/3 | — | 채권 분산 효과 약함 |
| 0.7.2 | 자본 배분 (EQUAL/INV_VOL/VOL) | 분리 박제 | — | EQUAL = baseline, VOL trade-off |
| **0.7.3** | 종목 조성 (채권→골드) | **3/3 PASS** | **A** | **자산군 분산 = success factor** |
| 0.8.1 | 매수 패러다임 (PriceDrop→SupportLevel) | 2/3 | C | trade-off 패턴 (whipsaw) |
| **0.9.1** | **자산 종류 (ETF→개별 주식)** | **2/3** | **C** | **종목 자체 ≠ 분산** |
| **0.9.2** | **종목 수 + 업종 분산 (2→5)** | **2/3** | **C** | **KOSPI 대형주 분산도 ≠ 자산군 분산** |

→ **Phase 0.9 시리즈 = 자산군 분산 일반화의 최종 검증 단계**.

### 2.2 변수 통제의 strict 준수 (ADR 0005 §1.11 박제)

Phase 0.9.1 (vs Phase 0.7.3): **자산 종류만 변경** (ETF → 개별 주식).
Phase 0.9.2 (vs Phase 0.9.1): **종목 수 + 업종 분산만 변경** (2 → 5).
다른 모든 변수 (매수/매도/재진입/배분/기간) 동일.

→ 단일 변수 변경의 효과를 정확히 측정 가능 → 학습 신뢰성 ↑.

---

## 3. 게이트 결과 종합 (4 Phase 누적)

| 지표 | 0.7.3 | 0.8.1 | 0.9.1 | 0.9.2 | trend (0.7.3 → 0.9.2) |
|---|---:|---:|---:|---:|---|
| Total return % | 13.23 | 14.06 | **18.83** | 14.87 | 비단조 (0.9.1 peak) |
| CAGR % | 2.58 | 2.74 | **3.60** | 2.88 | 비단조 |
| Max drawdown % | -8.27 | -21.28 | -22.66 | **-37.65** | **단조 ↓ (악화)** |
| Sharpe ratio | **0.5255** | 0.2679 | 0.4139 | **0.2424** | 비단조 (0.7.3 max) |
| Calmar ratio | **0.3116** | 0.1287 | 0.1587 | **0.0765** | 비단조 |
| Capital turnover | 0.3270 | 0.4188 | 0.6173 | **1.1893** | **단조 ↑** |
| Cumulative buy KRW | 159.7M | (참고) | 301.6M | 580.9M | 단조 ↑ (3.64x) |
| Cumulative sells | 28 | 33 | 50 | 89 | 단조 ↑ (3.18x) |
| **Gate verdict** | **3/3 (A)** | **2/3 (C)** | **2/3 (C)** | **2/3 (C)** | **0.7.3 만 시나리오 A** |

**핵심 trend**:
- **MDD 단조 악화** (-8.27% → -37.65%) — 자산군 분산 부재의 직접 영향
- **Capital turnover 단조 증가** — 종목 수 / 변동성 비례
- **Sharpe / Calmar 0.7.3 max** — 자산군 분산이 위험조정 수익의 결정적 요인
- **Return / CAGR 비단조** — 종목 자체 추세에 의존적

---

## 4. 학습 — "자산군 분산 = H3 회복의 충분 조건" 일반화 박제 (ADR §9.6.2)

### 4.1 일반화 명제 (정식 박제)

> 1. **자산군 분산** (KR 주식 + 비주식, 예: 골드) = H3 회복의 충분 조건
> 2. KOSPI 대형주만으로는 종목 수 / 업종 분산 무관하게 H3 회복 불가
> 3. PriceDropStrategy 의 trade-off 패턴 (변동성 ↑ → return ↑ vs MDD ↑
>    → Sharpe ↓) 이 자산군 분산 약화 시 항상 발현

### 4.2 검증 경로 (3 회 반복)

| Phase | 변경 차원 | 자산군 분산 | H3 결과 |
|---|---|---|---|
| 0.7.3 | (baseline) | **주식 + 골드** | **0.5255 ✅** |
| 0.8.1 | 전략 변경 (SupportLevel) | 주식 + 골드 (정책 약화) | 0.2679 ❌ |
| 0.9.1 | 종목 변경 (개별 주식) | KOSPI 대형주 (자산군 약화) | 0.4139 ❌ |
| 0.9.2 | 종목 수 + 업종 변경 | KOSPI 대형주 (5 종 다양 업종) | 0.2424 ❌ |

→ **자산군 분산 약화 = H3 미달의 충분 조건**. ADR 0004 §7 박제
("PriceDrop + 분산이 본질") 의 **3 회 반복 검증 완료**.

### 4.3 Phase 0.9.1 + 0.9.2 신규 발견 패턴

#### 4.3.1 Lock-in 패턴 (ADR §6.3 / §9.3.1)

| Phase | split_level=7 lock-in 종목 수 | unrealized_pnl_total |
|---|---|---|
| 0.9.1 (2 종) | 1 (005930) | -11.1M KRW |
| 0.9.2 (5 종) | **3 (005930+015760+097950)** | **-38.0M KRW** (3.41 배) |

→ 종목 수 증가 시 lock-in 종목 수 비례 증가. 시장 동조성 강함 (KOSPI
대형주) → 동시 하락 → 동시에 매도 trigger 미달 → 자본 잠금.

→ **Phase 1 ADR 0007 손절 정책 trigger** (CLAUDE.md §16.5 + ADR 0005
§10.6.3 박제).

#### 4.3.2 자본 분산 부족 (ADR §9.4.1)

| Phase | insufficient_balance skip | 자본 / 최대 필요 |
|---|---:|---|
| 0.9.1 (2 종) | 0 | 100M / 70M (충분) |
| **0.9.2 (5 종)** | **1299** | **100M / 175M (부족)** |

→ 산식: 5 종 × max_split=7 × per_split=5M = 175M 필요. 자본 100M 으로
21% skip 발생.

→ **Phase 1 ADR 0007 자본 배분 정교화 trigger**.

### 4.4 Phase 0.7.3 의 진정한 success factor 분해

| 차원 | Phase 0.7.3 | 효과 |
|---|---|---|
| 정책 (PriceDrop + EQUAL + cooldown) | 동일 (Phase 0.7.x / 0.9.x 모두) | H3 결과 차이 본질 아님 |
| **자산군 분산 (주식 + 골드)** | **유일** | **유일하게 H3 PASS** |
| 종목 수 (2 vs 5) | 변경 무관 | H3 회복 효과 zero |
| 업종 분산 | Phase 0.9.2 5 업종 다양화에도 H3 ❌ | H3 회복 효과 zero |

---

## 5. Phase 0.9 인프라 검증 결과 (본질 100% 충족)

ADR 0005 §1 박제 본질 = **개별 주식 인프라 검증**:

| 인프라 항목 | 검증 결과 | 박제 위치 |
|---|---|---|
| Asset 모델 확장 (Market / listed_at / delisted_at) | ✅ PASS | ADR §3 / §5 |
| tick_size helper (`src/domain/tick_size.py`) | ✅ PASS (KR_ETF 회귀 invariant 보존) | ADR §5 |
| 다운로드 스크립트 일반화 | ✅ PASS (3 ETF byte-identical) | ADR §4 |
| Asset registry 8 종 확장 | ✅ PASS (단위 테스트 + 통합 테스트) | sub-step 0.9.d Step 2 |
| BacktestRunner 통합 (KR_STOCK 8 종 처리) | ✅ PASS | ADR §5 / §6 / §9 |
| 5-year 백테스트 실행 가능 (8 종) | ✅ PASS | ADR §4 / §6 / §9 |
| 인프라 부작용 zero (회귀 invariant 4 측면) | ✅ PASS | ADR §5 |

→ **Phase 0.9 본질 충족**. H3 미달 = Phase 0.9 본질 외 차원 (자산군
분산 = Phase 1+ 도입 영역).

---

## 6. 발견된 이슈 / 제약 (Phase 1 ADR 0007 trigger)

### 6.1 Lock-in loss 패턴 → Phase 1 손절 정책 trigger

ADR §6.3 / §9.3.1 박제. 005930 / 015760 / 097950 split_level=7 가득찬
상태 + 매도 trigger 미달 → 끝까지 보유 → -38M unrealized loss. Phase 1
ADR §1 손절 정책 본격 검토 (ADR 0002 §12.4.2 H3 거짓 대응 정합).

### 6.2 Insufficient balance → Phase 1 자본 배분 정교화 trigger

ADR §9.4.1 박제. 5 종 × 7 split × 5M = 175M 필요 vs 자본 100M → 21%
skip. per_split_amount / max_split 동적 조정 또는 동적 자본 배분 정책.

### 6.3 KOSPI 대형주 분산 본질적 한계 → Phase 1 자산군 분산 회복 trigger

ADR §9.5.2 / §9.6 박제. 종목 수 / 업종 분산 무관하게 H3 회복 불가. Phase
0.7.3 의 골드 hedge 효과 = 자산군 분산이 결정적. Phase 1+ 검토 항목:
- 채권 / 골드 ETF / 부동산 / US ETF 추가 (자산군 분산 회복)
- Phase 0.7.4 (부동산) placeholder (ADR 0003 §18.12.4)

### 6.4 종목 추세 의존성 → PriceDropStrategy 본질

ADR §9.2.1 박제. 상승 추세 종목만 정상 사이클. 하락 추세 종목 모두
lock-in. PriceDropStrategy 의 평균 회귀 가정의 본질적 한계 — Phase 1+
손절 정책 또는 strategy 다양화로 처방 검토.

### 6.5 후행 편향 단순화 (ADR §1.6.3 / §1.10)

Phase 0.9.x 5 종 모두 살아있는 종목. 백테스트 결과 = 낙관적 추정.
Phase 1+ 정교화 보류.

---

## 7. 라운드 #15 결정 박제 결과 (ADR §11)

사용자 명시 결정 (2026-05-08):

### 7.1 Phase 0.9 시리즈 종료

옵션 A (Phase 0.9 시리즈 종료) 채택. 옵션 B (Phase 0.9.x 추가) 거부.

근거 (ADR §11.2):
- Phase 0.9.1 + 0.9.2 모두 시나리오 C / 게이트 2/3 PASS = 진입 자격 충족
- 인프라 검증 본질 100% 충족 (ADR §9.7.2)
- H3 미달 본질 = 자산군 분산 부재 (Phase 0.9 본질 외 차원, Phase 1+ 도입)

### 7.2 Phase 1 직진 거부 + Phase 0.10 진입

옵션 B (Phase 0.10 — Backtest Reporting Enhancement) 채택. 옵션 A (Phase
1 직진) 거부.

근거 (ADR §11.3):
- KIS API 라이브 트레이딩 진입 전 백테스트 진단 도구 확립 필요
- 다중 전략 운용 (Phase 1+) 앞두고 strategy-agnostic 리포팅 layer 구축
- Phase 0.9 결과 (시나리오 C 3 회 반복, lock-in / insufficient_balance /
  자산군 분산 부족 패턴) 의 시각적 진단 가능

### 7.3 ADR 0006 / 0007 명명 변경 (필수 수반)

기존 박제 "Phase 1 ADR 0006 (가칭)" → **ADR 0007**:
- ADR 0005 §1.13 / §10.6.3 / CLAUDE.md §16.5 / roadmap.md / 회고 cross-ref
  모두 갱신 (sub-step 0.10.a 동시 commit)
- ADR 0006 신규 = Phase 0.10 (Backtest Reporting Enhancement)
- Phase 별 ADR 분리 패턴 일관 (0001 ~ 0006 / 0007)

### 7.4 시리즈 회고 동시 작성 (Q2 = A)

본 회고 (`phase-0.9.md`) 본 commit (sub-step 0.10.a) 동시. Phase 0.7 /
0.8 패턴 정합.

### 7.5 CLAUDE.md §16 in-place 갱신 (Q3 = A)

§16 헤더 = "Phase 1 호환성 의식 (Phase 0.9 동안만 적용)" → "Phase 1
호환성 의식 (Phase 0.10 동안 적용)". 기존 Phase 0.9 박제 보존 + Phase
0.10 본질 (분석 강화 — 코어 reporting 변경 zero) 추가.

---

## 8. Phase 0.10 권고 (다음 단계 — ADR 0006 §1)

### 8.1 Phase 0.10 진입 default

| 항목 | Phase 0.10 default |
|---|---|
| **본질** | **인프라 강화 (analytical reporting layer)** |
| **가설 / 게이트** | **없음** (Phase 0.7 / 0.8 / 0.9 패턴과 다름) |
| **변경 차원** | 백테스트 출력 리포팅 (drawdown episode + strategy-agnostic markers) |
| **평가 기준** | Acceptance Criteria 5 항목 (ADR 0006 §1.3) |
| **Mock / 실거래** | Mock (Phase 1 미진입) |
| **기존 코드 영향** | **변경 zero** (신규 추가만) |

### 8.2 Phase 0.10 본질 차원 (ADR 0006 §3 ~ §7)

- ADR-1 (§3): TradeView (application view model, 도메인 엔티티 추가 zero)
- ADR-2 (§4): StrategyRenderer Protocol + Registry (Hexagonal Port/Adapter)
- ADR-3 (§5): DrawdownEpisodeDetector (strategy-agnostic)
- 차트: mplfinance (정적 PNG embed)
- HTML: stdlib f-string
- 출력: `reports/backtest/<config>_<window>/episode_<n>.html`
- 임계치: -5% default (yaml/CLI override)
- Episode 정의: portfolio default + asset 옵션 + both

### 8.3 Phase 1 미래 권고 (ADR 0007 가칭, ADR 0005 §10.6.3)

Phase 0.10 종료 후 Phase 1 ADR 0007 박제 시 다뤄질 항목:

1. KIS API 어댑터 (BrokerPort / MarketDataPort)
2. **손절 정책 — H3 거짓 대응 + lock-in loss 처방** (Phase 0.9 데이터 근거)
3. **자본 배분 정교화 — insufficient_balance 처방** (Phase 0.9.2 데이터)
4. 텔레그램 알림
5. 종목별 vs 전체 kill switch / 자산 격리 정지
6. partial fill 처리 ADR
7. 거래세 / 수수료 모델링 (`OrderResult.tax` / `commission`)
8. 모의투자 → 실거래 전환 게이트
9. SupportLevelStrategy + cooldown 도입 검토 (ADR 0004 §7.3.2)
10. **자산군 분산 회복 (Phase 0.7.3 골드 + KR 주식)** — Phase 0.9 일반화
    박제 데이터 근거

---

## 9. 지표 요약 종합 (Phase 0.5 ~ Phase 0.9.2)

| 지표 | 0.5 | 0.7.1 | 0.7.2 (EQUAL) | 0.7.3 | 0.8.1 | 0.9.1 | 0.9.2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Return % | (참고) | (참고) | (참고) | 13.23 | 14.06 | 18.83 | 14.87 |
| MDD % | -25 | -37 | -22 | -8.27 | -21.28 | -22.66 | -37.65 |
| Sharpe | 0.32 | 0.06 | 0.49 | 0.5255 | 0.2679 | 0.4139 | 0.2424 |
| Turnover | 0.18 | 0.21 | 0.16 | 0.3270 | 0.4188 | 0.6173 | 1.1893 |
| Gate | 1/4 | 0/3 | (분리) | **3/3 (A)** | 2/3 (C) | 2/3 (C) | 2/3 (C) |

(Phase 0.5 / 0.7.1 / 0.7.2 수치는 참고용 — 정확한 strict 비교는 각 Phase
의 retrospective.md 참조)

→ Phase 0.7.3 = 유일한 시나리오 A. Phase 0.9 시리즈 = 시나리오 C 일관.

---

## 10. Phase 0.9 시리즈 → Phase 0.10 진입 체크포인트

- [x] ADR 0005 §1 (라운드 #12 — Phase 0.9 진입) 박제
- [x] CLAUDE.md §14 / §16 본문 갱신 (Phase 1 호환성 의식 — Phase 0.9 동안)
- [x] 사전 검증 (5 종 PASS) — ADR 0005 §2
- [x] ADR 0005 §3 박제 (라운드 #13 — sub-step 0.9.d ↔ 0.9.f 합병)
- [x] Asset 모델 확장 + `src/domain/tick_size.py` helper + 단위 테스트
- [x] 개별 주식 5 종 factory 신규 + composition 테스트
- [x] 다운로드 스크립트 일반화 (`scripts/download_kr_assets.py`)
- [x] 8 종 5-year 데이터 다운로드 + 회귀 byte-identical PASS — ADR §4
- [x] BacktestRunner Phase 0.7.3 회귀 invariant 재실행 — ADR §5
- [x] Phase 0.9.1 백테스트 (시나리오 C, 2/3 PASS) — ADR §6 / §7
- [x] `phase-0.9.1.md` 회고
- [x] Phase 0.9.2 진입 결정 라운드 #14 — ADR §8
- [x] Phase 0.9.2 백테스트 (시나리오 C, 2/3 PASS, MDD 더 악화) — ADR §9 / §10
- [x] `phase-0.9.2.md` 회고
- [x] Phase 0.9 시리즈 종료 결정 라운드 #15 — ADR §11
- [x] 본 시리즈 회고 (`phase-0.9.md`)
- [x] CLAUDE.md §16 in-place 갱신 (Phase 1 호환성 의식 — Phase 0.10 동안)
- [x] roadmap.md 갱신 (Phase 0.9 종료 + Phase 0.10 진입)
- [x] ADR 0006 / 0007 명명 변경 (기존 "Phase 1 ADR 0006" → ADR 0007)
- [x] ADR 0006 신규 박제 (Phase 0.10 진입 결정 + ADR-1 / -2 / -3 + Open Questions 답변)
- [ ] sub-step 0.10.b ~ 0.10.g — Phase 0.10 진행 (Step A ~ D + 회고 + 종료 결정)
- [ ] Phase 1 진입 결정 라운드 (Phase 0.10 종료 시점, ADR 0007 가칭) — 후속

---

> Phase 0.9 시리즈 narrative 종합 회고 완료. 다음 phase = Phase 0.10
> (Backtest Reporting Enhancement). 세부 박제 = ADR 0006 (`docs/decisions/
> 0006-phase-0.10-backtest-reporting.md`). 다음 sub-step = 0.10.b
> (Step A — Domain entities 검토 + Drawdown episode detector + 단위 테스트).
