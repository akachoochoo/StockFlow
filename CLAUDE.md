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
[Research overlay (5th ring, outermost)]
        ↓ outer→inner read OK
[Frameworks] → [Adapters] → [Use Cases] → [Domain]
의존성은 항상 안쪽으로. 반대 방향 절대 금지.
```

**`src/domain/`에서 금지된 import**:
- `import sqlite3`, `sqlalchemy`, 기타 DB 라이브러리
- `import requests`, `httpx`, 기타 HTTP 클라이언트
- `import pandas`, `numpy` (모델 정의에는 불필요)
- `from src.adapters.*`, `from src.infrastructure.*`
- `from src.research.*` (research overlay 는 outermost — domain 이 import 하면 안 됨)
- `datetime.now()`, `date.today()` (시점은 항상 파라미터로 주입)

**`src/domain/`에서 허용된 것**:
- Python 표준 라이브러리 (`dataclasses`, `decimal`, `enum`, `typing`, `datetime` 등)
- `pydantic` (모델 검증용)
- `from src.domain.*`, `from src.ports.*` (Protocol만)

**`src/research/` (5th ring, outermost, Phase 0.11.a 신규 — ADR 0007 §1.6)**:

Research overlay — 박제 / 실험 / Phase 1 진입 전 검증용 격리 네임스페이스.

규칙:
- `src/research/**` 는 inner ring (`src/{domain,ports,use_cases,application,adapters,cli,infrastructure}/**`) 을 **읽기 OK** (outer→inner read).
- Inner ring 7개 (`adapters / application / cli / domain / infrastructure / ports / use_cases`) 에서 `from src.research.*` 또는 `import src.research.*` **FORBIDDEN**.
- 강제: `bash scripts/check_namespace.sh` (D11 plain grep — dep 추가 zero).
- `python -m src.research.<...>` CLI 진입은 ring boundary 위반 아님 (terminal 진입점).
- Export 정책: `src/research/**/__init__.py` 는 underscore-prefix private only (`__all__ = []`).
- Lifecycle: 각 research overlay 는 종료 sub-step 에서 lifecycle (archive / promote / abandon) 결정 박제.

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

## 14. Phase별 범위 (현재: Phase 0.11.e 완료, Phase 1 진입 ready)

> 완료 phase 의 sub-step / 결정 / 게이트 결과는 ADR (`docs/decisions/adr-NNNN-*.md`)
> + 회고 (`docs/retrospectives/phase-N.N.md`) + `docs/roadmap.md` 가 정본.
> 이 섹션은 현 상태 + 진행 중 phase + 다음 phase 만 유지. 완료 phase 상세는
> 정본에서 인용하고 여기에 다시 옮겨 적지 말 것.

### 현 상태 (2026-05-17)

- Phase 0.10 시리즈 (0.10 ~ 0.10.bb) 정식 종료 — 라운드 #22 (2026-05-11, ADR 0006 §18).
- **Phase 0.11.a** (DGT Research-Namespace Overlay) 정식 종료 — 라운드 #23 (2026-05-12, ADR 0007 §3). G1+G3+G4 PASS / G2 INFORMATIONAL FAIL (R1 일봉 ≠ 분봉). D10 = archive. DGT registry 미합류.
- **Phase 0.11.b** (DGT Parameter Tuning & Sensitivity Analysis) 정식 종료 — 라운드 #24 (2026-05-13, ADR 0008 §3). G1+G3+G4 PASS / G2 INFORMATIONAL FAIL (D11 DSR 0/95 구조적 unattainable). D10 = archive 확정 (supersede 없음). DGT registry 미합류 유지.
- **Phase 0.11.c** (Strategy-Specific Backtest Visualization Renderers) 정식 종료 — 라운드 #25 (2026-05-13, ADR 0009 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = permanent.
- **Phase 0.11.d** (Asset-Specific Strategy Differentiation Diagnosis & Design) 정식 종료 — 라운드 #26 (2026-05-13, ADR 0010 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = deferred reference. 본질 = *분석 phase 의 분석 phase*. D11 AND-gate 4/4 충족 — 후속 결정 라운드 진입 자격 완성.
- **Phase 0.11.e** (Dynamic Adjustment Proposal Engine L2/L3) 정식 종료 — 라운드 #27 (2026-05-14, ADR 0011 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = 5th ring 영구 유지 (D13). 신규 5th ring `src/research/dynamic_adjustment/` 10 파일 (~1403 LOC) + 141 tests (regression zero). §1.6 Design Contract 6 invariant **측정 가능 verification** + D14 structural constraints (12주 / ±30% / cooldown) + D15 governance 박제. **Phase 1 진입 ready 선언** — ADR 0012 D16 (ii) 5/6 충족 (잔여 = paper trading + NTP).
- **Phase 0.11.f** (DGT Paper-Faithful + Adaptive Hybrid + Multi-Asset Portfolio) 정식 종료 — 라운드 #28 (2026-05-15, ADR 0013 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = 5th ring 영구 (permanent-research-only). 4 runner (dynamic/adaptive/paper/paper_adaptive) + multi-asset portfolio B&H 벤치마크. 핵심 발견: **MDD 14-16% 일관성** (시장 regime/종목 수 무관) + Hyb-Daily 최적 DGT 구성 + 상승장 B&H 압도적 우위 (DGT 구조적 한계). 75 new tests (173 total DGT tests), inner ring 변경 zero.
- **Phase 0.11.g** (DGT Rebalancing Alpha — Core-Satellite + Asymmetric Grid) 정식 종료 — 라운드 #29 (2026-05-17, ADR 0014 §3). G1 PASS / **G2 FAIL** (H1 alpha ≤ 0, H2 monotonic). Lifecycle = 5th ring 영구 (permanent-research-only). Core-Satellite runner + Asymmetric Grid runner + 16-config sweep CLI. 핵심 발견: **리밸런싱 알파 없음** (bull -6~-12%, bear 근소 음수) + 비대칭 grid 하락장 MDD 23-25% (18% hard stop 초과) + Phase 1 권고: 정적 배분, DGT = MDD 방어 전용. 28 new tests (1551 total), inner ring 변경 zero.
- Phase 1 진입 결정 대기.

### 완료 phase 인덱스 (정본 = ADR / 회고)

| Phase | 종료일 | 본질 | 결과 | ADR | 회고 |
|-------|--------|------|------|-----|------|
| 0     | 05-02 | MVP | — | 0001 | phase-0.md |
| 0.5   | 05-03 | 매도 + 재진입 | H1/H4 ✅ H2/H3 ❌ | 0002 | phase-0.5.md |
| 0.7.1 | 05-04 | ETF 멀티 (KOSPI+채권) | 게이트 0/3 | 0003 §15 | phase-0.7.1.md |
| 0.7.2 | 05-05 | 배분 정책 비교 (EQ/VOL/INV_VOL) | 1/3 부분 | 0003 §16,§17 | phase-0.7.2.md |
| 0.7.3 | 05-05 | 종목 다양화 (주식+골드) | **3/3 PASS** | 0003 §18,§19 | phase-0.7.3.md |
| 0.8.1 | 05-06 | 매수 패러다임 (SupportLevel) | 2/3 (H3 ❌, MDD -21%) | 0004 | phase-0.8.1.md |
| 0.9.1 | 05-07 | 개별 주식 인프라 (2 종) | 2/3 (H3 ❌) | 0005 §1~§7 | phase-0.9.1.md |
| 0.9.2 | 05-08 | 분산 효과 (5 종 업종 분산) | 2/3 (H3 ❌, MDD -37%) | 0005 §8~§11 | phase-0.9.2.md |
| 0.10  | 05-08 | Backtest Reporting (TradeView / Renderer / DrawdownEpisode) | AC 5/5 | 0006 §1~§13 | phase-0.10.md |
| 0.10.x | 05-09 | Episode HTML 가독성 (포매터 / KPI / cycle pairing) | AC 10/10 | 0006 §14 | analysis |
| 0.10.y | 05-09 | Chart legend + StrategyInfo | AC 12/12 | 0006 §15 | analysis |
| 0.10.z | 05-09 | Slot annotation injection | AC 12/12 | 0006 §16 | analysis |
| 0.10.aa | 05-09 | Per-symbol chart panels | AC 14/14 | 0006 §17 | analysis |
| 0.10.bb | 05-11 | Reporting cleanup (_INT_KEYS / Sharpe-Calmar) | AC 21/21 | 0006 §18 | phase-0.10-analysis.md |
| 0.11.a | 05-12 | DGT Research-Namespace Overlay (`src/research/` 5th ring + KoreanMarketCostModel + 일봉 prototype runner informational) | G1+G3+G4 PASS / G2 INFORMATIONAL FAIL (R1 — 일봉 ≠ 분봉) / D10 = archive / DGT registry 미합류 | 0007 §1~§3 | phase-0.11.a.md + phase-0.11.a-comparison.md |
| 0.11.b | 05-13 | DGT Parameter Tuning & Sensitivity Analysis (WFO grid 95×5-fold + DSR Bailey-2014 + perturbation + PBO informational) | G1+G3+G4 PASS / G2 INFORMATIONAL FAIL (D11 AND-gate (b) DSR 0/95 구조적 unattainable) / D10 archive 확정 / Best n=11/k=3%/m=1 OOS Sharpe 2.27 → Phase 1 ADR 0012 분봉 DGT 근거 | 0008 §1~§3 | phase-0.11.b.md + sensitivity-heatmap.md + d11-trigger-judgment.md |
| 0.11.c | 05-13 | Strategy-Specific Backtest Visualization Renderers (5th ring `src/research/visualization/` Protocol + DGT renderer + comparison orchestration + CLI + figure 박제) | **게이트 4/4 PRIMARY PASS** / Lifecycle = permanent / 069500 5y figure 박제 (B&H +2.1M / 7split +1.34M / DGT +617K KRW) | 0009 §1~§3 | phase-0.11.c.md + figures/phase-0.11.c/*.png |
| 0.11.d | 05-13 | Asset-Specific Strategy Differentiation Diagnosis & Design (분석 phase 의 분석 phase — 코드 zero, 박제 only) | **게이트 4/4 PRIMARY PASS** / Lifecycle = deferred reference / D11 AND-gate 4/4 충족 (후속 라운드 진입 자격 완성) / "구조는 있지만 정책 게이트로 차단" 발견 (`per_asset_strategy_overrides` + `AssetContext` 기존 구현) | 0010 §1~§3 | phase-0.11.d.md + analysis/phase-0.11.d-{current-structure-diagnosis,coupling-model-candidates}.md |
| 0.11.e | 05-14 | Dynamic Adjustment Proposal Engine L2/L3 (5th ring `src/research/dynamic_adjustment/` Proposal 4-state 머신 + ProposalHistory D14 + TriggerEvaluator + CLI + ADR template scaffolding) | **게이트 4/4 PRIMARY PASS** / Lifecycle = 5th ring 영구 (D13) / §1.6 Design Contract 6 invariant 측정 가능 verification + D14 structural constraints + D15 governance 박제 / **Phase 1 진입 ready 선언** (ADR 0012 D16 (ii) 5/6 충족) | 0011 §1~§3 | phase-0.11.e.md |
| 0.11.f | 05-15 | DGT Paper-Faithful + Adaptive Hybrid + Multi-Asset Portfolio (4 runner + multi-asset B&H 벤치마크 + MDD 14-16% 일관성 발견 + Hyb-Daily 최적 DGT 구성 결론 + 상승장 B&H 구조적 우위 박제) | **게이트 4/4 PRIMARY PASS** / Lifecycle = 5th ring 영구 (permanent-research-only) / 75 new tests (173 total DGT) / inner ring 변경 zero / D1~D10 (3 accepts, 3 invalidations, 4 operational) | 0013 §1~§3 | phase-0.11.f.md |
| 0.11.g | 05-17 | DGT Rebalancing Alpha (Core-Satellite B&H+DGT + Asymmetric Grid + 16-config sweep) | G1 PASS / **G2 FAIL** (H1 alpha ≤ 0, H2 monotonic, H3 MDD breach) / Lifecycle = 5th ring 영구 / 28 new tests (1551 total) / inner ring 변경 zero | 0014 §1~§3 | phase-0.11.g.md |

**핵심 학습** (Phase 0.7 ~ 0.9, ADR 0005 §9.6.2 박제):
**자산군 분산 = H3 회복의 충분 조건** (3 회 반복 검증). 단일 자산군 (전부 주식
/ 전부 채권) 은 분산 효과 약화 → H3 FAIL 패턴. Phase 0.7.3 (주식+골드) =
시리즈 첫 3/3 PASS. "PriceDropStrategy + 분산이 본질" 정신 박제.

### Phase 1 (예정, 가칭) — KR 주식 실거래 (소액)

- KIS API 어댑터 + 100~500만원 소액 + 차단기 비활성 + 1~2개월 운영
- 결정: **ADR 0012** (ralplan #28, commit `e066554` 박제 — 재번호 history: 이전 가칭 ADR 0007/0008 stale, ADR 0011 §1.9 + §3.5 R7 mitigation 정합). 후보 박제: ADR 0003 §11.3 / ADR 0004 §7 / ADR 0005 §10.6.3
- 트리거 항목: §16.4 참조

### Phase 1 진입 전 작성 금지 (통합 목록)

- KIS API 어댑터 (BrokerPort / MarketDataPort 실 구현) — Phase 1
- 손절 정책 (avg_price 기준 -X% 매도) — Phase 1 ADR §1 (ADR 0005 §1.9)
- 텔레그램 알림 — Phase 1
- AI 차단기 / RuleBasedSignal — Phase 2 (NullSignal 유지)
- 거래세 / 수수료 모델링 (`OrderResult.tax` / `commission` 필드 추가) — Phase 1+ (ADR 0005 §1.13)
- 환율 처리 — Phase 3
- US 주식 직거래, BTC — Phase 3 / 4
- 종목 간 자본 동적 이동 — Phase 1+ ADR (ADR 0003 §6.1)
- 채권 / 단기 예치 (idle cash 활용) — Phase 1+
- partial fill 처리 — Phase 1 (현재 차단 유지, ADR 0002 §3 정신)
- 부분 매도 (slot 내 50%) — Phase 1+
- 매도 임계치 +15 / +20 % 비교 backtest — Phase 1+ (ADR 0002 §12.4.1)
- score-based 종목 우선순위 / Hot reload — Phase 1+
- 종목별 다른 정책 (자산별 다른 정책) — Phase 1+ (ADR 0003 §19.4 / ADR 0004 §7.4.2 보류)
- SupportLevelStrategy + cooldown — Phase 0.9.x / Phase 1+ (ADR 0004 §7.3.2 거부 박제 인용 필수)
- 멀티 종목 + SupportLevel 결합 — Phase 0.9.x 후속 (ADR 0004 §1.10)
- Phase 0.7.4 (부동산 분산) — placeholder 보존 (ADR 0003 §18.12.4 / §19.3)
- 그리드 트레이딩 — Phase 0.11.a 완료 (2026-05-12, ADR 0007 §3, D10 = archive). 분봉 DGT 재검토 = Phase 1 ADR 0012 진입 후 별도 결정 라운드.
- 종목 선정 자동화 / 박영옥 가치주 자동 식별 — Phase 2+
- 일중 데이터 (분봉 / 틱) — Phase 0 ~ 0.10 = 일봉 (pykrx) only
- 보존 (변경 금지, 회귀 invariant): `PriceDropStrategy` / `SupportLevelStrategy` /
  `SupportSlot` / `src/domain/indicators/` / Phase 0.10 reporting layer
  (TradeView / DrawdownEpisode / Renderer Protocol / SevenSplit slot palette /
  StrategyInfo / risk_metrics) — sub-step 박제 후 정본은 ADR 0004 §7.4.2 +
  ADR 0006 §3~§18
- "추후 Phase 1 확장 가능하게" 만든 unused parameter — CLAUDE.md §13.3

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

## 16. Phase 1 호환성 의식 (분석 phase + Phase 1 진입 전까지 적용)

> **조건부 룰**. Phase 0.10 시리즈 (0.10 ~ 0.10.bb) 정식 종료 (라운드 #22,
> ADR 0006 §18 박제, 2026-05-11) 후 사용자 분석 phase 동안 본 §16 적용.
> Phase 1 진입 결정 보류 — 그동안 reporting layer 외 코드 변경 zero +
> Phase 1 호환성 의식 유지. Phase 0.11 결정은 다음 session.
>
> 선행 phase 별 의식은 각 phase 의 ADR (0002 ~ 0006) 에 박제. 본 §16 은
> Phase 1 진입까지의 _현재_ 의식만 유지.

### 16.1 패턴 (의식 — 코드 추가는 금지)

1. **종목별 reconciliation** — 종목별 독립 reconcile 메서드 골격 유지.
   한 종목 mismatch 발견 시 전체 정지 (ADR 0003 §8.6); Phase 1 에서
   자산별 격리 정지로 분기 가능한 구조.
2. **종목별 잔고 분리 의식** — 단일 kill switch 가정 유지하되, 자산 격리
   정지 분기 가능. `AssetContext` (`src/use_cases/asset_context.py:37-57`)
   **기존 구현 활용 path** (ADR 0010 §3.7 발견 정합): `composition.py:230-243`
   단일 strategy instance broadcast 해제 + `yaml_strategy_config_loader.py:157-201`
   `_check_policy_uniformity` 완화. ADR 0010 §1.3 D3 (ii) AssetContext
   후보 정합 (sub-step 0.11.d.3, commit `01b3867`). 정정 history: 2026-05-11
   박제 시 "코드 추가 금지" 의식 → ADR 0010 §3.7 옵션 Z 권고 → 본 정정
   (Phase 0.11.e.5 follow-up commit B, 2026-05-14).
3. **partial fill 차단 유지** — KIS 는 partial fill 발생 가능. ADR 0002
   §3 (partial fill 차단) 정신 그대로. Phase 1 에서 partial fill 처리
   ADR 신규 박제.
4. **sell strategy 단일 가정** — `ProfitTargetSell` 단일 sell strategy
   가정 유지. 손절 (StopLoss) 은 Phase 1 ADR 에서 sell strategy 추가
   형태로 도입.
5. **OrderRequest / OrderResult 시그니처** — KIS API 응답에 partial fill
   / 슬리피지 / 수수료 / 세금 필드 가능. Mock 응답 그대로 (Phase 1 KIS
   API 진입 시점은 Phase 1 ADR) — 시그니처가 Phase 1 KIS 응답을 수용
   가능하도록 의식.

### 16.2 작성 금지

§14 "Phase 1 진입 전 작성 금지 (통합 목록)" 참조. 완료 sub-step
(Phase 0.7 ~ 0.10.bb) 의 🔒 작성 경계 / ❌ 거부 결정은 ADR 0003 ~ 0006
박제가 정본 — 인용 시 해당 ADR 직접 참조:

- Phase 0.7 박제 → ADR 0003 (§15 ~ §19)
- Phase 0.8 박제 (SupportLevel 보존 + cooldown 거부) → ADR 0004 §7
- Phase 0.9 박제 (개별 주식 인프라 + 자산군 분산 일반화) → ADR 0005
- Phase 0.10 박제 (reporting layer + 가독성 + per-symbol + cleanup) → ADR 0006 §3 ~ §18

### 16.3 의심 시 가이드

Mock 환경 + Phase 0.7.3 baseline (069500 + 132030, EQUAL,
PriceDropStrategy) 비교 가정 유지. 사용자 확인 없이 호가 가변 / 거래세
/ KIS API / 손절 / 텔레그램 인터페이스 짜기 금지 (CLAUDE.md §13.3
"친절한 추가 금지" 정신). 검토 필요한 영역에는 `# Phase 1 ADR 박제 후
검토` 주석 추가.

### 16.4 Phase 1 ADR 0012 트리거 항목

> 재번호 history: 이전 가칭 = ADR 0007 (Phase 0.11.a DGT 점유로 stale)
> → ADR 0008 (Phase 0.11.b DGT tuning 점유로 stale) → **ADR 0012**
> (ralplan #28, commit `e066554` 박제). 본 §16.4 재번호 정정 = Phase
> 0.11.e.5 follow-up commit (A), ADR 0011 §1.9 + §3.5 R7 mitigation 정합
> (2026-05-14).

Phase 1 ADR 박제 시 다뤄질 결정 (ADR 0003 §11.3 / ADR 0005 §10.6.3 인용):

1. KIS API 어댑터 (BrokerPort / MarketDataPort 구현)
2. 손절 정책 — H3 거짓 대응 (ADR 0002 §12.4.2)
3. 텔레그램 알림 (의사결정 / 매도 / Reconciliation 불일치)
4. 종목별 vs 전체 kill switch / 자산 격리 정지 (ADR 0003 §8.6 후속)
5. partial fill 처리 ADR
6. 모의투자 → 실거래 전환 게이트
7. 매도 임계치 +15 / +20 % 비교 backtest (ADR 0002 §12.4.1 보류)
8. 종목별 다른 정책 허용 여부 (ADR 0003 §7.3 / §19.4 보류)
9. SupportLevelStrategy + cooldown 도입 검토 (ADR 0004 §7.3.2 거부 박제 인용 후 결정)

---

*이 파일은 살아있는 문서입니다. 운영 중 발견된 새 규칙은 추가하세요.*
*마지막 업데이트: 2026-05-14 (Phase 0.11.e 완료 박제 + Phase 1 진입 ready 선언 — §14 현 상태 + 인덱스 갱신, ADR 0011 §1~§3 정본 인용. **§16.4 / §16.1 항목 #2 정정은 별도 follow-up commits 영역** — 본 commit fold 금지, ADR 0011 §3.5 R7 mitigation 정합)*

