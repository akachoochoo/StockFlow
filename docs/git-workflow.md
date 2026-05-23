# Git Workflow — Phase 1 실거래 진입 (D18)

> 박제: Phase 1.1 Stage 0.4 (2026-05-21). 정본 = ADR 0012 D18 (Missing Gap 3,
> ADR 0001 §1.5 정합). 본 문서는 실계좌 연결 = 돈 직결 환경의 branch 보호 +
> PR-review 룰을 박제한다. CLAUDE.md preamble "한 번의 버그가 돈으로 직결" 정합.

---

## 1. Branch 분리 (Phase 1 진입 시점)

| Branch | 역할 | 직접 push |
|--------|------|-----------|
| **`main`** | **실거래 운영 branch** — 실계좌가 실행하는 코드의 정본 | **금지** (PR-review 경유만) |
| **`develop`** | 통합/작업 branch — 모든 Phase 1.1 build (Stage 0~9) 진행 | 허용 (작업 branch) |

- Phase 0~0.11 까지는 `main` 단독이었다 (Mock 환경, 위험 zero). Phase 1 = 실계좌
  진입이므로 `main` 을 보호 branch 로 승격하고 `develop` 을 작업 branch 로 분리.
- 기능 단위가 크면 `develop` 에서 `feature/<name>` 분기 후 `develop` 으로 PR 가능
  (선택). `main` 으로의 merge 는 항상 PR-review 경유.

## 2. PR-review 룰 (실거래 = 돈, 직접 push 금지)

`develop → main` merge 는 **반드시 PR + review** 를 거친다:

1. **Review 주체**: 사용자 self-review (필수) + 가능 시 외부 reviewer / `/ultrareview`
   / `code-reviewer` 에이전트 패스. 자기 작성 코드의 자기 승인 단일 패스 금지
   (CLAUDE.md OMC `<execution_protocols>` "authoring/review 분리" 정합).
2. **Merge 차단 조건** (하나라도 미충족 시 merge 금지):
   - 전체 `pytest` 통과 + `bash scripts/check_namespace.sh` = OK.
   - 해당 Stage 의 게이트 (`pytest -k <name>` 목록) 통과 박제.
   - 0.11.e §1.6 6 verification command 통과 (회귀 invariant).
   - ADR / 회고 박제 (변경이 결정 항목을 건드릴 경우).
3. **실거래 ON 직전 merge** (Stage 7→8): D16 (i)~(vi) 6 조건 + D6 5 조건 충족
   박제가 PR 본문에 verbatim 인용되어야 한다. `.env` 실값 / 실거래 플래그 토글은
   merge 후 사람이 수동 (commit 절대 금지).

## 3. Phase 1.1 운영 윈도우 변경 zero invariant (D13)

Stage 8 (실거래 운영, 200→300→500만원) 동안 `src/` 코드 + `config/strategies.yaml`
변경 **zero**. 비상 변경 4 사유 (D13) 외 `main` 으로의 어떤 merge 도 금지:

1. Kill switch 발화 (`TRADING_HALT=1`, CLAUDE.md §11.1)
2. Reconciliation 불일치 hard halt (CLAUDE.md §11.2)
3. KIS API 시그니처 변경 (Pydantic parse 실패 → paper trading 재검증 후)
4. 단일 종목 손실 한도 도달 (-20%, D2 (b'))

각 비상 변경도 사람 명시 ADR 박제 후에만 `main` merge (D13 / §1.6 #2 정합).
문서 정정 (CLAUDE.md / ADR / 회고 commit) 은 변경 zero invariant 위반 아님 (D13).

## 4. Commit 규칙 (CLAUDE.md §12 정합)

- 한 commit = 한 변경. 도메인 변경과 어댑터 변경 별도 commit. 테스트 동봉.
- 도메인 모델 additive 확장 (`OrderResult.tax/commission`, ADR 0019) 은 build
  윈도우 (Stage 0~7) 한정 — Stage 8 운영 윈도우에서는 §3 비상 4 사유 외 금지.
