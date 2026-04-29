# Roadmap

## 현재 Phase: Phase 0 (종이 거래 시뮬레이터)

### 목표
실제 API 연결 없이 도메인 로직 검증.
백테스트와 페이퍼 트레이딩이 동일한 도메인 코드를 사용하는지 확인.

### 범위
- KR 인덱스 ETF 단일 종목 (KODEX 200 = 069500)
- PriceDropStrategy 1개
- Mock Broker, Mock MarketData
- NullSignal (차단기 비활성)
- SQLite 로컬 DB
- CLI 기반 백테스트/페이퍼 실행

### 명시적 제외
- 실제 KIS API 연결
- AI 차단기
- US 주식, BTC
- 매도 로직 (분할 매수만)
- 텔레그램 알림 (Console만)
- 멀티 종목
- 환율 처리
- Hot reload (정적 설정만)

### 작업 순서

1. **프로젝트 골격** — pyproject.toml, 디렉토리 구조, .gitignore, git init
2. **도메인 모델** — Asset, Money, Price, Position, Order, OrderResult, Decision, 예외 계층
3. **Port 정의** — BrokerPort, MarketDataPort, SignalPort
4. **PriceDropStrategy** — 도메인 로직 + 단위 테스트 (커버리지 100%)
5. **Mock Adapter** — MockBroker, MockMarketData, NullSignal
6. **DailyOrchestrator** — Use Case, DI 기반
7. **SQLite Repository** — positions, orders, decisions, portfolio_snapshots
8. **백테스트 러너** — 과거 데이터 주입
9. **페이퍼 트레이딩 CLI** — `trading paper --date YYYY-MM-DD` 형태
10. **통합 테스트** — 백테스트 vs 페이퍼 결과 동일성 검증

### 완료 기준
- KOSPI 200 5년치 데이터로 백테스트 성공
- 페이퍼 트레이딩 1주일 무사고 실행
- 백테스트와 페이퍼 결과 동일
- 모든 도메인 로직 단위 테스트 통과
- ruff, mypy 통과
- 시스템 재시작 후 상태 복구 확인

### 작업 진행 규칙
- 각 단계 완료 후 사용자 보고
- 다음 단계 진행 전 사용자 승인
- 단계 진행 중 명세 모호 발견 시 즉시 질문 (CLAUDE.md 13장)

---

## Phase 1 (예정): KR 주식 실거래 - 소액
- KIS API 연동
- 100~500만원 소액
- 차단기 비활성, 룰만 검증
- 1~2개월 운영

## Phase 2 (예정): AI 차단기 추가
- 차단기 신호 파이프라인
- Shadow mode 시작
- 1개월 검증 후 활성화

## Phase 3 (예정): US 주식 추가
## Phase 4 (예정): BTC 추가

상세는 docs/multi-asset-trading-system-design.md 7장 참조.
