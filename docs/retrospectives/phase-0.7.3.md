# Phase 0.7.3 회고 — 종목 다양화 (주식 + 골드)

> Phase 0.7.3 narrative 회고. 작성일: 2026-05-05. sub-step 0.7.3.f.
> 정량 결과: `phase-0.7.3-results.md`. 결정 박제: ADR 0003 §18 (라운드
> #8) + §18.12 (fallback (d)) + §19 (라운드 #9 — Phase 0.7 시리즈
> 정식 종료). 선행 회고: `phase-0.7.2.md`. 패턴 정합 (Phase 0.5 /
> 0.7.1 / 0.7.2 narrative 패턴).

---

## 1. 마일스톤

Phase 0.7.3 진입 (2026-05-05, ADR §18 박제) → 종료 (2026-05-05, 본
회고). **단일 일자 완료** — Phase 0.7.2 인프라 (BacktestRunner override
+ allocation 모듈 + 별도 스크립트) 재사용으로 시간 단축.

### 1.1 sub-step 흐름

| sub-step | 내용 | commit |
|---|---|---|
| 0.7.3.a | 라운드 #8 박제 (Phase 0.7.3 진입, 종목 3 종 후보) | 4120a36 |
| 0.7.3.a.1 | CLAUDE.md / roadmap 갱신 (Phase 0.7.2 종료 / 0.7.3 진입) | 0cb04b5 |
| 0.7.3.b.1 | 데이터 가용성 검증 — 329200 lookback 미달 발견 | 36d1a5e |
| 0.7.3.b.2 | Fallback 결정 (옵션 d — 종목 2 종 축소) | cb7ecbf |
| 0.7.3.b.2.a1 | CLAUDE.md / roadmap 갱신 (3종 → 2종) | e86664b |
| 0.7.3.b.3 | 132030 데이터 다운로드 + 무결성 검증 | 97c8319 |
| 0.7.3.c | strategies-0.7.3.yaml + 132030 asset factory | 0f25804 |
| 0.7.3.d | 백테스트 실행 + inline verification (게이트 3/3 PASS) | 32b3c95 |
| 0.7.3.e | phase-0.7.3-results.md 박제 | d67a553 |
| 0.7.3.f.0 | 라운드 #9 박제 (§19 — Phase 0.7 시리즈 정식 종료) | 84e67c4 |
| **0.7.3.f** | **본 회고 (현재)** | (본 commit) |

### 1.2 작업 범위 — Phase 0.7.2 인프라 재사용 + 종목 변경 1 차원

코드: 132030 asset factory 1 (composition.py 등록) + yaml 신규 1.

데이터: KRX_132030_2019-2024.csv 1 종 (1477 rows 신규).

박제: ADR §18 (라운드 #8 + sub-결정 + 가용성 검증 + fallback + 다운로드
+ 백테스트) + §19 (라운드 #9 — Phase 0.7 시리즈 종료) + results.md +
회고 (본 문서).

**재사용된 인프라 (코드 변경 zero)**:
- `BacktestRunner.per_asset_strategy_overrides` (옵션 C1, §16.13.9)
- `src/cli/allocation.py` (산식 모듈, §16.13.4)
- `scripts/run_phase_0_7_2_backtest.py` (별도 스크립트, §16.14.1)
- `analyze_phase_0_7_2.py` helpers (inline 호출, §18.14.1)
- `download_kr_etf.py` (Phase 0.7.2.b 그대로)

→ Phase 0.7.2 의 옵션 C 정신 (별도 스크립트 + None default 회귀
invariant) 의 강력한 재사용성 입증.

---

## 2. 완료 기준 충족 검증 (ADR §10)

### 2.1 코드 품질 게이트

- ✅ 132030 asset factory 추가 (composition.py 갱신) — 단위 테스트
  영향 없음 (factory 추가는 회귀 zero)
- ✅ Phase 0.7.1 / 0.7.2 회귀 invariant 자동 보존 — Phase 0.7.2 테스트
  + 685+ 통합 테스트 그대로 통과 (regression zero, 687 passed)
- ✅ ruff + mypy 통과 — composition.py 갱신만, 신규 코드 없음

### 2.2 Invariant 게이트

- ✅ Phase 0.7.1 baseline 보존 — Phase 0.7.3 의 EQUAL 정책은 자산이 다른
  baseline 측정. Phase 0.7.1 / 0.7.2 EQUAL 회귀 invariant 는 변경
  zero (자산 set 다름 → 당연히 다름, 그러나 회귀 자동 보존 패턴
  검증).
- ✅ BacktestRunner override 패턴 — None default 자동 적용 (Phase 0.7.3
  EQUAL → override 미사용)

### 2.3 백테스트 게이트 (ADR §18.4)

| 가설 | 임계 (Phase 0.7.1 baseline + H3 정확값) | Phase 0.7.3 | 판정 |
|---|---:|---:|---|
| **H1** util ≥ 15.6% | 15.6 | 34.37 | ✅ PASS (+18.77pp) |
| **H2** return ≥ +5.25% | 5.25 | 13.23 | ✅ PASS (+7.98pp) |
| **H3** Sharpe ≥ 0.3258 | 0.3258 | 0.5255 | ✅ PASS (+0.1997) |
| **통과** | ≥ 2/3 | **3/3** | **✅ PASS** |

**Phase 0.7 시리즈 첫 명확한 게이트 통과** — 0.7.1 (0/3 FAIL) / 0.7.2
(EQUAL = baseline 자기 동치, VOL = 069500 단일 회귀 부산물) 의 trade-off
제약 우회.

### 2.4 회고 게이트

본 문서 작성으로 충족. §19 라운드 #9 결정 박제 (Phase 0.7 시리즈 종료
+ 미박제 항목 처리) 선행 — Phase 0.7.1.i / 0.7.2.f 패턴 정합.

---

## 3. 5-year 결과 요약 (Phase 0.7.1 baseline 비교)

정량 상세: `phase-0.7.3-results.md`. 본 §3 narrative 비교만.

### 3.1 핵심 지표

| 지표 | Phase 0.7.1 baseline | Phase 0.7.3 (주식 + 골드) | diff |
|---|---:|---:|---:|
| Total return % | 5.2514 | **13.2280** | **+7.9766** |
| CAGR % | 1.0541 | **2.5779** | **+1.5238** |
| Max drawdown % | -7.9487 | -8.2737 | -0.3250 |
| Sharpe ratio | 0.3258 | **0.5255** | **+0.1997** |
| Calmar ratio | 0.1326 | **0.3116** | **+0.1790** |
| Capital turnover | 0.1633 | **0.3270** | **+0.1637** |
| Avg capital util % | 15.60 | **34.37** | **+18.77** |
| Cumulative sells | 13 | **28** | **+15** |

### 3.2 시각적 패턴

- **모든 핵심 지표 동시 개선** (MDD 미세 악화 -0.33pp 외 7 지표 ↑) —
  Phase 0.7.2 의 trade-off 제약 (return ↑ vs MDD ↑, Sharpe ↑ vs return ↓)
  완전 우회.
- **자본 활용 ↑↑** (15.60% → 34.37%, +18.77pp) — Phase 0.7.1 의 채권
  dormancy 완전 해소. 골드의 5% drop 빈번 발생.
- **매도 횟수 2배 +** (13 → 28) — 골드의 활발한 사이클. Phase 0.7.2
  의 INV_VOL (cumulative_sells 13, 채권 단일) 와 정반대.

---

## 4. 가설 검증 (ADR §18.4)

### 4.1 H1 (자본 활용 ≥ 15.6%) ✅

측정: 34.37 (+18.77pp). 골드의 변동성 (~중) 으로 5% drop 트리거 빈번
발생 → 분할 매수 누적 활발. Phase 0.7.2 INV_VOL 의 14.27% (균등 분모
한계 측정) 와 본질적으로 다른 의미 — Phase 0.7.3 은 분모 / 분자 모두
의미 있는 숫자.

### 4.2 H2 (total return ≥ +5.25%) ✅

측정: 13.23 (+7.98pp). 골드의 5-year 절대 상승폭 + 7-split 매수 사이클의
가치. Phase 0.7.2 VOL 의 13.38% (069500 단일 회귀) 와 비슷한 수준이지만
**자산군 분산 효과 보존** (069500 + 132030, 비중 EQUAL 50:50).

### 4.3 H3 (Sharpe ≥ 0.3258 정확값) ✅

측정: 0.5255 (+0.1997). §17.3 H3 임계 정밀도 학습 적용 (0.33 → 0.3258
정확값) 그대로 strict 비교 — 통과 명확. Phase 0.7.2 VOL 의 0.3012 미달
대조 — Phase 0.7.3 은 strict 임계도 통과.

### 4.4 게이트 종합 판정

3/3 PASS — Phase 0.7 시리즈 첫 명확한 게이트 통과. **§17.4 (γ) 분리
박제 의미상 "정책 효과 측정 통과"** (회귀 invariant 검증 통과 / 부산물
통과 와 다름).

---

## 5. 학습

### 5.1 기술 — 무엇이 잘 작동했나

1. **옵션 C1 (BacktestRunner override) + 옵션 C (별도 스크립트) 패턴
   재사용성 입증 ✅** (가장 중요한 학습). Phase 0.7.3 = 종목 변경 1
   차원 → 코드 변경 = 132030 asset factory 1 + yaml 1. 모든 인프라
   (allocation 산식 / runner override / 분석 도구) 재사용. **회귀
   invariant 자동 보존 + 신규 종목 통합 = 단일 일자 완료**. Phase 0.7.2
   의 설계 결정 (옵션 C / C1 / B 정합) 의 가치 후속 검증.

2. **데이터 가용성 검증 (verify) → fallback 결정 (decision) → 다운로드
   (download) sub-step 분리 패턴**. Phase 0.7.2.b 패턴 정합 — 0.7.3.b.1
   에서 329200 lookback 미달 조기 발견 → 사용자 결정 라운드 (§18.12)
   → 종목 2 종 축소. **추측 박제 차단 + 명시 결정 박제** (CLAUDE.md
   §13.1 정신 정합).

3. **inline verification (옵션 B)** — 분석 도구 신규 작성 zero.
   `analyze_phase_0_7_2` helpers (summarize / phase_0_7_1_baseline)
   inline 호출 → 단일 정책 검증 즉시. ~80% 코드 중복 회피.

4. **§17.3 H3 임계 정밀도 학습 적용** — 0.7.3 임계 = H3 ≥ 0.3258 (정확값,
   strict 비교). Phase 0.7.2 의 정밀도 발견 + 명시화 박제가 후속
   라운드에서 즉시 활용됨. **학습의 1-step 반영** 패턴.

### 5.2 기술 — 발견 후 보강한 것

1. **329200 (TIGER 부동산인프라고배당) lookback 부족 발견** — 상장일
   2019-07-19, 백테스트 시작일 2020-01-02 직전 거래일 = 111 < 246. **종목
   상장 history 자체의 한계** — 가용성 검증 도구의 가치 입증. Phase
   0.7.4 (가칭) 부동산 분산 후속 박제 (§18.12.4) 로 처리.

2. **종목 후보 변경 (3 종 → 2 종) — 변수 통제 + 단순성 우선**. §18.2
   결정 1=E (3 종) → §18.12.2 fallback (d) (2 종). 사용자 발의 추적성
   보존 + 종목만 갱신 패턴 박제 (§18.12.3).

3. **새 자산 통합의 단순성** — 132030 asset factory 추가 = 21 lines
   추가 (composition.py). yaml 박제 + factory 등록 + 다운로드 = 즉시
   통합. Phase 0.7.2.b.3 의 옵션 C1 패턴 (None default 회귀 invariant)
   덕분.

### 5.3 협업 — 무엇이 잘 작동했나

1. **결정 라운드 시리즈 #8 / #9 + sub-라운드** — Phase 0.7.3 동안 사용자
   명시 결정 라운드:
   - 라운드 #8 (§18) — 6 결정 항목 (종목 / 정책 동일성 / 게이트 baseline
     / 자본 배분 default / 데이터 sub-step / commit 분리)
   - Fallback 결정 (§18.12) — 옵션 (d) 2 종 축소 채택
   - 분석 도구 결정 (옵션 B) — analyze 도구 신규 작성 zero
   - 라운드 #9 (§19) — 3 결정 항목 (Phase 0.7 종료 / 0.7.4 placeholder
     / γ 후속 보류) + 부속 (Phase 0.8 진입 시점 사용자 검토)
   - 모든 결정 verbatim 박제 + 거부 옵션 근거 박제 + 부속 결정 명시화

2. **CLAUDE.md §12.3.1 누락 체크 — 일관 적용** (Phase 0.7.1 학습 §5.4
   재택용 박제). Phase 0.7.3 동안 5+ 회 적용. 누락 zero.

3. **회고 진입 전 결정 라운드 박제 패턴** (Phase 0.7.1.i / 0.7.2.f /
   0.7.3.f 모두 재현). 회고 §결론 / §권고가 결정에 의존 → 명시 결정
   박제 → 회고 narrative 정합. Phase 0.8.f / 0.9.f 등에서도 유지 권고.

### 5.4 협업 — Phase 0.8+ 회고에서 새로 채택할 규칙 후보

1. **인프라 재사용성 검증 패턴** — Phase 0.7.3 의 옵션 C / C1 / B
   재사용 검증 = 옵션 C 의 본질적 가치 입증. Phase 0.8 (지지선) /
   0.9 (개별 주식) 진입 시 IndicatorPort / 호가 가변 등 신규 추상이
   통합되더라도 옵션 C 정신 (main.py 변경 zero, 별도 스크립트 / runner
   override) 보존 시도 권고.

2. **fallback 결정의 부담** — 0.7.3.b.1 / 0.7.3.b.2 = 데이터 가용성
   부족 발견 + 사용자 명시 fallback 결정 = 2 commits. 빠른 회복 패턴
   (검증 도구 → 발견 → 결정 → 진행) 보존.

3. **단일 정책 검증의 inline approach (옵션 B)** — 분석 도구 신규 작성
   부담 회피. Phase 0.8 (지지선) 도 단일 정책 / 다중 baseline 검증 시
   동일 패턴 적용 가능.

---

## 6. 발견된 이슈 / 제약

### 6.1 전략 레벨 — Phase 0.8+ 검토 후보

1. **부동산 / 인프라 분산 미검증** — §18.12.4 placeholder 그대로. Phase
   0.7.3 = 주식 + 골드 만으로 충분한지 / 추가 자산군 (부동산 / 채권
   inflation-protected / 변동성 ETF 등) 의 의미 검증 미수행. **Phase
   0.7.4 (가칭) 또는 Phase 0.8+ 후속 검토** (§19.3).

2. **§14.7 γ (자산별 다른 정책) 미박제** — Phase 0.7.3 정책 동일성
   (§7.3) 으로 충분 입증. 그러나 Phase 0.8 (지지선) / 0.9 (개별 주식)
   환경에서는 자산별 변동성 차이 더 크다 — γ 의 의미 재검토 가능.
   **Phase 0.8+ 후속 검토** (§19.4).

3. **5-year 백테스트 윈도우의 한계** — 2020 COVID + 2022 인플레이션 +
   2024 회복 의 3 가지 macro 이벤트 포함. 다른 5-year window 에서의
   재현성 미검증. Phase 1+ paper / 실거래에서 자연 검증.

### 6.2 인프라 레벨 (해소됨)

1. **132030 asset factory 등록** — 21 lines composition.py 갱신.
   `_ASSET_FACTORIES` dict 패턴이 새 자산 통합의 자연스러움 입증.

2. **yaml 박제 단순성** — strategies-0.7.3.yaml = 0.7.2-equal.yaml
   복사 + 종목 코드 / 이름만 갱신. 정책 동일성 (§7.3) 강제 자동 검증.

3. **데이터 다운로드 도구 재사용** — `download_kr_etf.py` 그대로 사용
   (Phase 0.7.2.b). 132030 다운로드 1477 rows + 무결성 검증 통과.

### 6.3 코드 레벨 (해소됨)

1. **BacktestRunner override 패턴 검증** — Phase 0.7.3 EQUAL → None
   default 자동 적용 → 단일 strategy_config fallback. 동작 검증.

2. **출력 형식 호환성** — `format_backtest_result` JSON 출력이
   `analyze_phase_0_7_2` helpers 와 호환. 신규 자산 / 정책에서도 동작.

---

## 7. 라운드 #9 결정 박제 결과 (ADR §19)

### 7.1 §19.2 결정 1=(a) — Phase 0.7 시리즈 정식 종료

§15.5.1.C 진입 경로 그대로:
```
✅ Phase 0.7.1 (종료) → ✅ Phase 0.7.2 (종료) → ✅ Phase 0.7.3 (종료, 본 회고)
  ↓
Phase 0.7 시리즈 종료 (본 §19 박제)
  ↓
Phase 0.8 (지지선 전략, ADR 0004)
  ↓
Phase 0.9 (개별 주식, ADR 0005)
  ↓
Phase 1 (실거래, ADR 0006)
```

### 7.2 §19.3 결정 2=(i) — Phase 0.7.4 placeholder 보존

§18.12.4 그대로 — 부동산 / 인프라 분산은 Phase 0.8+ 자연 통합 가능.

### 7.3 §19.4 결정 3=(α) — §14.7 γ Phase 0.8+ 후속 보류

미래 옵션 보존. Phase 0.8 / 0.9 진입 시 1 차원 변경 정신과의 정합성
재검토.

### 7.4 §19.5 부속 — Phase 0.8 진입 시점

본 회고 commit 후 사용자 검토 시간. Phase 0.8 진입 결정 라운드 #10
(가칭) 박제 별도.

---

## 8. Phase 0.8 권고 (다음 단계)

### 8.1 우선순위 1 — Phase 0.8 진입 결정 라운드 #10 박제

ADR 0003 §15.2 후보 박제 → Phase 0.8 진입 ADR (0004 가칭) 박제 시
정식 박제. 검토 항목:

- **지지선 종류 7 슬롯 매핑** — §15.2.2 후보 (MA / BB / RSI 등) 확정
- **`IndicatorPort` 신설 vs Composition 직접 산출** — 옵션 C1 정신
  정합 (도메인 변경 zero) 검토
- **`SupportLevelStrategy` 신규 구현** — 도메인 strategy 추가
- **단일 종목 (069500) Phase 0.5 F 환경 vs Phase 0.7 multi 환경** —
  변수 통제 1 차원 (매수 패러다임만) 채택 권고
- **게이트 baseline** — Phase 0.5 F (단일 종목) 또는 Phase 0.7.3 (multi)
  중 baseline 선택

### 8.2 우선순위 2 — 회귀 invariant 보존 의식

Phase 0.8 도입 시 Phase 0 / 0.5 / 0.7.x 회귀 invariant 모두 보존:
- `PriceDropStrategy` (가치 기반) 그대로 — Phase 0.5 / 0.7 baseline
- `SupportLevelStrategy` (기술적 분석) 신규 — 별도 baseline
- yaml `buy_strategy: "support_level"` 선택 시만 활성

### 8.3 우선순위 3 — Phase 1 호환성 의식 갱신 (CLAUDE.md §16)

Phase 0.8 진입 시 CLAUDE.md §16 갱신:
- 보조지표 매수 (`SupportLevelStrategy`) — Phase 0.7 까지 ❌ 였으나
  Phase 0.8 부터 ✅
- IndicatorPort (도입 시) — Phase 1 호환성 의식 추가
- 손절 정책 / partial fill / 텔레그램 등 — Phase 1+ 그대로

---

## 9. Phase 0.9 / 1 권고 (후속 단계)

### 9.1 Phase 0.9 (개별 주식) — Phase 0.8 종료 후

ADR 0003 §15.3 후보 박제 → ADR 0005 (가칭). 검토 항목:
- ETF → 개별 주식 (종목 성격 차원)
- 인프라 변경: 호가 단위 가변 / 거래 정지 / 액면분할 / 거래세 모델링
- 변수 통제: 종목 차원만 변경 (Phase 0.8 의 매수 전략 그대로)

### 9.2 Phase 1 (실거래) — Phase 0.9 종료 후

ADR 0006 (가칭). KIS API 진입. CLAUDE.md §16.4 트리거 항목 (KIS 어댑터
/ 손절 정책 / 텔레그램 / kill switch / partial fill / 모의투자 → 실거래
전환 게이트) 박제.

### 9.3 §15.5.1 옵션 A 재확인

본 회고는 §15.5.1 옵션 A (Phase 0.7 시리즈 완주 + Phase 0.8/0.9 직교
차원 추가) 정합 — 변경 사유 없음. **§15.5.1 진입 경로 1 차 검증 ✅**
(Phase 0.7 시리즈 3 단계 모두 종료).

---

## 10. 지표 요약

| 항목 | 값 |
|---|---:|
| 백테스트 기간 | 2020-01-02 ~ 2024-12-30 (1231 거래일) |
| 종목 | 069500 (KODEX 200) + 132030 (KODEX 골드선물(H)) |
| 초기 자본 | 100,000,000 KRW |
| 정책 | F (HybridTimeBasedReentry, cooldown=60), 5% drop / 10% target |
| 자본 배분 정책 | EQUAL (default, §18.5) |
| **게이트 ✅ 3/3 PASS** | H1 34.37 ≥ 15.6 / H2 13.23 ≥ 5.25 / H3 0.5255 ≥ 0.3258 |
| Phase 0.7.1 baseline 대비 | return +7.98pp / Sharpe +0.20 / util +18.77pp |
| 신규 코드 | 132030 asset factory (21 lines) |
| yaml 신규 | strategies-0.7.3.yaml (40 lines) |
| 단위 테스트 (신규) | 0 (인프라 재사용으로 회귀 invariant 자동 보존) |
| 전체 regression | 687 passed (Phase 0.7.2 그대로) |
| 결정 라운드 | #8 (§18) + Fallback (§18.12) + 옵션 B (analyze inline) + #9 (§19) |
| 데이터 신규 | KRX_132030_2019-2024.csv (1477 rows) |
| 329200 거부 | 상장일 2019-07-19 → lookback 246 미달 (§18.11/§18.12) |

---

## 11. Phase 0.7.3 → Phase 0.8 진입 체크포인트

- [x] ADR §18 박제 (라운드 #8 + sub-결정) — 4120a36
- [x] CLAUDE.md / roadmap 갱신 (Phase 0.7.2 종료 / 0.7.3 진입) — 0cb04b5
- [x] 데이터 가용성 검증 — 36d1a5e
- [x] Fallback 결정 (옵션 d) — cb7ecbf
- [x] CLAUDE.md / roadmap 갱신 (3종 → 2종) — e86664b
- [x] 132030 다운로드 — 97c8319
- [x] strategies-0.7.3.yaml + 132030 asset factory — 0f25804
- [x] 백테스트 + inline verification (게이트 3/3 PASS) — 32b3c95
- [x] phase-0.7.3-results.md — d67a553
- [x] ADR §19 (라운드 #9 — Phase 0.7 시리즈 종료) — 84e67c4
- [x] phase-0.7.3.md (본 회고) — 본 commit
- [ ] **사용자 검토 시간** (Phase 0.8 진입 결정 트리거 — §19.5 박제)
- [ ] Phase 0.8 진입 결정 라운드 #10 (가칭) — 사용자 명시 결정 후
- [ ] Phase 0.8 진입 ADR 0004 (가칭) 신규 박제
- [ ] CLAUDE.md / roadmap 갱신 — Phase 0.7 정식 종료 / Phase 0.8 진입 (라운드
      #10 commit 시점에 일괄)

---

*작성: 2026-05-05 (sub-step 0.7.3.f)*
*Phase 0.7 시리즈 정식 종료. 다음 회고: `phase-0.8.f.md` 또는
`phase-0.8.md` (Phase 0.8 종료 후).*
