# ADR 0001: Phase 0 Design Decisions

> 누적 기록 문서. 새 결정은 아래에 섹션으로 추가.
> 마지막 업데이트: 2026-04-30

---

## 형식

각 결정은 다음을 포함:
- **번호 / 단계**: 어느 작업 단계에서 결정되었나
- **결정 (Decision)**: 무엇을 정했나
- **이유 (Why)**: 왜 그 선택을 했나
- **트레이드오프**: 포기한 것
- **재검토 시점**: 언제 다시 볼 만한가

---

## 1. 프로젝트 골격 (Step 1)

### 1.1 패키지 매니저: `uv`
- **결정**: `uv` 단독 사용. `pip`/`poetry`/`pdm` 사용 안 함.
- **이유**: 빠른 lock + Python 버전 관리 일체. 사용자 선호.
- **재검토**: 운영 안정화 후 GitHub Actions 캐시 전략 검토 시.

### 1.2 Python 버전: 3.11+
- **결정**: `requires-python = ">=3.11"`. `uv python install 3.11`로 인터프리터 관리.
- **이유**: `StrEnum` (3.11+), `datetime.UTC` (3.11+), `tomllib` (3.11+) 활용.
- **트레이드오프**: 3.10 사용자 배제. 라즈베리파이 OS 기본 Python에 따라 재컴파일 필요할 수 있음.

### 1.3 mypy 정책: 도메인 strict, 어댑터 progressive
- **결정**: `src.domain.*`, `src.ports.*`, `src.use_cases.*` strict. `src.adapters.*`, `src.infrastructure.*` 점진적.
- **이유**: 도메인은 타입 안전성 100% 강제. 어댑터는 외부 라이브러리 타입 누락 허용.
- **세부**: `disallow_any_explicit`는 도메인에서도 끔 (pydantic `BaseModel` 상속이 `Any` 시그니처를 가져 모든 클래스에서 발화).

### 1.4 ruff 규칙
- **결정**: E/W/F/I/B/C4/UP/SIM/N/RUF/TCH/PTH 활성화. `E501` (line length) 끔.
- **이유**: pyupgrade(UP)로 stdlib 모던 idiom, TCH로 typing-only import 격리.

### 1.5 conventional commit + main 브랜치 직접 작업
- **결정**: 첫 커밋부터 `<type>(<scope>): <subject>`. Phase 0은 `main` 브랜치 직접 작업.
- **이유**: PR 리뷰 인프라 없이 1인 운영. 커밋 히스토리는 보존.
- **재검토**: Phase 1+ 실거래 시작 시 `develop`/`main` 분리 + PR review 룰 도입.

---

## 2. 도메인 모델 (Step 2)

### 2.1 Pydantic 베이스: DomainModel / ValueObject
- **결정**: 모든 도메인 모델은 `DomainModel` 또는 `ValueObject` 상속. 둘 다 `frozen=True + strict=True + extra="forbid" + validate_assignment=True`.
- **이유**: 의도 표현(엔티티 vs 값 객체) + 공통 config 한 곳에서 관리. 잘못된 필드 추가/타입 캐스팅 차단.
- **트레이드오프**: pydantic 의존(허용된 도메인 라이브러리). dataclass보다 약간 무거움.

### 2.2 Asset.fqn 컴퓨티드 필드
- **결정**: `Asset.fqn -> "EXCHANGE:CODE"` (`@computed_field` + `@property`). dump에 포함.
- **이유**: 멀티 시장 식별자. dict key, 로그, idempotency_key 컴포넌트로 사용.

### 2.3 Exchange / AssetClass enum 분리
- **결정**: `AssetClass.KR_STOCK` ↔ `AssetClass.KR_ETF` 분리. `Exchange.KRX`만 정의.
- **이유**: 사용자 명시. ETF/주식은 매매/세무/리밸런싱 룰 다름. 향후 확장 시 분기 가능.

### 2.4 OrderType.LIMIT 단독
- **결정**: `OrderType` enum에 `LIMIT`만. `MARKET` 정의 안 함.
- **이유**: CLAUDE.md §4.2 — 슬리피지 예측 불가로 시장가 금지. 종가 베팅이라 LIMIT 충분.
- **재검토**: 강제 청산이 필요한 시나리오가 명세화되면 (Phase 4+ BTC).

### 2.5 OrderSide.BUY/SELL 둘 다 정의
- **결정**: 둘 다 enum에 정의. Phase 0 사용처(Strategy/Orchestrator)에서는 BUY만 emit.
- **이유**: 도메인 어휘 차원에서 매도가 미래에 추가될 것이 명확. enum 추가가 cheap.

### 2.6 Currency: KRW + USD
- **결정**: Phase 0 거래는 KRW만 사용. 그러나 enum에 USD 함께 정의.
- **이유**: `Money` 통화 mismatch 테스트(`KRW + USD → ValueError`)에 필요. CLAUDE.md §2.2 예시도 USD 포함.
- **트레이드오프**: 미사용 enum 값. 다만 test coverage 100% 유지.

### 2.7 Decimal 강제 / float 거부
- **결정**: 헬퍼 `_to_decimal`이 float/bool 거부. 검증기는 `ValueError` 던져 pydantic이 `ValidationError`로 감쌈. 운영자(Money * float 등)는 `TypeError` 직접 raise.
- **이유**: CLAUDE.md §2.1–2.3. float 부동소수점 오차로 잔고 불일치 방지.

### 2.8 UTC 강제
- **결정**: 모든 `datetime` 필드는 `_ensure_utc`로 검증. naive 또는 비-UTC tz는 거부.
- **이유**: CLAUDE.md §3.1. UTC 저장/계산, 표시할 때만 KST 변환.

### 2.9 OrderResult.asset 필드 (Step 5에서 추가)
- **결정**: `OrderResult`에 `asset: Asset` 필드 추가. `Order.from_request_result`에서 request/result asset 일치 검증.
- **이유**: 어댑터/오케스트레이터가 fill 후 포지션 업데이트 시 asset 정보가 결과에 함께 있으면 round-trip 불필요.

### 2.10 Position invariant 완화 (Step 5에서 변경)
- **결정**: `quantity > 0`이라도 `split_level == 0` 허용.
- **이유**: CLAUDE.md §4.4 — 부분 체결은 split_level 증가시키지 않음. 첫 매수가 부분 체결이면 quantity > 0이지만 완료된 split이 없는 상태가 됨.

### 2.11 StrEnum 사용 (Python 3.11+)
- **결정**: `class X(str, Enum)` 대신 `class X(StrEnum)`.
- **이유**: 모던 idiom. ruff UP042 권고.

---

## 3. Port 정의 (Step 3)

### 3.1 BrokerPort: get_order_status 포함
- **결정**: 5개 메서드 — `get_balance`, `get_positions`, `place_order`, `get_order_status`, `cancel_order`.
- **이유**: CLAUDE.md §4.3 timeout 후 `get_order_status(idempotency_key)`로 실제 상태 확인 흐름. Mock에서 시뮬레이션 가능해야 함.

### 3.2 MarketDataPort: 4개 메서드 (단순화 반대)
- **결정**: `get_price`, `get_ohlcv`, `is_market_open`, `next_market_close`. 분봉/호가/배치는 Phase 1+에서 추가.
- **이유**: Port 변경은 모든 어댑터에 영향. Phase 0 백테스트 러너와 이상치 검증에 OHLCV 필요. 사용자 명시.

### 3.3 SignalPort + CircuitBreakerSignal 본격 정의
- **결정**: `SignalPort.collect(asset_class, as_of) → CircuitBreakerSignal`. CircuitBreakerSignal에 `level`, `source`, `asset_class`, `evaluated_at`, `triggered_by`, `reasoning`, `valid_until` 모두 포함.
- **이유**: Phase 2에서 새 어댑터 추가 시 모델 변경 0. 마이그레이션 비용 회피.

### 3.4 SignalSource enum: NULL/RULE_BASED/AI_BASED/MANUAL
- **결정**: 4개 source 모두 enum에 정의.
- **이유**: 어떤 출처의 신호인지 영속화. AI vs RULE이 발동 시 메타데이터 추적 가능.

### 3.5 시간 주입 강제
- **결정**: MarketDataPort/SignalPort 모든 시간 의존 메서드는 `as_of: datetime` 파라미터를 받음. 어댑터 내부에서 `datetime.now()` 호출 금지.
- **이유**: CLAUDE.md §3.2. 백테스트와 실거래 동일 코드 공유의 핵심.

### 3.6 TYPE_CHECKING으로 import 격리
- **결정**: 도메인 모델 import는 `if TYPE_CHECKING:` 블록 안에. `from __future__ import annotations` 활용.
- **이유**: Port는 Protocol 정의만. 런타임에 도메인 모델을 로드할 필요 없음. ruff TCH 규칙 준수.

---

## 4. PriceDropStrategy (Step 4)

### 4.1 SplitStrategyConfig: per_split_amount 직접 명시
- **결정**: Config에 `per_split_amount: Money` 직접 받음. `capital_allocation` 자동 분배 없음.
- **이유**: Phase 0 명세 충실. 동적 배분은 Port 변경 동반 — Phase 1+에서.

### 4.2 today 명시 주입
- **결정**: `evaluate(..., today: date, ...)` 명시 파라미터.
- **이유**: 도메인 시계 조회 금지(CLAUDE.md §3.2). 백테스트 러너가 과거 날짜 주입 가능.

### 4.3 target_price = current_price.value
- **결정**: 매수 LIMIT 주문 가격을 현재 가격 그대로 사용.
- **이유**: CLAUDE.md §4.2 종가 베팅. 슬리피지는 LIMIT으로 흡수.

### 4.4 StrategyEvaluation 일관성 검증
- **결정**: `should_buy=True` ⇒ `target_quantity` & `target_price` 둘 다 설정. `should_buy=False` ⇒ 둘 다 None. `model_validator`로 강제.
- **이유**: 호출자가 잘못된 결과 구성 못하게.

### 4.5 [정정] CAUTION 처리 위치: Strategy → Orchestrator
- **원래 결정 (Step 4)**: Strategy 내부에서 `spend_amount * 0.5` 처리.
- **정정 (Step 6)**: Strategy에는 `signal` 인자 없음. Orchestrator의 `_adjust_quantity(level, qty, lot_size)`에서 처리.
- **이유 (정정)**: Strategy를 차단기-무관하게 유지. 사용자가 Step 6 라운드에서 명시 정정.

---

## 5. Mock Adapter (Step 5)

### 5.1 MockBroker: 즉시 FILLED 기본 + 3개 시뮬레이션 rate
- **결정**: 기본 FILLED. `simulate_timeout_rate`, `simulate_rejection_rate`, `simulate_partial_fill_rate` 모두 0.0 기본.
- **이유**: 백테스트는 종가 기준 즉시 체결이 자연스러움. 엣지 케이스는 rate 1.0으로 강제 가능.

### 5.2 MockBroker timeout: 내부 FILLED + BrokerConnectionError
- **결정**: timeout 시 `_orders` dict에 FILLED로 등록 후 `BrokerConnectionError` raise. `get_order_status`로 복구 가능.
- **이유**: CLAUDE.md §4.3 흐름 — 실제 처리는 됐지만 응답 못 받은 케이스. "조회해도 없는 케이스"는 테스트가 `_orders` 직접 조작.

### 5.3 MockBroker idempotency
- **결정**: 같은 `idempotency_key` 두 번째 호출은 첫 결과 반환 (재실행 안 함).
- **이유**: CLAUDE.md §4.1 — 모든 주문에 idempotency_key. timeout 후 retry 시 중복 주문 방지의 유일한 방법.

### 5.4 MockBroker 자동 포지션/잔고 갱신
- **결정**: FILLED/PARTIALLY_FILLED 시 `_update_position` 자동 호출. 잔고 차감 + 평균 단가 가중 평균.
- **결정**: `split_level`은 FILLED일 때만 +1. PARTIALLY_FILLED은 유지 (CLAUDE.md §4.4).

### 5.5 MockBroker 잔고 음수 안전장치
- **결정**: fill로 잔고가 음수가 되면 `BrokerConnectionError` raise.
- **이유**: 테스트에서 잘못 구성된 시나리오를 catch.

### 5.6 MockMarketData: KRX 09:00–15:30 KST + explicit_holidays
- **결정**: 영업일 = weekday < 5 AND `as_of.date() not in explicit_holidays`. 시간 = 09:00–15:30 KST.
- **이유**: 사용자 명시. fixture + holidays 이중 보강.

### 5.7 MockMarketData: 룩어헤드 자동 방지
- **결정**: `get_price(asset, as_of)`는 KRX close(15:30 KST) 시각이 `as_of` 이전인 bar 중 가장 최근 것의 close 반환.
- **이유**: 백테스트에서 "오늘 종가로 오늘 결정" 같은 룩어헤드 자동 방지(설계 §4.2).

### 5.8 NullSignal: 항상 NORMAL/NULL, valid_until = at + 1 day
- **결정**: 캐싱 로직 없음. 호출마다 새 CircuitBreakerSignal 생성. valid_until은 필드만 채움.
- **이유**: Phase 0 단순. 캐시 전략은 Phase 2에서 결정.

### 5.9 KST 상수 위치
- **결정**: `src/domain/constants.py`에 `KST = ZoneInfo("Asia/Seoul")` 정의.
- **이유**: zoneinfo는 stdlib이라 도메인 import 허용. 어댑터/오케스트레이터에서 공통 사용.

---

## 6. DailyOrchestrator (Step 6)

### 6.1 Decision 영속화: Step 6 vs Step 7
- **결정**: Step 6은 `Decision`을 단순히 `return`. Step 7(SQLite Repository)에서 호출자가 영속화.
- **이유**: 책임 분리. step 6은 흐름·결정, step 7은 영속화.

### 6.2 SkipReason enum
- **결정**: 9개 값 — `MARKET_CLOSED`, `CIRCUIT_BREAKER_HALT`, `MARKET_DATA_UNAVAILABLE`, `STRATEGY_NO_BUY`, `QUANTITY_TOO_SMALL`, `INSUFFICIENT_BALANCE`, `BROKER_REJECTED`, `BROKER_TIMEOUT`, `DATA_INTEGRITY_ISSUE`. `Decision.action`에 `f"skip:{reason.value}"` 형식.
- **이유**: 표준화된 vocabulary로 후처리/통계 가능. 사용자 명시.

### 6.3 strategy 사유 → SkipReason 매핑
- **결정**: `_STRATEGY_REASON_MAP`로 strategy의 granular reason ("skip:max_split_reached", "skip:drop_insufficient", "skip:quantity_below_lot_size", "skip:insufficient_balance")을 SkipReason 값으로 매핑. 디테일은 `reasoning["strategy_reason"]`에 보존.
- **이유**: 표준화 vs granular detail 둘 다 보존.

### 6.4 today + clock() 둘 다 사용
- **결정**: `today: date`는 의사결정 기준 날짜(전략 로직). `clock()`은 정확한 UTC 시점(타임스탬프, signal.evaluated_at).
- **이유**: 역할 다름. 백테스트는 매일 새 Orchestrator 또는 clock 갱신.

### 6.5 idempotency_key 형식
- **결정**: `f"{asset.fqn}:{today.isoformat()}"` (예: `"KRX:069500:2026-04-30"`).
- **이유**: 결정성 + 재현성. Phase 0은 1일 1회 매수 시도라 (asset, day) pair로 충분.
- **재검토**: Phase 1+에서 1일 다회 시도 필요해지면 `:split_N` 추가.

### 6.6 Order placement 실패 흐름
- **결정**:
  - `BrokerConnectionError` (timeout) → `get_order_status(idempotency_key)` 1회 시도.
    - None → `BROKER_TIMEOUT` skip
    - FILLED → success
    - PARTIALLY_FILLED → `buy_split_N_partial`
    - REJECTED → `BROKER_REJECTED` skip
    - 기타 → `BROKER_TIMEOUT` skip
  - `BrokerOrderError` → `BROKER_REJECTED` skip
  - `get_order_status` 자체 실패 → `BROKER_TIMEOUT` skip
- **이유**: CLAUDE.md §4.3 흐름. timeout은 idempotency 복구 시도 1회.

### 6.7 [정정] CAUTION 처리: Orchestrator
- **결정**: `_adjust_quantity(level, quantity, lot_size)` 메서드.
  - NORMAL: 그대로
  - CAUTION: × 0.5, lot_size로 floor
  - HALT/EMERGENCY: 0 (caller가 short-circuit으로 도달 안 함; 방어적 분기)
- **이유**: 4.5 항목 정정 사항. Strategy를 차단기-무관하게 유지.

### 6.8 IntegrityError 전파
- **결정**: Orchestrator에서 catch 안 함. CLI/runner가 받아서 시스템 정지.
- **이유**: CLAUDE.md §6.1 — 무결성 위반은 즉시 거래 중단.

### 6.9 Reconciliation은 Orchestrator 책임 아님
- **결정**: DB ↔ broker 포지션 대조는 CLI/runner가 `run_for_date()` 호출 전에 수행.
- **이유**: 단일 책임. Orchestrator는 결정만.

### 6.10 Action 라벨 컨벤션
- **결정**:
  - 매수 FILLED: `"buy_split_N"` (N은 next_split_level)
  - 매수 PARTIALLY_FILLED: `"buy_split_N_partial"`
  - 그 외 모든 skip: `f"skip:{SkipReason.value}"`
- **이유**: action 한 필드만 봐도 결과 파악 가능. detail은 reasoning.

---

## 추가 운영 규칙

### A.1 메모리 디렉토리
- `.omc/` 전체 gitignore (volatile state).

### A.2 GitHub Repo
- `akachoochoo/SevenSplit` (private, HTTPS+token via gh credential helper). 실계좌 연결 예정 시스템이라 public 안 함.

### A.3 결정 기록 정책
- 새 결정은 이 문서에 섹션으로 추가.
- 정정 시 `[정정]` 표기 + 원래 결정과 정정 이유 둘 다 보존.
