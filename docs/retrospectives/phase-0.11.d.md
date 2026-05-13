# Phase 0.11.d — Asset-Specific Strategy Differentiation Diagnosis & Design 회고

> Phase 0.11.d narrative 회고. 작성일: 2026-05-13. sub-step 0.11.d.5.
> 정본: ADR 0010 §1 + §2 + §3 (본 commit 동시) / 진단 보고서:
> `docs/analysis/phase-0.11.d-current-structure-diagnosis.md` (commit
> `cdb6e4d`) / 후보 박제: `docs/analysis/phase-0.11.d-coupling-model-
> candidates.md` (commit `01b3867`).

---

## 1. 위상 + 종료

Phase 0.11.d 진입 (2026-05-12, ADR 0010 §1 박제, ralplan #26 Round 1
ITERATE 14 patches 흡수 → Round 1 APPROVED commit `af7549a`) → 종료
(2026-05-13, ADR 0010 §3 박제, 본 회고).

기간: 2일 (2026-05-12 ~ 2026-05-13, multi-session).

선행: Phase 0.11.c 종료 (라운드 #25, ADR 0009 §3, 2026-05-13) — 게이트 4/4
PRIMARY PASS + visualization comparison 산출. 사용자 명시 trajectory
("Phase 0.11.d sub-step .2 진입 (ADR 0010 §1 박제 후) — Asset-Specific
Strategy Diagnosis") 직후 본 phase 진입.

본 phase 의 본질: **5 ralplan 사이클 (#24~#28) 의 세번째 실행 phase**.
*분석 phase 의 분석 phase* — Phase 0.11.a 의 "박제 primary, runner
secondary" pattern 을 **극단까지 적용** (§1.4 — 모든 게이트가 박제 산출
정합성으로만 정의, 실행 게이트 zero).

종료 사유: 사용자 spec verbatim ("현재 구조가 멀티 자산 운용시 자산별로
전략과 전략의 세부 파라미터를 다양하게 가져갈수 있는 구조야?") 에 대한
정밀 진단 + 후보 박제 + supersede template + 회귀 invariant + 트리거
정량화 완성. 후속 결정 라운드 (가칭 Phase 0.11.f / Phase 1 ADR 0012)
입력 정본 5 점 박제 완료 (ADR 0010 §2.5 정합).

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 / Commit |
|----------|------|---------------|
| 0.11.d.1 | D1~D11 결정 + ADR §1 박제 (ralplan #26 Round 1 APPROVED + Round 2 close-out) | `af7549a` (Round 1) / `cdb6e4d` (Round 2 close fold into .2) |
| 0.11.d.2 | 현재 구조 진단 보고서 (D1+D2 — 5 layer + 8 증거 + 시그니처 dump) + ADR 0010 §1 status header → APPROVED | `cdb6e4d` |
| 0.11.d.3 | 자산-전략 결합 모델 후보 박제 (D3 4 후보 + D4 3 후보 + D7 16-cell 매트릭스 + D6 + D11 trigger 영향) | `01b3867` |
| 0.11.d.4 | ADR 0010 §2 박제 (D5 supersede verbatim template + D8 회귀 invariant + D11 트리거 4 조건 정량화) | `1fa12a6` |
| 0.11.d.5 | 회고 + ADR §3 박제 + roadmap / CLAUDE.md §14 갱신 + CLAUDE.md §16.1 항목 #2 정정 권고 (옵션 Z) | (current) |

5 commits in 2 days. 회귀 invariant 보존 (`src/{domain,application,
adapters,use_cases,cli,infrastructure,ports}/**` 변경 zero, `pyproject.
toml` 변경 zero, 기존 1307 tests 영향 zero).

---

## 3. 게이트 판정

ADR 0010 §1.4 G1~G4 정합. **모든 게이트가 박제 산출의 정합성으로만 정의** —
실행 게이트 zero (§1.4 invariant). Phase 0.11.a 의 "박제 primary, runner
secondary" pattern 의 극한 적용.

### G1 (PRIMARY) — 현재 구조 진단 보고서 박제

**판정**: ✅ **PASS**.

근거:
- `docs/analysis/phase-0.11.d-current-structure-diagnosis.md` (sub-step .2,
  commit `cdb6e4d`, 380 lines) 박제 완료.
- 5 layer 진단 surface (domain / use_cases / application / cli /
  infrastructure) + 8 증거 + 변경 surface 표 + 객체 시그니처 dump (5 파일
  × 절대 line range + commit hash `38da6bf` 박제).
- ADR 0010 §1.3 D1+D2 정본 충족.

### G2 (PRIMARY) — 자산-전략 결합 모델 후보 박제

**판정**: ✅ **PASS**.

근거:
- `docs/analysis/phase-0.11.d-coupling-model-candidates.md` (sub-step .3,
  commit `01b3867`, 398 lines) 박제 완료.
- D3 4 후보 (Mapping / AssetContext / Registry / Portfolio) trade-off
  표 + 5-dimension + D4 3 후보 (buy-only / buy+sell / sell stack)
  cascading 영향 surface + D7 16-cell 매트릭스 (4 후보 × 4 reporting
  객체).
- D6 Portfolio cash management trade-off 박제 + D11 trigger 결과별 D3
  영향 (positive / neutral / negative) 박제.
- ADR 0010 §1.3 D3+D4+D6+D7 정본 충족.

### G3 (PRIMARY) — ADR header + 회고 + supersede 시나리오 template 박제

**판정**: ✅ **PASS**.

근거:
- ADR 0010 §1 박제 (Round 1 APPROVED + Round 2 close-out, sub-step .1+.2).
- ADR 0010 §2 박제 (sub-step .4, commit `1fa12a6`):
  * §2.1 sub-step 진행 박제.
  * §2.2 D5 supersede verbatim template — ADR 0003 §19.4
    (`0003:2983-2993`) + ADR 0004 §7.4.2 (`0004:1588-1601`) verbatim 인용
    + 4 단계 절차.
  * §2.3 D8 회귀 invariant — Phase 0.7.3 baseline 4 metric assertion 의사
    코드 + 5 surface 파일 변경 zero 검증 + R6 self-reference paradox.
  * §2.4 D11 4 조건 정량화 — (i) 사용자 confirmation / (ii) 후보 박제
    commit hash / (iii) ADR 0008 D11 결과 / (iv) ADR 0009 산출 가용.
- ADR 0010 §3 박제 (본 commit) — 게이트 판정 + D11 4 조건 종합 + 사용자
  confirmation verbatim + 다음 trajectory.
- 회고 `docs/retrospectives/phase-0.11.d.md` (본 commit).
- ADR 0010 §1.3 D5+D9 정본 충족.

### G4 (PRIMARY) — namespace CI + mypy strict + D10 lifecycle 정의

**판정**: ✅ **PASS**.

근거:
- `bash scripts/check_namespace.sh` exit 0 (4 sub-steps 누적 — 7-ring +
  intra-research dgt/visualization isolation 보존).
- `uv run mypy src/` Success (코드 변경 zero — 0.11.c 종료 시점 정합 유지).
- `git diff 38da6bf..HEAD -- src/` empty (Phase 0.11.c 종료 commit 이후
  코드 변경 zero, §1.6 #1 measurable 충족).
- D10 lifecycle = deferred reference 박제 (§1.7) — staleness tripwire
  명령 박제 (§1.3 D10 + sub-step .2 §7 + sub-step .3 §9 + sub-step .4
  §2.3.2).
- 1307 tests 통과 (Phase 0.11.c 종료 시점 invariant 보존, regression zero).

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 (현재 구조 진단 보고서 박제) | PRIMARY | ✅ PASS |
| G2 (자산-전략 결합 모델 후보 박제) | PRIMARY | ✅ PASS |
| G3 (ADR header + 회고 + supersede template 박제) | PRIMARY | ✅ PASS |
| G4 (namespace + mypy + D10 lifecycle) | PRIMARY | ✅ PASS |

**4/4 PRIMARY PASS** — Phase 0.11.c 와 동일 패턴 (infrastructure /
diagnosis phase 본질 정합). 단, 0.11.c 는 *코드 변경 ~1535 lines + 84
tests*, 0.11.d 는 *코드 변경 zero + tests zero* — 박제 산출만으로 게이트
4/4 PASS 의 극한 적용.

---

## 4. 산출 측정

### 4.1 신규 박제 문서 (5 sub-step 누적)

| 파일 | LOC | 본질 |
|------|----:|------|
| `docs/decisions/0010-phase-0.11.d-asset-specific-strategy-diagnosis.md` (§1) | 270 | D1~D11 결정 + ralplan #26 Round 1 ITERATE 14 patches 흡수 |
| `docs/decisions/0010-phase-0.11.d-asset-specific-strategy-diagnosis.md` (§2 sub-step .4 신규) | 233 | D5 supersede template + D8 회귀 invariant + D11 트리거 정량화 |
| `docs/decisions/0010-phase-0.11.d-asset-specific-strategy-diagnosis.md` (§3 sub-step .5 신규) | ~150 (예상) | 시리즈 종료 박제 (게이트 + 학습 + trajectory) |
| `docs/analysis/phase-0.11.d-current-structure-diagnosis.md` (sub-step .2) | 380 | 5 layer + 8 증거 + 시그니처 dump |
| `docs/analysis/phase-0.11.d-coupling-model-candidates.md` (sub-step .3) | 398 | D3 + D4 + D7 + D6 + D11 영향 |
| `docs/retrospectives/phase-0.11.d.md` (sub-step .5) | ~280 (예상) | 본 회고 |
| **Total** | **~1711** | docs/ 신규 박제만 (코드 변경 zero) |

### 4.2 코드 산출 측정

| 항목 | 측정 |
|------|------|
| 신규 코드 | **zero** (§1.6 #1 measurable 충족) |
| 신규 tests | **zero** (코드 변경 zero 정합) |
| 기존 tests 변경 | **zero** |
| 회귀 영향 | **zero** (1307 tests 통과 보존) |
| Production rings 변경 | **zero** (`src/{domain,application,adapters,use_cases,cli,infrastructure,ports}/**`) |
| `pyproject.toml` 변경 | **zero** |
| `scripts/check_namespace.sh` 변경 | **zero** |

### 4.3 변경 surface 정량 (sub-step .2 §4 + sub-step .3 §2 정본 인용)

후속 결정 라운드 채택 시 변경 surface (현 phase 는 *측정만, 변경 zero*):

| Path | 변경 surface | 본질 |
|------|--------------|------|
| 차단 해제 1 | `src/cli/composition.py:230-243` | 단일 strategy 인스턴스 broadcast 해제 |
| 차단 해제 2 | `src/infrastructure/yaml_strategy_config_loader.py:157-201` | `_check_policy_uniformity` 완화 |
| 차단 해제 3 (조건부) | `src/cli/composition.py:239` | `ProfitTargetSell()` 하드코딩 해제 (D4 (b)/(c) 채택 시) |
| 활용 surface 1 | `src/application/backtest_runner.py:187` | `per_asset_strategy_overrides` 기존재 일반화 |
| 활용 surface 2 | `src/use_cases/asset_context.py:37-57` | `AssetContext` 기존재 활용 |
| 보존 surface | `src/domain/strategies/` | domain layer 전체 보존 |
| invariant 측정 | `BacktestRunner(per_asset_strategy_overrides=None)` | Phase 0.7.3 baseline 보존 |

**총 변경 surface = 3 (차단 해제) + 2 (활용) + 1 (보존) + 1 (invariant) = 7 박제**.

### 4.4 D11 AND-gate 4 조건 최종 충족 상태

| 조건 | 현 상태 (sub-step .5 commit 시점) | 충족? |
|------|---------------------------------|------|
| (i) 사용자 명시 confirmation | 본 §1 + 본 commit message + ADR §3 본문 박제 | ✅ 충족 |
| (ii) 후보 박제 commit hash | `01b3867` (sub-step .3) | ✅ 충족 |
| (iii) ADR 0008 D11 결과 | INFORMATIONAL FAIL → neutral path | ✅ 충족 |
| (iv) ADR 0009 산출 가용 | `3af0415` (sub-step 0.11.c.4) | ✅ 충족 |

**최종 종합**: **4/4 충족** — 후속 결정 라운드 (가칭 Phase 0.11.f / Phase 1
ADR 0012) 진입 자격 완성.

---

## 5. 핵심 학습

### 5.1 "박제 primary" pattern 의 극한 적용 — 코드 변경 zero로 게이트 4/4 PASS

본 phase = **분석 phase 의 분석 phase**. Phase 0.11.a 의 "박제 primary,
runner secondary" pattern 을 *극한까지 확장* — 코드 변경 zero / 신규 test
zero / 새로운 실험 zero. 모든 게이트가 박제 산출의 정합성으로만 정의.

이 패턴의 가치:
- **사용자 spec 의 정밀 진단** — "현재 구조가 자산별 차별화 가능?" 에 대한 5 layer × 8 증거 정밀 답변.
- **후보 박제만으로 결정 미루기** — D3 4 후보 + D4 3 후보 + D7 16-cell 매트릭스 = 후속 라운드 입력 정본. *지금 결정 안 함*.
- **변경 surface 정량화** = 3 (차단 해제) + 2 (활용) + 1 (보존) + 1 (invariant) = 7 박제 — 후속 라운드의 cost-benefit 계산 기반.

→ "박제 자체가 phase 의 산출" 의 측정 가능 정합성 입증.

### 5.2 Architect critical finding — 기존 구현 발견의 가치

Round 1 ITERATE 의 Architect critical finding (sub-step .2 §3 증거 6+7):
- `BacktestRunner.per_asset_strategy_overrides` (`backtest_runner.py:187`)
  기존재 — application layer 자산별 파라미터 차별화 경로 **이미 구현**.
- `AssetContext` (`asset_context.py:37-57`) 기존재 — use_cases layer
  자산별 strategy + config + sell_strategy 번들링 **이미 구현**.

→ "구조는 준비됨, 게이트가 닫힘" 진단 패턴. 사용자 spec ("자산별 다양화
가능?") 의 답이 "부분적으로 가능 — 구조는 있지만 정책 게이트로 차단" 으로
정밀화. D3 (i)/(ii) 후보가 *기존 구현 활용* path 로 식별 — *신규 인프라
도입* (iii)/(iv) 대비 거리 정보 명확.

→ **진단 phase 의 핵심 가치 = 기존 구현 발견 + 의식/현실 괴리 박제**.

### 5.3 CLAUDE.md §16.1 항목 #2 "AssetContext 의식" 괴리 박제

CLAUDE.md §16.1 항목 #2 박제: "AssetContext 기반 데이터 흐름 (코드 추가
금지)" — 그러나 실제 코드에는 `AssetContext` dataclass + `DailyOrchestrator`
/ `composition.py` 사용처 *이미 구현*.

→ **의식 (코드 추가 금지) vs 코드 현실 (이미 구현) 괴리**. 옵션 Z 채택 —
본 phase 진단 보고서에 괴리 기록 + sub-step .5 회고에 정정 권고 박제 +
정정 commit 안 함 (별도 라운드 영역).

학습:
- CLAUDE.md 박제와 코드 현실 사이의 drift 감지 자체가 진단 phase 의 산출.
- 옵션 Z (정정 commit 안 함, 권고만) 의 본질 = *정본 추적성 우선* — 후속
  결정 라운드에서 정정 시점이 supersede 결정과 함께 이루어지면 inflation
  회피.

→ 본 학습은 ADR 0011 §1.9 §16.4 정정 패턴 (별도 commit, fold 금지) 정합.
후속 phase ralplan 시 본 ADR §3 회고 인용 의무 (Pre-mortem 시나리오 C
mitigation).

### 5.4 구조적 비용 vs 정책적 비용 괴리 (Architect tension 1)

D4 (b) buy + sell 자산별 차별화 후보 분석에서 발견된 본질적 긴장:
- **구조적 비용**: `AssetContext.sell_strategy: SellStrategyPort` 기존
  union type 수용 → 차단 지점 2 곳 (`composition.py:239` 하드코딩 +
  `_check_policy_uniformity` 필드 비교) 만 완화하면 **구조 가능**.
- **정책적 비용**: CLAUDE.md §16.1 항목 #4 invariant 해제 = *구조와 무관*
  하게 높음. Phase 1 ADR 0012 §2 손절 정책과 동시 결정 필요.

→ **두 비용 차원 분리 평가의 필수성**. 후속 라운드 결정 시:
- 구조 비용만 평가하고 정책 비용 누락 → 과소 평가.
- 정책 비용만 평가하고 구조 비용 누락 → 과대 평가.
- 양 차원 동시 박제 = 정확한 trade-off.

### 5.5 후속 라운드 입력 정본 5 점 박제 — D11 AND-gate 4/4 충족

ADR 0010 §1.3 D11 4 조건 모두 충족 (sub-step .5 commit 시점):
1. 사용자 confirmation (§1 + 본 회고).
2. 후보 박제 commit `01b3867`.
3. ADR 0008 D11 결과 (INFORMATIONAL FAIL → neutral).
4. ADR 0009 산출 가용 (commit `3af0415`).

→ 후속 결정 라운드 (가칭 Phase 0.11.f / Phase 1 ADR 0012) **진입 자격
완성**. ADR 0010 §2.5 진입 절차 7 단계 박제 정합.

학습: **AND-gate 4 조건 정량화** = 후속 phase 의 *명확한 trigger*. "언제 다시
다룰까?" 의 모호함 제거.

---

## 6. 한계 / 후속 권고

### 6.1 한계

- **본 phase 는 결정 zero** — 후속 결정 라운드 (가칭 Phase 0.11.f 또는
  Phase 1 ADR 0012) 가 D3/D4 후보 채택 결정 필요. 본 phase 산출이 *입력
  정본* 일뿐 *결정 정본* 아님.
- **CLAUDE.md §16.1 항목 #2 정정 미실시** — 옵션 Z 정합. 정정 commit 은
  후속 결정 라운드 (D3 (ii) AssetContext 후보 채택 시) 와 동일 commit
  영역으로 위임.
- **Staleness tripwire 의존성** — 본 ADR 박제 후 5 surface 파일 (sub-step
  .2 §4 + sub-step .4 §2.3.2) 변경 발생 시 진단 stale → 재진단 의무. 후속
  phase 가 ralplan 시 staleness check skip 시 *잘못된 baseline* 으로
  결정 risk.
- **Phase 1 ADR 0012 D11 분봉 DGT 재검토 영향 미반영** — 현 상태 (2026-05-13)
  ADR 0008 D11 = INFORMATIONAL FAIL → neutral path 기반. Phase 1 진입 시
  분봉 환경 재평가 결과 (positive/neutral/negative) 가 D3 후보 식별에 미치는
  영향은 sub-step 0.11.d.3 §6 cross-reference 의무.
- **D6 Portfolio cash management 결정 보류** — 자산별 차별화 시 cash flow
  비대칭 처리 (Portfolio pool 공유 vs 자산별 격리) 본 phase 범위 외 + 후속
  라운드 영역.

### 6.2 후속 권고 (Phase 0.11.f 또는 Phase 1 ADR 0012 진입 시)

1. **ADR 0010 §2.5 진입 절차 7 단계** 의무 박제. D11 4 조건 재확인 → D3
   후보 선택 → D4 후보 선택 → 회귀 invariant 활성화 → Supersede 박제 →
   CLAUDE.md 정정 → 사용자 final confirmation.
2. **`per_asset_strategy_overrides=None` baseline 재현 test suite 박제** =
   ADR 0010 §2.3 의사 코드 활성화. Phase 0.7.3 4 metric (CAGR=2.5779% /
   MDD=-8.2737% / Sharpe=0.5255 / Calmar=0.3116) assertion + ± tolerance.
3. **CLAUDE.md §16.1 항목 #2 정정 (옵션 Z 활성화 시)** — AssetContext 의식
   문구 → "AssetContext 기존 구현 활용 path (composition.py 단일 instance
   broadcast 해제 + yaml validator 완화)" 으로 update.
4. **ADR 0009 `_align.py` strategy_id 분기 처리 확장** = D3 (ii)/(iii)
   채택 시 의무. sub-step 0.11.c.4 산출 갱신 commit.
5. **Phase 1 ADR 0012 §2 손절 정책과 동시 결정** = D4 (b)/(c) 채택 시 의무.
   CLAUDE.md §16.1 항목 #4 invariant 해제는 손절 정책 결정과 단일 commit
   bundle 권장.

### 6.3 정정 사항 — 없음

본 phase 는 *진단 + 박제 only* — 정정 사항 zero. CLAUDE.md §16.1 항목 #2
괴리는 *발견* 이지 *정정* 아님 (옵션 Z 정합, §8 정정 권고 박제 영역).

---

## 7. 다음 Trajectory

- **즉시 다음** (사용자 결정 대기): Phase 0.11.e 진입 (ADR 0011 §1 박제 후)
  또는 Phase 0.11.f (D3/D4 후보 채택 결정 라운드) 진입.
- **Phase 0.11.f vs 0.11.e 선택**:
  - Phase 0.11.e = Dynamic Adjustment (ADR 0011 §1 박제 대상). 본 phase
    산출과 독립.
  - Phase 0.11.f = D3/D4 후보 채택 결정 라운드 (본 ADR §2.5 진입 절차 의무
    박제). 사용자 명시 confirmation + ADR 0008/0009 정합 필요.
- **Phase 1 ADR 0012 D16 (ii) 진척**: Phase 0.11.d 완료 → 9/16 → 13/16.

---

## 8. CLAUDE.md §16.1 항목 #2 정정 권고 박제 (옵션 Z 정합)

### 8.1 현 §16.1 항목 #2 박제 (정본)

```
2. **종목별 잔고 분리 의식** — 단일 kill switch 가정 유지하되, 자산 격리
   정지 분기 가능한 `AssetContext` 기반 데이터 흐름.
```

→ "AssetContext 기반 데이터 흐름" 이 *의식* 으로 표현 — *코드 추가 금지*
의미.

### 8.2 코드 현실 (sub-step 0.11.d.2 §3 증거 7 정합)

`src/use_cases/asset_context.py:37-57` 의 `AssetContext` frozen dataclass
+ `DailyOrchestrator` / `composition.py` 사용처 *이미 구현*. 사용 path:
- `src/use_cases/asset_context.py` — dataclass 정의 (Phase 0.8 ADR 0004
  §5.4).
- `src/cli/composition.py:230-243` — AssetContext 구축 (단일 strategy
  instance broadcast).
- `src/use_cases/daily_orchestrator.py` — AssetContext list 순회.

→ "AssetContext 기반 데이터 흐름 (코드 추가 금지)" 의식 vs *이미 구현된 코드*
괴리.

### 8.3 정정 권고 (옵션 Z — 정정 commit 안 함, 권고만)

정정 시점 = 후속 결정 라운드 (D3 (ii) AssetContext 후보 채택 시) 와 동일
commit. 본 phase 는 *권고 박제만* + *정정 commit 안 함* (옵션 Z 정합).

**제안 §16.1 항목 #2 정정 문구** (후속 라운드 채택 시 참조):

```
2. **종목별 잔고 분리 의식** — 단일 kill switch 가정 유지하되, 자산 격리
   정지 분기 가능. `AssetContext` (`src/use_cases/asset_context.py:37-57`)
   기존 구현 활용 path: `composition.py:230-243` 단일 strategy instance
   broadcast 해제 + `yaml_strategy_config_loader.py:157-201`
   `_check_policy_uniformity` 완화. ADR 0010 §1.3 D3 (ii) AssetContext
   후보 정합 (sub-step 0.11.d.3, commit `01b3867`).
```

→ 정정 시점 = 후속 라운드 + 정정 commit 은 supersede 결정과 단일 commit
fold 권장.

---

## 9. References

### Phase 0.11.d 5 commits
- `af7549a` — Phase 0.11.d.1 ADR §1 박제 (Round 1 APPROVED, ralplan #26)
- `cdb6e4d` — Phase 0.11.d.2 (5 layer 진단 + ADR Round 2 close-out)
- `01b3867` — Phase 0.11.d.3 (D3+D4+D7 후보 박제)
- `1fa12a6` — Phase 0.11.d.4 (ADR §2 — D5+D8+D11 정량화)
- `<current>` — Phase 0.11.d.5 (회고 + ADR §3 + roadmap + CLAUDE.md, 본 commit)

### 박제 문서
- `docs/decisions/0010-phase-0.11.d-asset-specific-strategy-diagnosis.md`
  §1+§2+§3 (정본 ADR).
- `docs/analysis/phase-0.11.d-current-structure-diagnosis.md` (sub-step .2 산출).
- `docs/analysis/phase-0.11.d-coupling-model-candidates.md` (sub-step .3 산출).
- `docs/retrospectives/phase-0.11.d.md` (본 회고).

### 선행 정본 (인용 의무)
- ADR 0003 §19.4 (`0003:2983-2993`) — D5 supersede verbatim 인용 정본.
- ADR 0004 §7.4.2 (`0004:1588-1601`) — D5 supersede verbatim 인용 정본.
- ADR 0005 §9.6.2 — "자산군 분산 = H3 충분 조건" 핵심 학습.
- ADR 0007 (Phase 0.11.a) — "박제 primary" pattern 원본.
- ADR 0008 (Phase 0.11.b) §3 — D11 trigger 결과 (현 = INFORMATIONAL FAIL → neutral).
- ADR 0009 (Phase 0.11.c) §3 — visualization comparison 산출 (commit `3af0415`).

### 진단 surface (commit `38da6bf` 박제 시점)
- `src/application/backtest_runner.py:67-97` — BacktestResult.
- `src/application/backtest_runner.py:172-231` — BacktestRunner.__init__.
- `src/use_cases/asset_context.py:37-57` — AssetContext.
- `src/cli/composition.py:230-243` — strategy 공유 주입.
- `src/infrastructure/yaml_strategy_config_loader.py:157-201` —
  _check_policy_uniformity.

### CLAUDE.md 인용
- §13.3 — "친절한 추가 금지" (D4 (c) sell stack 경계).
- §14 — "Phase 1 진입 전 작성 금지 통합 목록" / "종목별 다른 정책".
- §16.1 항목 #2 — AssetContext (옵션 Z 정정 권고 §8).
- §16.1 항목 #4 — sell strategy 단일 가정.

---

**본 회고 박제 완료 (Phase 0.11.d 시리즈 종료, 2026-05-13, sub-step
0.11.d.5). 게이트 4/4 PRIMARY PASS — Phase 0.11.c 패턴 정합 (infrastructure /
diagnosis phase 본질). 산출: 신규 박제 ~1711 docs lines + 코드 변경 zero +
tests zero. D11 AND-gate 4/4 충족 — 후속 결정 라운드 진입 자격 완성. 다음:
사용자 결정 대기 (Phase 0.11.e vs Phase 0.11.f).**
