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

### 10.3 DB 트랜잭션

여러 테이블 동시 변경 시 트랜잭션 사용:

```python
# ✅ 올바름
with db.transaction():
    order_repo.save(order)
    position_repo.update(position)
    decision_repo.save(decision)
# 하나라도 실패하면 모두 롤백
```

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

## 14. Phase별 범위 (현재: Phase 0)

### Phase 0 범위
- KR 인덱스 ETF 단일 종목 (KODEX 200)
- PriceDropStrategy 1개
- Mock Broker, Mock MarketData
- NullSignal (차단기 없음)
- 백테스트 + 페이퍼 트레이딩
- SQLite 로컬 DB

### Phase 0에서 명시적으로 제외
- 실제 KIS API 연결
- AI 차단기
- US 주식, BTC
- 매도 로직 (분할 매수만)
- 텔레그램 알림 (Console만)
- 멀티 종목
- 환율 처리
- Hot reload (정적 설정만)

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
*마지막 업데이트: 2026-04-29*