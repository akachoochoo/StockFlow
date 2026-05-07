# Roadmap

> 마지막 업데이트: 2026-05-07 (sub-step 0.9.j 완료 — ADR 0005 §6 박제, Phase 0.9.1 결과 분석 + 시나리오 C 박제)

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
| **Phase 0.9** | **진행 중 (2026-05-06 진입)** — 개별 주식 검증 (PriceDropStrategy default, ADR 0004 §7.4.2) | 진입 결정 라운드 #12 박제 완료 (2026-05-07) — ADR 0005 §1 |
| **Phase 0.9.1** | **진행 중 (2026-05-07 sub-step 0.9.c PASS)** — 005930 삼성전자 + 005380 현대차 (2 종, 인프라 검증). 사전 검증 lookback 246 + 백테스트 데이터 충족 | ADR 0005 §1.6.2 / §2 |
| Phase 0.9.2 | 예정 — 005930 + 005380 + 055550 + 097950 + 015760 (5 종, 분산 효과). 사전 검증 PASS (5 종 모두 lookback 246 충족) | ADR 0005 §1.6.2 / §2, 0.9.1 결과 후 진입 결정 |
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

### 진입 결정 라운드 #12 (완료, 2026-05-07) — ADR 0005 §1 박제
- sub-step 시리즈 (Phase 0.7 패턴) 채택 — 0.9.1 (인프라 검증, 2 종) → 0.9.2 (분산 효과, 5 종)
- ADR 0005 신규 (Phase 별 분리 패턴 일관)
- CLAUDE.md §16 본문 갱신 (Phase 1 호환성 의식 — Phase 0.9 동안 적용, §17 신규 X)
- 종목 = 다양 업종 (ADR 0005 §1.6.1 옵션 3) + 단계적 (§1.6.2)
- Asset 모델 확장 = Market enum 신규 (KOSPI / KOSDAQ) + listed_at / delisted_at + tick_size helper (`src/domain/tick_size.py`)
- Phase 0.7.3 baseline `drop_threshold_pct: 5.0` strict (ADR 0005 §1.8)
- 손절 정책 미도입 (Phase 0.9 본질 = 인프라 검증, 변수 통제 strict). Phase 1 ADR §1 본격 검토
- 후행 편향 단순화 (현재 살아있는 종목, 낙관적 추정 명시 — ADR 0005 §1.6.3)

### 범위 (ADR 0005 §1 박제)
- ETF → 개별 주식 (종목 성격 차원). 변수 통제: 종목 차원만 변경 (배분 / 매수 / 매도 / 재진입 동일)
- 인프라 변경: Market enum / listed_at / delisted_at / 호가 단위 가변 / 거래 정지 / 액면분할 (수정 종가)
- 거래세 / 수수료 모델링 = Phase 1+ 보류 (Phase 0.9 미도입)
- 매수 전략 default = **PriceDropStrategy** (검증된 가치, ADR 0004 §7.4.2)
- 매도 / 재진입 default = ProfitTarget +10% / Hybrid cooldown=60 (Phase 0.7.3 그대로)
- 비교 baseline = Phase 0.7.3 strict (H1=0.3270 / H2=13.23% / H3=0.5255, drop=5.0%)
- Mock Broker 유지 (Phase 1 KIS API 진입과 시점 관계는 Phase 0.9 종료 결정 라운드에서 결정)

### Phase 0.9.1 (진행 중, 2026-05-07): 인프라 검증 (2 종)
- 종목: 005930 삼성전자 (반도체) + 005380 현대차 (자동차) — Phase 0.7.3 와 동일 종목 수, 변수 통제 strict
- 게이트: H1 ≥ 0.3270 / H2 ≥ 13.23% / H3 ≥ 0.5255 (Phase 0.7.3 baseline strict, 통과 ≥ 2/3)
- 시나리오 (ADR 0005 §1.2.3):
  * A: 3/3 PASS → Phase 1 직진 후보
  * B: H1 + H3 PASS, H2 ❌ → 게이트 2/3 (수익률 trade-off)
  * C: H1 + H2 PASS, H3 ❌ → 게이트 2/3 (Phase 0.8.1 패턴 반복, H3 본질적 한계)
  * D: H1 만 PASS → 게이트 1/3 (시스템 한계 + 후속 결정 라운드)
- Sub-step 매핑 (ADR 0005 §1.12):
  * 0.9.a: ADR 0005 진입 결정 박제 (본 commit) ✅
  * 0.9.b: CLAUDE.md §16 / §14 본문 갱신 (별도 commit) ✅
  * 0.9.c: 사전 검증 (`scripts/verify_phase_0_9_assets.py`) — 종목별 5-year 가용성 / 거래 정지 / 액면분할 / `listed_at` 박제 ✅
  * 0.9.d: Asset 모델 확장 (Market enum / listed_at / delisted_at) + tick_size helper (`src/domain/tick_size.py` + `Asset.round_to_tick` 분기) — ADR 0005 §3 박제 후속, 0.9.f 합병 (라운드 #13) ✅
  * 0.9.e: 데이터 다운로드 스크립트 일반화 (`scripts/download_kr_assets.py`) ✅
  * ~~0.9.f: 호가 단위 동적 처리~~ → 폐기, 0.9.d 와 합병 (ADR 0005 §3)
  * 0.9.g: 데이터 다운로드 + CSV 생성 — 8 종 1477 rows × 5-year 윈도우, 3 ETF byte-identical 회귀 PASS (ADR 0005 §4) ✅
  * 0.9.h: BacktestRunner 통합 + Phase 0.7.3 회귀 invariant 재실행 — H1=0.3270 / H2=13.23% / H3=0.5255 ALL PASS (ADR 0005 §5) ✅
  * 0.9.i: Phase 0.9.1 백테스트 실행 (005930 + 005380) — H1=0.6173 ✅ / H2=18.8266% ✅ / H3=0.4139 ❌ → 시나리오 C (게이트 2/3 PASS, Phase 0.8.1 패턴 반복) ✅
  * 0.9.j: 결과 분석 + ADR §6 박제 — 종목별 기여도 / final snapshot / Phase 0.7.3 + 0.8.1 비교, "분산 효과 약화" 가 H3 미달 본질 확인 ✅
  * **0.9.k: 회고 작성 (`docs/retrospectives/phase-0.9.1.md`)**
  * 0.9.j: 결과 분석 + ADR 박제
  * 0.9.k: 회고 작성 (`docs/retrospectives/phase-0.9.1.md`)
  * 0.9.l: 게이트 판정 (시나리오 A/B/C/D)
  * 0.9.m: Phase 0.9.2 진입 결정 라운드 (5 종 확장)

### Phase 0.9.2 (예정, 0.9.1 결과 후 진입 결정): 분산 효과 (5 종)
- 종목: 005930 삼성전자 + 005380 현대차 + 055550 신한지주 (금융) + 097950 CJ제일제당 (소비재) + 015760 한국전력 (에너지)
- 변수 (vs 0.9.1): 종목 수 (2 → 5) + 분산 효과
- 게이트: 0.9.1 결과 후 결정 라운드 (0.9.m) 에서 박제

### SupportLevelStrategy 보존 (ADR 0004 §7.4.2)
- 코드 (`src/domain/strategies/support_level.py`) 보존
- yaml schema 보존 (`buy_strategy: Literal["price_drop", "support_level"]`)
- ADR 0004 박제 보존
- Phase 0.9.x 후속 결합 검토 가능 (멀티 종목 + SupportLevel — ADR 0004 §1.10)

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
