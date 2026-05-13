# Phase 0.11.b — DGT Parameter Tuning & Sensitivity Analysis 회고

> Phase 0.11.b narrative 회고. 작성일: 2026-05-13. sub-step 0.11.b.5.
> 정본: ADR 0008 §1 + §2 + §3 (본 commit 동시) / sensitivity heatmap:
> `docs/research/phase-0.11.b/sensitivity-heatmap.md` (commit `76b2400`) /
> D11 trigger 판정: `docs/research/phase-0.11.b/d11-trigger-judgment.md`
> (commit `2f7ff56`).

---

## 1. 위상 + 종료

Phase 0.11.b 진입 (2026-05-12, ADR 0008 §1 박제, ralplan consensus 라운드 #24
2-round 효율적 종결) → 종료 (2026-05-13, ADR 0008 §3 박제, 본 회고).

기간: 2일 (2026-05-12 ~ 2026-05-13, multi-session).

선행: Phase 0.11.a 종료 (라운드 #23, ADR 0007 §3, 2026-05-12) — D10 = archive
default 채택 직후 사용자 명시 trajectory ("파라미터 튜닝 좋은 방법") + 5 ralplan
사이클 (#24~#28, ADR 0008~0012 §1 박제) 의 첫 실행 phase.

종료 사유: ADR 0008 §1.10 시나리오 C graceful degradation path 정합 —
**D11 AND-gate FAIL (구조적 unattainable)** → G2 INFORMATIONAL 강등 + D10
archive 확정 (supersede 없음).

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 / Commit |
|----------|------|---------------|
| 0.11.b.1 | D1~D12 결정 + ADR §1 박제 + Round 1 ITERATE 10 patches → Round 2 APPROVE-WITH-RECOMMENDATION + D11 (c) 삭제 정리 | `b58558d` |
| 0.11.b.2 | DGT optimization infra (WFO splitter + DSR Bailey-2014 + grid generator) + intra-research cross-import grep rule + 60 tests | `635e1d3` |
| 0.11.b.3 | WFO grid search (95 grid × 5-fold = 475 backtests) + D7 4-way baseline + B2 trade-level diagnostics + sensitivity heatmap Markdown + 19 tests | `76b2400` |
| 0.11.b.4 | D11 AND-gate 정식 판정 (FAIL) + perturbation 27 points + PBO informational + INFORMATIONAL 강등 + D10 archive 확정 + ADR §2 박제 + 19 tests | `2f7ff56` |
| 0.11.b.5 | 회고 + ADR §3 박제 + roadmap 갱신 (본 commit) | (current) |

5 commits in 2 days. 회귀 invariant 보존 (`src/{domain,application,adapters,
use_cases,cli,infrastructure,ports}/**` 변경 zero, `pyproject.toml` 변경 zero,
기존 1129 tests + 신규 98 = 1227 tests 영향 zero).

---

## 3. 게이트 판정

ADR 0008 §1.4 G1~G4 + Round 2 APPROVE 시점 success criterion 재정의:

### G1 (PRIMARY) — 튜닝 방법론 + parameter search space + OOS protocol 박제
**판정**: **PASS**.

- D3 (a) WFO + (c) coarse grid 병행 채택 박제 (`_grid_runner.py` 522 lines).
- D4 (i)~(iii) 3 차원 grid (n=[3,5,7,9,11], k=[1,2,3,5,7], m=[0,1,2,3]) — 95 valid points (m<n strict filter, `_grid_generator.py`).
- D5 OOS protocol = WFO 5-fold + train_ratio 0.8 + purge_gap 5 days + min_cycle 60 bars (3-cycle statistical power guard).
- D8 hard threshold (DSR ≥ 1.0 / purge ≥ 5 / perturbation worst > 0.3) 박제.
- D9 intra-research cross-import grep rule (`scripts/check_namespace.sh` 확장, BSD-compat 2-step).
- Evidence: 60 unit tests (test_wfo_splitter + test_dsr + test_grid_generator + test_namespace_isolation) 100% pass.

### G2 (CONDITIONAL PRIMARY) — D11 trigger 충족 여부 판정
**판정**: **INFORMATIONAL FAIL** (시나리오 C graceful degradation 정합).

D11 AND-gate 4 조건 정식 판정 (sub-step .4 산출):

| 조건 | 임계 | 합격/전체 | 결과 |
|---|---|---:|---|
| (a) 4-metric ±10% band | CAGR≥2.32% AND MDD≥-9.10% AND Sharpe≥0.473 AND Calmar≥0.280 | 58/95 | ✅ PASS |
| (b) DSR ≥ 1.0 | Bailey-López de Prado 2014 5% 유의 | **0/95** | ❌ FAIL (구조적 unattainable) |
| (c) OOS Sharpe ≥ 0.473 (informational) | baseline × 0.9 | 79/95 | ✅ PASS |
| (d) Perturbation ±10% worst Sharpe > 0.3 | D8 (iii) PRIMARY (renumber) | worst = 1.7541 | ✅ PASS |

**AND-gate 종합 = FAIL** ((b) 0/95 → 구조적 unattainable).

DSR 0/95 발현 원인:
- n_trials=95 multiple-testing penalty 강함 (Bailey 2014 §2.2)
- 작은 OOS sample size (60 bars × 5 folds = 300 returns 총합)
- 두 요인 결합 → SR_star (E[max SR under null]) > observed SR_OOS — 구조적 단점

ADR 0008 §1.10 시나리오 C ("strict G2 FAIL → INFORMATIONAL 강등 → D10 archive
확정") graceful degradation path 발현 — Architect/Critic Round 1 antithesis
pre-mortem 정확성 입증.

### G3 (PRIMARY) — ADR header + 회고 + D11 trigger 결과 박제
**판정**: **PASS** (본 회고 commit 시점 완성).

- ADR 0008 §1 박제 commit (`b58558d`) ✅
- ADR 0008 §2 박제 commit (`2f7ff56` — sub-step .4 산출 영역) ✅
- ADR 0008 §3 박제 (본 commit) ✅
- 회고 `docs/retrospectives/phase-0.11.b.md` 본 commit ✅
- D11 trigger 결과 박제 `docs/research/phase-0.11.b/d11-trigger-judgment.md` (`2f7ff56`) ✅

### G4 (PRIMARY) — namespace CI + Decimal + 재현성 (0.11.a G4 invariant 보존 + D12)
**판정**: **PASS**.

- `bash scripts/check_namespace.sh` exit 0 (7-ring + intra-research dgt isolation OK) ✅
- `mypy --strict` 영향 zero (5th ring `src/research/dgt/optimization/` — strict 미적용 영역) ✅
- Decimal invariant 보존 (`_dsr.py` / `_grid_generator.py` / `_perturbation.py` / `_pbo.py` 모두 stdlib only, float 미경유) ✅
- D12 reproducibility — 2회 실행 byte-identical (Decimal/data 동일, timestamp 만 차이) ✅

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 | PRIMARY | ✅ PASS |
| G2 | CONDITIONAL PRIMARY | ❌ INFORMATIONAL FAIL (D11 AND-gate (b) 0/95) |
| G3 | PRIMARY | ✅ PASS |
| G4 | PRIMARY | ✅ PASS |

**박제 primary 측면 sub-step 성공** — G1 + G3 + G4 PASS, G2 INFORMATIONAL FAIL
은 시나리오 C graceful degradation 정합 결과.

---

## 4. D10 budget 측정 (실행시간 / 메모리)

| 항목 | 측정 | Bound | 결과 |
|------|------|-------|------|
| sub-step .3 실행시간 (real) | 0.32s | 120s | ✅ (~375× margin) |
| sub-step .4 실행시간 (real) | 0.42s | 120s | ✅ (~285× margin) |
| 총 실행시간 | 0.74s | 120s | ✅ |
| 백테스트 횟수 | 475 (95 grid × 5 fold) + 27 (perturbation) + 1 (DGT best full-period) = 503 | — | — |

D10 (Round 2 박제) 추정 = 65s coarse + 30s PBO/WRC = 95s ~ 120s worst case.
실제 측정 = **0.74s** — 추정 대비 ~130× 빠름. 원인:
- DGT runner 의 stateful loop 가 NumPy-free Decimal 연산임에도 fast (1 bar 당 ~10μs)
- WFO splitter 의 index slicing O(1)
- DSR Acklam approximation closed-form (iteration zero)

Bound margin 매우 큼 — 실행 비용은 본 sub-step 의 trade-off 가 아님 (Phase 0.11.a R6 0.13s 정합).

---

## 5. 통합 권고 — D10 = archive 확정 (supersede 없음)

ADR 0007 §1.7 D10 = archive (default 채택, 2026-05-12 Phase 0.11.a 종료 시
박제) 결정의 **supersede 조건 미발동**:

- ADR 0008 §1.7 박제: "G2 PASS + D11 trigger 충족 → 0.11.b 회고에서 ADR 0007
  §1.7 D10 supersede 권고 명시."
- ADR 0008 §1.10 시나리오 C 박제: "D11 strict 채택 후 G2 FAIL → 0.11.b
  archive 확정 → 사용자 '왜 0.11.b 했냐?' 의문." → Mitigation: G2 FAIL graceful
  degradation — INFORMATIONAL 강등 + best parameter set + DSR/perturbation
  수치 박제 → Phase 1 ADR 0012 분봉 DGT 검토 시 정량 근거 활용.
- 사용자 결정 (2026-05-13, sub-step .3 종료 시점): "0.11.b.4 진입 — D11
  INFORMATIONAL 강등 + D10 archive 확정 시나리오 C 수락".

→ **D10 = archive 확정 (supersede 없음)**. ADR 0007 §3 회고 정본 유지.

---

## 6. 통합 결정 (DGT strategy registry 합류 여부)

ADR 0007 §1.7.2 promote 경로 trigger **미발동** (D11 AND-gate FAIL → ADR
0007 §1.7.2 supersede 정당화 부재).

→ **DGT registry 미합류 유지** (ADR 0007 §1.5 R5 박제 정신 보존). `create_buy_strategy`
factory grep = 0 invariant 유지. CLAUDE.md §16.1 항목 #4 단일 sell strategy
가정 보존.

`src/research/dgt/optimization/` (sub-step .2~.4 산출) = 5th ring 영구 유지
(research overlay, archive lifecycle). Phase 1 ADR 0012 D11 분봉 DGT 검토 시
정량 근거 활용 영역 — 단, Phase 1.1 실거래 진입 시 production rings 진입 zero.

---

## 7. 핵심 학습

### 7.1 DSR multiple-testing penalty 의 구조적 한계 (R1 정신 추가 박제)

**발견**: 일봉 1231 bar 환경 + n_trials=95 (grid size) 조합에서 DSR ≥ 1.0
충족 *구조적 불가능*. 95 grid 모두 DSR ∈ [-2.62, -1.33] 범위 음수 — observed
SR 가 SR_star (E[max SR under null]) 보다 작은 절대 다수 case.

원인 분석:
- Bailey-López de Prado 2014 §2.1 formula: SR_star = sqrt(SR_variance) ×
  ((1 - γ) × Z^(-1)(1-1/N) + γ × Z^(-1)(1-1/(N·e)))
  - γ = Euler-Mascheroni constant (0.5772...)
  - N = 95 → Z^(-1)(1-1/95) ≈ Z^(-1)(0.9895) ≈ 2.305 → SR_star 크게 증가
- WFO fold 당 OOS bar = 41 (1231 × 0.2 / 5) — 작은 sample → SR_variance 큼
  → 두 요인 결합 → SR_observed < SR_star

**원리**: n_trials × OOS sample 의 곱이 *충분히 크지 않으면* DSR ≥ 1.0
구조적 unattainable. 일봉 환경의 본질적 한계.

**ADR 0008 D8 (i) DSR ≥ 1.0 threshold 의 사후 평가**: 임계 자체는 정당
(Bailey 2014 5% 유의), 단 *적용 환경* (일봉 + 95 grid) 부적합. Phase 1 분봉
DGT 검토 시 = (a) n_trials 축소 (top-K 만 평가) 또는 (b) OOS sample 확대
(분봉 = 일봉 × ~390 bars/day) 으로 mitigation 가능.

### 7.2 자산군 분산 정신 4회 재확인 (ADR 0005 §9.6.2)

D7 4-way baseline 결과 (sub-step .3 sensitivity-heatmap.md):

| Baseline | Sharpe |
|---|---|
| (i) Phase 0.7.3 (069500+132030 EQUAL, 자산군 분산) | **0.5255** |
| (ii) 069500 단독 B&H | 0.2902 |
| (iii) 069500 단독 SevenSplit (KIS regime) | 0.3012 |
| (iv) 069500 단독 DGT-best (full period) | 0.1722 |

ADR 0005 §9.6.2 "자산군 분산 = H3 충분 조건" 정신 **4회째 재확인**:
- Phase 0.7.3 (주식+골드, 3/3 PASS)
- Phase 0.8.1 (069500+132030 EQUAL, 2/3 PASS H3 FAIL)
- Phase 0.9.2 (5종 업종 분산, 2/3 PASS H3 FAIL)
- Phase 0.11.b D7 baseline (단일 자산 시리즈 Sharpe 모두 0.30 미만)

**원리**: 단일 자산의 *전략 다양화* (B&H → 7split → DGT) 는 Sharpe 회복에
부족. *자산군 분산* (주식+골드+채권 등 cross-asset class) 이 H3 (Sharpe
≥ 0.5) 충족의 핵심.

Phase 1 ADR 0012 D11 = Phase 0.7.3 baseline (069500+132030 EQUAL) 채택
정합성 강화 — 본 학습이 D11 (c) "DGT promote = Phase 1.2 위임" 의 정량 근거.

### 7.3 시나리오 C graceful degradation 실제 발현 (Architect/Critic pre-mortem 정확성)

ADR 0008 §1.10 시나리오 C 박제 (Round 1 ITERATE Patch 5):
> "D11 strict 채택 후 G2 FAIL → 0.11.b archive 확정 → 사용자 '왜 0.11.b
> 했냐?' 의문. Mitigation: G2 FAIL graceful degradation — INFORMATIONAL 강등
> + best parameter set + DSR/perturbation 수치 박제 → Phase 1 ADR 0012 분봉
> DGT 검토 시 정량 근거 활용."

**실제 발현 정확성**:
- D11 AND-gate FAIL 시점 = sub-step .3 sensitivity heatmap 산출 (informational
  preview, 사용자 알림 + 사용자 결정 = 시나리오 C 수락).
- INFORMATIONAL 강등 + D10 archive 확정 = sub-step .4 정식 박제.
- Phase 1 ADR 0012 D11 정량 근거 박제 = sub-step .4 §2.7.

Architect/Critic Round 1 antithesis 의 *예측 정확성* — Phase 0.11.b 진입 전
이미 graceful degradation path 박제 → 실제 발현 시 cascading 없이 종료.

### 7.4 WFO + grid + DSR 의 reproducibility (D12)

D12 invariant: byte-identical 2회 실행 (timestamp 만 차이).

검증:
- sub-step .3 CLI 2회 실행 = 95 grid OOS Sharpe 모두 동일 수치 (Decimal
  precision).
- sub-step .4 CLI 2회 실행 = 27 perturbation worst/mean + PBO 0.2766 동일.
- 원리: stdlib only (random sampling zero) + itertools.product deterministic
  + Decimal-only 연산 (float 비결정성 회피) + WFO splitter index-based
  (round-half-up bias 회피).

Phase 0.11.a AC15 reproducibility 정신 (Decimal-only, 2회 byte-identical)
승계 확인.

### 7.5 일봉 한계 → 분봉 재검토 trigger (Phase 1 ADR 0012 D11 정량 근거)

ADR 0008 §1.5 R1 (HIGH) "일봉 ≠ 분봉" 가설 (Phase 0.11.a §1.8 박제) 의 강화
확인:
- 일봉 환경: DGT-best OOS Sharpe 2.27 (WFO) vs full-period 0.17 — fold-mean
  optimism + regime change.
- DSR 0/95 → 분봉 환경에서 (a) sample size 확대 ((분봉 ≈ 일봉 × ~390)
  + (b) n_trials 축소 (top-K only) 로 mitigation 정량적 가능.

Phase 1 ADR 0012 D11 = 분봉 DGT 검토 *정당화 정량 근거* 영역:
- Best parameter set (n=11, k=3%, m=1) 일봉 환경 OOS Sharpe 2.2701 → DSR
  -1.3307 (구조적 단점)
- 일봉 한계 → 분봉 재검토 정당화 박제 (Phase 1 ADR 0012 §1.5 R-DGT 가칭 영역)

---

## 8. 한계 / 정정 / 후속 권고

### 8.1 한계

- **DGT 일봉 = 구조적 unattainable** (DSR ≥ 1.0). 분봉 데이터 접근 = Phase 1
  영역 (KIS API 분봉 endpoint).
- **WFO single-pass (in-sample best 단순화 path)** — D5 정통 path (fold별
  best → OOS) 는 sub-step .4 영역으로 보류 (실제로 fold-mean 단순화로 진행).
  정통 path 적용 시 OOS Sharpe 변동 가능 (informational).
- **PBO simplified (Bailey 2017 §2.1)** — full CPCV (combinatorial purged
  cross-validation) 미적용. D8 (iv) OPTIONAL invariant 정합.

### 8.2 정정 (sub-step 진행 중 발견 + 박제 drift)

- **G2.1~G2.3 자본/기간 잔재** (ADR 0012, Phase 1 Round 2 시 Architect Round
  2 발견) — ADR 0008 자체 정정 부재, ADR 0012 Round 2 패치로 흡수.
- **D6 (ii) reconciliation 산술 오류** (ADR 0012, Phase 1 Round 2 시 발견) —
  ADR 0008 영향 zero.
- **Sub-step .4 ADR §2 박제 영역 정의** — Round 2 박제 영역 (Architect/Critic
  amendment 흡수) 정의가 §1 박제 commit 시점에는 모호 → sub-step .4 산출
  영역으로 재정의 (현 §2 박제 정합).

### 8.3 후속 권고

**Phase 0.11.c sub-step .2 진입** (사용자 결정 = 새 session, 0.11.b 종료 후):
- ADR 0009 §1.8 0.11.c.2 = `VisualizationRenderer` Protocol + `DGTVisualizationArtifacts`
  sidecar + intra-research cross-import grep rule + namespace test.
- Phase 0.11.b sub-step .2 의 `_grid_runner.py` / `_baseline.py` 출력을 ADR
  0009 comparison mode 의 입력으로 활용 가능 (D6 공통 축 매핑).

**Phase 1 ADR 0012 D11 분봉 DGT 검토 영역**:
- 본 회고 §7.5 정량 근거 인용 의무.
- 분봉 환경에서 sample size 확대 + n_trials 축소 mitigation 검증.
- Phase 1.2 진입 결정 라운드 시 별도 ADR (가칭 ADR 0014, 분봉 DGT) 박제 가능.

**ADR 0012 D16 (ii) Phase 0.11.b/c/d/e sub-step .2~.5 실행 진척**:
- Phase 0.11.b 완료 (5/16) — 본 commit.
- 잔여 11 sub-step (Phase 0.11.c.2~.5 + 0.11.d.2~.5 + 0.11.e.2~.5).

---

## 9. 다음 trajectory

**즉시 다음** (사용자 결정 = 새 session):
- Phase 0.11.c sub-step .2 진입 (ADR 0009 §1.8 정합).

**Phase 0.11 시리즈 전체 진척**:
- Phase 0.11.a 완료 (2026-05-12, `phase-0.11.a.md`)
- Phase 0.11.b 완료 (2026-05-13, 본 회고) — 5 commits, 98 신규 tests, DGT
  일봉 한계 정량 박제, D10 archive 확정.
- Phase 0.11.c (Visualization Renderers) — 다음.
- Phase 0.11.d (Asset-Specific Strategy Diagnosis) — 0.11.b/c 와 독립 병렬.
- Phase 0.11.e (Dynamic Adjustment L2/L3) — 0.11.d 완료 후 hard 의존.

**Phase 1 진입 시점** = ADR 0012 D16 (i)~(vi) 6 조건 모두 충족 후:
- (i) ADR 0008~0011 §1 박제 ✅ (2026-05-12)
- (ii) Phase 0.11.b/c/d/e sub-step .2~.5 실행 — 0.11.b 완료 (5/16)
- (iii) §16.4 + §16.1 항목 #2 정정 별도 2 commit
- (iv-a) KIS Mock 5 영업일 / (iv-b) KIS 모의투자 서버 5 영업일
- (v) D6 entry gate 5 조건
- (vi) NTP 동기화 검증

---

## 10. References

### Phase 0.11.b 5 commits

- `b58558d` — ADR 0008 §1 박제 (ralplan #24, 2026-05-12).
- `635e1d3` — Phase 0.11.b.2: DGT optimization infra + intra-research grep
  rule (2026-05-13).
- `76b2400` — Phase 0.11.b.3: WFO grid search + D7 baseline + B2 diagnostics
  (2026-05-13).
- `2f7ff56` — Phase 0.11.b.4: D11 AND-gate 정식 판정 (FAIL) + INFORMATIONAL
  강등 + D10 archive 확정 + ADR §2 박제 (2026-05-13).
- (current) — Phase 0.11.b.5: 회고 + ADR §3 박제 + roadmap 갱신.

### 박제 문서

- `docs/decisions/0008-phase-0.11.b-dgt-parameter-tuning.md` §1 + §2 + §3 (본
  commit) — Phase 0.11.b ADR 정본.
- `docs/research/phase-0.11.b/sensitivity-heatmap.md` (`76b2400`) — 95 grid
  sensitivity heatmap + D7 4-way baseline + B2 trade-level diagnostics.
- `docs/research/phase-0.11.b/d11-trigger-judgment.md` (`2f7ff56`) — D11
  AND-gate 정식 판정 + INFORMATIONAL 강등 + D10 archive 확정 + Phase 1 ADR
  0012 정량 근거 박제.

### Phase 0.11.a 정본 (선행)

- ADR 0007 (Phase 0.11.a) §1 + §2 + §3 — `src/research/` 5th ring 격리 +
  KoreanMarketCostModel + 박제 primary 정신.
- `docs/retrospectives/phase-0.11.a.md` — Phase 0.11.a 회고 (pattern reference).
- `docs/retrospectives/phase-0.11.a-comparison.md` — Phase 0.7.3 baseline 4
  지표 vs DGT 비교.

### 신규 코드 (5th ring `src/research/dgt/optimization/`)

- `_wfo_splitter.py` (90 lines, sub-step .2)
- `_dsr.py` (215 lines, sub-step .2, Bailey 2014 + Acklam approximation)
- `_grid_generator.py` (82 lines, sub-step .2)
- `_grid_runner.py` (522 lines, sub-step .3)
- `_baseline.py` (365 lines, sub-step .3)
- `_runner_cli.py` (427 lines, sub-step .3 + .4 subcommand)
- `_perturbation.py` (231 lines, sub-step .4)
- `_pbo.py` (102 lines, sub-step .4)
- 총 ~2034 lines (production code, stdlib only)

### 신규 tests (`tests/research/dgt/optimization/`)

- `test_wfo_splitter.py` (146 lines, 17 tests)
- `test_dsr.py` (184 lines, 15 tests)
- `test_grid_generator.py` (136 lines, 14 tests)
- `test_namespace_isolation.py` (81 lines, 4 tests)
- `test_grid_runner.py` (218 lines, 13 tests)
- `test_baseline.py` (153 lines, 6 tests)
- `test_perturbation.py` (158 lines, 12 tests)
- `test_pbo.py` (137 lines, 7 tests)
- 총 ~1213 lines + **98 tests** (regression zero, 1129 prior + 98 new = 1227
  total — 회귀 invariant 보존).

### Reference Papers

- Bailey & López de Prado (2014) — "The Deflated Sharpe Ratio: Correcting
  for Selection Bias, Backtest Overfitting, and Non-Normality." DSR formula
  + threshold (5% significance) 정본.
- Bailey, Borwein, López de Prado, Zhu (2017) — "The Probability of Backtest
  Overfitting." PBO simplified path 정본.
- López de Prado (2018) — *Advances in Financial Machine Learning*. CPCV +
  PBO + WFO 정본.
- Acklam (2003) — "An algorithm for computing the inverse normal cumulative
  distribution function." Normal CDF inverse closed-form approximation 정본.

---

**Phase 0.11.b 시리즈 종료** (2026-05-13). G1+G3+G4 PASS / G2 INFORMATIONAL
FAIL / D10 archive 확정. ADR 0012 D16 (ii) 4/16 → 5/16 진척. 다음: Phase
0.11.c sub-step .2 진입 (사용자 결정 = 새 session).
