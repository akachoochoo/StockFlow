# Phase 0.8.1 회고 — 매수 패러다임 비교 (PriceDropStrategy vs SupportLevelStrategy)

> Phase 0.8.1 narrative 회고. 작성일: 2026-05-06. sub-step 0.8.h.
> 정량 결과: `phase-0.8.1-results.md`. 결정 박제: ADR 0004 §1 (라운드
> #10 — Phase 0.8 진입) + §6 (Phase 0.8.f 백테스트 결과) + §7 (라운드
> #11 — Phase 0.8 종료). 선행 회고: `phase-0.7.3.md`. 패턴 정합 (Phase
> 0.7.x narrative 패턴).

---

## 1. 마일스톤

Phase 0.8 진입 (2026-05-05, ADR §1 라운드 #10) → Phase 0.8.1 단일
sub-step 진행 → Phase 0.8 종료 (2026-05-06, ADR §7 라운드 #11). **2 일
완료** — Phase 0.7.x 인프라 (BacktestRunner / AssetContext / yaml
loader / MockBroker) 재사용 + 변수 1 차원 통제 (buy_strategy 만 변경).

### 1.1 sub-step 흐름

| sub-step | 내용 | commit |
|---|---|---|
| 0.8.a | ADR §1 라운드 #10 박제 (Phase 0.8 진입, 지지선 패러다임) | 99dade6 |
| 0.8.a.1 | CLAUDE.md / roadmap 갱신 (Phase 0.7 종료 / 0.8 진입) | 0b96de1 |
| 0.8.b.0 | ADR §2 박제 (7 슬롯 매핑 + 우상향 전제 + 슬롯 즉시 활성) | b885b52 |
| 0.8.b | indicators 모듈 (calculate_sma + find_recent_high) | b05cb21 |
| 0.8.c | SupportSlot 모델 + Position.slots union + ADR §3 | 7409572 |
| 0.8.d | SupportLevelStrategy 도메인 구현 + ADR §4 | 098eadc |
| 0.8.e | BacktestRunner + DailyOrchestrator + factory 통합 + ADR §5 | 1104223 |
| 0.8.f | yaml + script + 5-year 백테스트 실행 + ADR §6 (게이트 2/3 PASS) | e094257 |
| 0.8.g.1 | ADR §7 라운드 #11 박제 (Phase 0.8 종료 결정) | b7b2717 |
| 0.8.h.1 | 본 회고 + `phase-0.8.md` 시리즈 회고 | (현재) |
| 0.8.h.2 | CLAUDE.md / roadmap 갱신 (Phase 0.9 호환성) | (다음) |

---

## 2. 완료 기준 충족 검증

Phase 0.8 진입 시 ADR §1.7 (비교 baseline) + §1.6.2 (게이트 strict
임계) 박제 그대로:

| 완료 기준 | 충족 | 근거 |
|---|---|---|
| 변수 1 차원 통제 (buy_strategy 만 변경) | ✅ | yaml strategies-0.8.1.yaml = strategies-0.7.3.yaml + buy_strategy: support_level (다른 모든 필드 동일) |
| 회귀 invariant (PriceDropStrategy 변경 zero) | ✅ | 동일 script 로 baseline yaml 실행 시 5 지표 모두 1e-4 이내 일치 (results.md §회귀 표) |
| 5-year 백테스트 실행 | ✅ | 2020-01-02 ~ 2024-12-30 (1231 거래일) |
| 게이트 strict 평가 | ✅ | H1/H2/H3 strict 비교 (반올림 미적용 — §17.3 정밀도 학습) |
| 단위 테스트 + 통합 테스트 통과 | ✅ | 748 passed (746 + 2 신규 통합) |
| ruff + mypy 통과 | ✅ | 50 source files clean |
| 회귀 invariant 보존 (728 → 748 passed, 0 regression) | ✅ | Phase 0.7.3 / Phase 0.5 / Phase 0 모든 기존 테스트 통과 |

---

## 3. 5-year 결과 요약 (Phase 0.7.3 baseline 비교)

| 지표 | Phase 0.7.3 baseline | Phase 0.8.1 | diff |
|---|---:|---:|---:|
| Total return % | 13.2280 | **14.0586** | **+0.8306** |
| CAGR % | 2.5779 | 2.7392 | +0.1613 |
| Max drawdown % | -8.2737 | **-21.2815** | **-13.0078** |
| Sharpe ratio | 0.5255 | **0.2679** | **-0.2576** |
| Calmar ratio | 0.3116 | 0.1287 | -0.1829 |
| Capital turnover | 0.3270 | **0.4188** | **+0.0918** |
| Avg capital util % | 34.37 | 44.35 | +9.98 |
| Cumulative sells | 28 | 33 | +5 |

**개선 4 (return / CAGR / turnover / util) vs 악화 3 (MDD / Sharpe /
Calmar)** — 자본 회전 활발화 + 절대 수익 미세 개선 vs 위험 분산 약화의
trade-off.

---

## 4. 가설 검증 (ADR §1.6.2 게이트 strict)

| 가설 | 임계 | Phase 0.8.1 | 판정 | 학습 |
|---|---|---:|---|---|
| **H1** Capital turnover ≥ 0.3270 | strict | 0.4188 | ✅ PASS (+0.0918) | indicator-based 트리거 = 자본 회전 활발 |
| **H2** Total return % ≥ 13.2280 | strict | 14.0586 | ✅ PASS (+0.8306pp) | 자본 회전 활성화의 누적 수익 효과 |
| **H3** Sharpe ratio ≥ 0.5255 | strict | 0.2679 | ❌ **FAIL** (-0.2576) | MDD 큰 폭 악화로 위험조정 수익 미달 |
| **통과** | ≥ 2/3 | **2/3** | **✅ PASS** | 게이트 통과 = 다음 단계 진입 자격 |

**Final verdict — 통과 (2/3) but 본질적 한계 발현**:

- H1 + H2 통과 = SupportLevelStrategy 의 indicator-based 트리거가
  PriceDropStrategy anchored 트리거 대비 자본 회전 활발화 입증
- H3 미달 = MDD -8.27% → -21.28% (-13.01pp) 악화. 위험 분산 측면에서
  PriceDropStrategy 의 anchored + cooldown 매커니즘이 우월

---

## 5. 학습

### 5.1 패러다임 비교의 정직한 결론 — "PriceDropStrategy + 분산이 본질"

**Phase 0.7.3 + Phase 0.8.1 종합** (ADR §7.2.3 박제):

| 항목 | Phase 0.7.3 (PriceDropStrategy + 채권→골드) | Phase 0.8.1 (SupportLevelStrategy) |
|---|---|---|
| 게이트 | ✅ 3/3 strict PASS | ⚠️ 2/3 PASS |
| 본질 | **자산 분산 + anchored trigger** | indicator-based trigger + cooldown 무 |
| MDD | -8.27% (양호) | -21.28% (악화) |

→ **Phase 0.7.3 의 "정책-자산 부정합 처방" (채권→골드) 의 결정타가
PriceDropStrategy 의 anchored 매커니즘과 결합했을 때 발현**. 패러다임
변경 (가치 → 기술적) 자체는 자본 회전 활발화 + 절대 수익 미세 개선
까지는 가능하나, **위험 분산 측면에서 PriceDropStrategy 의 anchored
+ cooldown 매커니즘이 우월**.

박영옥 세븐스플릿 원전 정신 (분할 매수 + 평단 관리) 은 PriceDropStrategy
의 의사결정 변수 (평단 + 임계) 와 직접 매핑 — Phase 0.8.1 결과로 데이터
근거 입증.

### 5.2 Whipsaw 위험 발현 (ADR §4.3.3 박제 정합)

Phase 0.8.1 의 "cooldown 무 + indicator-based 트리거" trade-off:

- MA 이탈 직후 회복 시 매도 / 즉시 재매수 사이클 가능
- 주가 추가 하락 시 모든 슬롯 채워진 상태 → 추가 매수 불가 → 손실 누적
- MDD 큰 폭 악화 = 본 가설 발현의 정량적 입증

ADR §4.3.3 진입 박제 시점에 박제한 위험 가설이 백테스트 결과로 확인.
"패러다임 자체의 trade-off" — 처방 (cooldown 도입) 으로 해결 시도 시
SupportLevelStrategy 의 정체성 (indicator-based 즉시 반응) 약화 →
PriceDropStrategy F 정책의 흉내가 됨.

### 5.3 Phase 0.7.2 VOL 정책 결과와 trade-off 패턴 일치

| 항목 | Phase 0.7.2 VOL | Phase 0.8.1 SupportLevel |
|---|---|---|
| return | ↑ (개선) | ↑ (개선) |
| turnover | ↑ (개선) | ↑ (개선) |
| MDD | ↓ (악화) | ↓ (악화) |
| Sharpe | ↓ (악화) | ↓ (악화) |
| 결론 | EQUAL > VOL (자산 분산 약화) | PriceDropStrategy > SupportLevel (위험 분산 약화) |

→ **자본 회전 활발화의 비용 = 위험 분산 약화** 라는 일관된 패턴.

### 5.4 변수 통제의 가치 — 1 차원 변경의 학습 명확성

Phase 0.8.1 = `buy_strategy` 만 변경. 다른 모든 변수 (자산 / 자본 배분
/ 매도 정책 / 재진입 / 기간) Phase 0.7.3 baseline 동일. **단일 변수
변경의 효과를 정확히 측정** — Phase 0.5/0.7 시리즈 회고에서 박제한
변수 통제 원칙 (CLAUDE.md §13 / ADR 0001 §1.3) 의 가치 재입증.

### 5.5 회귀 invariant 보존의 패턴 — `cast` + 분기 dispatch

Phase 0.8.e (factory + AssetContext + DailyOrchestrator + MockBroker
통합) 에서 PriceDropStrategy 회귀 invariant 보존 패턴:
- yaml `buy_strategy` field default = price_drop (기존 yaml 변경 zero)
- AssetContext.strategy = union (PriceDropStrategy 분기 = 기존 동작)
- DailyOrchestrator isinstance dispatch (PriceDropStrategy 시그니처 변경 zero)
- MockBroker slot_model default = SplitSlot (기존 동작)
- BacktestRunner buy_strategy_name default = "price_drop"
- mypy `list[A] | list[B]` 한계 — `cast` 적용으로 runtime invariant 보존

→ 728 → 748 passed (0 regression) 로 정량 입증.

---

## 6. 발견된 이슈 / 제약

### 6.1 mypy `list[A] | list[B]` heterogeneous union 한계

`Position.slots: list[SplitSlot] | list[SupportSlot]` (homogeneous)
선언 시 mypy 가 iteration 후 heterogeneous union 으로 widening — 내부
에서 `list[_Slot]` (heterogeneous) 사용 후 Position 경계에서 cast 적용
패턴 도입 (ADR §3.5).

→ Phase 0.9+ persistence (sqlite) 진입 시 동일 패턴 재사용 가능.

### 6.2 순환 import (composition.py ↔ backtest_runner.py)

`src/cli/__init__.py` → `main.py` → `backtest_runner.py` → `composition.py`
→ `src/cli/__init__.py` 순환. lazy import (run() 메서드 내부) 로 해소.

→ Phase 0.9+ 새 composition root 추가 시 import 경계 재검토 필요.

### 6.3 SupportLevelStrategy 의 `drop_threshold_pct` 미사용

yaml `drop_threshold_pct` 필드는 SupportLevelStrategy 가 무시. yaml
schema 호환을 위해 그대로 유지 (Phase 0.7.x baseline 값 5.0). Phase
0.9+ 에서 SupportLevelStrategy yaml 분리 또는 schema-level 분기 검토
가능 (ADR §4.7 미박제 항목).

### 6.4 슬롯 5 단순화 (recent_high(60) = N일 max) 미해결

ADR §2.2.1 박제: "박영옥 '지지로 전환' 단순화 (Phase 0.8.x 정교화 가능)".
본 Phase 0.8.1 에서는 단순 N일 max 채택. "돌파 후 되돌림" 패턴 인식
정교화는 Phase 0.8.x 후속 검토 (ADR §2.7 미박제) — 그러나 §7 (Phase
0.8 종료) 박제로 Phase 0.9 우선. SupportLevelStrategy 보존 (§7.4.2)
으로 Phase 0.9.x 후속 결합 검토 가능.

### 6.5 cooldown 무의 명시적 trade-off

ADR §4.3.3 박제한 whipsaw 위험이 발현 (MDD -13pp 악화). cooldown 도입
거부 (§7.3.2 정직성 박제) — Phase 0.9.x 어느 시점에서 cooldown 도입
검토 시 §7.3.2 인용하여 data snooping 위험 명시 후 결정.

---

## 7. 라운드 #11 결정 박제 결과 (ADR §7)

사용자 명시 결정 (2026-05-06):

### 7.1 Phase 0.8 시리즈 종료 + Phase 0.9 직진

옵션 c (Phase 0.8 종료 + Phase 0.9 진입) 채택. 옵션 a (cooldown 도입)
+ b (단기 매매) + d (추가 분석) 거부.

근거 박제 (ADR §7.2):
- 게이트 2/3 통과 = 진입 자격
- H3 FAIL = SupportLevelStrategy 의 본질적 trade-off (처방 가능한
  미달 아님)
- ADR 0003 §15.5.1.C 옵션 A 매핑 일관 (Phase 0.7 → 0.8 → 0.9 직진)

### 7.2 H3 미달 처방 거부 (본질적 한계 인정)

cooldown / 슬롯별 차등 tolerance / 슬롯 5 정교화 모두 거부 (ADR §7.3).

근거 박제:
- cooldown = SupportLevelStrategy 정체성 약화 + F 정책 흉내 위험
- tolerance = data snooping (단일 백테스트 결과로 튜닝)
- 슬롯 5 정교화 = 트리거 빈도만 조정 (H3 본질 미해결)

### 7.3 ADR 박제 사항 (§7.4)

- §7.4.1 Phase 0.8.1 결과 명시 (게이트 2/3 + 본질적 trade-off)
- §7.4.2 Phase 0.9 진입 default = PriceDropStrategy + SupportLevelStrategy 보존
- §7.4.3 cooldown 도입 거부의 정직성 박제

### 7.4 narrative 회고 (§7.5)

- `phase-0.8.1.md` (본 회고)
- `phase-0.8.md` (시리즈 회고)

### 7.5 CLAUDE.md §16 갱신 (§7.6)

옵션 α (in-place 갱신) — Phase 0.8 호환성 → Phase 1 호환성 (Phase 0.9
동안). 0.8.h.2 sub-step 책임.

---

## 8. Phase 0.9 권고 (다음 단계)

### 8.1 Phase 0.9 진입 default (ADR §7.4.2)

| 항목 | Phase 0.9 default |
|---|---|
| **buy_strategy** | **PriceDropStrategy** (검증된 가치) |
| **자산** | **개별 주식** (3 ~ 5 종목) |
| 자본 배분 | EQUAL |
| 매도 정책 | profit_target=10% / max_sells=7 |
| 재진입 정책 | F (HybridTimeBasedReentry, cooldown=60) |
| 게이트 | Phase 0.7.3 baseline strict (H1=0.3270 / H2=13.2280 / H3=0.5255) |

### 8.2 Phase 0.9 본질적 차원 변경 (ADR 0003 §15.3 후보)

- ETF → 개별 주식 (종목 성격 차원)
- 인프라 변경: 호가 단위 가변 / 거래 정지 / 액면분할 / 증권거래세 +
  수수료 모델링
- 변수 통제: 종목 차원만 변경, ETF 분산 비교 가능 (ADR 0003 §18.5
  변수 통제 정신 정합)

### 8.3 Phase 0.9 ADR 0005 (가칭) 트리거 항목 (CLAUDE.md §16.4 인용)

1. ETF → 개별 주식 종목 후보 (3 ~ 5 종목)
2. 호가 단위 가변 처리 (테이블 / 함수)
3. 거래 정지 / 액면분할 데이터 소스 + 도메인 처리
4. 증권거래세 / 수수료 모델링 정밀도 (`OrderResult` 필드 추가)
5. 백테스트 / 페이퍼 / 실거래 동일성 (CLAUDE.md §7.4) 재검증
6. Phase 1 KIS API 진입과의 시점 관계

### 8.4 SupportLevelStrategy 보존 (§7.4.2)

- 코드 보존 (`src/domain/strategies/support_level.py`)
- yaml schema 보존 (`buy_strategy: Literal["price_drop", "support_level"]`)
- ADR 0004 보존 (Phase 0.8 결정 박제 그대로)
- Phase 0.9.x 후속 결합 검토 가능 (예: 멀티 종목 + SupportLevel /
  cooldown 도입 후 비교 등)

---

## 9. Phase 0.9.x / Phase 1 후속 (SupportLevelStrategy 보존)

§7.4.2 박제 그대로:

- **Phase 0.9.x 결합 가능성** — 개별 주식 환경에서 SupportLevelStrategy
  검증 (Phase 0.8.1 ETF 환경 결과와 비교)
- **cooldown 도입 검토** (Phase 0.9.x 또는 Phase 1+) — 도입 시 §7.3.2
  data snooping 위험 명시 후 결정
- **슬롯 5 정교화 / 슬롯별 tolerance** — Phase 0.9.x 후속 (data
  snooping 위험 검토)

---

## 10. 지표 요약

| 지표 | Phase 0.7.3 | Phase 0.8.1 | diff | gate |
|---|---:|---:|---:|---|
| Total return % | 13.2280 | 14.0586 | +0.8306 | **H2 ✅** |
| CAGR % | 2.5779 | 2.7392 | +0.1613 | |
| Max drawdown % | -8.2737 | -21.2815 | -13.0078 | (H3 동반) |
| Sharpe ratio | 0.5255 | 0.2679 | -0.2576 | **H3 ❌** |
| Calmar ratio | 0.3116 | 0.1287 | -0.1829 | (H3 동반) |
| Capital turnover | 0.3270 | 0.4188 | +0.0918 | **H1 ✅** |
| Avg capital util % | 34.37 | 44.35 | +9.98 | |
| Cumulative sells | 28 | 33 | +5 | |
| **Gate verdict** | **3/3 strict PASS** | **2/3 PASS** | | |

---

## 11. Phase 0.8.1 → Phase 0.9 진입 체크포인트

- [x] ADR 0004 §1 (라운드 #10 — Phase 0.8 진입) 박제
- [x] indicators 모듈 + SupportSlot 모델 + SupportLevelStrategy 도메인 구현
- [x] BacktestRunner / DailyOrchestrator / factory / MockBroker 통합
- [x] config/strategies-0.8.1.yaml + 5-year 백테스트 실행
- [x] phase-0.8.1-results.md 박제 + 게이트 평가 (2/3 PASS)
- [x] ADR 0004 §7 (라운드 #11 — Phase 0.8 종료 결정) 박제
- [x] 본 narrative 회고 (`phase-0.8.1.md`)
- [ ] `phase-0.8.md` 시리즈 회고 — 본 commit 함께
- [ ] CLAUDE.md §16 갱신 (Phase 1 호환성, Phase 0.9 동안) — 다음 commit
- [ ] roadmap.md 갱신 (Phase 0.8 종료 / Phase 0.9 진입) — 다음 commit
- [ ] Phase 0.9 진입 결정 라운드 (ADR 0005 가칭 박제) — 별도 ADR 라운드
