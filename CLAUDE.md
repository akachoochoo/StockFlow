# CLAUDE.md

> **이 파일은 모든 코드 작업 전에 반드시 읽으세요.**
> 이 프로젝트는 실계좌가 연결될 자동매매 시스템입니다. 한 번의 버그가 돈으로 직결됩니다.
> "동작하는 것 같다"와 "안전하다"는 다릅니다. 항상 후자를 추구하세요.

---

## 0. 작업 시작 전 체크리스트

1. 작업 범위가 현재 Phase에 속하는가? (`docs/roadmap.md` + §14 참조)
2. 기존 인터페이스(`src/ports/`) 변경? → 사용자 승인 필요
3. 새 외부 의존성 추가 (`pyproject.toml` 수정)? → 사용자 승인 필요
4. 도메인 로직 변경? → 테스트 먼저 작성 후 구현

**모르겠으면 코드 짜지 말고 사용자에게 질문하세요.** 추측으로 채우지 마세요.

---

## 1. 아키텍처 규칙 (가장 중요)

### 1.1 Clean Architecture — Dependency Rule

```
[Research overlay (5th ring, outermost)]
        ↓ outer→inner read OK
[Frameworks] → [Adapters] → [Use Cases] → [Domain]
의존성은 항상 안쪽으로. 반대 방향 절대 금지.
```

**`src/domain/` 금지 import**: DB 라이브러리(sqlite3/sqlalchemy), HTTP 클라이언트
(requests/httpx), pandas/numpy, `src.adapters.*`, `src.infrastructure.*`,
`src.research.*`, 그리고 `datetime.now()` / `date.today()` (시점은 항상 파라미터 주입).

**`src/domain/` 허용**: 표준 라이브러리, `pydantic`, `src.domain.*`,
`src.ports.*` (Protocol만).

**`src/research/` (5th ring, ADR 0007 §1.6)**: 박제/실험용 격리 네임스페이스.
- research → inner ring 읽기 OK. inner ring 7개에서 `src.research.*` import **FORBIDDEN**.
- 강제: `bash scripts/check_namespace.sh`. `python -m src.research.<...>` CLI 진입은 위반 아님.
- `src/research/**/__init__.py` 는 private only (`__all__ = []`).
- 각 overlay 는 종료 시 lifecycle (archive/promote/abandon) 결정 박제.

**위반 발견 시**: 코드 작성하지 말고 사용자에게 보고 (설계가 잘못된 신호).

### 1.2 의존성 주입

모든 외부 의존은 생성자 주입 (`broker: BrokerPort`). 구현체 직접 생성
(`self.broker = KISBroker()`) 금지. 테스트 Mock 교체 + 백테스트/실거래 코드 공유의 핵심.

### 1.3 Port/Adapter

새 외부 시스템: ① `src/ports/`에 Protocol 정의 → ② `src/adapters/<시스템명>/`에 구현
→ ③ 도메인/Use Case는 Protocol만 import.

---

## 2. 돈 관련 규칙 (절대적)

- 모든 가격/수량/금액은 **`Decimal`**. float 절대 금지 (잔고 불일치 원인).
- Decimal 생성은 **string으로**: `Decimal("0.1")` ✅ / `Decimal(0.1)` ❌ (float 오차 전파).
- 통화 명시: `Money(amount: Decimal, currency: str)`. 다른 통화 연산은 명시적 환전만 — 자동 변환 금지.

---

## 3. 시간 관련 규칙

- 저장/계산은 항상 **UTC aware** (`datetime.now(timezone.utc)`). naive `datetime.now()` 금지. 표시할 때만 KST 변환.
- **도메인에서 현재 시간 조회 금지** — `today`/`now`는 파라미터로 주입 (백테스트 가능성의 핵심).
- NTP 동기화 가정 금지 — 시작 시 검증, 1초 이상 skew면 거래 시작 거부.

---

## 4. 주문 처리 규칙

- **모든 주문에 `idempotency_key` (uuid4) 예외 없이** — 재시작/재시도 중복 주문 방지의 유일한 방법.
- **지정가 주문만** 사용. 시장가 금지 (슬리피지 예측 불가).
- **타임아웃 시 즉시 재시도 절대 금지** — PENDING으로 DB 저장 후 `get_order_status(idempotency_key)`로 실제 상태 확인 (별도 흐름).
- 부분 체결은 별도 차수로 인정 안 함 — `split_level`은 100% 체결 시만 증가.

---

## 5. 데이터 검증 규칙

- 외부 데이터는 **adapter 경계에서 검증 후** 도메인 진입 (price ≤ 0, high < low 등 → 즉시 raise). 도메인 모델은 valid 상태만 가정.
- 전일 대비 ±30% 초과 변동은 의심 (액면분할/데이터 오류) → 매수 결정 스킵 + 알림.

---

## 6. 예외 처리 규칙

`src/domain/exceptions.py` 3분류:

| 분류 | 의미 | 처리 |
|------|------|------|
| `DomainError` | 정상 흐름의 일부 (잔고 부족 등) | catch → Decision 기록 → 계속 |
| `ExternalSystemError` | 외부 시스템 오류 | 재시도 또는 스킵 |
| `IntegrityError` | 무결성 위반 | **catch 금지** → 전파 → 시스템 정지 |

- `except Exception: pass` 등 **침묵의 실패 금지**. 광범위 catch 금지.
- `result = op() or default` 금지 (None과 0 구분 안 됨).
- 실패는 `logger.error(..., exc_info=True)` 후 raise 또는 명시적 처리.

---

## 7. 테스트 규칙

- 새 코드 = 테스트 동시 작성. Domain 단위 테스트 커버리지 100% 목표 / Adapter·Use Case 통합 테스트.
- Given-When-Then 구조 + 엣지 케이스 포함.
- Mock 원칙: 도메인 = Mock 없이 순수 / Use Case = Port Mock 주입 / Adapter = 외부 라이브러리만 Mock.
- 백테스트와 페이퍼 트레이딩은 같은 입력 → 같은 결과여야 함 (불일치 = 시계/외부 상태 의존성 신호).

---

## 8. 로깅 규칙

- **모든 의사결정은 Decision으로 저장** — `reasoning`에 결정에 사용된 모든 입력값을 JSON 보존 (6개월 뒤 디버깅 가능해야 함).
- 레벨: DEBUG(개발만) / INFO(정상 결정·체결) / WARNING(재시도·스킵·의심 데이터) / ERROR(주문 거부·API 실패) / CRITICAL(무결성 위반).
- 민감 정보 로깅 금지 — API key/계좌번호는 `api_key[:4]***` 마스킹.

---

## 9. 설정 관리 규칙

- 3계층: 알고리즘(`src/domain/strategies/`, 코드) / 파라미터(`config/strategies.yaml`, hot reload) / 운영 명령(CLI 즉시).
- 파라미터 하드코딩 금지 — config에서 로드.
- 비밀 정보는 환경변수 (`os.environ["KIS_API_KEY"]`) + `.env` (gitignore 필수). 코드에 박지 말 것.

---

## 10. 동시성 규칙

### 10.1 단일 프로세스 가정

cron 호출 기반 단일 프로세스. 멀티스레드/asyncio/데몬 금지 (필요하면 사용자에게 질문).

**호출 주기** (ADR 0023 D4, 2026-05-30):
- 일봉 인프라 (Phase 0 ~ ADR 0022, 동결): cron 1회/일. 운영 차단 — env `ALLOW_DAILY_LIVE=1` 강제 필요.
- 분봉 인프라 (ADR 0023, Phase 1.x): cron 1분/장중 (09:00~15:30 KST, 390회/일). 동시호가 (15:20~15:30) = cron 정상 호출 + 주문 제출 zero.
- 각 호출 = 독립 프로세스 + lock file 직렬화 + 60초 budget hard cap (R2).

### 10.2 락 파일

시작 시 PID/DB 락 체크. 이미 실행 중이면 즉시 종료.

### 10.3 DB 트랜잭션 — UnitOfWork

여러 Repository에 걸친 변경은 UoW로 묶는다 (`with uow_factory() as uow: ... uow.commit()`).
commit 미호출 시 `__exit__` 자동 rollback이 안전한 기본값. 개별 Repository 별도
트랜잭션 금지 (부분 실패 시 불일치). Repository = 단일 SQL만, 경계 = UoW. ADR §8.2.

---

## 11. 안전장치 (절대 우회 금지)

1. **Kill Switch**: `TRADING_HALT=1` 이면 모든 의사결정 시작 전 체크 → 즉시 종료.
2. **Reconciliation**: 매일 시작 시 DB vs 브로커 포지션 대조. 불일치 → 자동 수정 절대 금지 + 전체 거래 정지 + 알림 + 사람 대기.
3. **자동 catch-up 금지**: 며칠 다운 후 재시작 시 누락분 자동 따라잡기 금지. 알림 후 사람이 명시적 `--force-run --date`.
4. **손실 한도**: 종목별 `max_loss_pct` 도달 시 추가 매수 정지 + 사람 대기 (자동 손절 안 함).

---

## 12. Git/PR 규칙

- 한 커밋 = 한 변경. 도메인/어댑터 변경 분리. 테스트는 같은 커밋에.
- 메시지: `<type>(<scope>): <subject>` — type: feat/fix/refactor/test/docs/config, scope: domain/adapter/infra/app/cli.
- 중요 결정 (의존성 추가 / 인터페이스 변경 / 알고리즘 변경)은 `docs/decisions/` ADR로 기록.

### 12.1 ADR 갱신 체크리스트

ADR 갱신 시마다: **이전 사용자 명시 요청 중 미구현 검색** (사용자 결정 인용
키워드로 코드 + ADR 양쪽 grep). 누락 발견 시 `§X.0` 형태로 명시 인정 후 진행
(누락 사실 / 인정 시점 / 재처리 방침 항목화 — 단순 사과 금지). 다음 결정 라운드
시작 전 수행.

---

## 13. 모르겠을 때 (가장 중요)

다음 상황은 코드 작성 중단 + 질문: 시그니처가 명세에 없음 / 엣지 케이스 처리
방식 없음 / 새 라이브러리 필요 / 도메인 규칙 모호 / 기존 코드와 충돌.

질문 형식: `[의문점] / [옵션 A·B + trade-off] / [추천]`.

**"친절한 추가" 금지**: 명세에 없는 기능 (자동 손절 / 매도 로직 / 알림 / UI /
추가 종목 / "추후 확장 가능하게" unused parameter)은 반드시 사용자 승인 후.

---

## 14. Phase별 범위 (현재: Phase 1.x — 분봉 일괄 전환, ADR 0023)

> **정본 = `docs/roadmap.md` (phase 인덱스) + ADR (`docs/decisions/`) + 회고
> (`docs/retrospectives/`)**. 완료 phase 상세를 이 파일에 다시 적지 말 것.
> 2026-06-12 슬림화로 제거된 §14 인덱스 테이블 / §16 전문은
> `docs/claude-md-archive-2026-06-12.md` 박제.

### 현 상태 (2026-06-12)

- Phase 0 ~ 0.11.k 정식 종료 (ADR 0001~0018). Phase 1 진입 (ADR 0012, `e066554`).
- Phase 1.1: DB 마이그레이션 (ADR 0019) + KIS API (ADR 0020) + 자산 registry (ADR 0021).
  Stage 8 split live runner = **코드 완성 + 운영 동결** (ADR 0023 D5/D17).
- **Phase 1.x 현행 (ADR 0023, 2026-05-30 박제)**: backtest/dry-run/live **분봉(1m) 일괄
  전환** + split 동결 + DGT-only. 일봉 인프라 = 코드 보존 + 운영 동결
  (`ALLOW_DAILY_LIVE=1` 강제). 진행 중 = §10.1/§10.2 세그먼트 (KIS 분봉 수집기 +
  분봉 grid backtest 엔진).
- 핵심 학습 박제: **자산군 분산 = H3 회복의 충분 조건** (ADR 0005 §9.6.2) /
  **DGT = MDD 방어·횡보 수확 도구, 추세장 수익 아님** (ADR 0014/0018).

### 작성 금지 (현재 유효)

- AI 차단기 / RuleBasedSignal — Phase 2 (NullSignal 유지)
- 환율 처리 — Phase 3 / US 주식·BTC — Phase 3/4
- 종목 선정 자동화 — Phase 2+
- 일봉 인프라 운영 부활 / split live 운영 재개 — 별도 결정 라운드 필요 (ADR 0023 D5/D17)
- Phase 1+ 미박제 항목 (손절 / partial fill / 텔레그램 / 거래세 모델링 / 종목별
  다른 정책 / 부분 매도 / Hot reload 등) — **해당 ADR 박제 전 작성 금지**
  (ADR 0012 트리거 목록 정본)
- **보존 invariant (변경 금지)**: `PriceDropStrategy` / `SupportLevelStrategy` /
  `SupportSlot` / `src/domain/indicators/` / Phase 0.10 reporting layer
  (TradeView / DrawdownEpisode / Renderer Protocol / SevenSplit slot palette /
  StrategyInfo / risk_metrics) — 정본 ADR 0004 §7.4.2 + ADR 0006 §3~§18

이 범위를 벗어나는 코드 작성 시 사용자 확인 필수.

---

## 15. 핵심 원칙 (압축)

1. **Domain은 외부 모름** — 외부 import 금지, 시계 조회 금지
2. **돈은 Decimal** — float 절대 금지
3. **시간은 UTC + 주입** — `datetime.now()` 도메인 금지
4. **모든 주문에 idempotency_key** — 중복 방지의 유일한 방법
5. **불확실하면 멈추고 알림** — 자동 복구/재시도 신중
6. **테스트 없으면 코드 없음** — 도메인 로직은 100% 커버
7. **모든 결정은 로그** — reasoning에 입력값 전체 보존
8. **모르면 묻기** — 추측 금지, 친절한 추가 금지

---

*이 파일은 살아있는 문서입니다. 운영 중 발견된 새 규칙은 추가하세요.*
*마지막 업데이트: 2026-06-12 (슬림화 — 816→약 230 lines. 규범 규칙 압축 유지,
§14 인덱스/§16 제거분은 `docs/claude-md-archive-2026-06-12.md` 박제, 현 상태
Phase 1.x ADR 0023 반영)*
