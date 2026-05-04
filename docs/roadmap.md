# Roadmap

> 마지막 업데이트: 2026-05-05 (Phase 0.7.3 종목 2 종 축소 — §18.12 fallback (d) 채택, 069500 + 132030, 329200 부동산은 Phase 0.7.4 후속)

## 현재 상태

| Phase | 상태 | 결정 / 회고 |
|---|---|---|
| Phase 0 | 완료 (2026-05-02) | ADR 0001 / `docs/retrospectives/phase-0.md` |
| Phase 0.5 | 완료 (2026-05-03) | ADR 0002 / `phase-0.5.md` + `phase-0.5-results.md` |
| Phase 0.7.1 | 완료 (2026-05-04) | ADR 0003 §14 / `phase-0.7.1.md` + `phase-0.7.1-results.md` |
| Phase 0.7.2 | 완료 (2026-05-05) | ADR 0003 §16, §17 / `phase-0.7.2.md` + `phase-0.7.2-results.md` |
| **Phase 0.7.3** | **진행 중 (2026-05-05 진입)** — 종목 2 종 (069500 + 132030, 정책 동일성, EQUAL default) | ADR 0003 §18 + §18.12 |
| Phase 0.7 종료 결정 | 예정 — 0.7.3 종료 후 | (별도 결정 라운드) |
| Phase 0.8 (가칭) | 예정 — 지지선 기반 세븐스플릿 (매수 패러다임 차원) | 후보: ADR 0003 §15.2. 진입 시 ADR 0004 |
| Phase 0.9 (가칭) | 예정 — 개별 주식 검증 (종목 성격 차원) | 후보: ADR 0003 §15.3. 진입 시 ADR 0005 |
| Phase 1 | 예정 — KR 주식 실거래 (KIS API 소액) | 진입 시 ADR 0006 |
| Phase 2 | 예정 — AI 차단기 추가 | |
| Phase 3 | 예정 — US 주식 추가 | |
| Phase 4 | 예정 — BTC 추가 | |

진입 경로 (ADR 0003 §15.5.1.C, 옵션 A 채택):
```
0.7.1 → 0.7.2 → 0.7.3 → Phase 0.7 종료 → 0.8 → 0.9 → Phase 1 → 2 → 3 → 4
```

근거 (사용자 명시, ADR §15.5.1.D):
1. 변수 통제 원칙 일관 (한 단계 = 한 차원 변경)
2. 게이트 무시 패턴 차단 (ADR §1.3)
3. Mock 환경 위험 zero 자원을 가설 검증에 끝까지 활용

---

## Phase 0 (완료, 2026-05-02): 종이 거래 시뮬레이터

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

## Phase 0.5 (완료, 2026-05-03): 매도 + 재진입 도입

### 범위
- `ProfitTargetSell` (10% target) 도입
- 재진입 정책 비교: D-2 (`MovingAverageReentry`) vs F (`HybridTimeBasedReentry`, cooldown=60)
- 결정: ADR 0002. 회고: `docs/retrospectives/phase-0.5.md` + `phase-0.5-results.md`

### 종료 라운드
- 5-year KOSPI 200 백테스트: H1 ✅ / H2 ❌ / H3 ❌ / H4 ✅ — 게이트 #2 미충족
- 옵션 A' 채택 (Phase 0.7 직진, 멀티 종목으로 H2/H3 본질 검증) — ADR 0002 §13 박제

---

## Phase 0.7 시리즈 (진행 중): 멀티 종목 + 자본 배분

### 0.7.1 (완료, 2026-05-04) — 인프라 2 종목
- 069500 (KODEX 200) + 214980 (KODEX 단기채권 PLUS), 균등 배분, 정책 동일성 강제
- 5-year 백테스트: H1 ❌ / H2 ❌ / H3 ❌ — 게이트 0/3 FAIL
- 라운드 #5 결정: 옵션 A (Phase 0.7 시리즈 완주 + Phase 0.8/0.9 직교 차원 추가)
- 결정: ADR 0003 §14, §15.5.1. 회고: `phase-0.7.1.md`

### 0.7.2 (완료, 2026-05-05) — 자본 배분 정책 비교
- 종목 유지 (069500 + 214980) — 변수 통제
- 3 정책 비교: EQUAL / INV_VOL (1/σ) / VOL (σ)
- 게이트 (§16.2): H1 ≥ 15.6% / H2 ≥ +5.25% / H3 ≥ 0.33 — EQUAL/VOL 통과 (각 2/3)
- 라운드 #7 결정: 1=(a) Phase 0.7.3 진입 + 2=(iii) H3 정밀도 명시화 + 3=(γ) 게이트 분리 박제
- 결정: ADR 0003 §16, §17. 회고: `phase-0.7.2.md` + `phase-0.7.2-results.md`

### 0.7.3 (진행 중, 2026-05-05 진입) — 종목 다양화 (2 종)
- 종목 2 종: 069500 + 132030 (KODEX 골드)
- **329200 (TIGER 부동산인프라고배당) 거부** — 상장일 2019-07-19, lookback 246 미달 (§18.11). §18.12 fallback (d) 채택
- 채권 (214980) 대체 — 정책-자산 부정합 처방. 주식 + 골드 분산 (다른 상관성)
- 부동산 / 인프라 분산은 **Phase 0.7.4 (가칭) 후속** 박제 (§18.12.4)
- 정책 동일성 강제 (§7.3) — 종목별 다른 정책 (§14.7 γ) 거부
- 자본 배분 default = EQUAL / 정책 F (drop=5%, target=10%, cooldown=60)
- 게이트: H1 ≥ 15.6% / H2 ≥ +5.25% / H3 ≥ **0.3258** (정확값, §17.3 학습)
- 결정: ADR 0003 §18 (라운드 #8) + §18.12 (fallback). 회고: `phase-0.7.3.md` (예정)

### Phase 0.7 종료 결정
- 0.7.3 종료 후 별도 결정 라운드 — Phase 0.8 진입 게이트

---

## Phase 0.8 (예정, 가칭): 지지선 기반 세븐스플릿

### 범위 (후보 박제: ADR 0003 §15.2)
- 매수 패러다임 변화 (가치 → 기술적). `SupportLevelStrategy` 신규
- 7 슬롯 = 지지선 종류 (MA / BB / RSI 등)
- 보조 지표 인프라 (`IndicatorPort` / `MockIndicatorAdapter`)
- 단일 종목 (069500) Phase 0.5 F 환경 — 변수 1 차원 통제

### 진입 게이트
- Phase 0.7 종료 결정 박제 + ADR 0004 (가칭) 박제

---

## Phase 0.9 (예정, 가칭): 개별 주식 검증

### 범위 (후보 박제: ADR 0003 §15.3)
- ETF → 개별 주식 (종목 성격 차원)
- 인프라 변경: 호가 단위 가변 / 거래 정지 / 액면분할 / 증권거래세 + 수수료 모델링
- 변수 통제: 종목 차원만 변경, ETF 분산 비교 가능

### 진입 게이트
- Phase 0.8 종료 결정 박제 + ADR 0005 (가칭) 박제

---

## Phase 1 (예정): KR 주식 실거래 - 소액
- KIS API 연동
- 100~500만원 소액
- 차단기 비활성, 룰만 검증
- 1~2개월 운영
- 진입 게이트: Phase 0.9 종료 결정 박제 + ADR 0006 (가칭) 박제

## Phase 2 (예정): AI 차단기 추가
- 차단기 신호 파이프라인
- Shadow mode 시작
- 1개월 검증 후 활성화

## Phase 3 (예정): US 주식 추가
## Phase 4 (예정): BTC 추가

상세는 docs/multi-asset-trading-system-design.md 7장 참조.
