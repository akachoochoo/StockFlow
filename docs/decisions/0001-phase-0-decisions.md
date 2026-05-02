# ADR 0001: Phase 0 Design Decisions

> 누적 기록 문서. 새 결정은 아래에 섹션으로 추가.
> 마지막 업데이트: 2026-05-02 (§11 Phase 0 완료 선언 — 회고는 docs/retrospectives/phase-0.md)

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
- **[정정 §8.5 참조]**: Step 7 진행 중 정정. Orchestrator가 `uow_factory`로 영속화까지 담당하도록 변경. 이유는 §8.5 참조.

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

## 7. Position 분할별 추적 (Step 7 직전 추가 변경 요청)

### 7.0 [누락 인정] 미구현 항목 일괄 정리
2026-05-01 §12.3.1 체크리스트 적용 시 발견된 이전 결정 미구현 항목들을 모아둔다.
재발 방지: 이번부터 ADR 갱신 시마다 이 체크 수행.

#### 7.0a entry_dates 미구현 (Step 5 Q5)
- **원래 요청**: `place_order` 체결 시 `entry_dates`도 FILLED일 때만 추가.
- **실제**: Position에 `last_buy_at: datetime | None`만 추가, `entry_dates: list[date]`는 빠짐.
- **재처리**: Step 5 요청을 그대로 복구하지 않고, §7.1~§7.3의 더 풍부한 구조(`SplitEntry` + `entries`)로 흡수. `SplitEntry.entry_date`가 `entry_dates`의 정보를 더 강하게 보존.

#### 7.0b round_to_tick 미구현 (Step 4 Q4 보강)
- **원래 요청**: "Asset에 tick_size 필드와 round_to_tick 메서드 추가. Strategy에서 target_price = asset.round_to_tick(current_price.value)."
- **실제**: `tick_size` 필드만 추가, `round_to_tick` 메서드 없음. Strategy는 `target_price = current_price.value`를 그대로 사용 (호가 단위 정렬 안 함).
- **재처리 방침**: Step 7.x 작업과 함께 별도 micro-step으로 추가. `Asset.round_to_tick(price: Decimal) -> Decimal` 메서드(`tick_size` 배수로 floor 또는 round) + Strategy `target_price = asset.round_to_tick(current_price.value)`. 새 ADR 항목 §7.10에서 정식 결정.
- **재검토**: KODEX 200 tick_size=5라 5원 단위 LIMIT 주문이 자연스러움. 이 누락이 KIS API 연결 시 주문 거부 유발 위험 — Phase 1 진입 전 반드시 보강.

#### 7.0c min_quantity vs lot_size 명명 (Step 4 Q4 보강)
- **원래 요청**: "수량 계산은 asset.min_quantity 활용해 floor".
- **실제**: 동일 의미의 필드를 `lot_size`로 명명해 구현. KODEX 200은 `lot_size=Decimal("1")`, 사용자가 명시한 `min_quantity=Decimal("1")`과 값/의도 일치.
- **재처리 방침**: 두 용어가 미묘하게 다를 수 있음(lot_size = 매매 단위, min_quantity = 최소 주문 수량). Phase 0 단일 ETF에서는 같지만 Phase 1+에서 분리 필요할 수 있음. **Phase 0은 `lot_size` 단일 명칭 유지** + ADR에 동의어 명시. Phase 1+에서 KIS API 명세 검토 후 분리 여부 결정.

#### 7.0d today → max_split_per_day 체크 미구현 (Step 4 Q3 보강)
- **원래 요청**: "today를 max_split_per_day 체크에 실제 사용. 형식적 인자가 아니라 실제 로직 기여."
- **실제**: `today: date`는 시그니처에 있고 reasoning에 기록되지만, "오늘 이미 N회 매수했나" 판정 로직은 없음. 사용자가 명시적으로 경고한 "형식적 인자" 상태 그대로.
- **재처리 방침**: Step 7.x에서 `Position.entries`가 추가되면 자연스럽게 구현 가능 — `sum(1 for e in entries if e.entry_date == today) >= max_split_per_day` 체크. 새 ADR 항목 §7.11에서 정식 결정 (`SplitStrategyConfig.max_split_per_day` 추가 + Strategy 분기).
- **재검토**: 현재 Phase 0 = 1일 1회 매수 가정이 묵시적 — 코드에 룰로 박혀있지 않음. entries 도입 시 명시 가드 추가 안 하면 retry/multi-trigger 시 다회 매수 위험.

### 7.1 SplitEntry 신규 도메인 모델
- **결정**: 새 `ValueObject` `SplitEntry(split_number, entry_date, quantity, entry_price, idempotency_key)` 추가.
- **이유**: 세븐 스플릿의 7계좌 운영을 1계좌 + 가상 분할로 재현하면서, 7계좌의 시각적 이점(분할별 손익 추적)을 코드로 보존하려면 단순 날짜 리스트로는 부족. 차수/가격/수량/주문 추적 키까지 함께 묶어야 분할별 PnL 계산이 가능.
- **검증**: `split_number >= 1`, `quantity > 0`, `entry_price > 0`.

### 7.2 Position.entries: list[SplitEntry]
- **결정**: Position에서 `entry_dates`(미구현) 대신 `entries: list[SplitEntry]` 채택. `last_buy_at`은 유지(가장 최근 시점 빠른 조회).
- **불변식 (model_validator)**:
  - `split_level == len(entries)`
  - `entries`의 `split_number`는 1, 2, …, `split_level` 순차적 (gap/중복 금지)
  - `quantity == sum(e.quantity for e in entries)` (Decimal 정확 일치)
  - `avg_price == sum(e.qty * e.entry_price) / sum(e.qty)` (Decimal 정확 일치)
  - 위반 시 `ValueError` (pydantic이 `ValidationError`로 감쌈)
- **이유**: 분할별 진입 정보를 잃지 않으면서 Position의 `quantity`/`avg_price`/`split_level`은 entries의 합산/가중평균/길이로 유도되도록 강제. 데이터 부정합 발생 시 도메인 layer에서 즉시 거부.
- **트레이드오프**: Position 생성 비용 증가. 그러나 Phase 0은 1자산 1일1회 매수라 무시 가능.

### 7.3 Position 분할별 조회/계산 메서드
- **결정**: `get_entry(split_number) -> SplitEntry | None`, `split_pnl(current_price) -> dict[int, Decimal]`, `split_pnl_pct(current_price) -> dict[int, Decimal]` 추가.
- **이유**: 7계좌 운영의 "분할별 손익을 한눈에" 시각적 이점을 1계좌 코드에서 그대로 재현. CLI/리포트가 직접 재계산할 필요 없음.
- **Phase 0 범위 외**: 분할별 부분 매도, 분할별 손절 트리거, 분할별 보유기간 분석 (매도 자체가 Phase 0 외).

### 7.4 Position frozen 유지 + 불변 갱신
- **결정**: Position은 `frozen=True` 그대로. 갱신은 `MockBroker._update_position`이 새 Position 인스턴스를 만들어 `_positions[asset.fqn]`에 교체하는 기존 패턴 유지.
- **이유**: 도메인 모델은 불변(`DomainModel` 계약). 부분 체결/전체 체결 로직이 새 entries 추가 시 새 Position을 만드는 것이 자연스러움.

### 7.5 부분 체결 처리 — entries에 미반영
- **결정**: `MockBroker._update_position`은 PARTIALLY_FILLED 시 `quantity`, `avg_price`, `last_buy_at`만 갱신하고 `entries`/`split_level`은 변동 없음. FILLED일 때만 새 `SplitEntry` append + `split_level += 1`.
- **이유**: CLAUDE.md §4.4 — 부분 체결은 split로 인정 안 함. entries는 "완료된 분할 기록"이므로 부분 체결을 추가하면 의미 왜곡.
- **트레이드오프**: 부분 체결만 누적된 상태에서는 `quantity > 0`이지만 `len(entries) == 0` (`split_level == 0`). 7.2의 합산 불변식과 충돌 가능 → **불변식 보강**: 부분 체결분은 `entries` 합산과 별도로 추적하지 않고 `quantity`/`avg_price`에만 반영. 따라서 7.2 합산 불변식은 "FILLED된 entries만 합산하면 안 되므로", **재정의**:
  - "split_level == len(entries)"는 유지
  - quantity/avg_price 합산 불변식은 적용 안 함 (부분 체결분이 entries에 없을 수 있으므로). 대신 보조 속성 `quantity_from_entries`, `avg_price_from_entries`만 제공하고, "Position.quantity >= quantity_from_entries"만 검증.
- **재검토**: Phase 1+에서 부분 체결을 별도 PartialEntry로 추적할지 결정.

### 7.6 SQLite 스키마 사전 합의 (Step 7 구현 시 적용)
- **결정**:
  ```sql
  CREATE TABLE positions (
      id INTEGER PRIMARY KEY,
      asset_fqn TEXT NOT NULL UNIQUE,
      quantity TEXT NOT NULL,        -- Decimal as string
      avg_price TEXT NOT NULL,
      split_level INTEGER NOT NULL,
      last_buy_at DATETIME,
      updated_at DATETIME NOT NULL
  );
  CREATE TABLE split_entries (
      id INTEGER PRIMARY KEY,
      position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
      split_number INTEGER NOT NULL,
      entry_date DATE NOT NULL,
      quantity TEXT NOT NULL,
      entry_price TEXT NOT NULL,
      idempotency_key TEXT NOT NULL,
      UNIQUE (position_id, split_number)
  );
  CREATE INDEX idx_split_entries_position ON split_entries(position_id);
  ```
- **이유**: 분할별 영속화 + position 삭제 시 cascade. Decimal은 모두 TEXT(string)로 저장(부동소수점 오차 방지, CLAUDE.md §2).

### 7.7 영향 범위 (Step 7.x 구현 시 적용)
- **수정 필요**:
  - `src/domain/models.py`: SplitEntry 신규, Position 갱신, 검증/메서드 추가
  - `src/adapters/mock/broker.py::_update_position`: entries 기반 갱신 로직
  - `tests/unit/test_models.py`: Position 신규 invariants/메서드 테스트
  - `tests/integration/adapters/mock/test_broker.py`: entries 기반 검증
- **변경 없음**:
  - `PriceDropStrategy`: position.split_level/avg_price/quantity만 사용. entries 직접 참조 안 함. (단, §7.11 max_split_per_day 적용 시 entries 참조 추가 예정.)
  - `DailyOrchestrator`: 동일 (Position을 broker에서 받아 strategy에 전달만).

### 7.8 [옵션 A 채택] Position invariant + helper 보강
- **결정**: §7.5의 "느슨한" 옵션 A를 채택하되 다음 항목으로 보강:
  - Position docstring에 부분 체결 정책 명시 (CLAUDE.md §4.4 + §7.5 정책 인용).
  - `pending_partial_quantity: Decimal` property — `Position.quantity - sum(e.quantity for e in entries)`. 0 이상.
  - `has_pending_partial() -> bool` 메서드 — `pending_partial_quantity > 0`.
  - `_validate_invariants` (model_validator) 검증:
    - `split_level == len(entries)`
    - entries의 split_number가 1부터 split_level까지 순차 (gap/중복 금지)
    - `quantity >= sum(e.quantity for e in entries)` (하한)
    - `avg_price > 0` (quantity > 0인 경우)
  - **avg_price 가중평균 일치 검증은 의도적으로 생략** (옵션 A 한계: 부분 체결분이 avg_price에 섞여 있어 entries만으로는 재계산 불가).
- **이유**: 부분 체결분의 흔적을 `pending_partial_quantity`로 가시화. 호출자(Orchestrator/Strategy)가 미체결 잔량 존재를 감지하고 적절히 처리할 수 있게 함.
- **트레이드오프**: avg_price 무결성 검증 약함. 대신 5.4(MockBroker 가중평균 책임) + 7.6(SQLite 영속화 시 stored value 신뢰)으로 보완.

### 7.9 [옵션 B] 부분 체결분의 다음날 처리 정책
- **결정**: 부분 체결분(`pending_partial_quantity`)은 **영구히 `entries`에 흡수되지 않음**. 다음날 이후에도:
  - 같은 차수에 대한 추가 매수가 발생해 *전체* 체결되면, 그 fill만 새 SplitEntry로 등록 (이전 partial은 그대로 quantity/avg_price에만 반영된 채 남음).
  - DailyOrchestrator가 `position.has_pending_partial()`을 감지하면 `Decision.reasoning`에 경고 키(`pending_partial_quantity`, `pending_partial_warning="True"`)를 기록.
  - 시스템은 자동으로 부분→완전 변환을 시도하지 않음. 운영자가 ADR 결정 또는 수동 개입으로 처리.
- **이유**: 부분 체결을 사후 split로 승급시키려면 "어느 차수의 일부였나"를 추적해야 하는데, 이는 split 정의를 흐리고 가격/시점 정보 합성도 모호해짐. CLAUDE.md §11.4 "자동 catch-up 금지" 정신과도 일치 — 부분 체결 처리도 사람 판단.
- **테스트 필수 케이스 (Step 7.e/f에서 작성)**:
  - `test_partial_fill_does_not_become_split_entry_next_day`: PARTIALLY_FILLED 후 다음날 다시 평가했을 때 entries에 partial이 추가되지 않음을 확인.
  - `test_decision_logs_pending_partial_warning`: `has_pending_partial()`이 True인 Position을 받은 Orchestrator의 Decision.reasoning에 경고 키 포함.

### 7.10 [구현 완료, 2026-05-01] Asset.round_to_tick + Strategy target_price 정렬 (§7.0b 재처리)
- **결정**: Step 7.x 6단계 외 별도 micro-step으로 추가:
  - `Asset.round_to_tick(price: Decimal) -> Decimal` 메서드: `tick_size`의 배수로 floor (매수 LIMIT은 보수적으로 더 낮은 호가 선택).
  - `PriceDropStrategy._compute_target_price`(또는 직접) 사용처: `target_price = asset.round_to_tick(current_price.value)`.
  - Decimal precision: 호가 단위가 5/10/100/500/1000원 등으로 변하므로 단순 `(price // tick_size) * tick_size` 사용.
  - 단위 테스트: KODEX 200(tick=5), 가상 stock(tick=10/100/1000)에서 floor 동작 확인.
- **구현**:
  - `Asset.round_to_tick`이 추가됨; `(price // self.tick_size) * self.tick_size`로 floor.
  - `PriceDropStrategy.evaluate`가 `target_price = asset.round_to_tick(current_price.value)`로 전환.
  - 5개 round_to_tick unit test (정확히 일치/floor/just-below/0.01 tick/edge price<tick).
  - 1개 strategy test (35003 → 35000으로 정렬 확인).
- **엣지 케이스**: `price < tick_size`이면 `round_to_tick`은 `Decimal(0)` 반환. Phase 0에서 Price 모델이 `value > 0` 보장하고 KODEX 200(tick=5, price ~35,000)에선 발생 안 함. 향후 마이크로캡 종목에선 가드 필요.

### 7.11 [구현 완료, 2026-05-01] today 기반 max_split_per_day 가드 (§7.0d 재처리)
- **결정**: `SplitStrategyConfig`에 `max_split_per_day: int` 필드 추가 (기본값 1, Phase 0 묵시 룰 명시화).
- **Strategy 분기**:
  - `today_buys = sum(1 for e in position.entries if e.entry_date == today)` 계산.
  - `if today_buys >= config.max_split_per_day: return skip:max_split_per_day_reached`.
  - 신규 SkipReason 항목: `MAX_SPLIT_PER_DAY_REACHED` (오케스트레이터 매핑은 `STRATEGY_NO_BUY` 그룹).
- **이유**: §7.0d 재처리. retry/multi-trigger로 인한 동일일 다회 매수 방지. entries.entry_date 추가가 전제이므로 §7.1~§7.3 작업 후 자연스럽게 추가 가능.
- **구현**:
  - `SplitStrategyConfig.max_split_per_day: int = Field(default=1, ge=1)` 추가.
  - `PriceDropStrategy.evaluate` 첫 분기로 `today_buys` 계산 + cap 체크 → `skip:max_split_per_day_reached`.
  - `SkipReason.MAX_SPLIT_PER_DAY_REACHED` 추가; `_STRATEGY_REASON_MAP`에 `"skip:max_split_per_day_reached" → STRATEGY_NO_BUY` 엔트리.
  - 5개 strategy test + 1개 orchestrator 매핑 test.
  - `_filled_position` 헬퍼 default `entry_date=YESTERDAY`로 변경 (이전 매수가 yesterday-or-earlier로 의미 명확).
- **부분 체결 처리**: ADR §7.5와 일관 — partial fills는 `entries`에 들어가지 않으므로 `today_buys` 카운트에 포함 안 됨. 결과적으로 partial-only 상태에서는 같은 날 추가 매수 시도가 가능 (Phase 0 cron-once-per-day 가정에서 발생 안 하지만, 다회 호출 시 노출).
  - 운영자가 `pending_partial_warning`(§7.9)으로 감지해야 함.
  - 자동 차단을 원하면 Phase 1+에서 partial 카운트 포함하는 옵션 추가 검토.

---

## 8. SQLite Repository + UnitOfWork (Step 7)

### 8.1 Port 분리: aggregate별 4개 + UnitOfWork
- **결정**: 단일 통합 Port가 아닌 aggregate별 4개 Repository Port + UnitOfWorkPort.
- **Port 시그니처**:
  - `PositionRepoPort`: `get(asset_fqn) -> Position | None`, `save(position)`, `list_all() -> list[Position]`, `delete(asset_fqn) -> bool`
  - `OrderRepoPort`: `save(order)`, `get_by_idempotency_key(key) -> Order | None`, `list_pending() -> list[Order]`, `list_by_date(d: date) -> list[Order]`
  - `DecisionRepoPort`: `save(decision)`, `list_by_date_range(start, end) -> list[Decision]`, `get_last_for_asset(asset_fqn) -> Decision | None`
  - `PortfolioSnapshotRepoPort`: `save(snapshot)`, `get_by_date(d: date) -> PortfolioSnapshot | None`, `list_by_date_range(start, end) -> list[PortfolioSnapshot]`
- **이유**: 책임 분리, Mock 단순화, 테스트 격리. 통합 Port면 미구현 메서드까지 mock해야 함.

### 8.2 UnitOfWork 패턴 (Phase 0부터 도입)
- **결정**: `UnitOfWorkPort`가 4개 Repository를 attribute로 노출하고 컨텍스트 매니저로 동작 (`__enter__`, `__exit__`, `commit`, `rollback`). Use Case는 connection을 모름.
- **자동 rollback**: `commit()` 미호출 채로 `__exit__` 진입 시 자동 ROLLBACK. 안전한 기본값.
- **Repository 책임**: 단일 SQL 실행만. 트랜잭션은 UoW 책임.
- **In-memory 변형**: `InMemoryUnitOfWork`(테스트/백테스트용)는 트랜잭션 시뮬레이션 안 함 (단일 프로세스 메모리, 부분 실패 가정 없음). Phase 1+ 실거래는 `SqliteUnitOfWork`의 진짜 트랜잭션이 보장.
- **트랜잭션 정책**: 매수 체결 = orders + positions + decisions 한 트랜잭션. Skip = decisions 단독. Reconciliation = positions + orders 한 트랜잭션. Snapshot = 별도 트랜잭션.

### 8.3 Asset Denormalization — asset_fqn + asset_json 함께 저장
- **결정**: 모든 거래/기록 테이블(positions, split_entries, orders, decisions, portfolio_snapshots)에 `asset_fqn`(인덱스 키) + `asset_json`(시점 박제) 둘 다 저장.
- **불변성**: `asset_json`은 첫 저장 시점에 박제, UPDATE 시 갱신 안 함. positions는 첫 매수 시점, split_entries는 각 분할 시점, orders/decisions는 각 발생 시점.
- **이유**: 거래 기록은 그 시점의 사실. 자산 메타데이터(`tick_size`, `lot_size`, `name` 등) 변경 시 과거 기록 보존 필요. Phase 0~1 단일/소수 자산 환경에서 정규화 이득 없음.
- **트레이드오프**: 저장 공간 약간 증가 (5년 운영 시 ~수 MB). 자산 메타데이터 일괄 변경 어려움 (의도된 동작).
- **직렬화/역직렬화**: 어댑터 내부에서만. 도메인 모델은 항상 `Asset` 객체로만 다룸 (CLAUDE.md §1.1). 저장: `asset.model_dump_json()`. 복원: `Asset.model_validate_json(row)`.
- **Position 복원**: `position_repo.get()`이 반환하는 Position의 asset은 저장 시점 Asset. 호출자가 현재 Asset 정의와 비교 필요 시 별도 로직 (Phase 0 미구현).
- **Phase 1+ 자산 마스터 테이블 도입 검토 시점**: 종목 50개 이상, 자산 분류/태깅 메타 필요, 메타데이터 일괄 업데이트 빈번. 단, 도입하더라도 거래 기록의 `asset_json`은 그대로 유지(시점 무결성).

### 8.4 SQLite 스키마
```sql
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_fqn TEXT NOT NULL UNIQUE,
    asset_json TEXT NOT NULL,        -- 시점 박제
    quantity TEXT NOT NULL,           -- Decimal as TEXT
    avg_price TEXT NOT NULL,
    split_level INTEGER NOT NULL,
    last_buy_at TEXT,                 -- ISO 8601 UTC
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_positions_asset_fqn ON positions(asset_fqn);

CREATE TABLE split_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    split_number INTEGER NOT NULL,
    entry_date TEXT NOT NULL,         -- YYYY-MM-DD
    quantity TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    UNIQUE (position_id, split_number)
);
CREATE INDEX idx_split_entries_position ON split_entries(position_id);

CREATE TABLE orders (
    idempotency_key TEXT PRIMARY KEY,
    asset_fqn TEXT NOT NULL,
    asset_json TEXT NOT NULL,         -- 시점 박제
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity TEXT NOT NULL,
    target_price TEXT NOT NULL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    filled_quantity TEXT NOT NULL,
    filled_price TEXT,
    submitted_at TEXT NOT NULL,
    filled_at TEXT
);
CREATE INDEX idx_orders_submitted_at ON orders(submitted_at);
CREATE INDEX idx_orders_status ON orders(status);

CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,          -- ISO 8601 UTC
    asset_fqn TEXT NOT NULL,
    asset_json TEXT NOT NULL,         -- 시점 박제
    action TEXT NOT NULL,
    reasoning TEXT NOT NULL,          -- JSON (json.dumps with sort_keys=True)
    resulting_order_id TEXT
);
CREATE INDEX idx_decisions_timestamp ON decisions(timestamp);
CREATE INDEX idx_decisions_asset_fqn ON decisions(asset_fqn);

CREATE TABLE portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL UNIQUE,
    snapshot_at TEXT NOT NULL,        -- ISO 8601 UTC
    initial_capital_amount TEXT NOT NULL,
    initial_capital_currency TEXT NOT NULL,
    cash_amount TEXT NOT NULL,
    cash_currency TEXT NOT NULL,
    valuations_json TEXT NOT NULL,    -- list[PositionValuation] 직렬화 (시점 박제)
    total_market_value_amount TEXT NOT NULL,
    total_market_value_currency TEXT NOT NULL,
    total_value_amount TEXT NOT NULL,
    total_value_currency TEXT NOT NULL,
    total_cost_basis_amount TEXT NOT NULL,
    total_cost_basis_currency TEXT NOT NULL,
    total_unrealized_pnl_amount TEXT NOT NULL,
    total_unrealized_pnl_currency TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```
- **Decimal**: 항상 TEXT (정밀도 보존, CLAUDE.md §2). 어댑터 내부에서 `str(decimal)` ↔ `Decimal(text)`.
- **datetime**: ISO 8601 UTC TEXT (예: `"2026-04-30T06:00:00+00:00"`).
- **date**: `YYYY-MM-DD` TEXT.
- **Money**: amount + currency 별도 컬럼 (JSON 대비 쿼리 가능, 단순).
- **JSON 직렬화**: `json.dumps(sort_keys=True)`로 결정적 출력.

### 8.5 [정정] §6.1 — Orchestrator가 UoW로 영속화
- **원래 결정 (Step 6)**: Step 6은 `Decision`을 단순 return, Step 7에서 호출자가 영속화.
- **정정 (Step 7, 2026-05-01)**: `DailyOrchestrator`가 생성자에 `uow_factory: Callable[[], UnitOfWorkPort]`를 받아 `run_for_date` 내부에서 영속화 수행. Use Case는 connection을 모르고 UoW의 `commit/rollback`만 호출.
- **이유 (정정)**: Use Case가 결정 + 영속화를 한 트랜잭션 단위로 묶어야 일관성 보장. 외부 호출자(CLI)가 따로 영속화하면 결정과 저장 사이에 race/실수 가능. UoW 패턴은 connection 추상화 + 자동 rollback 제공.
- **흐름**:
  ```python
  def run_for_date(self, today: date) -> Decision:
      outcome = self._make_decision(today, self._clock())  # DB 안 건드림
      with self._uow_factory() as uow:
          if outcome.order is not None:
              uow.orders.save(outcome.order)
          if outcome.updated_position is not None:
              uow.positions.save(outcome.updated_position)
          uow.decisions.save(outcome.decision)
          uow.commit()
      return outcome.decision
  ```

### 8.6 PortfolioSnapshot 확장 + PositionValuation 신규
- **결정**: `PortfolioSnapshot`에 시장가 평가 메타데이터 포함. `PositionValuation` 신규 도메인 모델 추가.
- **PositionValuation 필드**:
  - `asset: Asset`, `quantity: Decimal`, `avg_price: Decimal`, `market_price: Decimal`
  - `market_value: Money` (= `quantity * market_price`)
  - `unrealized_pnl: Money` (= `(market_price - avg_price) * quantity`)
  - `unrealized_pnl_pct: Decimal` (= `(market_price - avg_price) / avg_price * 100`)
  - `split_level: int`
  - 무결성: `market_value == quantity * market_price` (model_validator)
- **PortfolioSnapshot 필드**:
  - `snapshot_date: date`, `snapshot_at: datetime` (UTC)
  - `initial_capital: Money` (시스템 시작 시 자본, 매 snapshot 박제)
  - `cash: Money`
  - `valuations: list[PositionValuation]`
  - `total_market_value: Money`, `total_value: Money`, `total_cost_basis: Money`, `total_unrealized_pnl: Money`
  - `total_return_pct: Decimal` (`@property`, 파생)
  - 무결성:
    * `total_market_value == sum(v.market_value for v in valuations)`
    * `total_value == cash + total_market_value`
    * 모든 Money currency 일치
    * 불일치 시 ValueError → ValidationError (도메인 invariant)
- **부분 체결분 평가 (옵션 A)**: `position.quantity` 전체로 valuation 계산. `pending_partial_quantity`는 `Position`에서 별도 surfaceable, valuation 자체는 통합값 사용. 이유: Position.quantity가 진실의 단일 출처.
- **통화**: Phase 0 KRW 단일. `model_validator`가 currency 불일치 거부.
- **이유**: CAGR/MDD/Sharpe 등 백테스트 지표 계산에 필수. 시세 조회 비용은 의사결정 시 이미 발생.

### 8.7 DailySnapshotBuilder 분리 (Application 레이어)
- **결정**: `src/application/snapshot_builder.py::DailySnapshotBuilder`. 의사결정 트랜잭션과 분리된 별도 워크플로우.
- **흐름**:
  1. `uow.positions.list_all()` 조회
  2. `broker.get_balance()`로 cash 조회
  3. `market_data.get_price(asset, as_of)`로 각 포지션 현재가 조회
  4. `PositionValuation` 생성
  5. `PortfolioSnapshot` 조립
  6. `uow.snapshots.save(snapshot)` + `uow.commit()`
- **이유**: snapshot은 장 마감 후 종합 평가. 의사결정과 결합도 낮춤. 호출 순서: `orchestrator.run_for_date()` → `snapshot_builder.build_and_save()`.
- **CLI 책임**: 두 단계를 cron 또는 스크립트에서 직렬 호출.

### 8.8 [CLAUDE.md §10.3 보강] UoW 트랜잭션 정책
- **추가 명시**: "여러 Repository에 걸친 변경은 UnitOfWork로 묶는다. Use Case는 connection을 모르고 UoW의 commit/rollback만 호출. 자동 rollback (commit 미호출 시 __exit__에서)이 안전 기본값."
- **CLAUDE.md §10.3 갱신 예정**: 이번 ADR commit과 함께 CLAUDE.md 동시 업데이트.

### 8.9 InMemoryUnitOfWork (백테스트/페이퍼 트레이딩 용)
- **결정**: `src/adapters/mock/in_memory_unit_of_work.py::InMemoryUnitOfWork`. 4개 in-memory Repository를 보유. 트랜잭션 시뮬레이션 안 함 (commit/rollback이 no-op).
- **이유**: Phase 0 단일 프로세스 메모리, 부분 실패 가정 없음. 백테스트 결정성 + 단순성.
- **Phase 1+ 실거래**: SqliteUoW가 진짜 트랜잭션 보장.

### 8.10 작업 순서 (Step 7 sub-steps) — [구현 완료, 2026-05-01]
- **8.a** ✅ ADR + CLAUDE.md 업데이트 (`f59cf43`)
- **8.b** ✅ 도메인 모델 신규/확장: `PositionValuation`, `PortfolioSnapshot` + 단위 테스트 (`bbe38d2`)
- **8.c** ✅ Repository Port 4개 + `UnitOfWorkPort` (`3cb13ba`)
- **8.d** ✅ `src/infrastructure/db.py` 스키마 부트스트랩 + connection 팩토리 (`90aca98`)
- **8.e** ✅ 4개 SQLite Repository 어댑터 + 라운드트립 테스트 (`a47f92b`)
  - 부수 변경: `Asset.fqn`을 `@computed_field`에서 plain `@property`로 변경 (model_dump 출력 제외 → JSON 라운드트립 시 `extra="forbid"` 회피).
- **8.f** ✅ `SqliteUnitOfWork` + 트랜잭션 무결성 테스트 (`52f566f`)
- **8.g** ✅ `InMemoryUnitOfWork` (Phase 0 백테스트용) (`d673781`)
- **8.h** ✅ `DailyOrchestrator` 리팩터링 — `uow_factory` 주입, 영속화 흐름 추가 + 테스트 (`a0db785`)
  - `_Outcome` dataclass 도입; persistence 분리; 두 UoW 어댑터 모두 attribute를 Port 타입으로 명시(mypy 구조 적합성).
- **8.i** ✅ `DailySnapshotBuilder` + 단위/통합 테스트 (`a5c9907`)
- **8.j** ✅ ADR 마무리 + push

---

## 9. BacktestRunner (Step 8)

> 결정 라운드 시작 전 §12.3.1 체크리스트 적용:
> 직전 사용자 요청 중 미구현 항목 검색 (`grep -r entry_dates`, `grep -r round_to_tick`,
> `grep -r max_split_per_day`, `grep -r BacktestRunner`) → §7.10/§7.11 반영 완료,
> Step 8 신규 항목만 남음.

### 9.0 목적
- **결정**: `src/application/backtest_runner.py::BacktestRunner` — 단일 자산 과거 OHLCV를 day-by-day 재생하여 `DailyOrchestrator + DailySnapshotBuilder`를 실거래와 동일한 흐름으로 호출. `BacktestResult`로 결과 박제 (decisions, snapshots, 4개 성과 지표).
- **이유**: CLAUDE.md §7.4 "백테스트와 실거래 동일성 검증"의 1차 도구. Phase 0 종료 기준(KOSPI 200 5년치 백테스트 성공)을 충족하는 최소 단위.
- **Phase 0 한계 명시**: 단일 자산, 단일 프로세스, 단일 스레드. 멀티 자산은 Phase 1+.

### 9.1 시그니처
- **결정**: 생성자 주입형 클래스 + `run(start, end) -> BacktestResult`.
  ```python
  BacktestRunner(
      *,
      asset: Asset,
      strategy_config: SplitStrategyConfig,
      initial_capital: Money,
      ohlcv_by_asset: dict[Asset, list[OHLCV]],
      signal_factory: Callable[[], SignalPort] | None = None,  # default NullSignal
      decision_kst_time: time = time(9, 0),
      snapshot_kst_time: time = time(16, 0),
  )
  ```
- **이유**:
  - DI 일관성 (CLAUDE.md §1.2). `signal_factory`는 매 run마다 새 SignalPort를 만들 수 있게 callable로 받음 (Phase 2 RuleBasedSignal에서 캐시 상태 격리 필요할 때 대비).
  - `ohlcv_by_asset`은 호출자 책임으로 미리 로드. CSV/pykrx 로더는 Step 9에서 분리(§9.6).
  - `decision_kst_time` / `snapshot_kst_time`은 ADR §4.2의 두 시계 모델을 외부 주입 가능하게 노출 (테스트 시 KRX 외 시장에 응용 가능).
- **트레이드오프**: `signal_factory`가 약간의 보일러플레이트. 그러나 Phase 0 NullSignal은 stateless라 매 호출 새로 만들어도 비용 0.

### 9.2 Trading day 정의
- **결정**: `bars`에 OHLCV가 존재하는 날만 trading day. `[start, end]` 범위 안에서 OHLCV가 있는 `trade_date`만 iterate.
- **이유**:
  - 휴장일/주말은 외부에서 fixture가 이미 반영(KRX는 휴장일에 bar 없음). MockMarketData의 `is_market_open` 결과를 별도로 묻지 않음으로써 데이터-소스 단일 진실 유지.
  - 사용자가 5년치 KRX 데이터를 주입하면 자연스럽게 ~1250 영업일만 처리.
- **트레이드오프**: bar 누락(데이터 결손) = 휴장일 취급. 결손 vs 휴장 구분은 향후 데이터 소스(pykrx 등)에서 holiday calendar로 보강.

### 9.3 룩어헤드 방지 (두 시계 모델)
- **결정**:
  - `decision_at` = KST `decision_kst_time`(기본 09:00) → UTC. 이 시각에는 T-1 종가만 보임 (MockMarketData §5.7 룩어헤드 자동 방지).
  - `snapshot_at` = KST `snapshot_kst_time`(기본 16:00) → UTC. KRX 마감(15:30) 후라 T 종가가 가용.
- **흐름**:
  ```
  for trade_date in trading_dates:
      clock_holder[0] = utc_for(d, 09:00 KST)   # T-1 close visible
      decisions.append(orchestrator.run_for_date(d))
      clock_holder[0] = utc_for(d, 16:00 KST)   # T close visible
      snapshots.append(snapshot_builder.build_and_save(d))
  ```
- **이유**: ADR §4.2의 의도를 코드 흐름으로 박제. 의사결정은 정보 격차 ≤ 0(과거만 보임), 평가는 마감가 기준. CLAUDE.md §7.4 "백테스트와 실거래 동일성"의 핵심 메커니즘.
- **재검토**: 장중 트리거 전략(분봉) 도입 시 이 두-시계 모델은 다중-시계로 확장 필요 (Phase 1+).

### 9.4 인스턴스 공유 (한 run = 한 어댑터 세트)
- **결정**: 한 `run()` 호출 안에서는 `MockBroker`, `MockMarketData`, `NullSignal`, `InMemoryUnitOfWork`를 **한 번 생성하고 모든 trading day에서 재사용**. 각 `run()`은 독립 (생성자 주입값으로 매번 새 어댑터 세트 빌드).
- **이유**:
  - 포지션/잔고/주문/decision/snapshot이 day-to-day로 누적돼야 함 (페이퍼 트레이딩과 동일한 상태 진행).
  - run 단위 격리 → 같은 BacktestRunner 인스턴스로 여러 (start, end) 백테스트 가능.
  - `clock`은 mutable holder(`list[datetime|None]`) 1개를 모든 어댑터에 공유. 두 시계 사이 swap이 holder 1번 갱신으로 끝남.
- **트레이드오프**: `InMemoryUnitOfWork` 1개를 공유하므로 ADR §8.9 "no-op 트랜잭션" 정책에 따라 day간 격리 시뮬레이션 안 됨. Phase 0 결정성/단순성 우선.

### 9.5 성과 지표 (CAGR / MDD / Sharpe / Calmar)
- **결정**:
  - 계산 로직은 `src/application/metrics.py`에 **순수 함수**로 분리. 입력: `list[PortfolioSnapshot]`, 출력: `Decimal`.
  - `BacktestResult.from_run()` 팩토리에서 metrics 호출 → 4개 지표를 결과 필드로 직접 노출.
  - **Phase 0 단순화**: risk-free rate = 0, 거래일 = 252일/년 가정.
- **함수 시그니처**:
  ```python
  def cagr(snapshots: list[PortfolioSnapshot]) -> Decimal
  def max_drawdown(snapshots: list[PortfolioSnapshot]) -> Decimal  # 음수 (-15.5 등)
  def sharpe_ratio(snapshots: list[PortfolioSnapshot], *,
                   risk_free_rate: Decimal = Decimal(0),
                   trading_days_per_year: int = 252) -> Decimal
  def calmar_ratio(snapshots: list[PortfolioSnapshot]) -> Decimal
  ```
- **엣지 케이스**:
  - snapshots 비어있음 / 1개 → 모든 지표 0 반환 (시계열 부족).
  - MDD가 0 → Calmar는 0 반환 (분모 0 회피, infinity 방지).
  - 일일 수익률 표준편차 0 → Sharpe 0 반환.
- **이유**:
  - 순수 함수 분리는 페이퍼 트레이딩 / 실거래 보고서에서도 같은 함수 재사용 가능 (사용자 명시 — "외부 의존 없는 코드 최대화" 철학).
  - `PortfolioSnapshot.total_value`가 일일 자산가치 시계열 단일 진실의 출처 (ADR §8.6).
- **트레이드오프**: risk-free=0과 252일은 Phase 0 단순화. 실거래 시 KOSPI 무위험 수익률 / 시장별 거래일 수 주입 필요 (Phase 1+에서 파라미터 노출 이미 준비됨).

### 9.6 Phase 0 한계 / Phase 1+ 확장 포인트
- **단일 자산만**: `asset` 필드 1개. 멀티 자산은 `dict[Asset, SplitStrategyConfig]` 형태로 확장 필요.
- **OHLCV 사전 로드 가정**: CSV/pykrx 다운로더는 Step 9에서 추가. BacktestRunner는 데이터 소스에 의존 안 함.
- **CLI 진입점 없음**: Step 9에서 `trading paper / backtest` CLI 구축. Step 8은 `scripts/manual_backtest.py`로 일회성 manual 검증만 (사용자 명시 — "사람이 직접 결과 보고 직관 형성").
- **Reconciliation 없음**: 백테스트는 broker가 곧 진실. CLAUDE.md §11.2의 DB↔broker 대조는 페이퍼/실거래 CLI 책임 (Step 9+).
- **단일 통화 (KRW)**: 환율 변환 없음. PortfolioSnapshot의 currency 일치 invariant가 보호.
- **부분 체결분 valuation**: ADR §8.6 옵션 A 그대로 — Position.quantity 전체로 valuation. 백테스트 결과의 부분 체결 흔적은 Decision.reasoning + Position.has_pending_partial로 추적.

### 9.7 작업 순서 (Step 8 sub-steps)
- **9.a** ADR §9 신규 (이 문서)
- **9.b** `src/application/metrics.py` + `tests/unit/test_metrics.py`
- **9.c** `src/application/backtest_runner.py` 완성 (`BacktestResult.from_run` 추가)
- **9.d** `tests/integration/application/test_backtest_runner.py` (6개 시나리오)
- **9.e** `scripts/manual_backtest.py` (60일치 inline fixture)
- **9.f** ruff/mypy/pytest 통과
- **9.g** `python scripts/manual_backtest.py` 실행 → 사람 눈으로 결과 검증

---

## 10. CLI / Paper Trading (Step 9)

> 결정 라운드 시작 전 §12.3.1 체크리스트 적용:
> 직전 사용자 요청 항목 검색 (`grep -r "trading paper"`, `grep -r CashRepo`,
> `grep -r kill_switch`, `grep -r TRADING_HALT`, `grep -r CliRunner`,
> §9.6 "CLI 진입점 없음", §8.5 "Use Case가 connection을 모름") →
> Q1~Q7 모든 답변 항목이 본 §10에 박제 대상으로 식별됨.

### 10.0 목적
- **결정**: Phase 0 운영 진입점 — `trading backtest` (과거 OHLCV 재생)와 `trading paper` (cron 단발 실행, SQLite 영속화) 두 서브명령. `manual_backtest.py`(§9.7 Step 8 산출)는 폐기.
- **이유**: 로드맵 Step 9 명세 충족 + Step 10 (백테스트 vs 페이퍼 동일성 검증) 진입로 확보. Composition root를 CLI에 두어 도메인/어댑터 의존 그래프를 한 곳에서 와이어링.

### 10.1 CLI 골격
- **결정**: `src/cli/main.py`에 click group `trading` + 서브명령 `backtest` / `paper`.
  ```
  trading backtest --csv PATH --asset 069500 --start YYYY-MM-DD --end YYYY-MM-DD \
                   --capital 10000000 [--json]
  trading paper    --csv PATH --asset 069500 --date YYYY-MM-DD \
                   --db PATH --capital 10000000 [--json]
  ```
- **이유**: pyproject `[project.scripts] trading = "src.cli:main"` 이미 등록. click 8.1 기존 의존성. status / reconcile 등 부가 명령은 운영 중 발견 시 Phase 1+에서 추가.
- **CLAUDE.md §13.2 옵션 형식 준수**: 옵션 충돌 (예: `--date`/`--asset` 누락) 시 click 자체 에러로 즉시 거부 후 사람 개입 대기.

### 10.2 CSV Market Data Loader
- **결정**: `src/infrastructure/csv_market_data_loader.py::load_ohlcv_csv(path, asset) -> list[OHLCV]`. 표준 형식 `date,open,high,low,close,volume` (헤더 필수, ISO 8601 `YYYY-MM-DD`). 모든 숫자 필드는 `Decimal(str(...))`로 파싱.
- **검증**:
  - 헤더 누락 / 컬럼 부족 → `ValueError`
  - 빈 파일 → 빈 리스트 (예외 아님 — 호출자가 의미 결정)
  - OHLC 정합성 (`OHLCV` model_validator로 자동 위반 시 `ValidationError`)
  - 중복 `trade_date` → `ValueError` ("거래기록은 시점의 사실" §8.3 정신)
- **백테스트와 페이퍼 공유**: 같은 로더, 같은 검증, 같은 결정성. 차이는 caller의 `[start, end]` 범위만.
- **pykrx 다운로더**: `scripts/download_kodex200.py`에 placeholder 작성. 실제 구현은 Phase 1 직전. Phase 0에서 pykrx를 실행 의존성으로 추가하지 않음 (네트워크 의존 회피).
- **재검토**: tick_size가 시점에 따라 변하는 종목(액면병합 등) 도입 시 OHLCV에 `asset_json` 박제 또는 시계열 split factor 컬럼 추가 검토.

### 10.3 Cash / Positions 진실 출처 분리 [핵심]
- **결정**:
  - **Cash 진실**: `portfolio_snapshots.cash` (가장 최근 snapshot의 cash 값)
  - **Positions 진실**: `positions` 테이블 (PositionRepo)
  - **첫 실행 (snapshot이 없을 때)**: CLI의 `--capital` 인자 또는 환경 default → MockBroker initial_balance
- **이유**:
  - PortfolioSnapshot은 §8.6에서 매일 박제되며 cash + valuations 합계가 invariant로 검증됨 → cash 별도 Repository 추가 없이 기존 인프라 재사용.
  - Position 영속화는 §8.4의 positions 테이블에서 이미 보장.
  - 두 출처 일관성은 §10.4 sanity check가 보호.
- **흐름** (paper 명령 시작):
  ```python
  with uow_factory() as uow:
      last_snap = uow.snapshots.get_last()  # MAX(snapshot_date)
      cash_money = last_snap.cash if last_snap else config.initial_capital
      stored_positions = uow.positions.list_all()
  broker = MockBroker(initial_balance=Balance(cash=cash_money), clock=clock)
  for p in stored_positions:
      broker.set_position(p)  # §10.5에서 신규 메서드
  ```
- **트레이드오프**:
  - 첫 paper 실행은 snapshot 없음 → `--capital` 또는 config 필수. CLI에서 누락 시 명시 에러.
  - cash가 snapshot 단위로만 갱신되므로 같은 날 paper 명령을 두 번 실행하면 두 번째 실행은 첫 번째의 snapshot.cash를 시작값으로 사용 (idempotency_key가 `{asset.fqn}:{today}`이므로 두 번째 buy는 자동 차단됨 — §6.5).
- **신규 Port 메서드**: `PortfolioSnapshotRepoPort.get_last() -> PortfolioSnapshot | None` 추가. SqliteRepo는 `ORDER BY snapshot_date DESC LIMIT 1`, InMemoryRepo는 `max(self._snapshots, key=date)`.

### 10.4 Phase 0 Reconciliation 정책 (최소 sanity check)
- **결정**: 정식 reconciliation (DB ↔ broker 실제 포지션 대조)은 Phase 1+ 실거래 도입 시 추가. Phase 0 paper에서는 다음 **최소 sanity check만** 수행:
  - **Snapshot ↔ Positions 동기화**: 가장 최근 snapshot의 `valuations[*].asset.fqn` 집합이 positions 테이블의 `asset_fqn` 집합과 일치 (단, 비어있는 set 양쪽이면 통과).
  - **불일치 시**: `IntegrityError` raise → CLI가 받아 시스템 정지 + 사람 개입 대기 (CLAUDE.md §6.1).
  - **자동 수정 절대 금지** (§11.2 정신).
- **위치**: CLI `paper` 명령 진입 직후, broker 와이어링 전. 별도 `src/cli/sanity.py::check_snapshot_position_sync(uow)`.
- **이유**:
  - Phase 0 MockBroker는 in-memory + 매번 새로 만들어지므로 "broker 실제 포지션" 개념 없음 → 정식 reconciliation 불가능.
  - 그러나 SqliteUoW에서 두 출처 (cash from snapshots, positions from positions table)가 갈라지면 §10.3의 진실 출처 분리 가정이 깨짐 → sanity check가 수호자.
  - Phase 1 KIS API 도입 시 본격 reconciliation 함수가 이 sanity check를 흡수하는 형태로 진화.
- **재검토**: Phase 1 진입 직전.

### 10.5 안전장치 (Kill Switch + Lock File)
- **결정**: 두 항목 모두 Phase 0부터 도입. `src/cli/safety.py`에 헬퍼 분리.
- **Kill switch (CLAUDE.md §11.1)**:
  - 환경변수 `TRADING_HALT=1` 설정 시 모든 명령(backtest 포함) 즉시 종료, exit code 0, stderr에 critical 로그.
  - CLI 진입 첫 줄에서 체크.
- **Lock file (CLAUDE.md §10.2)**:
  - 위치: `~/.trading-system.lock` (사용자 홈, 절대경로). `--lock-file PATH` 인자로 override 가능 (테스트용).
  - 형식: 텍스트 1줄 — `f"{pid}\n"`.
  - acquire: 파일 없으면 PID 기록 후 진입. 파일 있으면 PID 검증 → 살아있는 프로세스면 `ConcurrentRunError` raise; 없으면 (stale) 정리 후 재acquire.
  - release: `atexit`으로 자동 정리 + 정상 종료 시 명시 정리.
  - paper / backtest 둘 다 적용 (백테스트도 cron 가능성 대비).
- **이유**:
  - CLAUDE.md 명시 항목. Phase 1 직전 부담 회피.
  - Lock file은 단순 PID-based로 구현 비용 작음 (psutil 등 외부 의존 없이 `os.kill(pid, 0)`로 살아있는지 검사).
- **트레이드오프**: 같은 머신 가정. NFS / 분산 환경은 Phase 2+에서.

### 10.6 출력 형식 (Text + --json)
- **결정**: 기본은 human-readable text. `--json` 플래그로 JSON 출력.
- **JSON 구조**: pydantic `model_dump_json()` 활용. `BacktestResult`는 `dataclass`라 `dataclasses.asdict` + 직접 JSON 변환 (Decimal → str). `Decision` / `PortfolioSnapshot`은 pydantic이라 자동.
- **헬퍼 위치**: `src/cli/output_formatter.py`:
  - `format_backtest_result(result, *, as_json: bool) -> str`
  - `format_paper_decision(decision, snapshot, *, as_json: bool) -> str`
- **이유**: text는 manual 검증/직관 형성 (§9.6 사용자 명시), JSON은 Phase 1+ 모니터링/대시보드 연결 대비 동시 노출.

### 10.7 Composition Root
- **결정**: `src/cli/composition.py`가 paper 와이어링 책임:
  - `build_paper_orchestrator(asset, csv_path, db_path, today, capital, clock_factory) -> tuple[DailyOrchestrator, DailySnapshotBuilder]`
  - `build_backtest_runner(asset, csv_path, capital, ...)` 는 `BacktestRunner` 자체가 self-contained라 단순 wrap.
- **이유**: CLI 명령 본체는 인자 파싱 + safety + 출력만. 실제 객체 그래프 빌드는 composition root에서. 테스트가 CLI를 by-pass하고 composition만 검증 가능.
- **MockBroker 확장**: `set_position(position: Position)` 메서드 추가 — 외부에서 복원된 Position을 broker 내부 dict에 주입. cash는 `__init__`의 `initial_balance`로 충분.

### 10.8 백테스트 vs 페이퍼 동일성 회귀 테스트 (Step 10 흡수)
- **결정**: `tests/integration/test_backtest_paper_equivalence.py` 작성. 같은 OHLCV / 같은 config로:
  - backtest 1회 → BacktestResult.decisions 시퀀스
  - paper N일 cron 시뮬레이션 (같은 SQLite DB, 매일 별도 CLI 호출로 시뮬) → Decision 시퀀스 from DB
  - 두 시퀀스의 `(action, reasoning["filled_quantity"], reasoning["filled_price"])` 일치 확인.
  - 최종 cash + position quantity / avg_price 일치 확인.
- **이유**: CLAUDE.md §7.4 "백테스트와 실거래의 동일성 검증". Phase 0에서 이 회귀 테스트가 통과하면, Phase 1+ 실거래 진입 시 broker만 교체로 동일성 자동 보존됨.
- **로드맵 Step 10 흡수**: 사용자 명시 — Step 9 안에서 함께 작성.

### 10.9 작업 순서 (Step 9 sub-steps)
- **10.a** ✅ ADR §10 신규 (이 문서)
- **10.b** ✅ `src/infrastructure/csv_market_data_loader.py` + 단위 테스트
- **10.c** ✅ `src/cli/safety.py` (kill switch + lock) + 단위 테스트
- **10.d** ✅ `src/cli/output_formatter.py` (text + JSON) + 단위 테스트
- **10.e** ✅ `MockBroker.set_position()` + `PortfolioSnapshotRepoPort.get_last()` (양쪽 어댑터)
- **10.f** ✅ `src/cli/composition.py` paper 와이어링
- **10.g** ✅ `src/cli/main.py` (click group + backtest + paper 서브명령)
- **10.h** ✅ `tests/integration/test_cli.py` (CliRunner) — 18 시나리오
- **10.i** ✅ `tests/integration/test_backtest_paper_equivalence.py` — Decision 시퀀스 + 최종 cash/포지션 동일성 invariant
- **10.j** ✅ `scripts/manual_backtest.py` 폐기, `scripts/download_kodex200.py` placeholder 추가 (Phase 1 진입 시 pykrx 의존성 도입 예정)
- **10.k** ✅ ruff / mypy / pytest 모두 그린 (489 passed, 99 % coverage)
- **10.l** ✅ `trading backtest` 60일 합성 데이터로 manual 검증 — split_1~7 모두 발화, 최종 -23.31 % return, MDD -23.91 %, Sharpe -4.06 (하락장에서 예상한 형태)
- **10.m** ✅ `trading paper` 10일 연속(2026-02-02~02-13) manual 검증 — cross-run cash/position 복원 정상, backtest와 동일한 (date, action, qty, price) 시퀀스 재현 확인 (split_1 33주@30135, split_2 36주@27740, split_3 36주@27435)

---

## 11. Phase 0 완료 (2026-05-02)

Phase 0 종료 기준 (CLAUDE.md §14) 모두 충족:
- 단일 자산(KODEX 200) PriceDropStrategy + Mock adapter set
- 백테스트 ↔ 페이퍼 동일성 invariant 통과
- KOSPI 200 5년치(2020-01-02 ~ 2024-12-30) 실데이터 백테스트 완료
  → +25.96 % return / -27.57 % MDD vs B&H +21.13 % / -34.64 %

상세 결과 + 학습 + Phase 1 권고: **`docs/retrospectives/phase-0.md`**.

Phase 1 진입은 본 회고의 §9 체크포인트 통과 후 별도 ADR 라운드로 시작.

---

## 추가 운영 규칙

### A.1 메모리 디렉토리
- `.omc/` 전체 gitignore (volatile state).

### A.2 GitHub Repo
- `akachoochoo/SevenSplit` (private, HTTPS+token via gh credential helper). 실계좌 연결 예정 시스템이라 public 안 함.

### A.3 결정 기록 정책
- 새 결정은 이 문서에 섹션으로 추가.
- 정정 시 `[정정]` 표기 + 원래 결정과 정정 이유 둘 다 보존.
