# Roadmap

> 마지막 업데이트: 2026-05-11 (Phase 0.11.a 진입 결정 라운드 #23 박제 — DGT 도입 검토 sub-step, ADR 0007 draft commit, Phase 1 ADR = 0008 재번호 동시)

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
| **Phase 0.9.2** | **진행 중 (2026-05-07 진입 결정 라운드 #14 박제)** — 005930 + 005380 + 055550 + 097950 + 015760 (5 종, 업종 분산). 가설: 분산 효과 회복 → 시나리오 C → A/B 변경 가능 여부 검증 | ADR 0005 §8 (라운드 #14 — Phase 0.9.2 진입 결정) |
| Phase 0.10 | 완료 (2026-05-08, 라운드 #17 종료) — Backtest Reporting Enhancement, AC 5/5 충족 | ADR 0006 §1 ~ §13 |
| Phase 0.10.x | 완료 (2026-05-09, 라운드 #18) — Episode HTML readability, AC 10/10 충족, 박제 zero / 의존성 zero / 도메인 zero | ADR 0006 §14 |
| Phase 0.10.y | 완료 (2026-05-09, 라운드 #19) — Chart legend + Strategy info, AC 12/12 충족, Protocol §4.2 + slot §4.3.1 보존, 박제 zero / 의존성 zero / 도메인 zero | ADR 0006 §15 |
| Phase 0.10.z | 완료 (2026-05-09, 라운드 #20) — Slot annotation injection (chart 검정 마커 버그 fix), AC 12/12 충족, Protocol + slot palette 보존, 도메인 reasoning dict 변경 zero — Clean Architecture 정합 | ADR 0006 §16 |
| Phase 0.10.aa | 완료 (2026-05-09, 라운드 #21) — Per-symbol chart panels (단일 차트에 5종목 marker outlier 문제 fix), AC 14/14 충족, Protocol + slot palette 보존, `write_episode_html` charts list 시그니처 (breaking) | ADR 0006 §17 |
| Phase 0.10.bb | 완료 (2026-05-11, 라운드 #22) — Reporting cleanup bundle (탭 UI defer / `_INT_KEYS` cleanup / Sharpe-Calmar episode-내 risk metrics). AC 21/21 충족. None vs Decimal(0) misinformation 차단. Phase 0.10 정리 종료 | ADR 0006 §18 |
| 분석 phase | 정리 종료 (2026-05-11) — Phase 0.11.a 진입 | — |
| **Phase 0.11.a** | **진행 중 (2026-05-11 진입, sub-step 0.11.a.1 박제)** — DGT (arxiv 2506.11921) 도입 검토. `src/research/` 5th ring overlay + KoreanMarketCostModel + 일봉 prototype runner (informational). D1~D11 default 채택 | ADR 0007 §1 (draft, 라운드 #23) / 회고 TBD (`phase-0.11.a.md`, sub-step 0.11.a.5) |
| Phase 1 | 예정 — KR 주식 실거래 (KIS API 소액). 진입 결정 = Phase 0.11.a 후속 또는 별도 trajectory | 진입 시 ADR 0008 (D6 default 재번호, 이전 가칭 ADR 0007) |
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

## Phase 0.9 (완료, 2026-05-08): 개별 주식 검증

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

### Phase 0.9.1 (완료, 2026-05-07): 인프라 검증 (2 종)
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
  * 0.9.k: 회고 작성 (`docs/retrospectives/phase-0.9.1.md`) ✅
  * 0.9.l: 게이트 판정 박제 — 시나리오 C / 게이트 2/3 PASS 정식 박제 (ADR 0005 §7) ✅
  * 0.9.m: Phase 0.9.2 진입 결정 라운드 #14 — Phase 0.9.2 진입 채택 (ADR 0005 §8 박제, Q1=A/Q2=B/Q3=A) ✅

#### Phase 0.9.2 sub-step 매핑 (ADR 0005 §8.5 박제)
  * 0.9.2.a: ADR §8 박제 (본 라운드 #14) + CLAUDE.md / roadmap 갱신 ✅
  * 0.9.2.b: `config/strategies-0.9.2.yaml` + 5 종 백테스트 실행 — H1=1.1893 ✅ / H2=14.8676% ✅ / H3=0.2424 ❌ → 시나리오 C 또 발현 (Phase 0.9.1 패턴 반복, MDD -37.65% 더 악화) ✅
  * 0.9.2.c: 결과 분석 + ADR §9 박제 — §6.6.3 가설 1 ❌ / 가설 2 ✅ 강력 입증, 자산군 분산 = H3 회복 충분 조건 일반화 박제 ✅
  * 0.9.2.d: 회고 (`docs/retrospectives/phase-0.9.2.md`) ✅
  * 0.9.2.e: 게이트 판정 박제 — 시나리오 C / 게이트 2/3 PASS 정식 박제 (ADR 0005 §10), Phase 0.9 시리즈 양쪽 진입 자격 충족 확인 ✅
  * 0.9.2.f: Phase 0.9 시리즈 종료 결정 라운드 #15 — Phase 1 직진 거부 + Phase 0.10 (Backtest Reporting Enhancement) 진입 채택 (ADR 0005 §11 박제) ✅

### Phase 0.9.2 (완료, 2026-05-08): 분산 효과 (5 종)
- 종목: 005930 삼성전자 + 005380 현대차 + 055550 신한지주 (금융) + 097950 CJ제일제당 (소비재) + 015760 한국전력 (에너지)
- 변수 (vs 0.9.1): 종목 수 (2 → 5) + 업종 분산
- 5-year 백테스트 결과: H1=1.1893 ✅ / H2=14.8676% ✅ / H3=0.2424 ❌ → 시나리오 C (게이트 2/3 PASS, MDD -37.65% Phase 0.9.1 보다 더 악화)
- ADR §6.6.3 가설 검증: 업종 다양화 ❌ → H3 회복 실패 / KOSPI 대형주 분산 부족 ✅ 강력 입증
- 자산군 분산 일반화 박제 (ADR §9.6.2): "자산군 분산 = H3 회복의 충분 조건"

### Phase 0.9 종료 결정 (완료, 2026-05-08, 라운드 #15) — ADR 0005 §11
- Phase 0.9 시리즈 정식 종료 + Phase 1 직진 거부 + Phase 0.10 진입
- 학습 종합: 시나리오 C 3 회 반복 (Phase 0.8.1 / 0.9.1 / 0.9.2) — 자산군 분산 부재 → H3 미달 본질
- 인프라 검증 본질 100% 충족 (Asset 모델 / tick_size helper / 다운로드 / registry / BacktestRunner)
- 시리즈 회고: `docs/retrospectives/phase-0.9.md` (sub-step 0.10.a 동시)
- ADR 0006 / 0007 명명 변경: 기존 "Phase 1 ADR 0006 (가칭)" → ADR 0007. ADR 0006 = Phase 0.10 신규 (Backtest Reporting)

### SupportLevelStrategy 보존 (ADR 0004 §7.4.2)
- 코드 (`src/domain/strategies/support_level.py`) 보존
- yaml schema 보존 (`buy_strategy: Literal["price_drop", "support_level"]`)
- ADR 0004 박제 보존
- Phase 0.9.x 후속 결합 검토 가능 (멀티 종목 + SupportLevel — ADR 0004 §1.10)

---

## Phase 0.10 (진행 중, 2026-05-08 진입): Backtest Reporting Enhancement

### 진입 결정 라운드 #16 (완료, 2026-05-08) — ADR 0006 §1 박제
- 사용자 명시 결정: Phase 1 이전 백테스트 진단 도구 강화 (Phase 0.9 결과의 시각적·구조적 진단 + 다중 전략 운용 대비)
- ADR 0006 신규 (Phase 별 분리 패턴 일관)
- CLAUDE.md §16 in-place 갱신 (Phase 1 호환성 의식 — Phase 0.10 동안 적용)

### 본질 (ADR 0006 §1.2 박제)
- **인프라 강화 (analytical reporting layer)** — 가설 / 게이트 없음
- 변경 차원: 백테스트 출력 리포팅 (drawdown episode + strategy-agnostic trade markers)
- 평가 기준: Acceptance Criteria 5 항목 (ADR 0006 §1.3)
- Mock 환경 유지 (Phase 1 미진입)
- 기존 코드 영향: **변경 zero** (신규 추가만)

### 핵심 결정 (ADR 0006 §3 ~ §7)
- ADR-1 (§3): TradeView (application view model, 도메인 엔티티 추가 zero — 기존 BuyActionRecord/SellActionRecord 활용)
- ADR-2 (§4): StrategyRenderer Protocol + Registry (`src/ports/` + `src/adapters/reporting/renderers/`)
- ADR-3 (§5): DrawdownEpisodeDetector (application layer, strategy-agnostic)
- 차트 라이브러리: mplfinance (정적 PNG embed in HTML)
- HTML 출력: stdlib f-string (jinja2 미도입)
- 출력 위치: `reports/backtest/<config>_<window>/episode_<n>.html` (`.gitignore` 추가)
- 임계치 default: -5% (yaml/CLI override 가능)
- Episode 정의: portfolio default + asset 옵션 + both
- 신규 의존성: matplotlib / mplfinance / pandas (`[project.optional-dependencies] reporting`)

### Sub-step 매핑 (ADR 0006 §11 박제)
  * **0.10.a: 본 commit — ADR 0006 박제 + ADR 0005 §11 + 시리즈 회고 (`phase-0.9.md`) + CLAUDE.md §16 in-place 갱신 + ADR 0006/0007 명명 변경 + roadmap 갱신** ✅
  * 0.10.b: Step A — Domain entities 검토 + Drawdown episode detector + 단위 테스트 ✅
  * 0.10.c: Step B — Renderer Protocol + SevenSplitRenderer + DefaultRenderer + Registry ✅
  * 0.10.d: Step C — Chart adapter (mplfinance) + HTML 리포트 출력기 ✅
  * 0.10.e: Step D — Phase 0.9.2 결과로 end-to-end 통합 + 신규 dummy strategy 검증 (Phase 0.9.2 = 4 episodes 진단, AC3 검증) ✅
  * 0.10.f: 회고 (`docs/retrospectives/phase-0.10.md`) + Acceptance Criteria 검증 박제 (ADR 0006 §12, 5/5 충족) ✅
  * 0.10.g: Phase 0.10 종료 결정 라운드 #17 — Phase 1 진입 보류 + 분석 phase 시작 (Q1=C / Q2=B / Q3=B, ADR 0006 §13) ✅

### 분석 phase (진행 중, 2026-05-08 시작) — 사용자 분석 보류
- 본질: Phase 0.10 결과 (Phase 0.9.2 4 episodes 리포트 + AC 5/5 검증 결과) 검토 후 다음 trajectory 결정
- 코드 변경 zero (Phase 0.10 박제 보존). **라운드 #18 (2026-05-09)
  에서 Phase 0.10.x readability 채택 + 즉시 종결, 라운드 #19 (2026-05-09)
  에서 Phase 0.10.y chart legend + strategy info 채택 + 즉시 종결, 라운드
  #20 (2026-05-09) 에서 Phase 0.10.z slot annotation injection 채택 + 즉시
  종결, 라운드 #21 (2026-05-09) 에서 Phase 0.10.aa per-symbol chart panels
  채택 + 즉시 종결 — 분석 phase 자체는 유지**
- 분석 대상 (예시):
  * Phase 0.9.2 episode 리포트 (HTML) 시각적 분석
  * Phase 0.7.3 vs 0.9.2 비교 (자산군 분산 효과)
  * Phase 1 ADR 0007 박제 항목 10 의 우선순위 재검토
  * Phase 0.10.aa 가능성 (vestigial cleanup / asset scope / 다중 차트 / 멀티
    strategy 등) 재검토
  * 기타 trajectory (Phase 0.7.4 부동산 / SupportLevel + 개별 주식 / 손절 단독 검증 등)
- 종료: 라운드 #22 박제 (사용자 분석 결과 + 다음 trajectory 결정)

## Phase 0.10.x (완료, 2026-05-09 — 라운드 #18): Episode HTML Readability

### 진입 + 즉시 종결 결정 라운드 #18 (완료, 2026-05-09) — ADR 0006 §14 박제
- 사용자 명시: "report 결과가 사람이 알아보기 힘들어. 개선할수 없을까?"
- ralplan consensus 2 iter (Planner → Architect AGREE-WITH-CHANGES → Critic ITERATE → Planner revise → Architect AGREE → Critic APPROVE)
- 채택: Option A (in-place formatter helpers + per-symbol details + cycle pairing)
- 거부: Option B (TradeCycleView + Renderer 확장, Phase 0.11 검토) / Option C (인터랙티브 JS, ADR 0006 §7.2 위반)
- 분석 phase 자체는 유지 — 라운드 #19 (가칭) 에서 Phase 1 vs Phase 0.10.y vs 기타 trajectory 결정

### 본질 (ADR 0006 §14 박제)
- 인프라 후속 보강 (analytical reporting layer 가독성 강화)
- 가설 / 게이트 없음 — Phase 0.10 패턴 동일
- Acceptance Criteria 10 항목 (ADR 0006 §14.10) — 10/10 충족
- 박제 인터페이스 변경 zero (TradeView / Renderer Protocol / DrawdownEpisode 동결)
- 신규 의존성 zero (`pyproject.toml` 변경 0 줄)
- 도메인 변경 zero
- 전체 테스트 1010/1010 PASS (신규 56 tests 추가)

### 핵심 결정 (ADR 0006 §14)
- §14.5 포매팅 정책 — Decimal places=2 / KRW ``₩`` prefix / KST 일봉 ``"YYYY-MM-DD (요일)"`` / `Decimal.quantize` ROUND_HALF_UP / float 미경유
- §14.6 Cycle 페어링 정책 — list-order FIFO primary, annotation `entry_price` diagnostic only, ``realized_pnl (FIFO 표시)`` 라벨링, Phase 1 reconciliation 후속
- §14.7 KPI strip 5 deterministic — Drawdown / Duration / Recovered / Trades / Invested (Realized 미포함)
- §14.8 표시 vs 모델 분리 원칙 — CLAUDE.md §2.1 / §3.1 보강 박제
- §14.9 SYMBOL_NAMES 위치 — `src/adapters/reporting/symbol_names.py`, DI 주입 가능, Phase 0.11 yaml 분리 보류

### Sub-step 매핑 (ADR 0006 §14.11 박제)
- 0.10.h (포매터 + 거래 행 + annotation 표) ✅
- 0.10.i (KPI strip + episode 메타 포매팅) ✅
- 0.10.j (application-layer cycle pairing + 종목별 details) ✅
- 0.10.k (index aggregate + ADR §14 박제 + commit) ✅

---

## Phase 0.10.y (완료, 2026-05-09 — 라운드 #19): Chart Legend + Strategy Info Display

### 진입 + 즉시 종결 결정 라운드 #19 (완료, 2026-05-09) — ADR 0006 §15 박제
- 사용자 명시 (3 trigger): "그래프에서 레전드가 없어서 확인이 어렵네" + "Buy/Sell 색깔로 구분" + "어떤 매매로직인지 report 에 포함"
- ralplan consensus 2 round × 2 iter (각 round APPROVE)
- Falsification gate (0.10.y.c) 사용자 응답 verbatim — γ' edge ring 거부 + legend 5 조정 명시 (상승/하락 삭제 / MA 전 구간 / 고점·저점·회복 유지 / 매수 빨강 / 매도 초록)
- 채택: 5.A baseline (legend-only, palette unchanged) + user feedback override (legend 5 조정)
- 거부: γ (palette swap), γ' (edge ring), α (open marker), β (two-shade), δ (slot-shape)
- 분석 phase 그대로 유지 — 라운드 #20 (가칭) 에서 Phase 1 vs 기타 trajectory 결정

### 본질 (ADR 0006 §15.2 박제)
- 인프라 보강 (analytical reporting layer 차트 가독성 + 전략 투명성)
- 가설 / 게이트 없음 — Phase 0.10 패턴 동일
- Acceptance Criteria 12 항목 (ADR 0006 §15.10) — 12/12 충족
- 박제 인터페이스 변경 zero (`StrategyRenderer` Protocol §4.2 + SevenSplit slot palette §4.3.1 모두 보존)
- 신규 의존성 zero (`pyproject.toml` 변경 0 줄, AC10)
- 도메인 변경 zero (`StrategyInfo` = application view model — `TradeView` 패턴 재사용, ADR 0006 §3.2 정합)
- 전체 테스트 1041/1041 PASS (신규 31 tests — chart 강화 +11 + strategy_info +14 + html_writer +6)

### 핵심 결정 (ADR 0006 §15)
- §15.4 Chart legend 5 조정 — 사용자 명시 박제
- §15.5 chart.py 데이터 기반 legend (`_summarize_labels` regex `r"^(.+?)(\d+)$"` + 5 decision rules) + `returnfig=True` migration + by_style key widen + Korean 폰트 fallback (`FontProperties` 명시 적용)
- §15.6 StrategyInfo application view model + factory frozen contract surface (6 bundle attrs docstring + test_factory_reads_documented_field_set)
- §15.7 Multi-strategy 감사 — A1 (legend "차수" hard-coding) + A2 (strategy 미표시) 처방, A3 (멀티 strategy 동시 차트) Phase 1+ ADR 0007 trigger
- §15.8 §4.2 / §4.3.1 / §6 / §7 unchanged 명시 (face color = slot palette, swatch 색상은 representative 표시값)
- §15.9 Alternatives 거부 — α/β/γ/γ'/δ + StrategyInfo 도메인/Protocol/opaque dict 모두 거부 박제

### Sub-step 매핑 (ADR 0006 §15.11 박제)
- 0.10.y.a (plan freeze + alternatives 기록) ✅
- 0.10.y.b (chart legend, palette unchanged) ✅
- 0.10.y.c (falsification gate, file-sentinel) ✅
- 0.10.y.d (revised — 사용자 5 조정 적용) ✅
- 0.10.y.e (4 episodes regen + 시각 sanity) ✅
- 0.10.y.g (StrategyInfo + 3 test files) ✅
- 0.10.y.f (ADR §15 박제 + CLAUDE.md / roadmap 갱신 + commit) ✅

---

## Phase 0.10.z (완료, 2026-05-09 — 라운드 #20): Slot Annotation Injection

### 진입 + 즉시 종결 결정 라운드 #20 (완료, 2026-05-09) — ADR 0006 §16 박제
- 사용자 명시 (트리거): "report에 그래프에서 검은색 화살표는 무슨의미야?" — 분석
  phase 발견 버그
- 사용자 명시 (옵션 + 제약): "옵션 C로 진행해줘, 이때 clean architecture가
  유지 되도록 꼭 주의해줘"
- ralplan consensus 2 iter (Architect AGREE-WITH-CHANGES C1→C2 switch + Critic
  ITERATE 6 patches → APPROVE)
- 채택: Option C2 — application layer enrichment (uniform `slot_number`) +
  adapter naming alignment (1-line `seven_split.py` fix)
- 거부: Option A (도메인 reasoning 변경 — 사용자 승인 필요), Option B (renderer
  fallback to other key — 절반의 해결), C1 (renderer-key-aware injection —
  Clean Architecture 위반), setdefault collision policy (silent regression)
- 분석 phase 그대로 유지 — 라운드 #21 (가칭) 에서 Phase 1 vs 기타 trajectory 결정

### 본질 (ADR 0006 §16.2 박제)
- 인프라 보강 (chart marker bugfix + 명명 align). 분석 phase 발견 버그의
  Clean Architecture-정합 fix
- Acceptance Criteria 12 항목 — 12/12 충족
- 박제 인터페이스 변경 zero (`StrategyRenderer` Protocol §4.2 + SevenSplit
  slot palette §4.3.1 모두 보존)
- 신규 의존성 zero / 도메인 변경 zero (`git diff src/domain/` empty —
  Clean Architecture invariant)
- 전체 테스트 1047/1047 PASS (신규 6 tests — slot_number enrichment +
  collision-buy/sell + strategy-neutral + domain-untouched)

### 핵심 결정 (ADR 0006 §16)
- §16.3 Application enriches `TradeView.annotations["slot_number"]` from typed
  `BuyActionRecord.slot_number` / `SellActionRecord.slot_number` field — 도메인
  reasoning dict 변경 zero (view-side dict 만 mutate)
- §16.4 SevenSplitRenderer 도메인 명명 align — `_slot()` 가 `slot_number`
  uniform read (BUY/SELL 모두). pre-Phase-0.5 fossil `split_number` 키 제거
  (half-done rename 마무리)
- §16.5 strict no-collision invariant — `assert "slot_number" not in
  annotations` (silent setdefault 거부)
- §16.6 Renderer-agnostic application layer — 어떤 renderer 의 read key
  convention 도 포착하지 않음 (E4 증명 test)
- §16.7 Vestigial `_INT_KEYS = {split_number, slot_number}` cleanup deferred
  Phase 0.11+

### Sub-step 매핑 (ADR 0006 §16.9 박제, 1 sub-step)
- 0.10.z.a (application enrichment + adapter align + tests + 박제 + commit) ✅

---

## Phase 0.10.aa (완료, 2026-05-09 — 라운드 #21): Per-Symbol Chart Panels

### 진입 + 즉시 종결 결정 라운드 #21 (완료, 2026-05-09) — ADR 0006 §17 박제
- 사용자 명시 (트리거): "종목이 5개인데 차트는 하나이고, 종목별 가격대가
  다른데 여기에 모든 매수/매도 마트를 찍으니 확인하기 어려운 차트가
  되어버린것 같아"
- 사용자 명시 (옵션): "/ralplan A로 진행해줘 종목별 per-symbol chart panel"
- ralplan consensus 2 iter (Architect AGREE-WITH-CHANGES E1-E5 + Critic
  ITERATE 8 patches → APPROVE)
- 채택: A1 application-layer per-symbol orchestration — N independent
  charts in `<details class="chart-symbol" open>` stack
- 거부: A2 (adapter helper iteration), 단일 차트 + symbol marker 필터만,
  multi-panel mpf (panel_ratios), `chart_symbol` no-op deprecated
- 분석 phase 그대로 유지 — 라운드 #22 (가칭) 에서 Phase 1 vs 기타 trajectory 결정

### 본질 (ADR 0006 §17.2 박제)
- 인프라 보강 (chart layout per-symbol panels). 5종목 가격대 25k~250k 차이로
  단일 chart 의 y-axis auto-scale 이 outlier marker 에 지배되어 캔들 납작화
  발생 — 종목별 panel stack 으로 해결
- Acceptance Criteria 14 항목 — 14/14 충족
- 박제 인터페이스 변경: `write_episode_html(charts: Sequence[tuple[str, bytes]])`
  (breaking — `chart_png: bytes` 폐기). Protocol §4.2 / `MarkerStyle` /
  SevenSplit slot palette §4.3.1 모두 보존
- 신규 의존성 zero / 도메인 변경 zero
- 전체 테스트 1050/1050 PASS (신규 4 tests). 시각: 5 chart panels per episode,
  sorted 순서 (005380 / 005930 / 015760 / 055550 / 097950)

### 핵심 결정 (ADR 0006 §17)
- §17.3 A1 application-layer per-symbol orchestration — `chart.py` 단일-symbol
  계약 보존 (adapter portfolio-aware 강요 회피)
- §17.4 `skip_empty_symbols: bool = False` kwarg — default render-all
  (cross-symbol context 보존)
- §17.5 `<details class="chart-symbol" open>` per-symbol HTML 구조 — CSS
  shared selector with `.symbol-group, .strategy-info`
- §17.6 `chart_symbol` 파라미터 explicit 제거 — silent-ignore "no-op
  deprecated" 거부 (CLAUDE.md §13.3 정합)
- §17.7 Pinned chart symbol order = `sorted(bars_by_asset.keys())` —
  yaml load order / dict 구성에 결합되지 않은 deterministic layout
- §17.8 자동화된 figure-leak AC — `plt.get_fignums() == []` (CI 게이트)
- §17.9 multi-panel mpf 거부 — N independent figures 단순성 우선

### Sub-step 매핑 (ADR 0006 §17.11 박제, 1 sub-step)
- 0.10.aa.a (application orchestrator + adapter HTML template + script + tests + ADR 박제) ✅

---

## Phase 0.10.bb (완료, 2026-05-11 — 라운드 #22): Reporting Cleanup Bundle

### 진입 + 즉시 종결 결정 라운드 #22 (완료, 2026-05-11) — ADR 0006 §18 박제
- 사용자 명시 (트리거): "Phase 0.10.bb (탭 UI / vestigial cleanup /
  Sharpe-Calmar episode-내) 에 대해서 자세히 상기좀 해줘"
- 사용자 명시 (진입 + session 종료): "Phase 0.10.bb 까지 추가후, session
  종료 하고 다음 Phase 0.11로 들어갈게 Pahse 0.11은 다음 session에서 알려줄게"
- ralplan consensus 2 iter (Architect AGREE-WITH-CHANGES E1-E5 + Critic
  ITERATE 5 patches → APPROVE)
- 채택: B + C (cleanup + risk metrics) implement. A (탭 UI) defer
- 거부: A now (premature), C1 hybrid `<details>` (§17.5 박제 위반)
- **Phase 0.11 결정은 다음 session 으로** — 사용자 명시 박제 후 session 종료

### 본질 (ADR 0006 §18.2 박제)
- Phase 0.10 시리즈 reporting layer 정리 마무리. Phase 1 진입 전 마지막 sub-phase
- Acceptance Criteria 21 항목 — 21/21 충족
- 박제 인터페이스 변경 zero (Protocol §4.2 + slot palette §4.3.1 보존)
- 신규 의존성 zero / 도메인 변경 zero
- 전체 테스트 1074/1074 PASS (신규 24 tests)
- 시각 검증: 4 episodes 모두 Risk-Adjusted Metrics section 포함

### 핵심 결정 (ADR 0006 §18)
- §18.A 탭 UI **defer** — 트리거: scroll-pain 불만 OR ≥10 종목 (rule-of-thumb)
- §18.B `_INT_KEYS` vestigial cleanup — §16.7 reverse (원 박제 가정 contradicted
  + reverse cost < carry cost). Meta-principle 박제 — 박제 reverse 시 양쪽
  rationale 인용 필수
- §18.C `risk_metrics.py` 신규 view model + Risk-Adjusted Metrics HTML 섹션:
  * None vs Decimal(0) disambiguation (CRITICAL — 금융 misinformation 차단)
  * Section omit > row-N/A (§14.7 "always-available facts" 정합)
  * Sort invariant (input dict 순서 무관 deterministic)
  * `has_nonzero_return_variance` public predicate 신규 (`metrics.py`)

### Sub-step 매핑 (ADR 0006 §18.D 박제, 2 sub-steps)
- 0.10.bb.b (_INT_KEYS cleanup + §18.A defer paragraph fold) ✅
- 0.10.bb.c (risk_metrics.py + has_nonzero_return_variance + HTML section +
  report.py thread + 24 신규 tests) ✅

기존 plan 의 standalone 0.10.bb.a (ADR-only commit) drop — §18.A paragraph
가 0.10.bb.b commit 에 fold (ceremonial commit 회피).

---

## Phase 1 (예정): KR 주식 실거래 - 소액
- KIS API 연동
- 100~500만원 소액
- 차단기 비활성, 룰만 검증
- 1~2개월 운영
- 진입 게이트: Phase 0.10 종료 결정 박제 + ADR 0007 (가칭, 기존 ADR 0006 명명 변경 — ADR 0005 §11.5) 박제

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
