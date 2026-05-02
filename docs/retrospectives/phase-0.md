# Phase 0 Retrospective — SevenSplit

> 작성일: 2026-05-02
> Phase 기간: 2026-04-23 ~ 2026-05-02 (약 9일, 9 step / 44 commits)
> 회고 작성: Phase 0 완료 직후, Phase 1 (KIS API 연동) 진입 직전

---

## 1. 마일스톤

| Step | 산출 | 핵심 결정 (ADR) |
|---|---|---|
| 1 | 레포 부트스트랩 + Clean Architecture 디렉토리 + CLAUDE.md | §1 |
| 2 | 도메인 모델 (Asset, OHLCV, Money, Position, Order, Decision …) | §2 |
| 3 | Port 정의 (BrokerPort, MarketDataPort, SignalPort, RepositoryPorts) | §3 |
| 4 | PriceDropStrategy 순수 함수 — drop % 계산, 분할 carry-over | §4 / §7 |
| 5 | Mock Adapter — MockBroker (idempotency, 부분/거부/타임아웃 시뮬레이션), MockMarketData (룩어헤드 자동 차단) | §5 |
| 6 | DailyOrchestrator — Use Case가 Decision 결정 + UoW 영속 | §6 / §8.5 |
| 7 | SQLite (connection 팩토리, 4 Repository, SqliteUnitOfWork) | §8 |
| 8 | BacktestRunner + 4개 성과 지표(CAGR/MDD/Sharpe/Calmar) 순수 함수 분리 | §9 |
| 9 | CLI (`trading backtest` / `trading paper`) + safety + composition + equivalence regression | §10 |

**Phase 0 종료 기준 (CLAUDE.md §14):**
- ✅ KR 인덱스 ETF 단일 종목 지원
- ✅ PriceDropStrategy 1개 + NullSignal
- ✅ Mock Broker / Mock MarketData
- ✅ 백테스트 + 페이퍼 트레이딩 (양 흐름 결과 동일성 회귀 테스트 통과)
- ✅ SQLite 로컬 DB (4 Repo + UoW)
- ✅ KOSPI 200 5년치(2020-01-02 ~ 2024-12-30) 백테스트 성공

---

## 2. 완료 기준 충족 검증

| 항목 | 결과 | 위치 |
|---|---|---|
| 도메인 100% 커버리지 | 100% (line/branch) | `src/domain/` |
| 전체 테스트 그린 | 489 passed | `tests/` |
| 라인 커버리지 | 99% | `src/` |
| ruff / mypy | 0 errors | strict on `src/domain` |
| 백테스트 ↔ 페이퍼 동일성 invariant | 통과 — Decision 시퀀스 + 최종 cash/포지션 byte-identical | `tests/integration/test_backtest_paper_equivalence.py` |
| Phase 0 명시적 제외 영역 | 모두 미구현 (의도) | §5 |

---

## 3. 5년 KOSPI 200 백테스트 결과 (메인)

### 3.1 실행 조건

| 파라미터 | 값 |
|---|---|
| 기간 | 2020-01-02 → 2024-12-30 |
| 데이터 | KODEX 200 (069500), pykrx 일봉 1231개 |
| 초기 자본 | 100,000,000 KRW (1억) |
| `per_split_amount` | 10,000,000 KRW (1천만) |
| `drop_threshold_pct` | 5.0 % |
| `max_split_count` | 7 |
| `max_split_per_day` | 1 |

### 3.2 핵심 지표

| 지표 | 전략 | Buy & Hold (벤치마크) | 델타 |
|---|---|---|---|
| Total return | **+25.96 %** | +21.13 % | **+4.82 pp** |
| CAGR | 4.84 % | 3.91 % (산출) | +0.93 pp |
| Max drawdown | **-27.57 %** | -34.64 % | **+7.07 pp 개선** |
| Sharpe (rf=0, 252d) | 0.39 | — | — |
| Calmar | 0.18 | — | — |
| 자본 활용 | 69.92 % | 100 % | -30.08 pp |
| 잠긴 현금 | 30,084,490 KRW | 14,848 KRW (lot 잔여) | — |

벤치마크 산식: 첫날 종가(25,856 KRW)에 1억 가능한 정수 최대 매수(3,867주) 후 마지막 종가(31,321 KRW)에 평가.

### 3.3 분할 매수 타이밍 — COVID-19 단기 폭락 구간 집중

| 분할 | 일자 | 가격 | 수량 | 직전 분할 대비 |
|---|---|---|---|---|
| split_1 | 2020-01-03 | 25,855 | 386 | 첫 매수 (position=None) |
| split_2 | 2020-03-02 | 23,900 | 418 | +59일 |
| split_3 | 2020-03-10 | 23,470 | 426 | +8일 |
| split_4 | 2020-03-12 | 22,900 | 436 | +2일 |
| split_5 | 2020-03-13 | 22,135 | 451 | +1일 |
| split_6 | 2020-03-16 | 21,565 | 463 | +3일 |
| split_7 | 2020-03-17 | 20,780 | 481 | +1일 |

**관찰:**
- 7회 분할 전체가 **2020년 1~3월(76일)** 안에 발생.
- COVID-19 1차 충격 구간(2020-02 ~ 2020-03 중순)에 split_2~7 6회 연속 발화 — 가격이 25,855 → 20,780으로 ~20% 떨어지는 동안 평단가도 25,855 → 22,861로 11.6 % 낮춤.
- 평단가 22,861 KRW vs 마지막 종가 31,321 KRW → **포지션 미실현 +37 %** (B&H의 +21 % 대비 우위 원천).

### 3.4 4.7년 잠수 (Dormancy) 구간

split_7 이후 (2020-03-17 ~ 2024-12-30, 1175 거래일) 동안 **추가 매수 0회**.
- 이유 1: `max_split_count=7` 도달 → 전략 자체가 추가 buy 차단.
- 이유 2: 2020-03-17 종가 20,780 vs 2024-12-30 종가 31,321 → 평단가 22,861 대비 **항상 매수 트리거(평단 -5%) 미달** = 회복 + 강세 추세.
- skip 분포: `skip:strategy_no_buy 1223회`, `skip:market_data_unavailable 1회 (T-1 데이터 없음)`.

이 구간은 **매도 로직의 부재가 가장 뼈아픈 곳**. 회복(2020-Q3) 시점이나 2021년 고점(35,000~) 부근에서 일부 익절했다면 추가 수익 + 다음 변동성에 재투입 가능했을 것.

### 3.5 자본 효율 vs B&H

| 비교 축 | 전략 | B&H |
|---|---|---|
| 사용 자본 | 70 M | 100 M |
| 사용 자본 대비 수익 | **(125.96 - 100) / 70 = 37.1 %** | (121.13 - 100) / 100 = 21.1 % |
| 시간가중 (5년) | 6.5 % / yr | 3.9 % / yr |

**결론:** 전략이 B&H보다 절대수익도 우위지만, **자본 효율(committed capital 대비)은 1.76배** 더 높다. Phase 1에서 매도 로직 + 다중 자산이 추가되면 잠긴 30M가 다른 종목/사이클에 활용될 수 있는 여지를 시사.

---

## 4. 학습

### 4.1 기술 — 무엇이 잘 작동했나

- **Clean Architecture 의존성 룰** (CLAUDE.md §1.1) — `src/domain`이 진정으로 외부 import 0 / 시계 0인 채 유지된 덕에 `BacktestRunner`/`paper`가 같은 코드 경로 공유. 동일성 회귀 테스트가 한 번에 통과.
- **두 시계 모델** (decision_at 09:00 KST / snapshot_at 16:00 KST) — 룩어헤드 차단의 단일 메커니즘. MockMarketData가 `as_of` 이후 데이터를 자동 숨김 → 도메인이 실수로 미래를 볼 수 없음.
- **Decimal 일관 사용** — 평단 계산이 5년 경과 후에도 byte-identical (백테스트와 페이퍼 동일). float 사용 시 0.0001 % 단위 누적 오차로 동일성 invariant 깨졌을 것.
- **Idempotency key 강제** — Phase 0 단발 cron에서는 무용해 보였지만 페이퍼 N일 시뮬레이션에서 같은 날 재실행 안전성을 자연스럽게 확보.
- **UoW 패턴 + 자동 rollback** — Use Case가 `connect`/`commit` 모름. 실패 시 partial-write 위험 0.

### 4.2 기술 — 발견 후 보강한 것

| 발견 | 조치 |
|---|---|
| Sharpe `zip strict=True`가 길이 1에서 ValueError | `itertools.pairwise` 전환 (RUF007 자동 가이드) |
| pydantic `model_dump`가 Decimal/Date를 그대로 반환 → `json.dumps` 실패 | `model_dump_json` round-trip 헬퍼 |
| `Asset(tick_size="5")` mypy strict 거부 | `Decimal("5")` 명시 (런타임 coercion 있어도 정적 타입 위반) |
| OHLCV `low<=close<=high` 정합성 위반 fixture | csv_market_data_loader가 사전 거부 (다운로더에도 동일 검증 추가) |
| `pyproject.toml` `trading = "src.cli:main"` 진입점 | `src/cli/__init__.py`에서 `main` 재노출 |

### 4.3 협업 — 무엇이 잘 작동했나

- **결정 → 박제(ADR) → 구현 → 테스트** 4단계 게이트가 사용자/AI 양쪽 헷갈림 없이 진행.
- **Sub-step 번호화** (예: §10.a~10.m) — 작업 분할이 명시적이라 중단 후 복귀가 매끄러움.
- **Conventional Commits** 강제 (CLAUDE.md §12.2) — 14 commit이 모두 단일 책임 단위로 분할되어 회고 시 맥락 추적 쉬움.
- **수동 검증을 코드 산출 끝마다 강제** — `manual_backtest.py` 같은 일회용 스크립트로도 사람 눈 검증이 결정성 회귀를 잡음.

### 4.4 협업 — 회고에서 새로 채택할 규칙

- **백테스트 결과를 매 phase 종료 시 박제** — 이번엔 Phase 0 완료 시점에 한 번 했지만, Phase 1+에서는 Step 종료마다 한 줄 결과 노트(`docs/retrospectives/phase-1.md` 미리 만들어 누적) 추가.
- **벤치마크 비교를 BacktestResult에 빌트인** — 현재는 외부 스크립트로 계산. Phase 1에서 `BacktestResult.benchmark_buy_and_hold` 필드 추가 검토.

---

## 5. Phase 0 의도된 제외 (재확인)

CLAUDE.md §14의 명시적 제외 항목 — 모두 Phase 0에서 손대지 않음 + 회고 시점에도 도입 신호 없음.

| 제외 항목 | Phase 1+ 도입 시점 |
|---|---|
| 실제 KIS API | Phase 1 첫 작업 |
| AI 차단기 (RuleBasedSignal → ML) | Phase 2+ |
| US 주식 / BTC | Phase 1 후반 ~ Phase 2 |
| **매도 로직** | Phase 1 (회고 결과 우선순위 상승) |
| 텔레그램 알림 | Phase 1 (실거래 시 알람 필수) |
| 멀티 종목 | Phase 1 |
| 환율 처리 | Phase 1 후반 (US 도입과 연계) |
| Hot reload | Phase 2 |

---

## 6. 발견된 이슈 / 제약

### 6.1 코드 레벨 (모두 해소됨)

§4.2 표 참조. 모두 5월 2일 이전에 픽스 + 테스트 추가.

### 6.2 전략 레벨 (Phase 0 의도, Phase 1에서 재고)

1. **매도 로직 부재로 4.7년 dormant** — 가장 큰 기회비용. Phase 1 우선순위.
2. **자본 활용 70%** — `max_split=7` × `per_split=10M` = 70M 한계. Phase 1 multi-asset이 잠긴 자본 활용처 제공.
3. **`max_split` 도달 후 dormant** — 추가 변동성 활용 불가. Phase 2에서 "split level reset on N% recovery" 등 정책 검토.
4. **장기 횡보장 비효율** — 5% drop threshold + 5년 동안 7회만 발화 = 거래 빈도 낮음. KR ETF 변동성에 비해 지나치게 보수적인지 검증 필요. drop_threshold 3%/4% 시뮬 비교를 Phase 1에서 추가.

### 6.3 인프라 레벨

1. **pykrx 런타임 dep로 추가됨** — KRX 사이트 변경에 종속. Phase 1 KIS API 도입 시 pykrx는 백테스트/리플레이 전용으로 격리.
2. **단일 머신 lock 가정** — 분산 환경(NFS, 컨테이너 다중)에서는 PID 기반 lock이 안전하지 않음. Phase 2+에서 fcntl 또는 외부 lock service.
3. **단일 통화 (KRW)** — 다중 통화 시 `Money` 연산 정책 (자동 환전 금지 §2.2) 적용 검증 필요.

---

## 7. Phase 1 권고

### 7.1 우선순위 1 — 실거래 가능 상태로 만들기

| 작업 | 예상 sub-step 수 |
|---|---|
| KIS API 어댑터 (실 BrokerPort + MarketDataPort 구현) | ~10 |
| KIS API 응답 검증 + 도메인 모델 변환 (CLAUDE.md §5) | ~4 |
| 텔레그램 알림 어댑터 + Use Case 훅 | ~3 |
| Reconciliation 정식 구현 (DB ↔ KIS 포지션 대조, §11.2) | ~3 |
| 매도 로직 — `SellStrategy` 도입 (목표가 / trailing stop / split level 회복) | ~6 |

### 7.2 우선순위 2 — 다중 종목

- `BacktestRunner` 시그니처 확장 (`asset` → `assets: list[Asset]`, `strategy_config: dict[Asset, SplitStrategyConfig]`).
- DailyOrchestrator iteration 순서 결정 (idempotency_key 충돌 방지).
- 자본 분배 정책 (균등/시가총액 가중/맞춤 비중).

### 7.3 우선순위 3 — 운영 도구

- `trading status` (현재 잔고/포지션/오늘 결정 요약).
- `trading reconcile` (수동 트리거).
- Hot reload of `config/strategies.yaml`.
- Grafana / Prometheus 같은 Observability layer.

### 7.4 회고 시 추가하기로 결정한 규칙

- 매 step 종료마다 짧은 백테스트 비교 노트를 `docs/retrospectives/phase-N.md`에 누적.
- `BacktestResult`에 `benchmark_buy_and_hold` 빌트인 필드 추가 검토.

---

## 8. 지표 요약

| 지표 | 값 |
|---|---|
| Phase 0 기간 | 2026-04-23 ~ 2026-05-02 (9 일) |
| 총 commit | 44 (Step 8 + 9에서 14 commit) |
| `src/` LOC | 4,871 |
| `tests/` LOC | 7,747 |
| 테스트 수 | 489 (모두 그린) |
| 라인 커버리지 | 99 % |
| 분기 커버리지 | 97 % |
| ruff / mypy 위반 | 0 |
| ADR 섹션 | §1 ~ §10 + A.* + 본 회고 |
| **5년 KOSPI 200 backtest CAGR** | **4.84 %** |
| **vs Buy-and-Hold delta** | **+4.82 pp return / -7.07 pp MDD** |

---

## 9. Phase 1 진입 체크포인트

Phase 1 진입 전 다음을 사용자가 검토:

1. ☐ 본 회고 4·5·6 섹션 합의
2. ☐ Phase 1 우선순위 1 (KIS API + 매도) 범위 + 일정 합의
3. ☐ KIS API 키 발급 / 모의투자 계좌 준비
4. ☐ pykrx → 백테스트 전용 격리 결정 박제 (Phase 1 ADR §1)
5. ☐ Phase 1 첫 ADR 라운드 트리거

---

*본 문서는 Phase 0 완료 시점의 사실 + 학습을 박제한다. Phase 1 진행 중
관점이 바뀌더라도 본문은 정정하지 않고, 각 phase 회고에 "Phase 0 회고
재해석" 항목을 추가하는 방식으로 누적한다 (CLAUDE.md §12.3 ADR 정책 정신).*
