# Phase 0.7.2 회고 — 자본 배분 정책 비교

> Phase 0.7.2 narrative 회고. 작성일: 2026-05-05. sub-step 0.7.2.f.
> 정량 결과: `phase-0.7.2-results.md`. 결정 박제: ADR 0003 §16, §17.
> 라운드 #7 결정 박제: ADR §17 (옵션 a + iii + γ 채택).
> 선행 회고: `phase-0.7.1.md`. 패턴 정합 (Phase 0.5 narrative 패턴).

---

## 1. 마일스톤

Phase 0.7.2 진입 (2026-05-04, ADR §16 박제) → 종료 (2026-05-05, 본 회고).

### 1.1 sub-step 흐름

| sub-step | 내용 | commit |
|---|---|---|
| 0.7.2.a | 라운드 #6 박제 — Phase 0.7.2 진입 결정 (배분 정책 3 종 비교) | 137bf3d |
| 0.7.2.b.1 | 데이터 가용성 검증 — pykrx 2019 246 거래일 확인 | b8a80ae |
| 0.7.2.b.2 | Fallback 결정 (옵션 a — CSV 확장) + 부속 결정 박제 | 989d7dd |
| 0.7.2.b (data) | KRX_*_2019-2024.csv 다운로드 + 무결성 검증 | 9ee17af |
| 0.7.2.b.3 #2 | 도메인 enum `AllocationPolicy` 추가 | 0bd8e92 |
| 0.7.2.b.3 #3 | Config schema 확장 (`allocation_policy` 필드) | cec1e4e |
| 0.7.2.b.3 #4 결정 | ADR §16.13 — Composition 통합 구조 (1=γ + 2=A + 3=iii) | fca687d |
| 0.7.2.b.3 #4a | `src/cli/allocation.py` 신규 (순수 함수 + 단위 테스트 19) | 7b5bd09 |
| 0.7.2.b.3 #4b.1 | C1 결정 박제 (BacktestRunner override 패턴, key=asset.fqn) | bff82db |
| 0.7.2.b.3 #4b.2 | BacktestRunner `per_asset_strategy_overrides` 옵셔널 인자 + 테스트 | 9559a11 |
| 0.7.2.b.3 #4b.3 | end-to-end 검증 (옵션 B 재정의 — AssetContext 분산) | 295b0cc |
| 0.7.2.b.3 #4b.4 | 회귀 invariant + 산식 검증 + scripts/run_phase_0_7_2_backtest.py | 4608d8e |
| 0.7.2.c | strategies-0.7.2-{equal,inv-vol,vol}.yaml 박제 | 496dfab |
| 0.7.2.d | scripts/analyze_phase_0_7_2.py 신규 (회귀 + 게이트 자동 평가) | 660392d |
| 0.7.2.e | phase-0.7.2-results.md 박제 (정량) | b12d313 |
| 0.7.2.f.0 | 라운드 #7 결정 박제 (§17 — 1=a + 2=iii + 3=γ) | 90c0673 |
| **0.7.2.f** | **본 회고 (현재)** | (본 commit) |

### 1.2 작업 범위 — 코드 / 테스트 / 데이터 / 박제

코드: 도메인 enum 1 + Config schema 확장 + Composition 산식 모듈 +
BacktestRunner override + 별도 스크립트 2 (run + analyze) + 단위 테스트
24 (allocation 19 + runner override 6 + AssetContext 분산 검증 2 +
config schema 6 — 일부 중복).

데이터: KRX_*_2019-2024.csv 2 종 (1477 rows × 2 자산 = 2954 OHLCV bars
신규).

박제: ADR 0003 §16 (16.0 ~ 16.14) + §17 + §16.2 갱신. results.md 1 종.
회고 1 종 (본 문서).

---

## 2. 완료 기준 충족 검증 (ADR §10)

### 2.1 코드 품질 게이트

- ✅ Phase 0.7.1 회귀 invariant 자동 보존 — `per_asset_strategy_overrides=None`
  default 패턴 (옵션 C1, §16.13.9). 모든 기존 callers (cli/main.py 2
  곳, 통합 테스트 ~9 곳) 영향 zero.
- ✅ 단위 테스트 통과 — allocation 19 + runner override 6 + AssetContext
  분산 검증 2 + config schema 6 = 신규 33 tests, 전체 regression
  687+ passed.
- ✅ ruff + mypy 통과 — 신규 코드 모두 (allocation.py / runner /
  schema / scripts).

### 2.2 Invariant 게이트 (회귀)

- ✅ Phase 0.7.1 baseline 5 지표 1e-4 오차 이내 일치 (EQUAL 정책 →
  total_return 5.2514 / cagr 1.0541 / mdd -7.9487 / sharpe 0.3258 /
  calmar 0.1326). `analyze_phase_0_7_2.py` 자동 검증.

### 2.3 백테스트 게이트 (ADR §16.2)

3 정책 게이트 (H1 ≥ 15.6% / H2 ≥ +5.25% / H3 ≥ 0.33, ≥ 2/3 통과):
- EQUAL 2/3 PASS — H1✓ H2✓ H3✗
- INV_VOL 1/3 FAIL — H1✗ H2✗ H3✓
- VOL 2/3 PASS — H1✓ H2✓ H3✗

**Final**: EQUAL + VOL 2 정책 통과. **§17.4 (γ) 분리 해석**:
- EQUAL = "회귀 invariant 검증 통과" (baseline 자기 동치)
- VOL = "정책 효과 측정 통과" (자산 비중 변경 → return ↑)
- INV_VOL = "Sharpe 단독 통과 차단" (≥ 2/3 임계)

### 2.4 회고 게이트

본 문서 작성 자체로 충족. 라운드 #7 결정 박제 (§17) 선행 — Phase 0.7.1.i
패턴 정합 (Phase 0.7.1.i 학습 §5.4 재택용).

---

## 3. 5-year 3-policy 결과 요약

정량 상세: `phase-0.7.2-results.md`. 본 §3 narrative 비교만.

### 3.1 4-way 핵심 지표

| 지표 | Phase 0.7.1 | EQUAL | INV_VOL | VOL |
|---|---:|---:|---:|---:|
| Total return % | 5.2514 | **5.2514** | 1.6440 | **13.3791** |
| MDD % | -7.9487 | **-7.9487** | -0.1418 | -22.5027 |
| Sharpe | 0.3258 | **0.3258** | 4.5321 | 0.3012 |
| Calmar | 0.1326 | **0.1326** | 2.3592 | 0.1158 |
| Capital turnover | 0.1633 | **0.1633** | 0.0607 | 0.4062 |
| Avg capital util % | 15.60 | **15.61** | 14.27 | 30.22 |
| Cumulative sells | 13 | 13 | 13 | 13 |

(EQUAL 굵은 글씨 = Phase 0.7.1 baseline 자기 동치, 회귀 invariant
PASS.)

### 3.2 시각적 패턴

- **EQUAL = baseline** — 회귀 invariant 검증. 정책 효과 측정 의미 zero.
- **INV_VOL = "안정 자산 단독 운용의 극한"** — 채권 비중 99%+ (실측
  1:136), MDD -0.14% / Sharpe 4.53 / return 1.64%. 사실상 채권 ETF
  단일.
- **VOL = "069500 단일 회귀"** — 주식 비중 99%+ (142:1), MDD -22.50%
  / Sharpe 0.30 / return 13.38%. 사실상 Phase 0.5 F (단일 069500).

---

## 4. 가설 검증 (ADR §16.2)

### 4.1 H1 (자본 활용 ≥ 15.6%)

- EQUAL: 15.61 ✅ (baseline 자기 동치)
- INV_VOL: 14.27 ❌ (1.33pp 미달)
- VOL: 30.22 ✅ (1.94× baseline)

**H1 의미 한계** — 균등 분모 (50M) 기준. INV_VOL 의 "채권 commit
80M+" 이 자연스럽게 반영 안 됨 (옵션 A 산정 한계, §17 박제). VOL 의
30.22% 는 069500 commit ↑ + 214980 commit zero — 평균 처리상 자연.

### 4.2 H2 (total return ≥ +5.25%)

- EQUAL: 5.2514 ≃ baseline (자기 동치)
- INV_VOL: 1.64 ❌ (3.61pp 미달)
- VOL: 13.38 ✅ (8.13pp 초과)

**baseline 갱신 효과** — Phase 0 strict (+25.96%) 거부 + Phase 0.7.1
multi (+5.25%) 채택 (§16.2). VOL 정책의 "069500 단일 회귀 = 13.38%"
는 명목 통과이지만 자산군 분산 가치 일부 상실의 부산물.

### 4.3 H3 (Sharpe ≥ 0.33)

- EQUAL: 0.3258 (baseline 자기 동치, §17.3 H3 동치 인정)
- INV_VOL: 4.5321 ✅ (압도적 — 안정 자산 단독)
- VOL: 0.3012 ❌ (0.0288 미달, 069500 단일 회귀)

**H3 임계 정밀도 발견** (§17.3 옵션 iii 박제):
- 임계 0.33 (반올림) vs baseline 0.3258 (정확) — strict 비교 시 EQUAL
  미달. baseline 자기 동치는 동치 인정.
- §16.2 narrative 갱신 — strict 비교 / 동치 분리 명시화.

### 4.4 게이트 종합 판정 (§17.4 분리 해석)

| 정책 | H1 | H2 | H3 | Pass | 의미 |
|---|---|---|---|---|---|
| **EQUAL** | ✓ | ✓ | ✗ (동치 인정) | 2/3 (3/3 동치) | 회귀 invariant 검증 통과 |
| **INV_VOL** | ✗ | ✗ | ✓ | 1/3 | Sharpe 단독 통과 차단 |
| **VOL** | ✓ | ✓ | ✗ | 2/3 | 정책 효과 측정 통과 (자산군 분산 약화) |

---

## 5. 학습

### 5.1 기술 — 무엇이 잘 작동했나

1. **옵션 C1 (BacktestRunner override) 패턴 — 회귀 invariant 자동 보존
   설계의 정합성 입증** (§17.4 EQUAL 게이트 의미). `per_asset_strategy_overrides=None`
   default → 단일 strategy_config fallback → Phase 0.7.1 baseline 5
   지표 1e-4 오차 일치. 모든 기존 callers (cli/main.py 2 곳, 통합 테스트
   ~9 곳) 영향 zero. **시그니처 변경 부담 없이 자산별 다른 config 수용**
   — 옵션 C2 (강제 시그니처 변경) 거부 정합성 확증.

2. **AssetContext 분산 구조의 단순성 — 옵션 B 재정의 정합** (§16.13.9
   4b.3 갱신). 4b.2 에서 코드 구조 발견 — runner 의 AssetContext 별
   config 보유 → orchestrator 변경 zero. `get_strategy_config_for_asset`
   메서드 박제 거부 → AssetContext 자체가 자산별 lookup 의 본질. **중복
   책임 회피** (코드 스멜 차단).

3. **별도 스크립트 (옵션 C) — Phase 0.7.2 일회성 검증 도구의 응집**.
   `scripts/run_phase_0_7_2_backtest.py` + `scripts/analyze_phase_0_7_2.py`
   가 main.py / runner / composition 변경 zero 로 INV_VOL/VOL 검증.
   Phase 0.7.1.d / 0.7.1.h 의 `verify_phase_0_7_1_assets.py` /
   `analyze_phase_0_7_1.py` 패턴 그대로 재현 — 검증 도구는 일회성
   (Phase 0.8 indicator 추상 도입 시 통합 검토).

4. **데이터 다운로드 + 무결성 검증 자동화** — `verify_phase_0_7_2_data.py`
   가 lookback 가용성 + KRX 거래일 표준 (246) 발견. Phase 0.7.2 의
   ADR §16.5 default 갱신 동기 (252 → 246).

### 5.2 기술 — 발견 후 보강한 것

1. **백테스트 OHLCV 범위 명시 필터** (§16.14.1.1). 4b.4 실행 중 발견
   — 2019 lookback 데이터가 백테스트에 포함되면 strategy T-1 close
   평가 변함 → Phase 0.7.1 baseline 일치 깨짐. 해결: 스크립트가
   `[start, end]` 명시 필터 + lookback 별도 추출.

2. **σ 산출 위치 결정 (옵션 c — Composition 직접 산출)** (§16.5.1).
   YAGNI — IndicatorPort 신설 거부 (도메인 σ 미요구) + MarketDataPort
   확장 거부 (책임 비대화). D-2 MovingAverageReentry 패턴 (Strategy 가
   OHLCV → SMA) 정합. Phase 0.8 indicator 인프라 도입 시 통합 검토.

3. **NYSE 252 → KRX 246 임계 갱신** (§16.5 / §16.11.2 부속 #3). KRX
   거래일 표준 발견 (full year = 246). 시장별 분리 가능성 (Phase 3+
   미국 ETF 추가 시 LOOKBACK_DAYS_KRX/NYSE) 박제.

4. **σ raw stddev (annualization 없음)** (§16.13.5). 양 자산 weight
   산정 시 √N 동일 곱 cancel out → 무차별 (수학적 동치). 단순화
   채택.

### 5.3 협업 — 무엇이 잘 작동했나

1. **결정 라운드 시리즈 #6 / #7 + sub-라운드** — Phase 0.7.2 동안
   사용자 명시 결정 라운드 풍부:
   - 라운드 #6 (§16) — 5 결정 항목 (배분 정책 / 게이트 / 종목 / budget
     / commit 분리)
   - σ 산출 위치 결정 (§16.5.1)
   - Fallback 결정 (§16.10 / §16.11)
   - 작업 #4 결정 (§16.13)
   - 작업 #4b 통합 경로 (§16.13.9)
   - 라운드 #7 (§17) — 3 결정 항목 (Phase 0.7.3 진입 / H3 임계 정밀도
     / 게이트 결과 해석)
   - 모든 결정 verbatim 박제 + 표준 매핑 정합화 + 거부 옵션 근거 박제
     — 미래 ADR 독자 / 6개월 후 자기 자신 가능.

2. **CLAUDE.md §12.3.1 누락 체크 — 일관 적용**. 매 ADR 갱신 시 누락
   체크 ✅ 명시. Phase 0.7.1 학습 §5.4 의 "ADR §12.3.1 발의" 후속 -
   Phase 0.7.2 동안 7+ 회 적용.

3. **단계별 commit + ADR 박제 흐름** — 사용자 박제 → 코드 → 테스트 →
   결과 → ADR 갱신 → 다음 단계. Phase 0.7.1.h 패턴 재현. Phase 0.7.3
   에서도 유지 권고.

### 5.4 협업 — Phase 0.7.3+ 회고에서 새로 채택할 규칙 후보

1. **사용자 박제 vs 표준 매핑 정합화 박제 패턴**. §15.5.1.B (라운드
   #5) 처음 도입, §17.X 라운드 #7 에서도 유지. 사용자 mental model
   라벨 (α / β 등) 과 ADR 표준 옵션 라벨이 다를 때, 양쪽 verbatim +
   정합 매핑 분리 박제 — 미래 독자 혼동 방지.

2. **회고 진입 전 결정 라운드 박제 패턴 (Phase 0.7.1.i + 0.7.2.f
   재현)**. 결정 사항 (§17 의 "라운드 #7" 같은 것) 이 회고 §결론 /
   §권고에 영향 → 회고 작성 전 명시 결정 박제 → 회고 narrative 정합.
   Phase 0.7.3.f / 0.8.f 등에서도 유지 권고.

3. **옵션 B 재정의 패턴** — 작업 진입 후 코드 구조 발견 시 사용자
   박제 (e.g. "Orchestrator method") 와 실제 구조 (AssetContext 분산)
   가 다른 경우, 사용자에게 옵션 (A/B/C) 제시 + 명시 결정 → ADR
   갱신. 박제 가벼움 보존 + 코드 스멜 차단.

---

## 6. 발견된 이슈 / 제약

### 6.1 전략 레벨 — Phase 0.7.3+ 검토 후보

1. **VOL 정책의 "069500 단일 회귀" — 자산군 분산 가치 약화** (가장
   중요한 발견). VOL 비중 142:1 (069500:214980) → 사실상 단일 자산
   운용. MDD -22.50% (069500 5-year MDD 그대로). 자산군 분산이 정책
   설계상 채권 비중 ↓ 시 자동으로 약화됨. **Phase 0.7.3 결정 라운드
   #8 핵심 검토 항목** — 종목 조합 변경 (채권 → 변동성 더 높은 분산
   자산, e.g. 골드 132030 / 부동산).

2. **INV_VOL 의 "안정 자산 단독 운용 극한" — 7-split 세븐스플릿 가치
   부정**. INV_VOL 비중 1:136 → 사실상 채권 단일. 1 split 으로 충족
   (cumulative_sells 13 — 채권 매도 거의 없음). 세븐스플릿의 본질
   (가격 하락 시 분할 매수) 이 채권 단일에는 적용 불가. **§14.7 γ
   (자산별 다른 정책) 후속 검토** — 라운드 #8 항목.

3. **H1 자본 활용 측정 한계 — 옵션 A 균등 분모의 의미 한계** (§17 박제).
   INV_VOL 의 채권 commit 압도적이어도 균등 분모 50M 기준 측정 시
   util > 100% 가능 — 그러나 실측 14.27% 로 baseline 미달. 채권 ETF
   의 본질 (5% drop 트리거 거의 미발화) 의 자연스러운 결과. **H1 측정
   정의 자체의 retrospective 가치**.

### 6.2 인프라 레벨 (해소됨)

1. **BacktestRunner override 옵셔널 패턴 (옵션 C1)** — runner 단일
   파일 변경. callers regression zero. AssetContext 분산 구조와 자연스러운
   통합.

2. **AssetStrategyBundle / Config schema 확장** — `allocation_policy`
   필드 (default EQUAL) → 기존 yaml 호환성 자동 보존.

3. **scripts/ 패턴 일관성** — Phase 0.7.1.d / 0.7.1.h 와 동일 (verify
   + run + analyze 분리). Phase 0.8 / 0.9 에서 재사용 가능.

### 6.3 코드 레벨 (해소됨)

1. **CSV market data loader 재사용** — `--csv code=path` 형식 그대로
   (Phase 0.7.1.e 박제).

2. **출력 형식 — `format_backtest_result` 재사용** — 별도 스크립트가
   main.py 와 동일 JSON output → analyze 도구 호환.

---

## 7. 라운드 #7 결정 박제 결과 (ADR §17)

### 7.1 §17.2 결정 1=(a) — Phase 0.7.3 진입

진입 경로 정합 (§15.5.1.C):
```
Phase 0.7.2 (종료, 본 회고)
  ↓
Phase 0.7.3 (종목 다양화 — 다음 단계)
  ↓
Phase 0.7 종료 결정
  ↓
Phase 0.8 (지지선 전략, ADR 0004)
  ↓
Phase 0.9 (개별 주식, ADR 0005)
  ↓
Phase 1 (실거래, ADR 0006)
```

### 7.2 §17.3 결정 2=(iii) — H3 임계 정의 명시화

- strict 비교 = `Sharpe ≥ 0.33` (반올림 임계)
- baseline 자기 동치 = EQUAL 5 지표 1e-4 오차 PASS 시 H3 동치 인정
- 측정 결과 변경 zero — `phase-0.7.2-results.md` 표 그대로

### 7.3 §17.4 결정 3=(γ) — 게이트 결과 분리 박제

- EQUAL 통과 = 회귀 invariant 검증 통과 (옵션 C1 패턴 정합성 입증)
- VOL 통과 = 정책 효과 측정 통과 (자산군 분산 약화 부산물)
- INV_VOL 미달 = Sharpe 단독 통과 차단

---

## 8. Phase 0.7.3 권고 (다음 단계)

### 8.1 우선순위 1 — 라운드 #8 결정 박제

종목 조합 + 종목별 정책 + 게이트 baseline + 데이터 준비:

- **종목 후보**: 채권 (214980) 대체. 골드 (132030) / 부동산 (e.g.
  TIGER 부동산인프라고배당 329200) / 변동성 ETF / 시장 다각화 (코스닥
  150) 등. 3 ~ 5 종목.
- **종목별 다른 정책 허용 (§14.7 γ)**: 자산별 drop_threshold / max_split
  / profit_target 다르게 허용 가능. ADR §7.3 정신 갱신 필요.
- **게이트 baseline**: Phase 0.7.2 결과 (EQUAL or VOL) 또는 새 baseline.
  Phase 0.7.2 의 strict 임계 (H3 0.33) 정밀도 발견 학습 — 라운드 #8
  baseline 정밀화 권고.
- **자본 배분 정책 default**: Phase 0.7.2 의 VOL 또는 EQUAL 채택. Phase
  0.7.3 검증 시 다른 차원 (종목 조합) 변경 → 1 차원 통제.

### 8.2 우선순위 2 — 정책-자산 부정합 처방

§6.1 후보 #1 / #2 / #3 동시 처방 가능 단계:
- 채권 ETF 제거 → 변동성 ETF 추가
- 종목별 다른 정책 (§14.7 γ) — 자산 특성에 맞는 임계 / max_split
- 자본 배분 정책 (§16.1) 효과 검증

### 8.3 우선순위 3 — 회귀 invariant 보존

Phase 0.7.1 + Phase 0.7.2 baseline 모두 회귀 invariant 보존:
- EQUAL 정책 + 0.7.1 yaml + 0.7.1 데이터 → 5 지표 일치
- 0.7.2 yaml 3 종 + 0.7.2 데이터 → 4-way 결과 일치
- 0.7.3 인프라 변경 (종목 조합) 이 위 invariant 깨지 않도록.

### 8.4 우선순위 4 — H3 임계 정밀화 (§17.3 후속)

Phase 0.7.3 의 baseline 갱신 시 H3 임계도 정확값 박제 (반올림 회피).
정의 명시화 (strict / 동치) 일관 적용.

---

## 9. Phase 0.7+ 권고 (후속 단계)

### 9.1 Phase 0.7 종료 결정 (Phase 0.7.3 종료 후)

§10.2 단계 간 게이트 후속 결정:
- 게이트 통과 / 부분 통과 / 미통과 분기
- §15.5.1 옵션 A 정신상 어느 경우든 Phase 0.8 진입

### 9.2 Phase 0.8 / 0.9 / 1 — §15.2 / §15.3 / 후속 ADR

- Phase 0.8 (지지선 전략, ADR 0004) — 매수 패러다임 차원
- Phase 0.9 (개별 주식, ADR 0005) — 종목 성격 차원
- Phase 1 (실거래 KIS API, ADR 0006) — Mock → 실거래

### 9.3 라운드 #5 옵션 A 재확인

본 회고는 §15.5.1 옵션 A (Phase 0.7 시리즈 완주 + Phase 0.8 / 0.9
직교 차원 추가) 정합. 변경 사유 없음.

---

## 10. 지표 요약

| 항목 | 값 |
|---|---:|
| 백테스트 기간 | 2020-01-02 ~ 2024-12-30 (1231 거래일) |
| 종목 | 069500 (KODEX 200) + 214980 (KODEX 단기채권 PLUS) |
| 초기 자본 | 100,000,000 KRW |
| 정책 | F (HybridTimeBasedReentry, cooldown=60), 5% drop / 10% target |
| 자본 배분 정책 | 3 종 비교 (EQUAL / INV_VOL / VOL) |
| Phase 0.7.1 회귀 invariant (EQUAL) | ✅ PASS — 5 지표 1e-4 오차 일치 |
| 게이트 (EQUAL) | 2/3 (회귀 invariant 검증 통과) |
| 게이트 (INV_VOL) | 1/3 FAIL (Sharpe 단독 통과 차단) |
| 게이트 (VOL) | 2/3 (정책 효과 측정 통과, 자산군 분산 약화) |
| 신규 코드 | allocation.py + 4b.2 runner override + scripts 2 종 |
| 단위 테스트 (신규) | 33 (allocation 19 + runner 6 + AssetContext 2 + schema 6) |
| 전체 regression | 687 passed |
| 결정 라운드 | #6 (§16) + #7 (§17) + 5 sub-round |
| 데이터 신규 | KRX_*_2019-2024.csv 2 종 (1477 rows × 2) |

---

## 11. Phase 0.7.2 → 0.7.3 진입 체크포인트

- [x] ADR §16 박제 (라운드 #6 + sub-결정) — 137bf3d ~ fca687d
- [x] ADR §16.13.9 박제 (옵션 C1) — bff82db
- [x] BacktestRunner override + 단위 테스트 — 9559a11
- [x] AssetContext 분산 검증 — 295b0cc
- [x] 회귀 invariant + 산식 검증 + scripts/run_phase_0_7_2_backtest.py — 4608d8e
- [x] strategies-0.7.2-{equal,inv-vol,vol}.yaml — 496dfab
- [x] scripts/analyze_phase_0_7_2.py — 660392d
- [x] phase-0.7.2-results.md — b12d313
- [x] ADR §17 라운드 #7 결정 박제 + §16.2 H3 narrative 갱신 — 90c0673
- [x] phase-0.7.2.md (본 회고) — 본 commit
- [ ] Phase 0.7.3 진입 결정 라운드 #8 — 다음 작업
  - 종목 후보 (3 ~ 5 종목, 채권 대체)
  - 종목별 다른 정책 허용 (§14.7 γ 재검토)
  - 게이트 baseline 갱신 + H3 임계 정밀화
  - 자본 배분 정책 default 채택
  - 데이터 준비 (KRX_<신규>_2019-2024.csv)
- [ ] CLAUDE.md §14 갱신 (Phase 0.7.2 종료 표기 + Phase 0.7.3 진입) — 0.7.3.a 진입
  commit 시점에 일괄
- [ ] docs/roadmap.md 갱신 — 0.7.3.a 진입 commit 시점에 일괄

---

*작성: 2026-05-05 (sub-step 0.7.2.f)*
*다음 회고: `phase-0.7.3.md` (Phase 0.7.3 종료 후)*
