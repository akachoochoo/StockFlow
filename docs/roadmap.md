# Roadmap

> 마지막 업데이트: 2026-05-06 (Phase 0.8 시리즈 정식 종료 + Phase 0.9 진입 (개별 주식) — ADR 0004 §7 라운드 #11 후속)

## 현재 상태

| Phase | 상태 | 결정 / 회고 |
|---|---|---|
| Phase 0 | 완료 (2026-05-02) | ADR 0001 / `docs/retrospectives/phase-0.md` |
| Phase 0.5 | 완료 (2026-05-03) | ADR 0002 / `phase-0.5.md` + `phase-0.5-results.md` |
| Phase 0.7.1 | 완료 (2026-05-04) | ADR 0003 §14 / `phase-0.7.1.md` + `phase-0.7.1-results.md` |
| Phase 0.7.2 | 완료 (2026-05-05) | ADR 0003 §16, §17 / `phase-0.7.2.md` + `phase-0.7.2-results.md` |
| Phase 0.7.3 | 완료 (2026-05-05) — 게이트 3/3 PASS | ADR 0003 §18, §18.12, §19 / `phase-0.7.3.md` + `phase-0.7.3-results.md` |
| Phase 0.7 종료 결정 | ✅ 완료 (2026-05-05) — 라운드 #9 ADR 0003 §19 | |
| Phase 0.8.1 | 완료 (2026-05-06) — 게이트 2/3 PASS (H3 FAIL, 본질적 trade-off) | ADR 0004 §1~§7 / `phase-0.8.1.md` + `phase-0.8.1-results.md` + `phase-0.8.md` |
| Phase 0.8 종료 결정 | ✅ 완료 (2026-05-06) — 라운드 #11 ADR 0004 §7 (시리즈 종료 + cooldown 거부 + Phase 0.9 직진) | |
| **Phase 0.9** | **진행 중 (2026-05-06 진입)** — 개별 주식 검증 (PriceDropStrategy default, ADR 0004 §7.4.2) | 진입 결정 라운드 ADR 0005 (예정) |
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

## Phase 0.7 시리즈 (완료, 2026-05-05): 멀티 종목 + 자본 배분

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

### 0.7.3 (완료, 2026-05-05) — 종목 다양화 (2 종)
- 종목 2 종: 069500 + 132030 (KODEX 골드)
- 329200 (부동산) 거부 — 상장일 2019-07-19, lookback 246 미달 (§18.11/§18.12)
- 5-year 백테스트: H1 ✅ 34.37 / H2 ✅ 13.23 / H3 ✅ 0.5255 — **게이트 3/3 PASS**
- Phase 0.7 시리즈 첫 명확한 통과. 핵심 발견: 종목 조성 (채권 → 골드) = 정책-자산 부정합 처방
- 결정: ADR 0003 §18, §18.12, §19. 회고: `phase-0.7.3.md` + `phase-0.7.3-results.md`

### Phase 0.7 종료 결정 (완료, 2026-05-05) — 라운드 #9
- ADR 0003 §19 박제 — 1=(a) Phase 0.7 종료 + 2=(i) Phase 0.7.4 placeholder + 3=(α) γ 보류
- 부속: Phase 0.8 진입 시점 = 사용자 검토 후 (라운드 #10)

---

## Phase 0.8 시리즈 (완료, 2026-05-06): 매수 패러다임 비교 (단일 sub-step)

### 0.8.1 (완료, 2026-05-06) — 매수 패러다임 1 차원
- 종목 유지 (069500 + 132030, EQUAL) — 변수 통제 strict
- `SupportLevelStrategy` 신규 (slot 1~5: first-buy / MA5 / MA10 / MA20 / recent_high(60))
  + `SupportSlot` (B-1 옵션) + `src/domain/indicators/` 모듈 (옵션 3)
- 5-year 백테스트: H1 ✅ 0.4188 / H2 ✅ 14.0586 / H3 ❌ 0.2679 — **게이트 2/3 PASS**
- 핵심 발견: SupportLevelStrategy 자본 회전 활발화 + 절대 수익 미세 개선 vs
  **MDD -8.27% → -21.28% (-13.01pp) 큰 폭 악화** (ADR §4.3.3 박제 whipsaw 가설 발현)
- 결정: ADR 0004 §1~§6. 회고: `phase-0.8.1.md` + `phase-0.8.1-results.md`

### Phase 0.8 종료 결정 (완료, 2026-05-06) — 라운드 #11
- ADR 0004 §7 박제 — 1=Phase 0.8 시리즈 종료 + 2=H3 처방 거부 (본질적 한계 인정)
  + 3=Phase 0.9 default = PriceDropStrategy + SupportLevelStrategy 보존
- 학습: "PriceDropStrategy + 분산이 본질" 데이터 근거 입증 (Phase 0.7.3 + 0.8.1 종합)
- 미진행: 0.8.2 (단기 매매) / 0.8.x (cooldown 도입) — ADR §7.2 / §7.3 거부 박제
- 시리즈 회고: `phase-0.8.md`

### 명시적 제외 (완료 시점)
- Phase 0.8.2 (단기 매매 +3~5%) — ADR §7.2 옵션 b 거부
- Phase 0.8.x (cooldown / tolerance / 슬롯 5 정교화) — ADR §7.3 처방 거부
- 멀티 종목 + SupportLevel 조합 — Phase 0.9.x 후속 (ADR 0004 §1.10)
- Phase 0.7.4 (부동산 분산) — ADR 0003 §18.12.4 placeholder
- §14.7 γ (자산별 다른 정책) — ADR 0003 §19.4 / Phase 1+ 보류

---

## Phase 0.9 (진행 중, 2026-05-06 진입): 개별 주식 검증

### 범위 (ADR 0003 §15.3 / ADR 0004 §7.4.2 default 박제)
- ETF → 개별 주식 (종목 성격 차원). 변수 통제: 종목 차원만 변경
- 인프라 변경: 호가 단위 가변 / 거래 정지 / 액면분할 / 증권거래세 + 수수료 모델링
- 매수 전략 default = **PriceDropStrategy** (검증된 가치, ADR §7.4.2)
- 비교 baseline = Phase 0.7.3 strict (H1=0.3270 / H2=13.2280 / H3=0.5255)
- Mock Broker 유지 (Phase 1 KIS API 진입과 시점 관계는 ADR 0005 박제 시 결정)

### 진입 결정 라운드 (예정, ADR 0005 가칭)
- ETF → 개별 주식 종목 후보 (3 ~ 5 종목, 5-year 백테스트 가용성 검증)
- 호가 단위 가변 처리 / 거래 정지 / 액면분할 데이터 소스 + 도메인 처리
- 증권거래세 / 수수료 모델링 정밀도 (`OrderResult` 필드 추가)
- 백테스트 / 페이퍼 / 실거래 동일성 (CLAUDE.md §7.4) 재검증
- Phase 1 KIS API 진입과의 시점 관계
- SupportLevelStrategy + 개별 주식 결합 검토 (Phase 0.9.x sub-step)

### SupportLevelStrategy 보존 (ADR 0004 §7.4.2)
- 코드 (`src/domain/strategies/support_level.py`) 보존
- yaml schema 보존 (`buy_strategy: Literal["price_drop", "support_level"]`)
- ADR 0004 박제 보존
- Phase 0.9.x 후속 결합 검토 가능

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

---

## Phase 0.10+ 후보 (placeholder)

진입 시점 미정. Phase 0.9 결과 후 결정. 각 항목은 진입 라운드 시 ADR 신규 박제 (현재 코드 작성 금지 — CLAUDE.md §13.3 "친절한 추가 금지").

### 그리드 트레이딩 (Phase 0.10+ 후보)
- 배경: Strategy 패턴의 본질 활용 (박영옥 원전 / `PriceDropStrategy` 패러다임에 묶이지 않음)
- 형태: 순수 그리드 매매 — slot / split 개념 없음
- 가정: 횡보장 가정 강함 (추세장 trade-off 인정)
- 참고 논문: arxiv 2506.11921
- 모델 영향 후보: `Position` 추상화 일반화 또는 `GridPosition` 신규 (진입 시 ADR 박제)
- 진입 트리거: Phase 0.9 종료 결정 라운드 시 후보로 검토
