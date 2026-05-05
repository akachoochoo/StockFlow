# Phase 0.8 시리즈 회고 — 매수 패러다임 비교 (단일 sub-step 종료)

> Phase 0.8 시리즈 narrative 회고. 작성일: 2026-05-06. sub-step 0.8.h.
> 결정 박제: ADR 0004 §1 (라운드 #10 — Phase 0.8 진입) + §7 (라운드
> #11 — Phase 0.8 종료). sub-step 회고: `phase-0.8.1.md`. 선행 시리즈
> 회고 (Phase 0.7 시리즈) 는 `phase-0.7.3.md` §7 (라운드 #9 박제 결과)
> 에 통합 박제 — 본 시리즈 회고는 단일 sub-step 시리즈 패턴 (0.8.1
> 만 진행) 으로 별도 파일.

---

## 1. 시리즈 마일스톤

| 일자 | 이벤트 | commit |
|---|---|---|
| 2026-05-05 | Phase 0.7 시리즈 정식 종료 + Phase 0.8 진입 (ADR 0004 §1 라운드 #10) | 99dade6 / 0b96de1 |
| 2026-05-05 | Phase 0.8.1 진행 (sub-step 0.8.b ~ 0.8.f) — 인프라 + 도메인 + 통합 + 백테스트 | b885b52 ~ e094257 |
| 2026-05-06 | Phase 0.8.1 종료 + Phase 0.8 시리즈 정식 종료 (ADR 0004 §7 라운드 #11) | b7b2717 |
| 2026-05-06 | 본 시리즈 회고 + sub-step 회고 + CLAUDE.md/roadmap 갱신 | (현재) |

**시리즈 기간**: 2 일 (2026-05-05 ~ 2026-05-06).

---

## 2. sub-step 흐름 (단일 sub-step 시리즈)

| sub-step | 상태 | 비고 |
|---|---|---|
| **0.8.1** (매수 패러다임 1 차원 변경) | ✅ 완료 (게이트 2/3 PASS) | sub-step 회고: `phase-0.8.1.md` |
| 0.8.2 (단기 매매 +3~5%) | ❌ 미진행 | ADR §7.2 옵션 b 거부 — H3 FAIL 상태에서 MDD 더 악화 위험 |
| 0.8.x (cooldown 도입 / whipsaw 완화) | ❌ 미진행 | ADR §7.3 처방 거부 — SupportLevelStrategy 정체성 약화 + data snooping 위험 |

→ Phase 0.8 시리즈 = **단일 sub-step 시리즈** (0.8.1 만 진행). Phase
0.7 시리즈 (0.7.1 → 0.7.2 → 0.7.3 3 sub-step) 와 다른 패턴.

---

## 3. 시리즈 종료 결정 박제 (ADR §7 라운드 #11)

### 3.1 결정 1 — Phase 0.8 시리즈 종료 + Phase 0.9 직진 (옵션 c)

근거 (ADR §7.2):
- 게이트 2/3 PASS = 다음 단계 진입 자격
- H3 FAIL = SupportLevelStrategy 의 본질적 trade-off (처방 가능한
  미달 아님)
- Phase 0.7.3 + Phase 0.8.1 종합 = "PriceDropStrategy + 분산이 본질"
- 박영옥 원전 정신 = PriceDropStrategy 매핑 (데이터 근거)
- ADR 0003 §15.5.1.C 옵션 A 매핑 일관 (Phase 0.7 → 0.8 → 0.9 직진)

### 3.2 결정 2 — H3 미달 처방 거부 (본질적 한계 인정, ADR §7.3)

cooldown / 슬롯별 차등 tolerance / 슬롯 5 정교화 모두 거부:
- cooldown = SupportLevelStrategy 정체성 약화 + F 정책 흉내 위험
- tolerance = data snooping (단일 백테스트 결과 튜닝)
- 슬롯 5 정교화 = 트리거 빈도만 조정 (H3 본질 미해결)

**"처방 가능한 미달" vs "본질적 한계" 구분**: 본 결과는 후자 (패러다임
자체의 trade-off). 처방 거부 = 데이터 정직성.

### 3.3 결정 3 — Phase 0.9 진입 default 박제 (ADR §7.4.2)

| 항목 | Phase 0.9 default |
|---|---|
| **buy_strategy** | **PriceDropStrategy** (검증된 가치) |
| **자산** | **개별 주식** (3 ~ 5 종목) |
| 자본 배분 | EQUAL |
| 매도 정책 | profit_target=10% / max_sells=7 |
| 재진입 정책 | F (HybridTimeBasedReentry, cooldown=60) |
| 게이트 | Phase 0.7.3 baseline strict |

**SupportLevelStrategy 보존** (§7.4.2):
- 코드 (`src/domain/strategies/support_level.py`) 보존
- yaml schema 보존
- ADR 0004 박제 보존
- Phase 0.9.x 후속 결합 검토 가능 (개별 주식 + SupportLevel 등)

### 3.4 결정 4 — narrative 회고 (§7.5)

- `phase-0.8.1.md` (sub-step narrative)
- `phase-0.8.md` (본 시리즈 회고)

### 3.5 결정 5 — CLAUDE.md §16 갱신 (§7.6)

옵션 α (in-place 갱신) — Phase 0.8 호환성 → Phase 1 호환성 (Phase 0.9
동안). 0.8.h.2 sub-step 책임.

---

## 4. 시리즈 학습 종합

### 4.1 패러다임 비교의 정직한 결론

> "PriceDropStrategy + 분산이 본질" — 데이터 근거 입증.

Phase 0.8.1 결과 (게이트 2/3 PASS) 는 통과 자격이지만, **Sharpe
0.5255 → 0.2679, MDD -8.27% → -21.28%** 의 큰 폭 악화는 패러다임
변경의 본질적 비용. 박영옥 세븐스플릿 원전 정신 (분할 매수 + 평단
관리) 은 PriceDropStrategy 의 의사결정 변수와 직접 매핑됨이 입증.

### 4.2 변수 통제 + 회귀 invariant 보존

Phase 0.8 = 매수 패러다임 1 차원 변경 (yaml `buy_strategy` 만). 다른
모든 변수 (자산 / 자본 배분 / 매도 / 재진입 / 기간) Phase 0.7.3 baseline
동일. **단일 변수 효과를 정확히 측정** + 모든 default path 가
PriceDropStrategy 그대로 동작 (728 → 748 passed, 0 regression).

### 4.3 Whipsaw 위험 가설의 정량적 입증

ADR §4.3.3 박제 시점 (Phase 0.8.d) 에 박제한 cooldown 무 trade-off
가설이 백테스트 결과로 확인. MDD -13pp 큰 폭 악화 = 가설 발현. **사전
가설 박제의 가치** — 결과 해석 시 data snooping 회피 가능.

### 4.4 Phase 0.7.2 VOL 정책 결과 패턴 일치

| 패턴 | Phase 0.7.2 VOL | Phase 0.8.1 SupportLevel |
|---|---|---|
| return / turnover ↑ | ✅ | ✅ |
| MDD / Sharpe ↓ | ✅ | ✅ |
| 결론 | EQUAL > VOL | PriceDrop > SupportLevel |

**자본 회전 활발화의 비용 = 위험 분산 약화** — 일관된 trade-off 패턴.

### 4.5 단일 sub-step 시리즈 패턴의 가치

Phase 0.7 시리즈 (3 sub-step) 와 비교:
- Phase 0.7.1 (인프라) → 0.7.2 (배분 정책) → 0.7.3 (종목 다양화)
  3 차원 순차 변경
- Phase 0.8 (매수 패러다임) = 1 차원 변경 — **단일 sub-step 으로 충분**

Phase 0.8.2 / 0.8.x 미진행은 결정 라운드 (§7) 의 명시적 거부 — Phase
0.7 와 다른 시리즈 형태이지만 동등한 결정 정합성 박제.

---

## 5. Phase 0.9 진입 권고

### 5.1 진입 경로 (ADR 0003 §15.5.1.C 옵션 A)

```
Phase 0.7 종료 (3/3 PASS) → Phase 0.8 진입 (단일 sub-step) →
Phase 0.8 종료 (2/3 PASS, 본질적 trade-off 인정) → Phase 0.9 진입
```

### 5.2 Phase 0.9 본질적 차원 변경

ETF → 개별 주식 (종목 성격 차원). 인프라 변경:
- 호가 단위 가변 / 거래 정지 / 액면분할 / 증권거래세 / 수수료 모델링

### 5.3 ADR 0005 (가칭) 트리거 항목 (CLAUDE.md §16.4 인용)

1. ETF → 개별 주식 종목 후보 (3 ~ 5 종목)
2. 호가 단위 가변 처리 (테이블 / 함수)
3. 거래 정지 / 액면분할 데이터 소스 + 도메인 처리
4. 증권거래세 / 수수료 모델링 정밀도 (`OrderResult` 필드 추가)
5. 백테스트 / 페이퍼 / 실거래 동일성 재검증
6. Phase 1 KIS API 진입과의 시점 관계

---

## 6. 후속 / 보류 항목

- **Phase 0.7.4 (부동산 분산)** — ADR 0003 §18.12.4 / §19.3 placeholder
  보존 그대로
- **§14.7 γ (자산별 다른 정책)** — ADR 0003 §19.4 보류 그대로
- **SupportLevelStrategy + 멀티 종목 결합** — Phase 0.9.x 후속 검토
  (ADR 0004 §1.10)
- **cooldown 도입 검토** (Phase 0.9.x / Phase 1+) — §7.3.2 정직성 박제
  인용 후 결정 가능
- **슬롯 5 정교화 / 슬롯별 tolerance** — Phase 0.9.x 후속 (data
  snooping 위험 검토)

---

## 7. Phase 0.8 → Phase 0.9 진입 체크포인트

- [x] Phase 0.8 진입 결정 박제 (ADR 0004 §1 라운드 #10)
- [x] Phase 0.8.1 인프라 + 도메인 + 통합 + 백테스트 (0.8.b ~ 0.8.f)
- [x] phase-0.8.1-results.md + 게이트 평가 (2/3 PASS)
- [x] Phase 0.8 종료 결정 박제 (ADR 0004 §7 라운드 #11)
- [x] sub-step narrative 회고 (`phase-0.8.1.md`)
- [x] 본 시리즈 회고 (`phase-0.8.md`)
- [ ] CLAUDE.md §16 갱신 (Phase 1 호환성 / Phase 0.9 동안) — 다음 commit
- [ ] roadmap.md 갱신 (Phase 0.8 종료 / Phase 0.9 진입) — 다음 commit
- [ ] Phase 0.9 진입 결정 라운드 (ADR 0005 가칭) — 별도 ADR 라운드
