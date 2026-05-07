# CLAUDE.md

> **이 파일은 모든 코드 작업 전에 반드시 읽으세요.**
> 이 프로젝트는 실계좌가 연결될 자동매매 시스템입니다. 한 번의 버그가 돈으로 직결됩니다.
> "동작하는 것 같다"와 "안전하다"는 다릅니다. 항상 후자를 추구하세요.

---

## 0. 작업 시작 전 체크리스트

새 코드를 작성하기 전:

1. 작업 범위가 현재 Phase에 속하는가? (Phase는 `docs/roadmap.md` 참조)
2. 기존 인터페이스(`src/ports/`)를 변경해야 하는가? → 변경 시 사용자 승인 필요
3. 새 외부 의존성을 추가하는가? → `pyproject.toml` 수정 시 사용자 승인 필요
4. 도메인 로직 변경인가? → 테스트 먼저 작성 후 구현

**모르겠으면 코드 짜지 말고 사용자에게 질문하세요.** 추측으로 채우지 마세요.

---

## 1. 아키텍처 규칙 (가장 중요)

### 1.1 Clean Architecture - Dependency Rule

```
[Frameworks] → [Adapters] → [Use Cases] → [Domain]
의존성은 항상 안쪽으로. 반대 방향 절대 금지.
```

**`src/domain/`에서 금지된 import**:
- `import sqlite3`, `sqlalchemy`, 기타 DB 라이브러리
- `import requests`, `httpx`, 기타 HTTP 클라이언트
- `import pandas`, `numpy` (모델 정의에는 불필요)
- `from src.adapters.*`, `from src.infrastructure.*`
- `datetime.now()`, `date.today()` (시점은 항상 파라미터로 주입)

**`src/domain/`에서 허용된 것**:
- Python 표준 라이브러리 (`dataclasses`, `decimal`, `enum`, `typing`, `datetime` 등)
- `pydantic` (모델 검증용)
- `from src.domain.*`, `from src.ports.*` (Protocol만)

**위반 발견 시**: 해당 코드를 작성하지 말고 사용자에게 보고하세요. 어딘가에서 설계가 잘못된 신호입니다.

### 1.2 의존성 주입 (DI)

모든 외부 의존은 생성자 주입:

```python
# ✅ 올바름
class DailyOrchestrator:
    def __init__(
        self,
        broker: BrokerPort,
        market_data: MarketDataPort,
        ...
    ):
        self.broker = broker

# ❌ 금지
class DailyOrchestrator:
    def __init__(self):
        self.broker = KISBroker()  # 직접 생성 금지
```

이유: 테스트 시 Mock으로 갈아끼우기 위함. 백테스트와 실거래의 코드 공유 핵심.

### 1.3 Port/Adapter 패턴

새 외부 시스템 연동 시:
1. `src/ports/`에 Protocol 정의 (또는 기존 Protocol 사용)
2. `src/adapters/<시스템명>/`에 구현
3. 도메인/Use Case는 Protocol만 import

---

## 2. 돈 관련 규칙 (절대적)

### 2.1 Decimal 사용

```python
# ✅ 올바름
from decimal import Decimal
price = Decimal("35000.50")
quantity = Decimal("10")
total = price * quantity

# ❌ 금지
price = 35000.50  # float은 부동소수점 오차 발생
total = price * 10
```

**모든 가격, 수량, 금액은 `Decimal`**. float 사용 시 0.1 + 0.2 = 0.30000000000000004 같은 오차로 잔고 불일치 발생.

### 2.2 통화 명시

```python
# ✅ 올바름
@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str  # "KRW", "USD", "BTC"

# ❌ 금지: 단순 Decimal로 USD인지 KRW인지 알 수 없음
```

서로 다른 통화 연산 시 명시적 환전. 자동 변환 절대 금지.

### 2.3 Decimal 생성 시 string 사용

```python
# ✅ 올바름
Decimal("0.1")

# ❌ 금지 (float 오차가 Decimal에 전파)
Decimal(0.1)  # = Decimal('0.1000000000000000055511151231257827021181583404541015625')
```

---

## 3. 시간 관련 규칙

### 3.1 모든 시간은 UTC

```python
# ✅ 올바름
from datetime import datetime, timezone
now = datetime.now(timezone.utc)

# ❌ 금지 (타임존 정보 없음)
now = datetime.now()
```

표시할 때만 사용자 타임존(KST 등)으로 변환. 저장/계산은 항상 UTC.

### 3.2 도메인에서 현재 시간 조회 금지

```python
# ❌ 금지 (도메인에서)
class SplitStrategy:
    def evaluate(self, position):
        today = date.today()  # 이러면 백테스트 불가능

# ✅ 올바름
class SplitStrategy:
    def evaluate(self, position, today: date):  # 주입받음
        ...
```

이유: 백테스트는 과거 날짜를 주입해야 함. 도메인에서 시계를 읽으면 백테스트와 실거래가 분리됨.

### 3.3 NTP 동기화 가정 금지

시스템 시작 시 NTP 동기화 상태를 검증해야 함. 1초 이상 차이면 거래 시작 거부.

---

## 4. 주문 처리 규칙

### 4.1 idempotency_key 필수

```python
# ✅ 올바름
import uuid
order = OrderRequest(
    idempotency_key=str(uuid.uuid4()),
    ...
)

# 같은 key로 재시도 시 브로커에서 중복 처리 안 함
# DB에서도 동일 key 체크 후 기존 결과 반환
```

**모든 주문에 예외 없이 idempotency_key**. 재시작/재시도 시 중복 주문 방지의 유일한 방법.

### 4.2 지정가 주문만 사용

```python
# ✅ 올바름
order = OrderRequest(
    side=OrderSide.BUY,
    quantity=Decimal("10"),
    target_price=Decimal("35000"),  # 지정가
)

# ❌ 금지: 시장가 주문 (슬리피지 예측 불가)
```

종가 베팅이라 어차피 종가 근처 지정가로 충분합니다.

### 4.3 주문 타임아웃 시 즉시 재시도 금지

```python
# ❌ 절대 금지
try:
    result = broker.place_order(order)
except TimeoutError:
    result = broker.place_order(order)  # 위험! 중복 주문 가능

# ✅ 올바름
try:
    result = broker.place_order(order)
except TimeoutError:
    # PENDING 상태로 DB 저장
    save_pending_order(order)
    # get_order_status(idempotency_key)로 실제 상태 확인 (별도 흐름)
```

### 4.4 부분 체결 처리

부분 체결은 **별도 차수로 인정 안 함**. `split_level`은 100% 체결됐을 때만 증가.

---

## 5. 데이터 검증 규칙

### 5.1 외부 데이터는 항상 검증 후 도메인 진입

```python
# ✅ 올바름 (Adapter에서)
class KISMarketData:
    def get_current_price(self, asset, as_of):
        raw = self._call_api(asset)
        # 검증
        if raw["price"] <= 0:
            raise InvalidPriceError(f"Invalid price: {raw['price']}")
        if raw["high"] < raw["low"]:
            raise DataIntegrityError("high < low")
        # 도메인 모델로 변환
        return Price(asset=asset, value=Decimal(str(raw["price"])), timestamp=...)
```

도메인 모델은 valid한 상태만 가정. 검증은 경계(adapter)에서.

### 5.2 가격 이상치 감지

전일 대비 ±30% 초과 변동은 의심:
- 액면분할/병합인지 확인
- 데이터 오류 가능성
- 의심스러우면 매수 결정 스킵 + 알림

---

## 6. 예외 처리 규칙

### 6.1 예외 분류

```python
# src/domain/exceptions.py 참조

class DomainError(TradingSystemError):
    """정상 흐름의 일부. catch해서 Decision에 기록 후 계속 진행."""
    # 예: InsufficientBalanceError, CapitalAllocationExceededError

class ExternalSystemError(TradingSystemError):
    """외부 시스템 오류. 재시도 또는 스킵."""
    # 예: BrokerConnectionError, MarketDataUnavailableError

class IntegrityError(TradingSystemError):
    """시스템 무결성 위반. 즉시 모든 거래 정지."""
    # 예: StateMismatchError, ClockSkewError
```

### 6.2 예외 처리 패턴

```python
# ✅ 올바름
try:
    self._evaluate_and_execute(asset, today)
except DomainError as e:
    self._log_skip(asset, e)  # 정상 흐름
except ExternalSystemError as e:
    self._handle_external(asset, e)  # 재시도/스킵
# IntegrityError는 catch 안 함 → 위로 전파 → 시스템 정지

# ❌ 금지
try:
    self._evaluate_and_execute(asset, today)
except Exception:  # 너무 광범위
    pass  # 무엇이 실패했는지 모름, 침묵의 실패
```

### 6.3 침묵의 실패 금지

```python
# ❌ 금지
try:
    risky_operation()
except Exception:
    pass

# ❌ 금지
result = risky_operation() or default_value  # None과 0 구분 안 됨

# ✅ 올바름
try:
    result = risky_operation()
except SpecificError as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    raise  # 또는 명시적 처리
```

---

## 7. 테스트 규칙

### 7.1 테스트 작성 의무

새 코드 작성 시 동시에 테스트 작성:
- **Domain 로직**: 단위 테스트 필수, 커버리지 100% 목표
- **Adapter**: 통합 테스트 (Mock 외부 시스템 사용)
- **Use Case**: 통합 테스트 (Mock Port 주입)

### 7.2 테스트 구조

```python
# tests/unit/test_price_drop_strategy.py

class TestPriceDropStrategy:
    def test_first_buy_when_no_position(self):
        # Given
        strategy = PriceDropStrategy()
        config = SplitStrategyConfig(...)

        # When
        decision = strategy.evaluate(
            position=None,
            current_price=Price(value=Decimal("35000"), ...),
            config=config,
            today=date(2026, 4, 29),
        )

        # Then
        assert decision is not None
        assert decision.split_level == 1

    def test_skip_when_drop_insufficient(self):
        ...

    def test_skip_when_max_split_reached(self):
        ...

    # 엣지 케이스
    def test_invalid_price_raises_error(self):
        ...
```

### 7.3 Mock 사용 원칙

- 도메인 로직 테스트: Mock 없이 순수 함수처럼 테스트
- Use Case 테스트: Port를 Mock으로 주입
- Adapter 테스트: 외부 라이브러리만 Mock, 어댑터 로직은 실제 실행

### 7.4 백테스트와 실거래의 동일성 검증

같은 입력으로 백테스트와 페이퍼 트레이딩 결과가 일치해야 함. 불일치 발생 시 어딘가에 시계 의존성 또는 외부 상태 의존성이 있다는 신호.

---

## 8. 로깅 규칙

### 8.1 모든 의사결정은 로그

```python
# ✅ 올바름
decision = Decision(
    timestamp=now,
    asset=asset,
    action="buy_split_2",
    reasoning={
        "current_price": str(current_price.value),
        "avg_price": str(position.avg_price),
        "drop_pct": str(drop_pct),
        "threshold": str(config.drop_threshold_pct),
        "available_balance": str(balance.cash),
    },
    resulting_order_id=order_id,
)
decision_repo.save(decision)
```

`reasoning`에는 **결정에 사용된 모든 입력값**을 JSON으로 보존. 6개월 뒤 디버깅 가능해야 함.

### 8.2 로그 레벨

- `DEBUG`: 개발 시에만, 운영에서 비활성화
- `INFO`: 정상 의사결정, 정상 주문 체결
- `WARNING`: 재시도, 스킵, 비정상 데이터 의심
- `ERROR`: 주문 거부, API 실패, 데이터 누락
- `CRITICAL`: 시스템 무결성 위반, 즉시 대응 필요

### 8.3 민감 정보 로깅 금지

```python
# ❌ 금지
logger.info(f"API key: {api_key}")
logger.info(f"Account number: {account}")

# ✅ 올바름
logger.info(f"API key: {api_key[:4]}***")
```

---

## 9. 설정 관리 규칙

### 9.1 3계층 분리

| 계층 | 위치 | 변경 빈도 | 변경 방식 |
|------|------|----------|----------|
| 알고리즘 | `src/domain/strategies/*.py` | 거의 안 바뀜 | 코드 + 재배포 |
| 파라미터 | `config/strategies.yaml` | 자주 | 파일 수정 + Hot reload |
| 운영 명령 | CLI | 즉시 | `trading skip/pause/halt` |

### 9.2 하드코딩 금지

```python
# ❌ 금지
DROP_THRESHOLD = 7.0  # 코드에 박지 말 것

# ✅ 올바름
config = config_manager.get_strategy_config(asset)
threshold = config.drop_threshold_pct
```

### 9.3 비밀 정보는 환경변수

```python
# ❌ 금지
KIS_API_KEY = "abc123..."

# ✅ 올바름
import os
KIS_API_KEY = os.environ["KIS_API_KEY"]
# .env 파일 사용 (gitignore 필수)
```

---

## 10. 동시성 규칙

### 10.1 단일 프로세스 가정

이 시스템은 **cron 기반 1회성 실행**이 기본:
- 멀티스레드 사용 금지 (필요하면 사용자에게 질문)
- 비동기 사용 금지 (asyncio 등)
- 데몬 형태 운영 안 함

### 10.2 락 파일로 중복 실행 방지

시작 시 PID 파일 또는 DB 락 체크. 이미 실행 중이면 즉시 종료.

### 10.3 DB 트랜잭션 — UnitOfWork 패턴

여러 Repository에 걸친 변경은 `UnitOfWork`로 묶는다. Use Case는 connection을
모르고 UoW의 `commit`/`rollback`만 호출한다. **자동 rollback** (commit 미호출
시 `__exit__`에서)이 안전한 기본값.

```python
# ✅ 올바름 — UoW 컨텍스트
with uow_factory() as uow:
    uow.orders.save(order)
    uow.positions.save(position)
    uow.decisions.save(decision)
    uow.commit()  # 명시 commit. 빠뜨리면 자동 rollback
# 하나라도 실패하면 모두 롤백 (commit 도달 안 함)

# ❌ 금지 — 개별 Repository에 별도 트랜잭션
order_repo.save(order)        # 트랜잭션 1
position_repo.update(position) # 트랜잭션 2 (실패 시 1번은 살아남음)
decision_repo.save(decision)
```

Repository는 단일 SQL 실행만 책임. 트랜잭션 경계는 UoW가 담당한다.
ADR §8.2 참조.

---

## 11. 안전장치 (절대 우회 금지)

### 11.1 Kill Switch

환경변수 `TRADING_HALT=1` 설정 시 모든 거래 즉시 중단:

```python
# 모든 의사결정 시작 전 체크
if os.environ.get("TRADING_HALT") == "1":
    logger.critical("Kill switch activated, exiting")
    sys.exit(0)
```

### 11.2 Reconciliation

매일 시작 시 DB 포지션 vs 브로커 실제 포지션 대조. 불일치 발견 시:
- 자동 수정 절대 금지
- 모든 거래 정지
- 알림 발송
- 사람 개입 대기

### 11.3 자동 catch-up 금지

시스템이 며칠 다운됐다가 재시작 시:
- 누락된 며칠치 의사결정을 자동으로 따라잡지 말 것
- 알림 후 사람이 명시적으로 `--force-run --date YYYY-MM-DD` 명령

### 11.4 손실 한도

종목별 평가손실 한도(`max_loss_pct`) 도달 시:
- 추가 매수 자동 정지
- 사람 개입 대기 (자동 손절 안 함, Phase 0 기준)

---

## 12. Git/PR 규칙

### 12.1 커밋 단위

- 한 커밋에 한 가지 변경
- 도메인 로직 변경과 어댑터 변경은 별도 커밋
- 테스트는 같은 커밋에 포함

### 12.2 커밋 메시지

```
<type>(<scope>): <subject>

<body>
```

type: feat, fix, refactor, test, docs, config
scope: domain, adapter, infra, app, cli

예시:
```
feat(domain): add PriceDropStrategy with split level tracking

- Implements gradual buy on price drops
- Tracks split_level per position (1~7)
- Skips when max_split_per_day reached
```

### 12.3 ADR (Architecture Decision Record)

중요 결정은 `docs/decisions/`에 기록:
- 새 외부 의존성 추가
- 인터페이스 변경
- 알고리즘 변경

#### 12.3.1 ADR 갱신 체크리스트

ADR을 갱신할 때마다 다음을 반드시 수행:

- **이전 사용자 명시 요청 사항 중 미구현 있는지 검색**
  - 검색 키워드: 사용자가 결정한 내용을 정확히 인용한 부분 (예: `entry_dates`, `simulate_timeout_rate`)
  - `grep -r` 또는 코드 + ADR 양쪽 검색
- **누락 발견 시 `§X.0` 형태로 명시 인정 후 진행**
  - 누락 사실, 인정 시점, 재처리 방침을 항목화
  - 단순 사과/넘어가기 금지

이 체크는 다음 결정 라운드 시작 전에 수행하여, 같은 누락이 다음 단계로 전파되지 않도록 한다.

---

## 13. 모르겠을 때 (가장 중요)

### 13.1 추측하지 말 것

다음 상황에서는 코드 작성 중단하고 사용자에게 질문:

- 인터페이스 시그니처가 명세에 없음
- 엣지 케이스 처리 방식이 카탈로그에 없음
- 새 외부 라이브러리 필요
- 도메인 규칙이 모호함
- 기존 코드와 새 코드의 충돌

### 13.2 질문 형식

```
[의문점]
<무엇이 명확하지 않은지>

[옵션]
A) <옵션 1과 trade-off>
B) <옵션 2와 trade-off>

[추천]
<있다면 선호 옵션과 이유>
```

### 13.3 "친절한 추가" 금지

명세에 없는 기능을 "있으면 좋을 것 같아서" 추가하지 말 것:
- 자동 손절
- 매도 로직
- 알림
- UI
- 추가 종목

명세 외 기능은 **반드시 사용자 승인 후**.

---

## 14. Phase별 범위 (현재: Phase 0.9)

### Phase 0 (완료, 2026-05-02)
회고: `docs/retrospectives/phase-0.md`. 결정: ADR 0001.

### Phase 0.5 (완료, 2026-05-03)
- 매도 (`ProfitTargetSell`) + 재진입 (`MovingAverageReentry` D-2 / `HybridTimeBasedReentry` F) 도입
- 결정: ADR 0002. 회고: `docs/retrospectives/phase-0.5.md`. 결과: `docs/retrospectives/phase-0.5-results.md`
- 5-year KOSPI 200 백테스트 결과: H1 ✅ / H2 ❌ / H3 ❌ / H4 ✅ — 게이트 #2 미충족
- 종료 라운드: 옵션 A' (Phase 0.7 직진 — 멀티 종목으로 H2/H3 본질 검증) 채택. ADR 0002 §13 박제.

### Phase 0.7 범위 (시리즈 진행 중)
- KR 거래소 상장 ETF 멀티 종목 (2종목 시작 → 3~5개 확장)
- 자본 배분 정책 비교 (균등 → 역변동성 / 정변동성)
- 종목 간 우선순위 = config 정의 순서 (단순)
- 종목 간 자본 동적 이동 없음 (per-asset budget 고정)
- 매도 정책 default = F (HybridTimeBasedReentry, cooldown=60). D-2 비교 baseline 보존.
- Mock Broker, Mock MarketData 유지 — 위험 zero
- 단계 분리: 0.7.1 (인프라 2종목) → 0.7.2 (배분 정책) → 0.7.3 (종목 다양화). 단계별 회고.
- 결정: ADR 0003. 회고: `docs/retrospectives/phase-0.7.{N}.md` (단계별).

#### Phase 0.7.1 (완료, 2026-05-04)
- 멀티 종목 인프라 (069500 KODEX 200 + 214980 KODEX 단기채권 PLUS), 균등 배분, 정책 동일성 강제
- 5-year KOSPI 200 + 채권 백테스트 결과: H1 ❌ / H2 ❌ / H3 ❌ — 게이트 0/3 FAIL
- 라운드 #5 결정: 옵션 A (Phase 0.7 시리즈 완주 + Phase 0.8/0.9 직교 차원 추가). ADR 0003 §15.5.1 박제.
- 회고: `docs/retrospectives/phase-0.7.1.md`. 결과: `docs/retrospectives/phase-0.7.1-results.md`.

#### Phase 0.7.2 (완료, 2026-05-05) — 자본 배분 정책 비교
- 종목 유지 (069500 + 214980) — 변수 통제 (배분 정책 1 차원만 변경)
- 배분 정책 3 종 비교 결과: EQUAL = baseline 자기 동치 (회귀 invariant 검증 통과) / VOL = 정책 효과 측정 통과 (return 13.38% / MDD -22.50% — 자산군 분산 약화 부산물) / INV_VOL = Sharpe 4.53 단독 ≥ 2/3 미달
- 라운드 #7 결정: 1=(a) Phase 0.7.3 진입 + 2=(iii) H3 임계 정의 명시화 + 3=(γ) 게이트 결과 분리 박제. ADR §17 박제.
- 결정: ADR §16, §17. 회고: `docs/retrospectives/phase-0.7.2.md`. 결과: `docs/retrospectives/phase-0.7.2-results.md`.

#### Phase 0.7.3 (완료, 2026-05-05) — 종목 다양화
- 종목 2 종: 069500 (KODEX 200) + 132030 (KODEX 골드선물(H)) — 채권 대체, 주식 + 골드 분산
- 5-year 백테스트 결과: H1 ✅ 34.37 / H2 ✅ 13.23 / H3 ✅ 0.5255 — **게이트 3/3 PASS** (Phase 0.7 시리즈 첫 명확한 통과)
- 라운드 #9 결정: Phase 0.7 시리즈 정식 종료 + Phase 0.7.4 (부동산) placeholder 보존 + §14.7 γ Phase 0.8+ 보류. ADR 0003 §19 박제.
- 핵심 발견: 종목 조성 (채권 → 골드) 이 정책-자산 부정합 처방의 결정타.
- 결정: ADR 0003 §18, §18.12, §19. 회고: `docs/retrospectives/phase-0.7.3.md`. 결과: `docs/retrospectives/phase-0.7.3-results.md`.

### Phase 0.8 범위 (완료, 2026-05-06) — 매수 패러다임 비교 (단일 sub-step)
- 매수 패러다임 차원 변경 (가치 → 기술적). `SupportLevelStrategy` 신규 + `SupportSlot` (B-1 옵션)
- **박영옥 원전 정신 폐기 아님** — `PriceDropStrategy` 보존, 비교 검증 (yaml `buy_strategy` 분기)
- 보조 지표: `src/domain/indicators/` helper 모듈 (도메인 내부 응집)
- 비교 baseline = Phase 0.7.3 (069500 + 132030, EQUAL, PriceDropStrategy) — 변수 1 차원 (매수 전략만) 통제
- 결정: ADR 0004. 회고: `docs/retrospectives/phase-0.8.{1,}.md`.

#### Phase 0.8.1 (완료, 2026-05-06) — 매수 패러다임 1 차원
- 종목 2 종 (069500 + 132030) + EQUAL + SupportLevelStrategy (slot 1~5)
- 5-year 백테스트 결과: H1 ✅ 0.4188 / H2 ✅ 14.0586 / H3 ❌ 0.2679 — **게이트 2/3 PASS**
- 핵심 발견: SupportLevelStrategy 의 자본 회전 활발화 (+0.09 turnover) + 절대 수익 미세 개선 (+0.83pp)
  vs **MDD -8.27% → -21.28% (-13.01pp) 큰 폭 악화** + Sharpe / Calmar 동반 하락 (위험조정 수익 미달)
- ADR §4.3.3 박제한 whipsaw 위험 가설 발현 — cooldown 무 + indicator-based 트리거 trade-off
- Phase 0.7.2 VOL 정책 결과와 trade-off 패턴 일치 (return/turnover ↑ + MDD/Sharpe ↓)
- 라운드 #11 결정: Phase 0.8 시리즈 종료 + Phase 0.9 직진 + cooldown 도입 거부 (본질적 한계 인정).
  ADR 0004 §7 박제.
- 결정: ADR 0004 §1, §2, §3, §4, §5, §6, §7. 회고: `docs/retrospectives/phase-0.8.1.md`.
  결과: `docs/retrospectives/phase-0.8.1-results.md`. 시리즈 회고: `docs/retrospectives/phase-0.8.md`.

#### Phase 0.8 시리즈 종료 결정 (완료, 2026-05-06) — 라운드 #11
- ADR 0004 §7 박제 — Phase 0.8 시리즈 종료 + Phase 0.9 직진 + H3 본질적 한계 인정
- "PriceDropStrategy + 분산이 본질" 데이터 근거 입증
- SupportLevelStrategy / SupportSlot / indicators 모듈 보존 — Phase 0.9.x 후속 결합 검토 가능

### Phase 0.8에서 명시적으로 제외 (완료 시점)
- Phase 0.8.2 (단기 매매 +3~5%) — ADR §7.2 옵션 b 거부 (H3 FAIL 상태에서 MDD 더 악화 위험)
- Phase 0.8.x (cooldown 도입 / whipsaw 완화) — ADR §7.3 처방 거부 (정체성 약화 + data snooping)
- 멀티 종목 + SupportLevel 조합 — Phase 0.9.x 후속 (ADR 0004 §1.10)
- Phase 0.7.4 (부동산 분산) — ADR 0003 §18.12.4 / §19.3 placeholder 보존
- §14.7 γ (자산별 다른 정책) — ADR 0003 §19.4 / Phase 1+ 보류

### Phase 0.9 범위 (진행 중, 2026-05-06 진입) — 개별 주식 검증

진입 결정 라운드 #12 박제 완료 (2026-05-07) — **ADR 0005 §1**.

- ETF → 개별 주식 (종목 성격 차원). 변수 통제: 종목 차원만 변경
- 인프라 변경: Market enum (KOSPI / KOSDAQ) / listed_at / delisted_at /
  호가 단위 가변 (`src/domain/tick_size.py` helper) / 거래 정지 / 액면분할 (수정 종가)
- 거래세 / 수수료 모델링 = **Phase 1+ 보류** (ADR 0005 §1.13)
- 매수 전략 default = **PriceDropStrategy** drop=5.0% strict (ADR 0005 §1.8)
- 매도 / 재진입 default = ProfitTarget +10% / Hybrid cooldown=60 (Phase 0.7.3 그대로)
- 손절 정책 **미도입** (Phase 0.9 본질 = 인프라 검증). Phase 1 ADR §1 본격 검토
- 후행 편향 단순화 (현재 살아있는 종목, 낙관적 추정 — ADR 0005 §1.6.3)
- SupportLevelStrategy 보존 — Phase 0.9.x 후속 결합 검토 가능
- 비교 baseline = Phase 0.7.3 strict — H1=0.3270 / H2=13.23% / H3=0.5255
- 게이트: ≥ Phase 0.7.3 baseline strict, 통과 ≥ 2/3
- Mock Broker 유지 (Phase 1 KIS API 진입 시점은 Phase 0.9 종료 결정 라운드에서 결정)

#### Phase 0.9.1 (진행 중, 2026-05-07) — 인프라 검증 (2 종)
- 종목: 005930 삼성전자 + 005380 현대차 — Phase 0.7.3 와 동일 종목 수, 변수 통제 strict
- Sub-step (ADR 0005 §1.12 + §3 합병 박제): 0.9.a (ADR 박제) ✅ → 0.9.b (CLAUDE.md
  / roadmap 갱신) ✅ → 0.9.c (사전 검증) ✅ → 0.9.d (Asset 확장 + tick_size helper —
  ADR 0005 §3 박제, 0.9.f 합병) ✅ → 0.9.e (다운로드 일반화) ✅ → ~~0.9.f (폐기,
  0.9.d 합병)~~ → 0.9.g (다운로드 + CSV — ADR 0005 §4) ✅ → **0.9.h (BacktestRunner
  + 회귀 invariant)** → 0.9.i (백테스트 실행) → 0.9.j (결과 분석 + ADR) → 0.9.k
  (회고) → 0.9.l (게이트 판정) → 0.9.m (Phase 0.9.2 진입 결정)

#### Phase 0.9.2 (예정, 0.9.1 결과 후 진입 결정) — 분산 효과 (5 종)
- 종목: 005930 + 005380 + 055550 신한지주 + 097950 CJ제일제당 + 015760 한국전력
- 변수 (vs 0.9.1): 종목 수 (2 → 5) + 분산 효과
- 게이트 = 0.9.1 결과 후 결정 라운드 (0.9.m) 에서 박제

- 결정: ADR 0005 §1 (라운드 #12 박제 완료). 후보 박제: ADR 0003 §15.3 / ADR 0004 §7.4.2.

### Phase 0.9에서 명시적으로 제외 (ADR 0005 §1.13 박제)
- 실제 KIS API 연결 — Phase 1 (진입 결정 시 ADR 0006)
- 손절 로직 — Phase 1+ (H3 거짓 대응, ADR 0002 §12.4.2 + ADR 0005 §1.9)
- 거래세 / 수수료 모델링 — Phase 1+ (ADR 0005 §1.13)
- 텔레그램 알림 — Phase 1
- AI 차단기 — Phase 2
- US 주식 직접 거래소, BTC — Phase 3 / 4
- 환율 처리 — Phase 3
- 종목 간 자본 동적 이동 — Phase 1+ ADR
- 채권 / 단기 예치 (idle cash 활용) — Phase 1+
- 부분 매도 — Phase 1+ (KIS partial fill과 함께)
- 매도 임계치 +15/+20 % 비교 — Phase 1+ (실거래 데이터 확보 후)
- Hot reload — Phase 1+ 검토
- score-based 종목 우선순위 — Phase 1+
- 박영옥 가치주 스타일 자동 식별 — Phase 0.9.x 또는 Phase 1+
- 종목 선정 자동화 — Phase 2+ AI 영역
- 일중 데이터 (분봉 / 틱) — Phase 0.9 일봉만 (pykrx)
- SupportLevelStrategy 코드 변경 — Phase 0.8 박제 보존 (ADR 0004 §7.4.2)
- 멀티 종목 + SupportLevel 결합 — Phase 0.9.x 후속 결정 (ADR 0004 §1.10)
- 그리드 트레이딩 — Phase 0.10+ placeholder (`docs/roadmap.md`, arxiv 2506.11921)

### Phase 1 (예정, 가칭) — KR 주식 실거래 (소액)
- KIS API 어댑터 + 100~500만원 소액 + 차단기 비활성 + 1~2개월 운영
- 결정: ADR 0006 (가칭, 진입 시 박제). 후보 박제: ADR 0003 §11.3 / ADR 0004 §7.

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

## 16. Phase 1 호환성 의식 (Phase 0.9 동안만 적용)

> **조건부 룰**. Phase 0.9 진행 중 Mock 환경 + 개별 주식 인프라 (호가
> 가변 / 거래 정지 / 액면분할 — 거래세 / 수수료는 Phase 1+ 보류) 가정으로
> 코드 작성하되, Phase 1 에서 KIS API 실거래 + 손절 진입 예정이므로
> 다음을 의식한다. Phase 1 시작 시 본 §16 은 제거 또는 갱신.
>
> 선행: Phase 0.5 동안 (Phase 0.7 호환성) → Phase 0.7 동안 (Phase 1
> 호환성) → Phase 0.8 동안 (Phase 0.9 / Phase 1 호환성) → 본 §16
> (Phase 1 호환성, Phase 0.9 동안). ADR 0004 §7 (라운드 #11 — Phase
> 0.8 종료) 박제 후속 → ADR 0005 §1 (라운드 #12 — Phase 0.9 진입
> 결정) 박제 후속 갱신 (2026-05-07).

### 16.1 패턴 (의식 — 코드 추가는 금지)

**Phase 1 의식 (기존 Phase 0.7 / 0.8 박제 정신 그대로)**:
1. **종목별 reconciliation** — 종목별 독립 reconcile 메서드 골격 유지.
   한 종목 mismatch 발견 시 전체 정지 (ADR 0003 §8.6); Phase 1 에서
   자산별 격리 정지로 분기 가능한 구조.
2. **종목별 잔고 분리 의식** — 단일 kill switch 가정 유지하되, 자산
   격리 정지 분기 가능한 `AssetContext` 기반 데이터 흐름.
3. **partial fill 차단 유지** — KIS 는 partial fill 발생 가능. ADR
   0002 §3 (partial fill 차단) 정신 그대로. Phase 1 에서 partial fill
   처리 ADR 신규 박제.
4. **sell strategy 단일 가정** — `ProfitTargetSell` 단일 sell strategy
   가정 유지. 손절 (StopLoss) 은 Phase 1 ADR 에서 sell strategy 추가
   형태로 도입.
5. **OrderRequest / OrderResult 시그니처** — KIS API 응답에 partial
   fill / 슬리피지 / 수수료 / 세금 필드 가능. Phase 0.9 에서 Mock 응답
   그대로 (Phase 0.9 본질 = 개별 주식 인프라 시뮬레이션, KIS API 는
   Phase 1) — 시그니처가 Phase 1 KIS 응답을 수용 가능하도록 의식.

### 16.2 Phase 0.9 본질 (ADR 0005 §1 박제 결과)

Phase 0.9 의 본질적 변경은 **ADR 0005 §1 박제 완료 (라운드 #12,
2026-05-07)**. sub-step 분리 적용 (§16.3) — 각 본질은 박제된 sub-step
에서만 작성.

1. **호가 단위 가변** — `src/domain/tick_size.py` helper 모듈
   (`calculate_krx_stock_tick_size(price) → Decimal`). `Asset.round_to_tick`
   이 `asset_class` 분기 — KR_ETF 단일 tick_size 그대로, KR_STOCK 은
   helper 호출. **sub-step 0.9.d (0.9.f 합병) 에서 작성** (ADR 0005 §1.7.3
   + §3 박제 — 라운드 #13).
2. **Asset 모델 확장** — `Market` enum 신규 (KOSPI / KOSDAQ),
   `listed_at` (필수) + `delisted_at` (옵션, Phase 0.9 미사용)
   추가. **sub-step 0.9.d 에서만 작성** (ADR 0005 §1.7.1 / §1.7.2).
3. **거래 정지 / 액면분할** — 거래 정지 = `SkipReason.MARKET_DATA_UNAVAILABLE`
   재사용 (백테스트 OHLCV 없음). 액면분할 = pykrx `adjusted=True` 수정 종가
   (도메인 처리 zero). **sub-step 0.9.e / 0.9.g 에서만 작성** (ADR 0005
   §1.7.4).
4. **거래세 + 수수료 모델링** — **Phase 1+ 보류** (Phase 0.9 미도입).
   `OrderResult.tax` / `OrderResult.commission` 필드 추가 금지 — Phase 1
   ADR 에서 KIS 응답과 함께 박제 (ADR 0005 §1.13).
5. **개별 주식 데이터 가용성** — 5-year 백테스트 가능 종목 (상장일 ≤ 2019)
   + 거래 정지 / 액면분할 이력 + lookback 충분성. Phase 0.9.1 = 005930 +
   005380 / Phase 0.9.2 = + 055550 + 097950 + 015760. **sub-step 0.9.c
   에서만 사전 검증** (ADR 0005 §1.6.2).

### 16.3 금지 (Phase 0.9 동안 작성하면 안 되는 것)

**Phase 1 그대로**:
- ❌ KIS API 어댑터 코드 (BrokerPort / MarketDataPort 실 구현)
- ❌ 손절 정책 코드 (avg_price 기준 -X% 일괄 매도)
- ❌ 텔레그램 알림 코드
- ❌ AI 차단기 / RuleBasedSignal 코드 (NullSignal 유지)
- ❌ 환율 처리 코드 (KR 거래소 KRW 결제 전제)
- ❌ 종목 간 자본 동적 이동 코드 (ADR 0003 §6.1)
- ❌ 채권 / 단기 예치 (idle cash 활용) 코드
- ❌ partial fill 처리 코드 (Phase 0.9 동안 차단 유지)
- ❌ 부분 매도 (slot 내 50%) 코드
- ❌ 매도 임계치 +15/+20 % 비교 backtest (Phase 1+, ADR 0002 §12.4.1)
- ❌ score-based 종목 우선순위 코드
- ❌ Hot reload 코드
- ❌ "추후 Phase 1 확장 가능하게" 만든 unused parameter

**Phase 0.9 본질 (ADR 0005 §1 박제 완료, sub-step 분리 적용 — §3 합병 박제 후속)**:
- 🔒 호가 가변 코드 (`src/domain/tick_size.py`) — **sub-step 0.9.d (0.9.f 합병) 에서 작성** (ADR 0005 §1.7.3 + §3 박제 — 라운드 #13)
- 🔒 Asset 모델 확장 (`Market` enum / `listed_at` / `delisted_at`) — **sub-step 0.9.d 에서만 작성** (ADR 0005 §1.7.1 / §1.7.2)
- 🔒 데이터 다운로드 일반화 + 액면분할 (수정 종가) — **sub-step 0.9.e / 0.9.g 에서만 작성** (ADR 0005 §1.7.4)
- 🔒 개별 주식 종목 추가 (asset_factory) — **sub-step 0.9.d 에서만 작성**. Phase 0.9.1 = 005930 + 005380, Phase 0.9.2 = + 055550 + 097950 + 015760 (ADR 0005 §1.6.2)
- ❌ 거래세 / 수수료 OrderResult 필드 — Phase 1+ 보류 (ADR 0005 §1.13)
- ❌ 거래 정지 처리 코드 (corp_action table 등) — ADR 0005 §1.7.4 박제 = `SkipReason.MARKET_DATA_UNAVAILABLE` 재사용. 별도 코드 추가 금지

**Phase 0.8 보존 (변경 금지, ADR 0004 §7.4.2)**:
- ❌ `SupportLevelStrategy` 코드 변경 — Phase 0.8 박제 보존
- ❌ `SupportSlot` / `src/domain/indicators/` 모듈 변경 — 보존
- ❌ ADR 0004 신규 §X 추가 (Phase 0.8 박제 후속이 아닌 경우) — Phase
  0.9 결정은 ADR 0005 에 박제
- ❌ cooldown 도입 (SupportLevelStrategy + cooldown) — ADR 0004 §7.3.2
  거부 박제 (data snooping 위험). Phase 0.9.x / Phase 1+ 어느 시점에
  검토 시 §7.3.2 인용 후 결정

**Phase 0.9 후속 (sub-step 미박제)**:
- ❌ Phase 0.7.4 (부동산 분산) 코드 (ADR 0003 §18.12.4 / §19.3 placeholder
  보존)
- ❌ §14.7 γ (자산별 다른 정책) 코드 (ADR 0003 §19.4 보류)
- ❌ 멀티 종목 + SupportLevel 결합 코드 (ADR 0004 §1.10 — Phase 0.9.x
  후속 결정)
- ❌ `PriceDropStrategy` 변경 코드 (회귀 invariant 보존)

→ 모두 명시된 후속 Phase / sub-step 에서 사용자와 명시적 결정 후 작성.

### 16.4 의심 시 가이드

Mock 환경 + Phase 0.7.3 baseline (069500 + 132030, EQUAL,
PriceDropStrategy) 비교 가정 유지. Phase 0.9 본질 (호가 가변 / 거래세
등) 은 ADR 0005 박제 후 작성. `# Phase 1 에서 KIS API / 손절 시 검토`
또는 `# ADR 0005 박제 후 호가 가변 처리` 주석 추가. 사용자 확인 없이
호가 가변 / 거래세 / KIS API / 손절 / 텔레그램 인터페이스 짜기 금지
(CLAUDE.md §13.3 "친절한 추가 금지" 정신).

### 16.5 Phase 0.9 ADR 0005 + Phase 1 ADR 0006 트리거 항목

#### Phase 0.9 ADR 0005 §1 박제 결과 (라운드 #12, 2026-05-07)

ADR 0005 §1 박제 완료 — 다음 결정으로 박제됨:

1. 종목 후보 = 005930 + 005380 (Phase 0.9.1, 인프라 검증) → +
   055550 + 097950 + 015760 (Phase 0.9.2, 분산 효과). 다양 업종
   (옵션 3) + 단계적 (옵션 d). ADR 0005 §1.6.1 / §1.6.2.
2. 호가 단위 가변 = `src/domain/tick_size.py` helper 모듈
   (`Asset.round_to_tick` asset_class 분기). ADR 0005 §1.7.3. **sub-step
   = 0.9.d (0.9.f 합병)** — ADR 0005 §3 박제 (라운드 #13).
3. 거래 정지 = `SkipReason.MARKET_DATA_UNAVAILABLE` 재사용 (백테스트
   OHLCV 없음) / 액면분할 = pykrx `adjusted=True` 수정 종가 (도메인
   처리 zero). ADR 0005 §1.7.4.
4. 거래세 / 수수료 모델링 = **Phase 1+ 보류** (Phase 0.9 미도입,
   `OrderResult.tax` / `commission` 필드 추가 금지). ADR 0005 §1.13.
5. 백테스트 / 페이퍼 / 실거래 동일성 (CLAUDE.md §7.4) = sub-step 0.9.h
   에서 Phase 0.7.3 회귀 invariant 재실행으로 검증.
6. Phase 1 KIS API 진입 시점 = Phase 0.9 종료 결정 라운드에서 결정
   (Mock 유지). ADR 0005 §1.13.
7. SupportLevelStrategy + 개별 주식 결합 = Phase 0.9.x 후속 (보존,
   ADR 0004 §7.4.2 / §1.10).
8. 손절 정책 = **Phase 0.9 미도입** (변수 통제 strict). Phase 1 ADR §1
   본격 검토 (ADR 0002 §12.4.2 H3 거짓 대응). ADR 0005 §1.9.
9. 후행 편향 = 단순화 (현재 살아있는 종목, 낙관적 추정 명시). Phase 1+
   정교화 보류. ADR 0005 §1.6.3 / §1.10.

#### Phase 1 ADR 0006 (가칭) 트리거 항목 (ADR 0003 §11.3 인용)

Phase 0.9 종료 후 Phase 1 ADR 박제 시 다뤄질 결정:

1. KIS API 어댑터 (BrokerPort / MarketDataPort 구현)
2. 손절 정책 — H3 거짓 대응 (ADR 0002 §12.4.2)
3. 텔레그램 알림 (의사결정 / 매도 / Reconciliation 불일치)
4. 종목별 vs 전체 kill switch / 자산 격리 정지 (ADR 0003 §8.6 후속)
5. partial fill 처리 ADR
6. 모의투자 → 실거래 전환 게이트
7. 매도 임계치 +15 / +20 % 비교 backtest (ADR 0002 §12.4.1 보류)
8. 종목별 다른 정책 허용 여부 (ADR 0003 §7.3 후속, §19.4 보류)
9. SupportLevelStrategy + cooldown 도입 검토 (ADR 0004 §7.3.2 인용 후
   결정)

---

*이 파일은 살아있는 문서입니다. 운영 중 발견된 새 규칙은 추가하세요.*
*마지막 업데이트: 2026-05-07 (§14 — sub-step 0.9.d / 0.9.e / 0.9.g 완료 표기 갱신, ADR 0005 §4 박제 후속)*