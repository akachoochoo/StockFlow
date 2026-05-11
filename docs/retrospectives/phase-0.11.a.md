# Phase 0.11.a — DGT (Dynamic Grid Trading) Research-Namespace Overlay 회고

> Phase 0.11.a narrative 회고. 작성일: 2026-05-12. sub-step 0.11.a.5.
> 정본: ADR 0007 §1 + §2 + §3 (본 commit 동시) / 비교 표:
> `docs/retrospectives/phase-0.11.a-comparison.md`.

---

## 1. 위상 + 종료

Phase 0.11.a 진입 (2026-05-11, ADR 0007 §1 박제, ralplan consensus 라운드 #23
2-round) → 종료 (2026-05-12, ADR 0007 §3 박제, 본 회고).

기간: 2일 (2026-05-11 ~ 2026-05-12, 1 session 내 완주).

선행: Phase 0.10.bb 종료 (라운드 #22, ADR 0006 §18, 2026-05-11) 직후 분석
phase 의 첫 trajectory 결정.

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 / Commit |
|----------|------|---------------|
| 0.11.a.1 | D1~D11 결정 + ADR draft + roadmap | `04e95fe` |
| 0.11.a.2 | ADR §Namespace + CLAUDE.md §1.1 5th ring + check_namespace.sh | `0aa9fda` |
| (정정)   | ADR §2 — KRX tick 표 + AC6 floor + AC3 D8 rate (cost_model 진입 직전 발견) | `60d90ac` |
| 0.11.a.3a | KoreanMarketCostModel + AC1~AC6 (11 tests, 100% cov) | `7126b98` |
| 0.11.a.3b | DGTPrototypeRunner + Eq.1~5/Table 1 + namespace isolation test (51 tests) | `8181f73` |
| 0.11.a.4 | 5-year run + Phase 0.7.3 비교 + R6 측정 | `f75bf20` |
| 0.11.a.5 | 회고 + ADR §3 + CLAUDE.md §14/§16.4 + D10 archive (본 commit) | (current) |

7 commits in 2 days. 회귀 invariant 보존 (`src/{domain,application,adapters,
use_cases,cli,infrastructure,ports}/**` 변경 zero, `pyproject.toml` 변경 zero,
기존 1050+ tests 영향 zero).

---

## 3. 게이트 판정

ADR 0007 §1.4 G1~G4 + success criterion 재정의 (박제 primary, G2 informational):

### G1 (PRIMARY) — 수식 + KoreanMarketCostModel 박제
**판정**: **PASS**.

- AC1~AC6 (11 cost_model tests, 100% coverage) + Eq.1~5 + Table 1 (23 formula tests).
- 사용자 ADR draft §2 정신 ("깨지면 LLM 수정안 거부") 정합 — 박제 1차 방어선 활성.
- Evidence: `tests/research/test_cost_model.py` + `tests/research/test_formulas.py`. 34 tests pass.

### G2 (INFORMATIONAL) — DGT IRR vs Phase 0.7.3 baseline
**판정**: **FAIL** (anticipated, R1 mitigation 정신 — sub-step 성공 invariant).

- 4지표 (CAGR / MDD / Sharpe / Calmar) 모두 baseline 미달:
  - CAGR 1.23% < 2.58% (-1.35 pp)
  - MDD -19.55% < -8.27% (-11.28 pp 악화)
  - Sharpe 0.17 < 0.5255 (-0.35)
  - Calmar 0.063 < 0.3116 (-0.25)
- R1 (HIGH, 일봉 ≠ 분봉) 실증 — Architect Round 1 A2 antithesis "not faithful + not integrable" confirmed by data.
- Evidence: `docs/retrospectives/phase-0.11.a-comparison.md` §1 + §2.

### G3 (PRIMARY) — D4 + ADR header + 회고
**판정**: **PASS** (본 회고 commit 시점 완성).

- AC10 (D4=NO baselines.py 부재 invariant) ✅
- AC11 (ADR header grep G1~G4/D1~D11/§Namespace/§Lifecycle/§Sensitivity/R1~R7 — 25/25) ✅
- AC12 (회고 `## 게이트 판정` + 통합 권고) ✅ (본 §3 + §5)

### G4 (PRIMARY) — namespace CI + Decimal + 재현성
**판정**: **PASS**.

- AC13 (`scripts/check_namespace.sh` 7-ring grep OK, src.research isolated) ✅
- AC14 (`mypy --strict src/research/dgt/` 7 files Success) ✅
- AC15 (byte-identical 2회 실행 — `TestAC15Reproducibility`) ✅

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 | PRIMARY | ✅ PASS |
| G2 | INFORMATIONAL | ❌ FAIL (anticipated) |
| G3 | PRIMARY | ✅ PASS |
| G4 | PRIMARY | ✅ PASS |

**박제 primary 측면 sub-step 성공** — G1 + G3 + G4 PASS, G2 informational FAIL 은 R1
mitigation 정신 (박제 primary, runner secondary informational) 의 예상 결과.

---

## 4. R6 측정 (실행시간 / 메모리)

| 항목 | 측정 | Bound | 결과 |
|------|------|-------|------|
| 실행시간 (real) | 0.13s | 60s | ✅ |
| 최대 RSS | 36.78 MB | 1 GB | ✅ |
| Snapshot 수 | 1231 (5-year 일봉) | — | — |

Bound margin 매우 큼 — 실행 비용은 본 sub-step 의 trade-off 가 아님.

---

## 5. 통합 권고 — D10 = archive (default 채택)

ADR 0007 §1.7 lifecycle + §1.11 sub-step 0.11.a.5 명시. 3 옵션 평가:

| 옵션 | 권고 | 이유 |
|------|------|------|
| (a) **archive** | ✅ **채택** | `src/research/dgt/` 코드 보존 (Phase 1+ 재검토 / 분봉 ADR 트리거 시 참조). `KoreanMarketCostModel` = Phase 1 ADR 0008 (가칭) 재사용 후보. staleness tripwire = `tests/integration/test_namespace_isolation.py` FAIL. |
| (b) abandon | ❌ | 폐기는 박제 정신 (Phase 0.10.bb 패턴) 과 mismatch. cost model 재사용 가치 손실. |
| (c) promote | ❌ | G2 4/4 FAIL 으로 strategy registry 합류 정당화 불가. Phase 1 진입 결정 영역. |

**최종 D10 결정: archive**.

운영 정의 (ADR 0007 §1.7.1 + §2.5):
- `tests/integration/test_namespace_isolation.py` FAIL 시 자동 stale 표시.
- Phase 1 ADR 0008 (가칭) 도입 시점에 namespace isolation 가 깨지면 archive 의 의미가 종결.
- Calendar 6개월 reminder 가 아닌 운영 tripwire — Critic Round 2 Minor #5 정합.

---

## 6. 통합 결정 (DGT strategy registry 합류 여부)

ADR 0007 §1.1 사용자 spec Next Steps #4 verbatim:
> "buy-and-hold, 세븐 스플릿 단독 결과와 비교 → 통합 여부 결정"

**결정**: **합류 안 함 (registry 미통합 유지)**.

근거:
- §3 G2 4/4 FAIL — 일봉 환경 DGT IRR / MDD / Sharpe / Calmar 모두 Phase 0.7.3 baseline 미달.
- §3 R1 실증 — 분봉 → 일봉 arbitrage cycle 격감 + 자산군 분산 부재 (069500 단독).
- Phase 1 ADR 0008 (가칭) 진입 시 분봉 DGT 재검토 가능 (option B 결정 라운드 별도 트리거).

CLAUDE.md §16.1.4 단일 sell strategy 가정 + ADR 0007 §1.5 R5 (registry 우회) 정신 유지.

---

## 7. 핵심 학습

### 7.1 R1 (HIGH, 일봉 ≠ 분봉) 정량 박제

논문 (BTC/ETH 1분봉 24/7) 의 DGT 본질 = intraday arbitrage cycle 누적. 한국 ETF
일봉 (1230 bar / 5 year) 환경 + 거래세 0.18% sell + 수수료 0.015% 양방 적용 시:
- 85 trades (BUY + SELL 합) 중 SELL 효과 < BUY 비용 → wallet net negative (-49,765 KRW).
- Architect Round 1 A2 antithesis ("not faithful + not integrable") 4지표로 실증.
- Phase 1 ADR 0008 KIS API 분봉 검토 시 정량 근거 제공.

### 7.2 5th ring 격리 패턴 박제 — `src/research/`

ADR 0007 §1.6 § Namespace Discipline 박제 결과:
- `src/research/` 5th ring (outermost) + CLAUDE.md §1.1 갱신 → Clean Architecture 4-ring (Frameworks → Adapters → Use Cases → Domain) 모델 확장.
- `scripts/check_namespace.sh` 7-ring grep CI rule (D11 plain grep, import-linter dep 회피) — `tests/integration/test_namespace_isolation.py` 14 tests로 invariant 보장.
- 회귀 zero (Phase 0.10.bb 박제 invariant 보존) — Phase 1+ 분봉/AI 등 후속 실험적 모듈의 격리 pattern reusable.

### 7.3 박제 primary success criterion 재정의 (ADR 0007 §1.4)

Round 1 Architect A2 antithesis 흡수 결과:
- "박제 primary, runner secondary informational" 강등 → G2 FAIL 시에도 G1+G3+G4 PASS = sub-step 성공.
- 수식 + 한국 시장 마찰비용 모델 박제 = Phase 1+ 재사용 valuable (D10 archive 권고 정합).
- "실행이 spec 답 못 줘도 박제는 답이다" — 분석 phase 의 본질에 부합.

### 7.4 ADR drift 즉시 정정 패턴 — §2

0.11.a.3a 진입 시 `src/domain/tick_size.py:18-57` cross-check 결과 §1.8 + §1.10
mismatch 발견 → ADR §2 신규 박제 + silent 정정 거부 (CLAUDE.md §6.3 침묵의 실패 금지
정신). 패턴 자체 = 분석 phase 의 정직성 박제.

### 7.5 ralplan consensus 2-round 효율

Round 1 ITERATE (Critic 12 + Architect 5 + E1/E2 정정) → Round 2 APPROVE (모든
amendments 흡수 + 4 nudges non-blocking) → 코드 진입. Round 3 회피 = consensus
loop 의 효율적 종결 패턴.

---

## 8. 한계 / 정정 / 후속 권고

### 8.1 한계 — DGT 단독 069500 vs Phase 0.7.3 069500+132030 자산 1차원 차이

Phase 0.7.3 baseline 비교 시 D3 default (069500 단독) 와 baseline (069500 +
132030 EQUAL) 의 자산 차이 = 분산 효과 의 분리 측정 불가. 분산 부재가 G2 FAIL 의
일부 원인이지만 정량 분리 어려움. 본 한계는 ADR §1.7.3 D9 default abandon 정신
충분 (informational only).

### 8.2 정정 — ADR §2 KRX tick 표 + AC6/AC3 oracle

§7.4 참조. ADR drift 즉시 정정 패턴 박제 완료.

### 8.3 후속 권고 (D10 archive 후)

- **Q1**: Phase 1 ADR 0008 (가칭, D6 default) 진입 시 KIS API 분봉 가용성 검토 → 분봉 DGT 재검토 결정 라운드 트리거.
- **Q2**: `KoreanMarketCostModel` Phase 1 ADR 0008 에서 promote vs 재설계 결정 (Architect Round 2 Nudge 2).
- **Q3**: D7 (KRX tick 표) / D8 (거래세) 출처 URL/문서 버전 final 박제 (ADR §1.8 § Sensitivity 의무 — 본 회고 시점 사용자 확인 후 추가 박제 가능).

---

## 9. 다음 trajectory

분석 phase 의 첫 trajectory (DGT 검토) 종결. 사용자 다음 결정:

(a) Phase 0.11.b — 다른 placeholder (e.g., Phase 0.7.4 부동산 분산, score-based 종목 선정) 진입.
(b) Phase 1 진입 — KIS API 어댑터 (ADR 0008 가칭, D6 default).
(c) 분석 phase 종결 + 다음 session 결정 보류.

본 회고는 trajectory 결정 정보 제공 (Phase 0.11.a Decision Drivers §1 "사용자 분석
phase 의도 = trajectory 결정 정보" 충족).

---

## 10. References

- arXiv:2506.11921v1 (Chen, Chen, Jang 2025) — DGT 논문.
- `docs/decisions/0007-phase-0.11.a-dgt-research-namespace.md` — ADR 0007 §1 / §2 / §3 (본 commit 동시).
- `docs/retrospectives/phase-0.11.a-comparison.md` — 4지표 비교 표 + R1 실증.
- `docs/retrospectives/phase-0.7.3-results.md:45-54` — Phase 0.7.3 baseline verbatim.
- `docs/decisions/0005-phase-0.9-decisions.md` §9.6.2 — "자산군 분산 = H3 충분 조건" 핵심 학습.
- `docs/decisions/0006-phase-0.10-backtest-reporting.md` §18 — Phase 0.10.bb 종료 (선행 phase).
- ADR 0007 §1.15 — ralplan consensus 라운드 #23 박제 (Round 1 / Round 2).

---

**통합 권고: D10 = archive. 게이트 G1 + G3 + G4 PASS, G2 INFORMATIONAL FAIL (anticipated).
Sub-step 박제 primary 측면 성공. DGT strategy registry 미합류, Phase 0.11.a 종료.**
