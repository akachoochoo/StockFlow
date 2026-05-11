# 분석 phase 회고 — Phase 0.10.x ~ 0.10.aa + ad-hoc 분석

> 분석 phase narrative 회고 (통합).
>
> 기간: 2026-05-08 (Phase 0.10 종료 라운드 #17) ~ 2026-05-11 (본 회고 작성일).
> 범위: 사용자 피드백 트리거 4 sub-phase + 효성중공업 단일 종목 ad-hoc 분석.
>
> 선행 회고: `phase-0.10.md` (Phase 0.10 본체, 라운드 #16~#17).
> 후속: 라운드 #22 (가칭, 본 회고 후 사용자 결정) — Phase 1 진입 vs
> Phase 0.10.bb / 기타 trajectory 결정. Phase 1 ADR 0007 박제 = 라운드 #22 후속.

---

## 1. 마일스톤

Phase 0.10 정식 종료 (라운드 #17, ADR 0006 §13) 후 시작된 분석 phase 는
사용자 분석 보류 상태로 유지하되, 분석 과정에서 발견된 reporting layer
defect 4 건을 즉시 종결 sub-phase 로 처리. 추가로 사용자 ad-hoc 백테스트
(D-2 비교, 효성중공업 단일 종목, B&H 비교) 진행.

### 1.1 sub-phase 흐름

| 라운드 | sub-phase | 트리거 | ADR | commit |
|---|---|---|---|---|
| #18 | **Phase 0.10.x** — Episode HTML readability | "report 결과가 사람이 알아보기 힘들어. 개선할수 없을까?" | ADR 0006 §14 | 4 commits (87 (...lost)... / cd58087) |
| #19 | **Phase 0.10.y** — Chart legend + Strategy info | "그래프에서 레전드가 없어서 확인이 어렵네, Buy/Sell 색깔로 구분" + "어떤 매매로직인지 report 에 포함" | ADR 0006 §15 | 4 commits |
| #20 | **Phase 0.10.z** — Slot annotation injection (chart 검정 마커 bugfix) | "그래프에서 검은색 화살표는 무슨의미야?" | ADR 0006 §16 | 2 commits |
| #21 | **Phase 0.10.aa** — Per-symbol chart panels | "종목별 가격대가 다른데 모든 매수/매도 마트를 찍으니 확인하기 어려움" | ADR 0006 §17 | 2 commits |
| (분석) | **ad-hoc 분석** — D-2 비교 / 효성중공업 단일 종목 / B&H 비교 | "D-2 매매전략으로 report 생성" + "298040 단일 종목 진행" + "초기 자산 구매 vs D-2 차이" | (회고만) | (config + report-* 로컬 only) |

총 4 sub-phase × ~2 commit ≈ 12 commits + 1일~3일 작업.

### 1.2 ralplan consensus 진행 패턴

| sub-phase | iter | 결과 |
|---|---|---|
| Phase 0.10.x | 2 iter | Planner → Architect AGREE-WITH-CHANGES → Critic ITERATE → revise → APPROVE |
| Phase 0.10.y | 2 iter | 동일 패턴 + Critic 8 patches (γ' edge ring 거부 + legend 5 조정) |
| Phase 0.10.z | 2 iter | C1 → C2 switch (Clean Architecture 정합, Architect 주도) |
| Phase 0.10.aa | 2 iter | A1 + E1-E5 (sorted order / figure-leak AC / chart_symbol 제거) |

**4 / 4 모두 2 iter 후 APPROVE** — Planner → Architect → Critic loop 패턴 안정 도달.

---

## 2. 완료 기준 충족 검증

각 sub-phase 별 Acceptance Criteria:

| Sub-phase | AC 개수 | 충족 | 근거 |
|---|---|---|---|
| Phase 0.10.x | 10 | ✅ 10/10 | ADR §14.10 (places ≤ 2 / KRW / display_symbol / cycle FIFO / 의존성 zero 등) |
| Phase 0.10.y | 12 | ✅ 12/12 | ADR §15.10 (legend 5≤N≤12 / Korean labels / strategy info 8 rows / Protocol intact / 의존성 zero) |
| Phase 0.10.z | 12 | ✅ 12/12 | ADR §16.8 (chart 검정 0/48 / 차수별 panel 7 rows / 도메인 invariant / 의존성 zero) |
| Phase 0.10.aa | 14 | ✅ 14/14 | ADR §17.10 (5 chart panels sorted / figure leak == [] / skip_empty kwarg / `chart_symbol` removal) |

**전체 테스트**: 1010 (Phase 0.10 종료 시점) → 1041 (.y) → 1047 (.z) → 1050 (.aa). +40 신규 tests. 회귀 0.

**신규 박제 인터페이스**: `MarkerStyle` Protocol §4.2, SevenSplit slot palette §4.3.1, HTML stdlib f-string §7 모두 보존. 신규 의존성 zero (`pyproject.toml` byte-identical).

---

## 3. ad-hoc 분석 결과 (Phase 1 trajectory 결정 영향)

### 3.1 D-2 (MovingAverageReentry) vs F (HybridTimeBasedReentry cooldown=60)

**Phase 0.9.2 5종목 환경** (controlled — reentry 정책 1 차원만):

| 지표 | F (cooldown=60) | D-2 (MA20 SMA) | 차이 |
|---|---|---|---|
| Total return | **14.87%** | 14.51% | F +0.36pp |
| Sharpe | **0.2424** | 0.2392 | F +0.003 |
| Max drawdown | -37.65% | **-37.14%** | D-2 -0.51pp |
| Episode 수 | 4 | 5 | D-2 +1 |
| Trade 수 | 207 | 204 | F +3 |

**결론 (Phase 0.9.2 환경)**: F 가 D-2 미세 우위 (return / Sharpe), D-2 가 MDD 미세 개선. Phase 0.5 KOSPI 단일 종목 결론 유지하되 격차 좁아짐.

### 3.2 효성중공업 (298040) 단일 종목 — F vs D-2

| 지표 | F | **D-2** | 차이 |
|---|---|---|---|
| Total return | 77.92% | **135.80%** ⭐ | D-2 +57.88pp |
| Sharpe | 0.811 | **1.032** ⭐ | D-2 +0.221 |
| Max drawdown | -44.28% | **-41.16%** ⭐ | D-2 -3.12pp |
| Episode 수 | 3 | 8 | D-2 +5 |
| Trade 수 | 112 | 206 | D-2 +94 |

**결론 (효성중공업 환경)**: D-2 가 F 를 모든 3 차원에서 압도. 변동성 큰 단일 종목 + 강 상승 모멘텀 환경에서 가격 트리거 기반 (D-2) 이 시간 기반 (F) 보다 정확하게 진입 타이밍 포착.

**§3.1 vs §3.2 차이의 함의**: **strategy 우위 = 환경 (종목 특성) 의존**. F 가 분산 포트폴리오에서 우위, D-2 가 단일 변동성 종목에서 우위. Phase 0.5 박제 (F 채택) 는 KOSPI 단일 환경 한정 — 다른 환경에서는 재검토 필요.

### 3.3 효성중공업 D-2 vs Buy & Hold

| 전략 | 5-year return | 비고 |
|---|---|---|
| **Buy & Hold** | **+1,360.79%** ⭐⭐⭐ | ₩26,900 → ₩393,000, 100M 으로 3,717 주 후 보유 |
| D-2 | +135.80% | 8 episodes 분할 매매 |
| F | +77.92% | 3 episodes |

**B&H 가 D-2 대비 +1,225pp 압도**. PriceDropStrategy 의 본질적 한계 노출:

1. **단조 상승 종목 (가격이 5% 이상 떨어지지 않음) 에서 slot 1 만 채워짐** → 자본의 6/7 idle
2. **ProfitTargetSell +10% 매도 후 강 상승 모멘텀 못 잡음** → 5년 14.6 배 상승 종목에서 +10% 만 회수 후 재진입 cooldown 대기
3. **세븐 스플릿은 mean-reverting 환경 가정** — 단조 상승 종목 (효성중공업 / NVIDIA-like) 에서는 strategy 자체가 무력화

→ **종목 선정이 strategy 자체보다 훨씬 큰 영향**. ADR 0002 §1.3 controlled
experiment 정신 — strategy 의 ON-environment / OFF-environment 분리 필요.

---

## 4. 학습 및 발견

### 4.1 reporting layer 진화 패턴 (Phase 0.10.x~aa 공통)

- **분석 phase 발견 defect → 즉시 종결 sub-phase**: 사용자가 report 를
  사용하며 발견한 문제 (가독성 / chart marker / 가격대 / 검정 화살표) 가
  4 회 모두 ralplan consensus 로 처리됨. 패턴: 트리거 verbatim → consensus →
  ADR 박제 → 즉시 종결. 평균 2 iter, 평균 ~2 commit.
- **인터페이스 변경 zero 정책 유지 성공**: 4 sub-phase 모두 `MarkerStyle`
  Protocol §4.2 + SevenSplit slot palette §4.3.1 + HTML stdlib f-string §7
  보존. 의존성 zero. 도메인 변경 zero (Phase 0.10.z slot_number 도
  application enrichment 로 처리). Clean Architecture 정합.
- **Architect synthesis 가 일관되게 가치 있음**:
  - 0.10.x — `pair_cycles` 가 application layer 로 (chart 가 아닌)
  - 0.10.y — γ' edge ring 권고 (palette 변경 거부, 사용자 falsification 통해 더 좋은 안으로 수렴)
  - 0.10.z — C1 → C2 switch (uniform `slot_number` + 1-line adapter fix vs
    application layer 가 renderer 명명 capture)
  - 0.10.aa — sort by symbol code (dict insertion order 결합 회피)

### 4.2 Critic patches 의 효용

Critic ITERATE 가 일관되게 명확한 수정점 제시 — 가장 자주 등장한 패턴:

- **AC 자동화 강제** (smoke test → automated assertion): 0.10.y `<details>` 카운트,
  0.10.aa `plt.get_fignums() == []`
- **기존 fixture 충돌 사전 발견**: 0.10.z `_buy_record`/`_sell_record` reasoning
  default 가 새 strict invariant 와 충돌 → 사전 패치
- **silent-ignore 거부**: 0.10.aa `chart_symbol` no-op deprecated → explicit
  removal 권고 (CLAUDE.md §13.3 정합)

### 4.3 ad-hoc 분석에서 발견된 본질적 한계

- **세븐 스플릿 + ProfitTargetSell 의 ON-environment 범위**: mean-reverting
  변동성 종목. 단조 상승 / 단조 하락 / 추세 강 종목 에서는 무력화 (자본의
  대부분이 idle).
- **종목 선정 영향 압도**: 효성중공업 단일 종목 B&H = +1,360% vs 동일
  종목 D-2 = +135%. 분산 5 종목 baseline = +14.87%.
- **strategy 우위 ≠ universal**: F 가 5 종목 환경 우위, D-2 가 단일 변동성
  종목 우위. Phase 0.5 박제 (F 채택) 는 KOSPI 단일 환경 한정.

---

## 5. 미해결 / 다음 trajectory 후보

### 5.1 미해결 질문 (Phase 1 ADR 0007 박제 시 다룰 항목)

1. **종목 선정 정책**: 세븐 스플릿의 ON-environment 정의. mean-reverting
  종목 식별 자동화? 박영옥 가치주 스타일 자동 식별 (ADR 0002 §0)?
2. **B&H 대비 alpha 정의**: PriceDropStrategy 의 "분할 매수로 평균 단가
  낮춤" 가설이 단조 상승 종목에서 무력화 → B&H 대비 strategy alpha 측정
  지표 추가 검토.
3. **D-2 vs F 환경별 우위 박제**: §3.1 (5 종목) F 우위, §3.2 (단일 변동성)
  D-2 우위. Phase 1 시 환경별 reentry 정책 분기 검토.
4. **`MarkerStyle.side` 필드 / `TradeCycleView` view-model 승격**: 박제 미진행
  (Phase 0.11+ 검토 — ADR §17.12 / §15.12 등).
5. **`_INT_KEYS` vestigial cleanup** (ADR §16.7): `split_number` 키 제거 — Phase
  0.11+ deferred.

### 5.2 다음 trajectory 후보 (라운드 #22 결정)

| 후보 | 본질 | 예상 ADR |
|---|---|---|
| **Phase 1 진입** | KIS API + 손절 + 거래세 / 수수료 + partial fill + 텔레그램 알림. ADR 0007 박제 항목 10 (ADR 0005 §10.6.3) | ADR 0007 |
| **Phase 0.10.bb 추가** | Reporting layer 보강 — 탭 UI (≥10 symbols) / mpf multi-panel 재검토 / vestigial cleanup / Sharpe-Calmar episode-내 계산 | ADR 0006 §18 |
| **Phase 0.7.4 / 부동산** | ADR 0003 §18.12.4 placeholder | ADR 0003 §20 |
| **종목 선정 자동화 (mean-reverting filter)** | Phase 2+ AI 영역 — §3.3 B&H 패배의 본질적 처방 | TBD |
| **손절 정책 단독 검증** | Phase 0.9 데이터 근거 + max_loss_pct 본격 검토 | ADR 0007 §X |

본 회고 = trajectory 결정 zero. 라운드 #22 박제 시 사용자 명시 결정 후
ADR 박제.

---

## 6. 박제 항목 종합 (분석 phase 종료 시점)

| 항목 | 상태 |
|---|---|
| ADR 0006 §1 ~ §13 (Phase 0.10 본체) | ✅ |
| ADR 0006 §14 (Phase 0.10.x readability) | ✅ |
| ADR 0006 §15 (Phase 0.10.y chart legend + strategy info) | ✅ |
| ADR 0006 §16 (Phase 0.10.z slot annotation injection) | ✅ |
| ADR 0006 §17 (Phase 0.10.aa per-symbol chart panels) | ✅ |
| Acceptance Criteria — 4 sub-phase 별 합계 48/48 | ✅ |
| 전체 테스트 1050/1050 PASS | ✅ |
| CLAUDE.md §14 + §16.3 in-place 갱신 (4 회) | ✅ |
| roadmap.md 갱신 (4 회) | ✅ |
| **본 통합 회고 `phase-0.10-analysis.md`** | **✅ (현재)** |
| Phase 1 ADR 0007 박제 | ⏳ (라운드 #22, 사용자 결정 후) |
| 라운드 #22 trajectory 결정 | ⏳ (다음 단계) |

---

## 7. 박제 로그

회고 작성일: 2026-05-11
범위: Phase 0.10.x (라운드 #18) ~ Phase 0.10.aa (라운드 #21) + 분석 phase
ad-hoc (D-2 비교 / 효성중공업 단일 / B&H 비교)
ralplan consensus 누적: 4 sub-phase × 2 iter = 8 iter (모두 APPROVE)
신규 sub-phase commits: 12 commits (4 sub-phase × 평균 3 commit)
신규 tests: +40 (1010 → 1050)
선행 회고: `phase-0.10.md` (Phase 0.10 본체)
후속:
- 본 commit (회고 박제) — `docs/retrospectives/phase-0.10-analysis.md` 단독
- 라운드 #22 (가칭) — Phase 1 진입 vs 기타 trajectory 결정 + ADR 0007 박제
  (또는 Phase 0.10.bb 추가)

---

> **분석 phase 회고 박제 완료 (2026-05-11).** Phase 0.10.x ~ 0.10.aa
> 4 sub-phase 정식 마무리. 라운드 #22 (사용자 trajectory 결정) 진입 가능 —
> 본 회고 결과를 자료로 활용.
