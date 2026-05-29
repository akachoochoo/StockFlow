# DGT Grid Live Operations Runbook

> **Status**: ADR 0022 §13 D29. Phase 1.x DGT live promotion 운영 안내.
> 실주문 진입점 (`trading grid-live`) 의 비상 절차 / 운영 흐름 / 사용자
> 단계 가이드. 머니 크리티컬 — CLAUDE.md preamble 정합.

## 개요

`trading grid-live` 가 DGT 그리드 전략의 실 KIS API 주문 + 실계좌 잔고
인터페이스. ADR 0022 §13 D24~D33 박제 정합. 본 runbook = **운영 측면**
(사용자가 알아야 할 절차) 박제.

## 사전 조건 체크리스트

코드 측 (구현 완료, 본 runbook 작성 시점):

- [x] D17~D23 도메인 + use_case 구현 (`§12`)
- [x] grid_state 영속 (`§12 follow-up`)
- [x] `trading grid-dry-run` CLI 동작 + 텔레그램 알림 (`§12 follow-up`)
- [x] D25 holdings_provider 추상화 (`abd8cb7`)
- [x] D26 Reconciler grid 인식 (`75d8ea8` + `8e91fbd`)
- [x] D30 + D32 `trading grid-live` CLI + 분리 arming (`2ef27ad` + `9ccf13a`)
- [x] D33 운영 관찰성 알림 (`ac8f6bb`)

사용자 측 (운영 단계):

- [ ] D28 — `--use-kis` dry-run **최소 10 영업일** 운영 + 검토 (§13.3 D28 권고)
- [ ] D31 — 시작 자본 069500 단독 500만 KRW (§13.3 D31 권고)
- [ ] `.env` 의 `KIS_PAPER_APPKEY` / `KIS_PAPER_APPSECRET` / `KIS_PAPER_ACCOUNT_CANO`
      모의투자 (VTS) 키 발급 + 입력
- [ ] `.env` 의 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 알림 설정
- [ ] crontab 등록 (16:00 KST 평일, `scripts/grid_dry_run_cron.sh` 패턴 차용)

## 진입 게이트 (Stage 8-3 5-AND)

`trading grid-live` 는 실주문 직전 `assert_armed_for_live` 5-AND 게이트
통과 필수. **모두** 충족시에만 KIS `place_order` 호출:

1. **NTP 동기화** — `safety.verify_ntp_sync()` 통과 (CLAUDE.md §3.3).
2. **halt sentinel 부재** — `safety.is_halted() == False`.
3. **Reconciliation match** — DB (split + grid 합산, D26) == KIS `get_holdings`.
4. **CLI flag 무장** — `--arm-grid-live <tier>` (200 / 300 / 500).
5. **ENV 이중확인** — `TRADING_ARM_GRID_LIVE=<tier>` (CLI tier 와 일치).
6. **자본 한도 내** — intended `--tier` ≤ armed tier 의 KRW 한도.

게이트 실패 시 즉시 종료 + exit 1. **실주문 zero**.

## arming 분리 (D32)

split vs grid arming **독립**:

| 전략 | CLI flag | ENV |
|------|----------|-----|
| split | `--arm-live <tier>` | `TRADING_ARM_LIVE=<tier>` |
| grid | `--arm-grid-live <tier>` | `TRADING_ARM_GRID_LIVE=<tier>` |

의도: 한쪽 halt 시 다른쪽 영향 zero. 실수로 grid arming 으로 split 가
활성화되는 것 방지. 운영 시 두 ENV 동시 설정 금지 권장.

## 자본 진입 단계 (D31)

architect 권고 진입 경로:

| 단계 | 종목 | 종목당 자본 | 총자본 | 게이트 |
|------|------|-------------|--------|--------|
| 1차 | 069500 단독 | 500만 KRW | 500만 KRW | dry-run 10일 + 사람 결정 |
| 2차 | N=3~5 | 500만 KRW | 1500~2500만 KRW | 1차 2~4주 운영 + 사람 결정 |
| 최종 | N=9~10 | ~1000만 KRW | ~1억 KRW | 2차 안정 + 사람 결정 |

- **달력 시간 기준** (최소 2주 운영) + 사람 판단으로 단계 전환.
- **수익 기준 자동 증액 zero** (CLAUDE.md §11 정신).
- 종목당 500만 = §11.21 권고 A 목표 자본 (~1천만) 의 절반 — 검증 기간 소액.

## crontab 등록 예 (라이브)

```cron
# DGT grid-live — 평일 매일 16:00 KST (KRX 종가 15:30 + KIS publish 버퍼)
0 16 * * 1-5 /Users/USERNAME/workspace/StockFlow/scripts/grid_live_cron.sh

# 환경변수 (crontab 헤더)
MAILTO=ops@example.com
# arming 은 wrapper 스크립트가 .env 에서 로드
```

> **권장**: `scripts/grid_dry_run_cron.sh` 패턴 차용해 `grid_live_cron.sh`
> 작성 (별도 wrapper). 차이 = `--arm-grid-live` 플래그 + `--db
> grid-live.db` (dry-run 과 별도 격리).

## 비상 절차

### A. TRADING_HALT (모든 거래 즉시 정지)

```bash
trading halt --reason "사유 명시 (audit 용)"
```

- 영구 halt sentinel 기록. 다음 cron 진입 시 즉시 종료 (`safety.check_kill_switch`).
- **보유분 그대로 동결** — 자동 매도 zero (CLAUDE.md §11.1).
- 해제: `trading resume` (사람이 사유 검토 후 명시적 실행).

### B. supervised first-order hold

`--supervised-first-order` 플래그 ON 인 경우, **첫 주문 placed 후 자동
halt 기록** (`run_grid_live_pipeline._maybe_supervised_hold`).

- 다음 cron 진입 차단 → 사람이 KIS HTS 에서 체결 확인 → `trading resume`.
- D30 권고 운영 패턴 — 첫 N일 supervised, 안정 후 ON 해제.

### C. KIS API outage / token 만료

| 상황 | exception | 동작 |
|------|-----------|------|
| 네트워크 불가 | `BrokerConnectionError` | cron 종료 + 텔레그램 CRITICAL. 자동 재시도 zero (CLAUDE.md §4.3). 다음 cron 재시도. |
| 토큰 만료 | `KISAuthError` | 동일. `KISAuth` 가 자동 refresh 하므로 통상 발생하지 않음. 발생 시 `.env` 의 secret 검증. |
| 시세 누락 | `MarketDataUnavailableError` | 동일 — 빈 bars 결과 시 ClickException 직접 발사. |
| 데이터 무결성 | `DataIntegrityError` | 동일 — KIS 응답 검증 실패. 사람 검토 필요. |

### D. DB 손상

복원 순서:

1. `trading halt --reason "DB 손상 의심"` — 추가 거래 차단.
2. DB 백업에서 복원 (운영 정책 따라 — 별도 backup 절차 박제 후속).
3. `trading reconcile --db <restored.db>` — DB positions + grid_decisions
   재생 vs KIS `get_holdings` 대조.
4. 사람이 mismatch 검토 → 사실 일치라면 `trading resume`. 불일치라면 사람이
   `grid_decisions` 수동 정정 후 재 reconcile.
5. **자동 복원 zero** (CLAUDE.md §11.2). 모든 정정 = 사람 의사결정.

### E. 보유분 수동 청산 (사람이 KIS HTS 에서 매도)

1. halt 상태에서 사람이 KIS HTS 에서 직접 매도.
2. 다음 `trading grid-live` cron 진입 시 reconciliation 이 불일치 감지
   → StateMismatchError + halt 기록.
3. 사람이 `grid_decisions` 에 SELL row 수동 추가 (또는 `grid_states` 정정)
   → 다시 reconcile → match → `trading resume`.
4. **운영 권고**: 수동 청산은 비상 시에만. 평시는 cron 이 결정.

### F. Reconciliation mismatch

자동 동작:

1. Reconciler 가 mismatch 감지 (D26 — split + grid 합산 비교).
2. `notify(CRITICAL, ...)` — 텔레그램 즉시 발사.
3. `safety.write_halt(reason)` — 영구 halt 기록.
4. `StateMismatchError` raise → 모든 거래 정지, exit 1.

사람 절차:

1. 텔레그램 CRITICAL 알림 확인.
2. `trading reconcile` 다시 실행 — mismatch 상세 확인.
3. 원인 조사:
   - KIS 보유 변동 (수동 매도 / 외부 입출고)?
   - `grid_decisions` 누락 / DB 손상?
   - 종목 분할 / 합병?
4. 정정 후 `trading resume`.

## 손실 한도 알림 (D27)

`--max-loss-pct 20.0` (기본) — 종목별 평균가 (`GridRuntimeState.avg_cost`)
대비 현재 종가 비율 < -20% 시:

1. 텔레그램 WARNING — `[GRID LIVE] 손실 한도 도달 — {asset_fqn}`.
2. body = 평단 / 현재 / 손실% / 한도%.
3. **자동 매수 차단 미구현** — 알림-only (CLAUDE.md §11.4 + D7 정합).
4. 사람 검토 → 결정 (매도 / 보유 / 한도 완화 등).

## 텔레그램 알림 종류 (D33)

| 알림 | 수준 | 발사 시점 |
|------|------|-----------|
| cron 시작 | INFO | 매 cron 진입 시 (자본 / armed 상태 요약) |
| settle 요약 | INFO | settle 단계 종료 시 (grid / split / pending 건수) |
| settle 이벤트 | INFO~ | PendingSettler 가 emit (NF-1 warning 등) |
| 매수/매도 | INFO | per-decision (side / level / qty / price) |
| 손실 한도 | WARNING | breach 감지 시 (per-asset) |
| supervised hold | WARNING | first-order 후 halt 기록 시 |
| cron 종료 | INFO | 정상 종료 (결정 / breach / hold 요약) |
| reconciliation mismatch | CRITICAL | Reconciler 자동 발사 + halt |
| KIS / 기타 오류 | CRITICAL | CLI 가 처리 |

`.env` 의 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` 미설정 시 console fallback
(WARNING+ 만 표시, INFO 묵음 — 운영 시 텔레그램 설정 필수).

## 일반 운영 명령

```bash
# halt
trading halt --reason "이유"

# resume
trading resume

# reconcile (read-only 대조)
trading reconcile --db grid-live.db

# KIS connectivity smoke
trading kis-check --code 069500

# grid-dry-run (paper-on-live 검증)
trading grid-dry-run --config config/grid-095660-dryrun.yaml --use-kis \
    --db grid-dry-run.db --capital 10000000

# grid-live (armed 시 실주문)
trading grid-live --config config/grid-095660-dryrun.yaml \
    --tier 500 --arm-grid-live 500 \
    --db grid-live.db --capital 5000000 \
    --supervised-first-order
```

## 거버넌스 (G)

- 코드 변경 (live path) = 사용자 명시 승인 필수 (CLAUDE.md §0 체크리스트).
- 파라미터 (config YAML) 변경 = hot reload 미지원 — cron 재시작 권장.
- 매매 통계 검토 cadence: 매주 (사용자 운영 정책 — 별도 박제 후속).
- 회귀 절차: 버그 발견 → halt → patch → 사용자 승인 → resume.

## 후속 (별 ADR 라운드)

- 자동 손절 (자동 매수 차단) — Phase 1.x 후속 (D27 / CLAUDE.md §11.4).
- 자산별 차별화 파라미터 — ADR 0003 §19.4 / §7.3 보류.
- Multi-strategy combined arming gate — 현재 split / grid 독립.
- DB 백업 / 복원 자동화 — 현재 사람 절차.

## 참조

- `docs/decisions/0022-phase-1.x-dgt-live-promotion.md` §13 D24~D33
- `src/cli/grid_live_runner.py` — pipeline 정본
- `src/cli/main.py::grid_live` — CLI 정본
- `src/cli/composition.py::build_grid_live_components` — 배선 정본
- `src/cli/live_gate.py` — arming gate (D32)
- `docs/runbooks/grid-dry-run-cron.md` — dry-run 자동화 (parallel)
- `docs/runbooks/phase-1.1-emergency-change.md` — 일반 비상 절차 (split)
