# Runbook — PENDING limbo (broker_order_id 없는 PENDING 주문) 복구

> 작성 2026-06-12 (사용성 리뷰 ⑥-c). 대상: 주문 제출 타임아웃
> (`BrokerConnectionError`) 으로 DB 에 PENDING 선저장됐으나 broker_order_id
> (ODNO) 가 없는 주문. CLAUDE.md §4.3 / 코드리뷰 Fix 1 (`3d411a8`) 짝.

## 이 상태가 생기는 경위

1. `place_order` POST 중 타임아웃/연결 오류 → 주문이 KIS 에 **도달했는지
   알 수 없음** (limbo).
2. 시스템은 즉시 재시도하지 않고 (§4.3) PENDING Order 를 broker_order_id
   = NULL 로 DB 에 선저장.
3. 이후:
   - settle 흐름: `get_order_status` 가 ODNO 없는 주문은 **조회 불가** →
     PENDING 그대로 반환 → 영원히 `still_pending` (자동 해소 없음).
   - 같은 key 재주문 시도: KIS broker dedup 이 `StateMismatchError`
     (IntegrityError) raise → **시스템 정지**. 사람이 풀기 전까지 재진입 불가.

**자동 복구는 설계상 없다** — 이 runbook 의 사람 절차가 유일한 해소 경로.

## 복구 절차

### 1. 상태 파악

```bash
trading status --db trading.db        # PENDING 목록 + halt 상태 확인
```

`broker_order_id=None` 인 PENDING 의 `idempotency_key` 와 `submitted_at`
(UTC — KST 로 +9h) 을 기록.

### 2. KIS 에서 사실 확인 (정본 = 브로커)

KIS MTS/HTS → 주문체결 내역 → **submitted_at 의 KST 날짜** 조회.
해당 종목/수량/가격의 주문이 있는지 확인.

| 사실 | 판정 |
|------|------|
| 주문 내역에 없음 | **케이스 A** — 주문이 KIS 에 도달하지 않음 |
| 주문 내역에 있음 (체결/미체결/취소 무관) | **케이스 B** — 도달함, ODNO 존재 |

### 3-A. 케이스 A — 주문 미도달

DB 의 PENDING 은 허상. CANCELED 로 종결:

```bash
sqlite3 trading.db "UPDATE orders SET status='CANCELED'
  WHERE idempotency_key='<key>' AND broker_order_id IS NULL;"
```

`AND broker_order_id IS NULL` 가드 필수 — ODNO 있는 주문을 실수로 닫는
것을 방지.

### 3-B. 케이스 B — 주문 도달 (ODNO 확인됨)

**직접 FILLED 로 고치지 말 것.** ODNO 만 기입하면 다음 settle 이
inquire-daily-ccld 조회로 체결 사실을 **정상 경로로** 확정한다:

```bash
sqlite3 trading.db "UPDATE orders SET broker_order_id='<KIS ODNO>'
  WHERE idempotency_key='<key>' AND broker_order_id IS NULL;"
```

이후 다음 run 의 settle 선두 단계가 FILLED/취소를 확정하고 포지션을
갱신한다 (수동 포지션 계산 zero — 사람은 사실(ODNO)만 기입).

### 4. 대조 + 재개

```bash
trading reconcile --db trading.db     # DB vs 실계좌 read-only 대조
trading resume                        # 일치 확인 후에만
trading status --db trading.db        # PENDING 해소 확인
```

reconcile 이 mismatch 를 내면 이 runbook 범위 밖 —
`grid-live-operations.md` 의 mismatch 절차로 이동.

## 금지 사항

- PENDING 을 보고 같은 주문을 **수동으로 다시 넣지 말 것** (중복 매수 —
  idempotency 가 막는 것이 정확히 이것).
- `status='FILLED'` 직접 기입 금지 — filled_price/quantity/세금이 비거나
  틀어져 reconciliation 이 영구 mismatch 가 된다. ODNO 기입 → settle 위임.
- 확인 없이 `trading resume` 금지 — halt 는 원인 해소 후에만 푼다 (§11.2).
