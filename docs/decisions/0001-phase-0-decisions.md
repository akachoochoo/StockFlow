# ADR 0001: Phase 0 Design Decisions

> 누적 기록 문서. 새 결정은 아래에 섹션으로 추가.
> 마지막 업데이트: 2026-05-01

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

### 7.10 [예약] Asset.round_to_tick + Strategy target_price 정렬 (§7.0b 재처리)
- **결정**: Step 7.x 6단계 외 별도 micro-step으로 추가:
  - `Asset.round_to_tick(price: Decimal) -> Decimal` 메서드: `tick_size`의 배수로 floor (매수 LIMIT은 보수적으로 더 낮은 호가 선택).
  - `PriceDropStrategy._compute_target_price`(또는 직접) 사용처: `target_price = asset.round_to_tick(current_price.value)`.
  - Decimal precision: 호가 단위가 5/10/100/500/1000원 등으로 변하므로 단순 `(price // tick_size) * tick_size` 사용.
  - 단위 테스트: KODEX 200(tick=5), 가상 stock(tick=10/100/1000)에서 floor 동작 확인.
- **시점**: §7의 Position/SplitEntry 작업 직후, 이번 ADR commit 이후 시작 6단계와 별개로 잡음. 사용자 승인 후 진행.

### 7.11 [예약] today 기반 max_split_per_day 가드 (§7.0d 재처리)
- **결정**: `SplitStrategyConfig`에 `max_split_per_day: int` 필드 추가 (기본값 1, Phase 0 묵시 룰 명시화).
- **Strategy 분기**:
  - `today_buys = sum(1 for e in position.entries if e.entry_date == today)` 계산.
  - `if today_buys >= config.max_split_per_day: return skip:max_split_per_day_reached`.
  - 신규 SkipReason 항목: `MAX_SPLIT_PER_DAY_REACHED` (오케스트레이터 매핑은 `STRATEGY_NO_BUY` 그룹).
- **이유**: §7.0d 재처리. retry/multi-trigger로 인한 동일일 다회 매수 방지. entries.entry_date 추가가 전제이므로 §7.1~§7.3 작업 후 자연스럽게 추가 가능.
- **시점**: §7.10과 같은 6단계 작업 후 micro-step. 사용자 승인 후 진행.

---

## 추가 운영 규칙

### A.1 메모리 디렉토리
- `.omc/` 전체 gitignore (volatile state).

### A.2 GitHub Repo
- `akachoochoo/SevenSplit` (private, HTTPS+token via gh credential helper). 실계좌 연결 예정 시스템이라 public 안 함.

### A.3 결정 기록 정책
- 새 결정은 이 문서에 섹션으로 추가.
- 정정 시 `[정정]` 표기 + 원래 결정과 정정 이유 둘 다 보존.
