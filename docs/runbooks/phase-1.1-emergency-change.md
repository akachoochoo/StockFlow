# Phase 1.1 비상 변경 / Rollback Runbook

> **정본**: ADR 0012 D13 (변경 zero invariant + 비상 변경 4 사유) · D19 (자본 tier
> rollback) · CLAUDE.md §11 (안전장치). 본 runbook 은 *검증 가능 artifact* — Phase
> 1.1 실거래 운영 중 비상 상황 발생 시 사람이 따르는 절차. 코드: `src/cli/rollback.py`
> (D19 plan) · `src/cli/safety.py` (halt/resume) · `src/cli/live_runner.py` (runner).

---

## 0. 변경 zero invariant (D13 a)

Phase 1.1 안정화(35 영업일) 동안 **`src/` 코드 + `config/strategies.yaml` 변경 zero**.
예외: CLAUDE.md 이하 문서 정정(오타/회고 박제 commit)은 변경 zero 위반 아님.

아래 **비상 변경 4 사유** 외에는 코드/설정을 절대 변경하지 않는다. 모든 비상 변경도
**사람 명시 + ADR 박제 후** 적용 (자동 적용 절대 금지, ADR 0011 §1.6 #1).

`ProposalHistory` = **read-only 모드** (D13): trigger 발화 시 NULL proposal 누적은
허용(drift 검증 데이터), `Proposal.state == APPLIED` 전이는 차단.

---

## 1. 비상 변경 4 사유 (D13) — 이 4가지만 변경 트리거

### 사유 1 — Kill switch 발화 (CLAUDE.md §11.1)
- **트리거**: 운영자가 `TRADING_HALT=1` 명시 set (clean stop, exit 0).
- **조치**: 모든 명령이 entry 에서 즉시 중단. 원인 분석 후 변경 적용.

### 사유 2 — Reconciliation 불일치 hard halt (CLAUDE.md §11.2)
- **트리거**: `trading reconcile` / `trading live` 의 settle 후 recon 에서 DB
  포지션 ≠ KIS 보유 → `StateMismatchError` + 영속 halt sentinel + CRITICAL 알림.
- **조치**: 자동 수정 zero. 사람 개입 대기 + 분석 후 변경 적용.

### 사유 3 — KIS API 시그니처 변경 (ADR 0012 §1.6 #4)
- **트리거**: KIS 응답 Pydantic schema parse 실패 (`BrokerConnectionError` /
  `BrokerOrderError` 의 필드 오류).
- **조치**: paper trading 재검증 의무 후 변경 적용.

### 사유 4 — 단일 종목 손실 한도 -20% 도달 (D2 b')
- **트리거**: `trading live` stop-loss breach WARNING 알림 (평가손 ≤ -20%).
- **조치**: 추가 매수 정지 + 사람 매도 검토. 자동 매도 zero. `trading manual-sell`
  은 사람 명시 명령(미구현 — 현재는 `trading halt` 후 수동 검토).

---

## 2. 공통 대응 체크리스트

비상 상황 발생 시 순서대로:

- [ ] 1. `trading halt --reason "<무엇이/왜>"` 로 영속 halt sentinel 기록 (또는 이미
      자동 halt 된 경우 사유 확인: 사유 2 는 Reconciler 가 자동 halt).
- [ ] 2. 텔레그램/Console 알림 + halt sentinel 사유 확인.
- [ ] 3. KIS 실계좌(HTS/MTS)에서 실제 보유/주문/체결 직접 확인.
- [ ] 4. DB(`trading.db`) 상태와 대조: `trading reconcile --db trading.db`.
- [ ] 5. 원인 분류 (4 사유 중 어디 / 또는 미분류 → 더 보수적으로 정지 유지).
- [ ] 6. 변경이 필요하면 ADR 박제 commit 후에만 적용 (코드/설정).
- [ ] 7. 복구 확인 후 `trading resume` 로 halt sentinel 제거 (사람 명시).
- [ ] 8. 다음 `trading live` 가 정상 진입하는지 확인 (재발 시 8-2 단계로).

---

## 3. 자본 tier rollback 절차 (D19)

단계별 자본 확대(200→300→500만) 중 **무사고 위반**(운영/무결성 사고, P&L 손실
제외) 발생 시:

- [ ] 1. 위반을 사유 1~4 또는 미분류로 기록.
- [ ] 2. `src/cli/rollback.plan_capital_rollback(current_tier=…, prior_rollback_count=…,
      reason=…, occurred_at=…)` 로 rollback 계획 산출 → `RollbackLogEntry`.
- [ ] 3. 산출된 `to_tier` 로 자본 복귀 (사람 명시 — 자동 아님). 200 floor 또는
      누적 rollback ≥ 3 이면 `phase_terminated=True` → **Phase 1.1 종료** + 회고
      commit + Phase 1.2 진입 결정 라운드.
- [ ] 4. `RollbackLogEntry.to_dict()` 를 rollback-log 에 기록 (감사).
- [ ] 5. rollback 후 이전 tier 에서 **5 영업일 추가 무사고** 운영 후 재확대 시도.

규칙(D19): 위반 시 한 단계 하향(500→300→200). 200 에서 위반 또는 누적 ≥ 3 회 →
Phase 1.1 종료.

---

## 4. 절대 금지 (CLAUDE.md §11)

- 자동 catch-up (다운 후 누락분 자동 따라잡기) — 금지. 사람 명시 `--force-run` 만.
- 자동 손절 매도 — 금지 (알림 + 사람 검토만).
- Reconciliation 불일치 자동 수정 — 금지.
- 주문 타임아웃 시 즉시 재시도 — 금지 (PENDING 저장 후 settle 로 확인).
