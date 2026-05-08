# Phase 0.10 회고 — Backtest Reporting Enhancement

> Phase 0.10 narrative 회고. 작성일: 2026-05-08. sub-step 0.10.f.
>
> 정량 결과: 본 회고 §3 (Acceptance Criteria 검증) + ADR 0006 §12 박제.
> 결정 박제: ADR 0006 §1 (라운드 #16 — Phase 0.10 진입) + §3 / §4 / §5
> (ADR-1 / -2 / -3 세부) + §6 / §7 / §8 / §9 / §10 / §11 (차트 / HTML /
> 모듈 다이어그램 / 충돌 / 제외 / sub-step 매핑) + §12 (Acceptance
> Criteria 검증). 선행 회고: `phase-0.9.md` (Phase 0.9 시리즈 종합).
> 패턴 정합 (Phase 0.7 / 0.8 / 0.9 narrative 패턴).
>
> 본 회고 시점 sub-step 0.10.g (Phase 0.10 종료 결정 라운드 #17 + Phase
> 1 진입 trigger) 미진행 — 후속 sub-step 별도 박제.

---

## 1. 마일스톤

Phase 0.9 종료 + Phase 0.10 진입 결정 (2026-05-08 라운드 #15 / #16, ADR
0005 §11 + ADR 0006 §1) → 동일 일자 sub-step 0.10.a~0.10.e 진행 →
**1 일 완료**. 인프라 강화 phase 의 본질 — 가설 / 게이트 평가 phase
아니므로 빠른 진행 가능.

### 1.1 sub-step 흐름

| sub-step | 내용 | commit |
|---|---|---|
| 0.10.a | ADR 0006 박제 + ADR 0005 §11 + 시리즈 회고 + CLAUDE.md/roadmap + ADR 명명 변경 | 83b061d |
| 0.10.b | Step A — TradeView + DrawdownEpisode + detector + 단위 테스트 | d35b7cb |
| 0.10.c | Step B — Renderer Protocol + SevenSplit/Default + Registry | 7f15d4c |
| 0.10.d | Step C — chart (mplfinance) + html_writer (stdlib) | 89aa4d4 |
| 0.10.e | Step D — report use case + Phase 0.9.2 E2E + AC3 검증 | 2068714 |
| **0.10.f** | **본 회고 + ADR §12 AC 박제** | (현재) |
| 0.10.g | Phase 0.10 종료 + Phase 1 진입 trigger 라운드 #17 | 다음 |

총 6 commits (4 step + 박제 + 회고). Phase 0.7 / 0.9 보다 압축 — 인프라
재사용 zero (Phase 0.10 = 신규 분석 layer) + 도메인 엔티티 추가 zero
(view model only) 효과.

---

## 2. 완료 기준 충족 검증

ADR 0006 §1.3 박제 Acceptance Criteria 5 항목:

| AC # | 항목 | 충족 | 근거 |
|---|---|---|---|
| 1 | 백테스트 결과에 대해 episode 별 리포트 생성 성공 | ✅ | sub-step 0.10.e Phase 0.9.2 실데이터 E2E (4 episodes 진단, 207 trades, index.html + 4 episode HTML) |
| 2 | 세븐 스플릿 거래에 차수 (B1~B7) 라벨 표기 확인 | ✅ | sub-step 0.10.c SevenSplitRenderer + tests (test_seven_split_renderer.py 의 marker_label B1~B7 검증) |
| 3 | 신규 더미 전략 추가 시 코어 변경 zero | ✅ | sub-step 0.10.e test_dummy_strategy.py (AC3-1: DefaultRenderer fallback / AC3-2: runtime register MaCrossRenderer + custom panel HTML 검증) |
| 4 | ADR-1 / -2 / -3 박제 완료 | ✅ | ADR 0006 §3 (TradeView) / §4 (Renderer Protocol + Registry) / §5 (DrawdownEpisode + detector) |
| 5 | 단위 테스트 커버리지 기존 수준 유지 또는 향상 | ✅ | 797 → 947 passed (+150 신규 테스트, +18.8%) |

→ **5/5 Acceptance Criteria 모두 충족**.

---

## 3. Phase 0.9.2 실데이터 E2E 진단 결과

ADR 0005 §10 박제 baseline (Phase 0.9.2 시나리오 C / 게이트 2/3 PASS)
정합 + drawdown episode 시각적 진단:

```
$ uv run python scripts/generate_phase_0_9_2_report.py \
    --output-dir reports/backtest/strategies-0.9.2_20200102_20241230
→ 백테스트 return=14.87% / MDD=-37.65% / Sharpe=0.2424 (ADR 0005 §10 정합)
→ 4 episodes 진단:
  Ep 1: 2020-02-12 → 2020-03-19 (dd=-37.6516%, recovered) — COVID-19 crash
  Ep 2: 2021-01-08 → 2021-01-29 (dd=-6.8009%, recovered)
  Ep 3: 2021-06-07 → 2023-03-14 (dd=-24.8945%, recovered) — long downturn
  Ep 4: 2024-07-08 → 2024-12-30 (dd=-18.2490%, UNRECOVERED)
→ 207 trades + index.html + 4 episode HTML
```

### 3.1 Episode 4 의 진단 가치 — Phase 0.9.2 lock-in 패턴 시각화

ADR 0005 §9.3.1 박제 "all-in lock-in" 패턴 (Phase 0.9.2 final snapshot
= 3 종 split_level=7 가득찬 상태 + total unrealized -38M KRW) 의 **시각
적 증거**:

- Ep 4 = 2024-07-08 → 2024-12-30 (백테스트 종료까지 회복 안 됨)
- recovered=False / recovery_date=None
- duration_days=175 (백테스트 종료 시점)
- 종목별 lock-in 종목 (005930 / 015760 / 097950) 의 차수별 매수
  marker (B1~B7) 가 차트 상에 시각화됨

→ Phase 0.9.2 회고 (`phase-0.9.2.md` §6) 의 lock-in 패턴 분석이 본 차트
로 **데이터 진단 가능**. Phase 1 ADR 0007 의 손절 정책 / 자본 배분
정교화 설계 시 본 episode 가 직접적 근거.

### 3.2 Episode 1 의 진단 — COVID-19 crash 회복 검증

- Ep 1 = 2020-02-12 → 2020-03-19 (drawdown -37.65%, **recovered yes**)
- 전체 백테스트 MDD 와 동일 (single largest peak-to-trough)
- recovered=True → 회복 후 다시 새 peak 도달
- duration 약 5 주 → V-shape recovery (COVID-19 후 빠른 반등)

→ PriceDropStrategy + 자산군 분산 의 회복 능력 검증. 본 episode 만 분석
하면 Phase 0.7.3 baseline 과 유사 양상 (자산군 분산 효과 활용).

### 3.3 Episode 3 의 진단 — Long downturn

- Ep 3 = 2021-06-07 → 2023-03-14 (drawdown -24.89%, **recovered yes**)
- duration 약 21 개월 (long downturn) → 회복 매우 느림
- Phase 0.9.2 의 5 종 분산 약화 + KOSPI 대형주 동조 하락의 누적 영향

→ "분산 효과 약화 = H3 미달의 충분 조건" (ADR 0005 §9.6.2) 명제의 시각
적 증거. 동일 기간 Phase 0.7.3 (주식+골드) 백테스트 대비 차이 분석
가능 (Phase 0.10.x 후속 비교 분석 트리거).

---

## 4. 학습

### 4.1 도메인 엔티티 추가 zero — view model 채택의 가치 (ADR §3.2)

사용자 spec ADR-1 의 ``Trade`` 도메인 엔티티 거부 + ``TradeView``
application view model 채택:

| 항목 | 도메인 엔티티 추가 (사용자 spec) | View model 채택 (ADR §3.2) |
|---|---|---|
| 정보 중복 | Decision/BuyActionRecord 와 중복 | 단일 source of truth (기존 모델) |
| 영구화 부담 | 신규 schema + 마이그레이션 | 영구화 zero (in-memory only) |
| 다중 전략 진입 | 신규 모델 schema design | strategy_id 만 추가 (Phase 0.10) |
| 회귀 위험 | 기존 백테스트 영향 가능 | 변경 zero (974 테스트 정합) |

→ CLAUDE.md "친절한 추가 금지" 정신 + Hexagonal "도메인 ↔ application
분리" 원칙의 정합 결과. 기존 모델 (`Decision` / `BuyActionRecord` /
`SellActionRecord` / `Order`) 의 reasoning dict 가 이미 strategy 별
자유 메타데이터 패턴으로 동작 — view model 변환만으로 사용자 spec
``annotations: Mapping[str, Any]`` 와 1:1 매핑 가능.

### 4.2 Hexagonal Port + Plugin Registry — Acceptance Criteria 3 의 본질

ADR §4 박제 — Renderer 를 Port (`src/ports/strategy_renderer.py`) +
Adapter (`src/adapters/reporting/renderers/`) 분리. Registry 는
strategy_id key lookup + DefaultRenderer fallback.

→ **신규 strategy 추가 = renderer 구현체 추가 + Registry 등록만**:
1. `src/adapters/reporting/renderers/<new>.py` 작성
2. `StrategyRendererRegistry.register("new_strategy", NewRenderer())`
3. **코어 reporting 모듈 (`src/application/reporting/`) 변경 zero** ✓

Phase 0.10.e test_dummy_strategy.py 가 본 패턴 정량 검증:
- AC3-1: 등록 안 한 dummy → DefaultRenderer fallback → end-to-end 동작
- AC3-2: runtime register MaCrossRenderer (signal=golden_cross /
  fast=20 / slow=60) → custom panel ("MA Cross 신호") HTML 검증

→ Phase 1+ 다중 전략 운용 시 (MA cross / RSI / 모멘텀 / 가치주 등)
본 패턴이 직접적 확장 경로.

### 4.3 mplfinance 선택의 정합 (ADR §6)

차트 라이브러리 = mplfinance (vs plotly):
- 정적 PNG embed (HTML base64) → HTML 자체 portable
- matplotlib 의존성 zero 부담 (numpy / pandas 가 이미 보편적)
- 인터랙티브 미요 (정적 episode 진단 본질) — Phase 0.10 spec 정합

발견된 한계:
- mplfinance "too much data" warning (5-year 1231 거래일 일별 캔들):
  ```
  WARNING: YOU ARE PLOTTING SO MUCH DATA THAT IT MAY NOT BE
           POSSIBLE TO SEE DETAILS (Candles, Ohlc-Bars, Etc.)
  ```
  → 정적 PNG 에서 5-year 캔들은 너무 조밀 — episode window padding
  (default 10 days) 으로 chart 가 episode 구간만 표시. 그러나
  generate_episode_report 가 chart 에 ohlcv_bars 전체를 전달 → chart 가
  내부 필터. 동작은 정상.
  → Phase 0.10.x 검토: 차트에 전달할 ohlcv 도 미리 필터해서 warning 회피.

### 4.4 stdlib f-string HTML — jinja2 미도입의 정합 (ADR §7.2)

Phase 0.10 의 단순 episode 페이지 (1 차트 + 메타 표 + 거래 로그 + 진단
패널) 는 f-string 으로 충분:
- 의존성 추가 zero (jinja2 미도입)
- HTML escape 명시 (`html.escape` 활용 — XSS 방지)
- 한국어 utf-8 / DOCTYPE / inline CSS — 단순 HTML 1 페이지

발견된 한계 (Phase 0.10.x 검토):
- 복잡 reporting (예: 다중 episode 종합 + 자산별 break-down) 시 jinja2
  유리. Phase 0.10.x 또는 Phase 1+ reporting 확장 시 재검토.

### 4.5 Phase 0.10.e scope="portfolio" 한정 (ADR §5.5 / §11)

ADR §5.5 박제 = "portfolio default + asset 옵션 + both". Phase 0.10.e
구현 범위는 **portfolio scope 만**:

- scope="asset" / "both" → NotImplementedError (Phase 0.10.x 후속)
- 근거: portfolio scope 만으로 80% 가치 — 사용자 의도 ("전체 손실
  진단") 충족
- Phase 0.10.x 또는 Phase 1+ 에서 asset scope 추가 검토

발견된 trade-off:
- Phase 0.9.2 의 종목별 lock-in 패턴 (005930 / 015760 / 097950) 은 현재
  portfolio scope 로는 차트 1 장 (chart_symbol 인자 — default 첫 자산)
  만 시각화. 종목별 panel + 다중 차트는 asset scope 후속.

### 4.6 sub-step 압축 가능성 — 인프라 phase 의 본질

Phase 0.10 sub-step 흐름 = 1 일 완료 (6 commits). Phase 0.7 / 0.9 (각
시리즈 약 13~18 commits) 대비 압축. 본질:

- 인프라 강화 phase 는 **가설 / 게이트 평가 zero** → 결과 분석 / 박제
  / 회고 / 게이트 판정 sub-step 불필요
- 도메인 엔티티 추가 zero → 회귀 invariant 검증 sub-step 불필요
- 외부 의존성 (mplfinance 등) extras 격리 → 핵심 백테스트 영향 zero
  → 통합 회귀 sub-step 부담 zero

→ 향후 인프라 phase (Phase 0.11+ 또는 Phase 1+ 분석 도구 확장) 도 동일
패턴 적용 가능 — sub-step 압축으로 빠른 진행.

---

## 5. 발견된 이슈 / 제약

### 5.1 mplfinance "too much data" warning — Phase 0.10.x 처방

§4.3 박제. 정적 PNG 에서 5-year 일별 캔들은 너무 조밀. Phase 0.10.x
처방:
- generate_episode_report 가 chart 에 episode window 만 전달 (현재는
  chart 내부 필터)
- 또는 mpf.plot 에 `warn_too_much_data=N` (충분히 큰 N) 설정

### 5.2 asset scope 미구현 (Phase 0.10.e)

§4.5 박제. ADR §5.5 의 "portfolio + asset + both" 중 asset / both 미
구현. Phase 0.9.2 의 종목별 lock-in 진단 가치 ↑ → Phase 0.10.x 우선
순위 ↑. 후속 처방:

- per-asset equity curve 추출 (PortfolioSnapshot.valuations[].market_value)
- 종목별 detect_drawdown_episodes 호출 → Episode 의 asset_code 필드 활용
- HTML 출력 시 종목별 분리 (asset_label 표시)
- chart_symbol 도 asset scope 시 자동 매핑

### 5.3 single-strategy assumption — Phase 1+ 다중 전략

ADR §3.4 박제. Phase 0.10 = single-strategy assumption (BacktestRunner
가 단일 buy_strategy_name 보유). Phase 1+ 다중 전략 운용 시:

- BuyActionRecord / SellActionRecord 에 strategy_name field 추가
- 또는 Decision.reasoning["strategy_name"] 로 영구화
- 다중 전략 trades_from_decisions 변환 시 per-action strategy_id 매핑

→ Phase 1 ADR 0007 박제 항목.

### 5.4 chart_symbol 단일 자산 한정

§4.5 박제. portfolio scope 시 chart 는 단일 자산 (chart_symbol, default
첫 자산). 다중 자산 동시 시각화 미지원. Phase 0.10.x 검토:
- 다중 차트 (subplot 격자)
- 또는 합성 portfolio 가격 (가중 평균) chart

### 5.5 reporting extras 의존성

ADR §6.1 박제. matplotlib / mplfinance / pandas 의존성 = `[reporting]`
extras. 핵심 백테스트는 의존성 zero → 깔끔한 격리. 단:
- CI / dev 환경에서 `uv sync --extra dev --extra reporting` 필요
- mplfinance 0.12.10b0 (beta) — stable release 시점 검토 필요

### 5.6 1 일 완료의 신뢰성

Phase 0.10 = 1 일 완료. 빠른 진행은 인프라 phase 본질 정합이지만:
- mplfinance 통합 시점에 제대로 cross-platform 테스트 부족 (macOS only)
- 다양 episode 시나리오 (예: peak-to-trough 매우 짧은 / 긴 / threshold
  근처 등) 로 stress test 추가 검토
- Phase 0.10.x 정교화 시 본 ramp-up 비용 회수

---

## 6. ADR §12 박제 결과 (sub-step 0.10.f)

ADR 0006 §12 박제 = Acceptance Criteria 5 항목 정식 검증 (본 commit
동시).

요약:
- AC1 ✅ episode 별 리포트 생성 성공 (Phase 0.9.2 4 episodes)
- AC2 ✅ 세븐 스플릿 B1~B7 라벨 (test_seven_split_renderer.py)
- AC3 ✅ 신규 dummy strategy 코어 변경 zero (test_dummy_strategy.py)
- AC4 ✅ ADR-1 / -2 / -3 박제 (ADR §3 / §4 / §5)
- AC5 ✅ 단위 테스트 커버리지 향상 (797 → 947, +150)

---

## 7. 후속 권고 (Phase 0.10.x / Phase 1)

### 7.1 Phase 0.10 종료 결정 (라운드 #17, 0.10.g)

**Phase 0.10 종료 + Phase 1 진입 강력 권고**:

- Acceptance Criteria 5 항목 모두 충족
- 인프라 본질 100% 충족 (analytical reporting layer)
- Phase 0.9.2 실데이터 E2E 검증 완료 (4 episodes 시각적 진단)
- 추가 정교화 (asset scope / 다중 차트 / stress test) 는 Phase 0.10.x
  또는 Phase 1+ 후속 가능

### 7.2 Phase 0.10.x 가능성 (낮음)

§5 발견된 이슈 처방 후보:
- §5.1 mplfinance warning 처리
- §5.2 asset scope 추가 구현
- §5.4 다중 자산 차트 (subplot)
- §5.6 stress test (다양 episode 시나리오)

→ 모두 Phase 1 ADR 0007 또는 Phase 1+ 후속 검토 가능. 우선 순위 낮음.

### 7.3 Phase 1 ADR 0007 박제 항목 (10 항목, ADR 0005 §10.6.3 박제 인용)

Phase 0.10 종료 + Phase 1 진입 시 다뤄질 결정:

1. KIS API 어댑터 (BrokerPort / MarketDataPort)
2. 손절 정책 — Phase 0.9 lock-in 데이터 근거 (Phase 0.10 Episode 4 시각화)
3. 자본 배분 정교화 — Phase 0.9.2 insufficient_balance 1299회 데이터
4. 텔레그램 알림
5. 종목별 vs 전체 kill switch / 자산 격리 정지
6. partial fill 처리 ADR
7. 거래세 / 수수료 모델링 (`OrderResult.tax` / `commission`)
8. 모의투자 → 실거래 전환 게이트
9. SupportLevelStrategy + cooldown 도입 검토 (ADR 0004 §7.3.2)
10. **자산군 분산 회복 (Phase 0.7.3 골드 + KR 주식)** — Phase 0.9 일반화
    박제 데이터 근거 (Phase 0.10 Episode 1/3 비교 분석 가능)

### 7.4 다중 전략 운용 (Phase 1+)

§5.3 박제. Phase 0.10 single-strategy assumption → Phase 1+ 다중 전략:

- BuyActionRecord / SellActionRecord 에 strategy_name 추가 또는
  Decision.reasoning["strategy_name"] 로 영구화
- StrategyRendererRegistry 의 정적 dict → 동적 plugin discovery
  (entry points 또는 yaml-driven)
- 다중 strategy 동시 운용 시 portfolio level 복합 분석

---

## 8. 지표 요약

| 지표 | Phase 0.10 |
|---|---|
| sub-step 수 | 6 (a/b/c/d/e/f, g 후속) |
| commit 수 | 6 |
| 신규 모듈 | 7 (`src/application/reporting/{__init__,trade_view,episode,report}.py`, `src/ports/strategy_renderer.py`, `src/adapters/reporting/{chart,html_writer,renderer_registry}.py`, `src/adapters/reporting/renderers/{__init__,seven_split,default}.py`) |
| 신규 의존성 | 3 (matplotlib / mplfinance / pandas, `[reporting]` extras) |
| 도메인 엔티티 추가 | **0** (view model only) |
| 기존 코드 변경 | **0** (Decision / BuyActionRecord / BacktestResult / yaml loader 모두 그대로) |
| 신규 단위 테스트 | +150 (797 → 947, +18.8%) |
| Phase 0.9.2 E2E episodes | 4 (1 unrecovered, 3 recovered) |
| Acceptance Criteria | **5/5 충족** |

---

## 9. Phase 0.10 → Phase 1 진입 체크포인트

- [x] ADR 0005 §11 (라운드 #15 — Phase 0.9 종료 + Phase 0.10 진입) 박제
- [x] ADR 0006 §1 (라운드 #16 — Phase 0.10 진입) + §3 / §4 / §5 (ADR-1/-2/-3) 박제
- [x] sub-step 0.10.b — TradeView + DrawdownEpisode + detector + 단위 테스트
- [x] sub-step 0.10.c — Renderer Protocol + SevenSplit/Default + Registry + 단위 테스트
- [x] sub-step 0.10.d — chart (mplfinance) + html_writer (stdlib) + 단위/통합 테스트
- [x] sub-step 0.10.e — report use case + Phase 0.9.2 E2E + AC3 검증
- [x] 본 narrative 회고 (`phase-0.10.md`)
- [x] ADR 0006 §12 박제 (Acceptance Criteria 5 항목 검증)
- [ ] sub-step 0.10.g — Phase 0.10 종료 결정 라운드 #17 + Phase 1 진입 trigger — 다음
- [ ] Phase 1 진입 결정 라운드 (ADR 0007 가칭) — 후속

---

> Phase 0.10 narrative 회고 완료. 다음 단계 = sub-step 0.10.g (Phase 0.10
> 종료 결정 라운드 #17 + Phase 1 진입 trigger). 사용자 명시 결정 후 박제.
