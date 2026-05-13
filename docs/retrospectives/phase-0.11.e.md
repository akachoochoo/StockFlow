# Phase 0.11.e — Dynamic Adjustment Proposal Engine (L2/L3) 회고

> Phase 0.11.e narrative 회고. 작성일: 2026-05-14. sub-step 0.11.e.5.
> 정본: ADR 0011 §1 + §2 + §3 (본 commit 동시) / 코드 산출: 5th ring
> `src/research/dynamic_adjustment/` (~2030 LOC) + tests
> `tests/research/dynamic_adjustment/` (174 tests).

---

## 1. 위상 + 종료

Phase 0.11.e 진입 (2026-05-12, ADR 0011 §1 박제, ralplan #27 Round 1
ITERATE 14 patches 흡수 → Round 2 APPROVE commit `7586337`) → 종료
(2026-05-14, ADR 0011 §3 박제, 본 회고).

기간: 3일 (2026-05-12 ~ 2026-05-14, multi-session).

선행: Phase 0.11.d 종료 (라운드 #26, ADR 0010 §3, 2026-05-13) — D11
AND-gate 4/4 충족 + 후속 결정 라운드 진입 자격 완성. 사용자 명시
trajectory ("Phase 0.11.e로 진행해줘") 직후 본 phase 진입.

본 phase 의 본질: **5 ralplan 사이클 (#24~#28) 의 네번째 실행 phase**.
*비범한 위험성* (§1.3) — multi-asset-trading-system-design §1.3 "AI
일단위 파라미터 튜닝 거부" invariant 와 정면 충돌 가능 영역에 박제 →
§1.6 Design Contract 6 invariant 가 다른 phase 보다 strict + D15
governance "정신 supersede 불가".

종료 사유: 사용자 spec ("자동매매 전략 변경 + 파라미터 변경 + 종목
제거/추가 + 위험성 인지") 의 L2/L3 영역 박제 완료. *시스템은 제안만,
적용은 사람 + ADR* 본질 유지하며 4-state 머신 + ADR enforcement +
Reflexive overfitting 방지 + D14 structural constraints 완성. Phase 1
ADR 0012 진입 ready.

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 / Commit |
|----------|------|---------------|
| 0.11.e.1 | D1~D15 결정 + ADR §1 박제 + Design Contract 박제 (ralplan #27 Round 1 ITERATE 14 patches → Round 2 APPROVE) | `7586337` |
| 0.11.e.2 | `_Proposal` 도메인 (4-state + 8 필드) + `_ProposalHistory` (D14 cumulative + structural constraints) + `_TriggerSignal` / `_ProposalType` enum (exhaustive) + L2/L3 trigger evaluator + namespace test (77 tests) | `0a4ae64` |
| 0.11.e.3 | CLI proposal list / approve / reject / verify-adr / apply + ADR template scaffolding + APPROVED→ADR_FILED file_exists + content gate + end-to-end test (31 tests) | `d2e2feb` |
| 0.11.e.4 | §1.6 6 invariant verification command 전체 + D14 structural constraints 통합 test + 회귀 invariant cross-check (33 tests) | `879b926` |
| 0.11.e.5 | 회고 + ADR §3 박제 + roadmap / CLAUDE.md §14 갱신 + Phase 1 진입 ready 선언 (본 commit) → **별도 2 commit** (R7 mitigation): (A) CLAUDE.md §16.4 ADR 0008→0012 재번호, (B) §16.1 항목 #2 정정 (ADR 0010 옵션 Z 정합) | (current) + 별도 2 follow-up |

5 commits in 3 days + 2 follow-up commits 예정 (별도 commit, fold 금지).
회귀 invariant 보존 (`src/{domain,application,adapters,use_cases,cli,
infrastructure,ports}/**` 변경 zero, `pyproject.toml` 변경 zero, 기존
1307 tests + 신규 141 = 1448 tests 통과, regression zero).

---

## 3. 게이트 판정

ADR 0011 §1.4 G1~G4 정합. 본 phase 의 모든 게이트는 PRIMARY (실행 게이트
명확) — 0.11.d 의 *박제 only* 와 달리 코드 + tests + e2e cycle 검증
의무.

### G1 (PRIMARY) — Proposal 도메인 + L2/L3 trigger evaluator + 제안 박제 인프라

**판정**: ✅ **PASS** (sub-step .2 commit `0a4ae64`).

근거:
- `_Proposal` (4-state 머신 + 8 필드 + identity) frozen dataclass 박제.
- `_ProposalHistory` (D14 cumulative + 3 축 structural constraints) 박제.
- `_TriggerSignal` / `_ProposalType` / `_ProposalState` StrEnum exhaustive
  match — L1-shadow + STOP_LOSS + SELL_STRATEGY_CHANGE / REGIME_CHANGE
  부재 강제.
- `_TriggerEvaluator` (D1 AND-gate + NULL proposal semantics + sample
  size threshold) 박제.
- 77 unit tests (test_proposal_type / test_change_spec / test_proposal /
  test_proposal_history / test_trigger_evaluator / test_namespace_isolation).

### G2 (PRIMARY) — 사람 승인 워크플로우 end-to-end test

**판정**: ✅ **PASS** (sub-step .3 commit `d2e2feb`).

근거:
- CLI 5 subcommands (`proposal list / create-pending / approve / reject /
  verify-adr / apply`) 박제.
- ADR auto-template scaffolding + `<TBD>` placeholder verification gate
  (D6 hybrid).
- `_ProposalStore` JSON atomic write 박제.
- End-to-end test (`test_full_state_machine`): trigger → proposal → human
  approve → ADR 박제 → verify-adr → apply 한 사이클 통과.
- 31 tests (test_store / test_adr_template / test_cli_e2e).

### G3 (PRIMARY) — ADR header + 회고 + design contract 박제

**판정**: ✅ **PASS** (sub-step .1 + .5 commits).

근거:
- ADR 0011 §1 박제 (Round 2 APPROVE, `7586337`).
- ADR 0011 §1.6 Design Contract 6 invariant 박제 — 정신 supersede 불가
  (D15 governance).
- ADR 0011 §3 박제 (본 commit) — 시리즈 종료 + 게이트 종합 + Phase 1
  진입 ready.
- 회고 `docs/retrospectives/phase-0.11.e.md` (본 commit).

### G4 (PRIMARY) — namespace CI + mypy strict + 재현성 + Reflexive overfitting 방지

**판정**: ✅ **PASS** (sub-step .4 commit `879b926`).

근거:
- `bash scripts/check_namespace.sh` exit 0 (확장 rule 포함 — dgt /
  visualization / dynamic_adjustment intra-research isolation 보존).
- `uv run mypy src/research/dynamic_adjustment/` Success (10 source files).
- `uv run ruff check` All checks passed.
- §1.6 6 invariant 측정 가능 verification 33 tests 모두 통과:
  * #1 `proposal_auto_apply_blocked` ✅
  * #2 `no_realtime_data_identifiers` + Input field signature OOS-only ✅
  * #3 `reflexive_data_isolation` (Phase 1 trade log path 부재) ✅
  * #4 `adr_enforcement_blocks_apply` (APPROVED→APPLIED 차단) ✅
  * #5 `trigger_signal_enum_exhaustive` ✅
  * #6 `sell_proposal_blocked_without_adr0010` ✅
- 회귀 invariant — 1307 → 1448 tests (regression zero, +141 신규).

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 (Proposal domain + trigger evaluator) | PRIMARY | ✅ PASS |
| G2 (사람 승인 워크플로우 e2e) | PRIMARY | ✅ PASS |
| G3 (ADR + 회고 + Design Contract 박제) | PRIMARY | ✅ PASS |
| G4 (namespace + mypy + 재현성 + Reflexive 방지) | PRIMARY | ✅ PASS |

**4/4 PRIMARY PASS** — 0.11.c 와 동일 success pattern (infrastructure
phase + 코드 + tests + e2e). 단, 0.11.c (visualization, ~1535 LOC + 84
tests) 대비 0.11.e 는 *비범한 위험성* phase — Design Contract 6 invariant
+ D15 governance + R7 별도 2 commit 등 strict 의무 layer 추가.

---

## 4. 산출 측정

### 4.1 신규 코드 (5th ring `src/research/dynamic_adjustment/`)

| File | LOC | 본질 |
|------|----:|------|
| `__init__.py` | 30 | namespace marker + §1.6 invariant 박제 주석 |
| `_proposal_type.py` | 92 | TriggerSignal / ProposalState / ProposalType StrEnum exhaustive |
| `_change_spec.py` | 60 | L2 (parameter delta) / L3 (strategy/universe delta) frozen |
| `_proposal.py` | 192 | 8 필드 + identity + `_can_transition` + `_transition` |
| `_proposal_history.py` | 235 | D14 cumulative + 3 축 constraints + chain tracing |
| `_trigger_evaluator.py` | 194 | D1 AND-gate + NULL proposal semantics |
| `_store.py` | 200 | JSON atomic write + tagged Decimal/str round-trip |
| `_adr_template.py` | 119 | Template scaffolding + content verification gate |
| `cli.py` | 270 | 5 subcommands argparse-based |
| `__main__.py` | 11 | `python -m ...` entry shim |
| **Total** | **~1403** | 5th ring dynamic_adjustment overlay |

### 4.2 신규 tests (`tests/research/dynamic_adjustment/`)

| File | 테스트 수 | 본질 |
|------|--------:|------|
| `test_proposal_type.py` | 7 | enum exhaustive + 부재 강제 |
| `test_change_spec.py` | 8 | invariants + frozen + Decimal |
| `test_proposal.py` | 23 | state machine + transition guards + happy path |
| `test_proposal_history.py` | 20 | D14 3 축 + chain tracing |
| `test_trigger_evaluator.py` | 14 | AND-gate + NULL semantics + diagnostic |
| `test_namespace_isolation.py` | 5 | check_namespace.sh + grep token |
| `test_store.py` | 11 | round-trip × 4 + ops + atomic write |
| `test_adr_template.py` | 9 | scaffolding + 4 verification cases |
| `test_cli_e2e.py` | 11 | full state machine + 차단 + edge cases |
| `test_design_contract_invariants.py` | 16 | §1.6 6 invariant verification |
| `test_proposal_history_constraints.py` | 7 | D14 통합 시나리오 + boundary |
| `test_regression_cross_check.py` | 10 | Phase 0.7.3 baseline + ADR 0006/0009 frozen |
| **Total** | **141** | regression zero (1307 → 1448 = +141 신규) |

### 4.3 인프라 변경

- `scripts/check_namespace.sh` — visualization → dynamic_adjustment 역방향
  차단 + dynamic_adjustment → {dgt, visualization, intra-self} 정방향 grep
  rule 추가.
- production rings 변경 **zero** (§1.6 #1 measurable 충족).
- `pyproject.toml` 변경 **zero** (stdlib only — argparse / json / uuid /
  pathlib / tempfile / re / datetime / decimal).

---

## 5. 핵심 학습

### 5.1 "박제 primary" pattern 의 다른 layer — Design Contract 6 invariant

본 phase 의 §1.6 Design Contract 는 다른 phase 의 invariant 보존보다
*더 strict*:
- *측정 가능 verification* 의무 (예: `pytest -k <test_name>`).
- *정신 supersede 불가* (D15 governance) — Amendment 는 wording 정밀화만,
  정신 변경 = L4 trigger.
- *별도 test 모듈* (`test_design_contract_invariants.py`) 박제.

이 layer 가 의미하는 것: 본 phase 는 다른 phase 와 달리 "도메인 모델 +
runner 검증" 으로 끝나는 게 아니라 "도메인 모델 + runner 검증 + Design
Contract 6 invariant 측정 가능 verification + D15 governance + 정신
supersede 차단" 전체가 산출. *비범한 위험성* (§1.3 reflexive overfitting
+ 결정 누락 cascading) 의 mitigation layer.

→ Phase 1 이후 (혹은 본 phase 산출의 promote 시점) 본 invariant 의
*정신* 이 보존되는지 cross-reference 의무.

### 5.2 4-state 머신 + ADR enforcement = 자동 적용 차단의 측정 가능 구현

§1.6 #1 "시스템은 제안만 한다" invariant 의 측정 가능 구현:
- 4-state 머신 (PENDING → APPROVED → ADR_FILED → APPLIED).
- APPROVED → APPLIED **직접 전이 차단 hard** (§1.6 #4 invariant — code
  level 검증).
- ADR_FILED 진입 의무 (file_exists + content gate + `<TBD>` marker 부재).
- 사람 명시 `verify-adr` + `apply` 명령만 진전 가능.

→ "사람 승인 + ADR 박제 없이는 변경 적용 불가" 가 단순 정신적 invariant
가 아닌 *코드 path 강제*. `test_apply_from_approved_blocked` /
`test_adr_filed_requires_reference` 등이 fail-fast.

### 5.3 D14 Structural Constraints — 누적 cascading 차단의 정량 박제

§1.3 D14 + R2 mitigation 핵심:
- Minimum interval: 12 주 (분기 1회 한도).
- Cumulative drift bound: ±30% (초기 설정 대비 절대 변동).
- Trigger cooldown: 12 주 (동일 trigger 재발화 차단).
- Self-trigger chain: `previous_proposal_ref` 체인 추적.

→ "이번 변경 → baseline 갱신 → 다음 변경 → ..." cascading 의 *시간 +
크기 + 동기 외부화* 제약. 사람의 의식에 의존하지 않고 *코드 level 검증*.

`test_proposal_history_constraints.py` 의 boundary tests — 12 weeks
exactly + 30% exactly 통과 (inclusive) → 정확성 확인.

### 5.4 Reflexive overfitting 방지 = file path + identifier isolation

§1.6 #3 "Phase 1 실거래 데이터 backtest input 사용 절대 금지" 의 측정
가능 구현:
- Path pattern grep (data/live_trades / trades_live_ / kis_executed_orders
  / phase1_trade_log) 부재.
- Identifier-level grep (vix_* / *sentiment* / twitter_* / news_* /
  realtime_*) 부재.
- `_TriggerEvaluationInput` 시그니처 OOS-only (5 필드 — rolling Sharpe /
  current MDD / baseline MDD / sample size / human ad-hoc).

→ multi-asset-trading-system-design §1.2 "샘플 부족 (연 250 데이터
포인트 미만)" risk 의 *구조적 분리* — 코드 path 가 Phase 1 trade log 에
도달 불가능.

### 5.5 별도 2 commit (R7 mitigation) — fold 차단의 commit 단위 박제

R7 (NUMBERING) + ADR 0010 §1.6 #5 옵션 Z 패턴 정합:
- (A) CLAUDE.md §16.4 ADR 0008→0012 재번호 정정 — 본 ADR 0011 §1.9
  박제 의무.
- (B) CLAUDE.md §16.1 항목 #2 "AssetContext 의식" 정정 — ADR 0010 §3
  회고 옵션 Z 권고 정합.
- 두 commit 모두 본 회고 commit 과 **fold 금지** — CLAUDE.md §12.1
  commit 단위 원칙 정합.

학습: 정정 commit 은 *의미 단위* 로 분리 — "재번호" 와 "본문 정정"
이 *독립 항목* → 각각 별도 commit. fold 시 commit 의미 흐려짐.

---

## 6. 한계 / 후속 권고

### 6.1 한계

- **L1 (실시간 차단기) 미구현** — Phase 2 위임. 본 phase 의 L2 trigger
  는 *backtest OOS metric only*. L1 신호 (실시간 가격 / VIX / 뉴스) 는
  Phase 2 ADR 영역.
- **Universe change 자동화 미구현** — D8 `UNIVERSE_CHANGE` 는 *사람 인지
  trigger only* (수동 종목 추가/제거). 자동 발굴 / score-based 종목 선정
  = Phase 2+ 위임 (CLAUDE.md §14).
- **Sell strategy 차별화 미허용** — ADR 0010 §3 D4 결정 부재 → `ProposalType.
  SELL_STRATEGY_CHANGE` enum variant 자체 부재. ADR 0010 D4 결정 후 별도
  ADR 박제 필요.
- **ProposalStore = 단순 JSON 파일** — sqlite 등 영구화 = Phase 1 promote
  후 영역 (D13 lifecycle). 현 구현은 5th ring research overlay 수준.
- **D11 (실제 backtest 호출) 미구현** — `_Proposal.supporting_backtest_result`
  필드는 dict 로 받음. ADR 0008 optimization / ADR 0009 visualization
  산출과의 *명시적 결합* = 0.11.e.2/.3 영역 외 (sub-step .3 산출이 trigger
  값을 수동 입력 받음 — `--from / --to / --rationale`).

### 6.2 후속 권고 (Phase 1 진입 또는 후속 결정 라운드)

1. **Phase 1 ADR 0012 진입 시점에 본 phase 산출 자격 cross-check** —
   §1.6 6 invariant 정신 supersede 부재 + Design Contract 측정 가능
   verification 33 tests 모두 통과 유지.
2. **D11 backtest 호출 자동화** — `_TriggerEvaluator` 가 ADR 0008
   optimization 산출 + ADR 0009 visualization comparison 산출을 직접
   호출하는 wrapper. 본 phase 산출과 결합 시점 = 후속 sub-step.
3. **CLAUDE.md §16.1 항목 #2 정정 commit** — 옵션 Z 정합. ADR 0010 §3
   회고 권고 충족 시점 (D3 (ii) AssetContext 후보 채택 시) 와 본 phase
   별도 follow-up commit (B) 가 정합 — 후속 phase 진입 시 본 phase 의
   별도 commit (B) 가 정본 정정.
4. **D11 분봉 DGT 재검토 시 본 phase 의 D5 (Phase 1 실거래 데이터 사용
   정책) 재확인** — Phase 1 안정화 후 (i) 절대 금지 → (ii) 6개월 lag 후
   사용 허용 / (iii) Walk-forward 외부 데이터 path 검토 가능.
5. **D13 promote 조건 충족 여부 cross-check** — Phase 1 안정화 6개월 +
   Phase 2 차단기 완료 후 promote 후보. 본 phase = 5th ring 영구 유지
   default.

### 6.3 정정 사항 — 별도 2 follow-up commit

1. **(A) CLAUDE.md §16.4 ADR 0008→0012 재번호** — 본 commit 직후 별도
   commit. R7 mitigation 정합.
2. **(B) CLAUDE.md §16.1 항목 #2 정정** — `AssetContext` 기존 구현 발견
   박제 (ADR 0010 §3 회고 옵션 Z 권고 정합). 본 commit + (A) 직후 별도
   commit.

두 commit 모두 본 회고 commit 과 **fold 금지** (CLAUDE.md §12.1 commit
단위 원칙 + ADR 0011 §1.7 R7 mitigation 정합).

---

## 7. Phase 1 진입 Ready 선언 + 다음 Trajectory

### 7.1 Phase 1 진입 ready 선언

본 commit (sub-step 0.11.e.5) + 별도 2 follow-up commit 완료 시점에 ADR
0012 D16 (ii) 조건 충족:

> Phase 0.11.b/c/d/e sub-step .2~.5 실행 + 별도 2 commit + paper trading
> + NTP 동기화 후 Phase 1 진입.

- **Phase 0.11.b sub-step .2~.5**: 완료 (라운드 #24, 2026-05-13).
- **Phase 0.11.c sub-step .2~.5**: 완료 (라운드 #25, 2026-05-13).
- **Phase 0.11.d sub-step .2~.5**: 완료 (라운드 #26, 2026-05-13).
- **Phase 0.11.e sub-step .2~.5**: 완료 (라운드 #27, 2026-05-14 — 본
  회고 commit).
- **별도 2 commit**: (A) §16.4 재번호 + (B) §16.1 항목 #2 정정 — 본
  회고 commit 직후 박제 예정.

→ **ADR 0012 D16 (ii) 5/6 충족** (잔여: paper trading + NTP 동기화).

**Phase 1 진입 ready** — 코드 / tests / 박제 측면 모두 완성. 남은 의무 =
paper trading 1~2 개월 + NTP 동기화 (운영 측면).

### 7.2 다음 Trajectory

- **즉시 다음** (사용자 결정 대기): Phase 1 진입 결정 라운드 — paper
  trading 시작 + ADR 0012 §1 본격 박제.
- **Phase 0.11.f (가칭)**: D3/D4 후보 채택 결정 라운드 (ADR 0010 §2.5
  진입 절차 정합). Phase 1 진입 전 결정 vs 진입 후 결정 사용자 선택.
- **Phase 2 (AI 차단기 / L1 실시간 차단기)**: Phase 1 안정화 후 진입.
  본 phase 의 L2 trigger 와 L1 의 책임 경계 재검토 (Architect 권고 D13
  정합).

---

## 8. References

### Phase 0.11.e 5 commits
- `7586337` — Phase 0.11.e.1 ADR §1 박제 (ralplan #27 Round 2 APPROVE)
- `0a4ae64` — Phase 0.11.e.2 (도메인 + trigger evaluator + namespace test)
- `d2e2feb` — Phase 0.11.e.3 (CLI + ADR template + e2e state machine)
- `879b926` — Phase 0.11.e.4 (§1.6 verification + D14 + regression)
- `<current>` — Phase 0.11.e.5 (회고 + ADR §3 + roadmap + CLAUDE.md, 본 commit)
- (+2 follow-up commits 예정 — A: §16.4 재번호, B: §16.1 항목 #2 정정)

### 박제 문서
- `docs/decisions/0011-phase-0.11.e-dynamic-adjustment.md` §1+§2+§3
- `docs/retrospectives/phase-0.11.e.md` (본 회고)

### 선행 phase 정본 (인용 의무)
- ADR 0007 (Phase 0.11.a) — `src/research/` 5th ring 격리 패턴 원본.
- ADR 0008 (Phase 0.11.b) — DGT optimization 산출 (본 phase D11 입력) +
  D11 AND-gate trigger 패턴 원본.
- ADR 0009 (Phase 0.11.c) — Visualization renderer 산출 (본 phase D11
  입력) + intra-research cross-import 방향성.
- ADR 0010 (Phase 0.11.d) — 자산별 전략 차별화 진단 (본 phase D4 sell
  strategy 종속, §1.6 #6).

### 신규 코드 (5th ring `src/research/dynamic_adjustment/`)
- 10 파일 (`__init__.py` / `_proposal_type.py` / `_change_spec.py` /
  `_proposal.py` / `_proposal_history.py` / `_trigger_evaluator.py` /
  `_store.py` / `_adr_template.py` / `cli.py` / `__main__.py`) ~1403 LOC.

### 신규 tests (`tests/research/dynamic_adjustment/`)
- 12 파일 (test_proposal_type / test_change_spec / test_proposal /
  test_proposal_history / test_trigger_evaluator / test_namespace_isolation /
  test_store / test_adr_template / test_cli_e2e / test_design_contract_invariants
  / test_proposal_history_constraints / test_regression_cross_check) = 141 tests.

### CLAUDE.md 인용
- §7.1 — 모든 의사결정 reasoning JSON 보존 (D3 (iv) 정합).
- §10.1 — 단일 프로세스 cron (D7 (c) 정합).
- §11.3 — 자동 catch-up 금지 (D2 catch-up 정책 정합).
- §11.4 — 손실 한도 / 자동 손절 안 함 (D1 (ii) drawdown ≠ 손절 분리).
- §13.3 — 친절한 추가 금지 (§1.6 #5).
- §14 — "Phase 1 진입 전 작성 금지" / "score-based 종목 우선순위 / Hot
  reload — Phase 1+".
- §16.1 — 의식 박제 (항목 #2 정정 = 별도 follow-up commit B).
- §16.4 — Phase 1 ADR 재번호 (0008 → 0012 = 별도 follow-up commit A).

---

**본 회고 박제 완료 (Phase 0.11.e 시리즈 종료, 2026-05-14, sub-step
0.11.e.5). 게이트 4/4 PRIMARY PASS — 비범한 위험성 phase 의 Design
Contract 6 invariant + D14 structural constraints + D15 governance 모두
측정 가능 형태 박제. 산출: 신규 5th ring ~1403 LOC + 141 tests
(regression zero) + ADR 0011 §1+§2+§3 박제. Phase 1 진입 ready 선언 —
ADR 0012 D16 (ii) 5/6 충족 (잔여 = paper trading + NTP). 다음:
사용자 결정 대기 (Phase 1 직진 vs Phase 0.11.f).**
