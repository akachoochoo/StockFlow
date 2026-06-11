# CLAUDE.md 슬림화 박제 (2026-06-12)

> CLAUDE.md 816 lines → 슬림화 시 제거된 섹션의 verbatim 보존.
> 제거 사유: (1) `docs/roadmap.md` / ADR 정본과 1:1 중복, (2) §16 자체 적용
> 조건 ("Phase 1 진입 전까지") 만료 — ADR 0012 박제 + ADR 0019~0023 +
> KIS 어댑터 코드 존재로 Phase 1.x 진입 사실 확정.
> 규범 규칙 (아키텍처/돈/시간/주문/예외/안전장치/작성 금지 중 현재 유효분) 은
> CLAUDE.md 에 압축 유지 — 본 파일은 history 전용.

---

## 제거 1: §14 "현 상태 (2026-05-21)" bullets + 완료 phase 인덱스 테이블

**정본**: `docs/roadmap.md` "현재 상태" 테이블 (동일 내용 1:1 중복이었음) +
각 ADR (`docs/decisions/adr-0001~0023`) + 회고 (`docs/retrospectives/`).
CLAUDE.md 에는 현 상태 요약 + 정본 포인터만 유지.

### 원문 — 현 상태 (2026-05-21)

- Phase 0.10 시리즈 (0.10 ~ 0.10.bb) 정식 종료 — 라운드 #22 (2026-05-11, ADR 0006 §18).
- **Phase 0.11.a** (DGT Research-Namespace Overlay) 정식 종료 — 라운드 #23 (2026-05-12, ADR 0007 §3). G1+G3+G4 PASS / G2 INFORMATIONAL FAIL (R1 일봉 ≠ 분봉). D10 = archive. DGT registry 미합류.
- **Phase 0.11.b** (DGT Parameter Tuning & Sensitivity Analysis) 정식 종료 — 라운드 #24 (2026-05-13, ADR 0008 §3). G1+G3+G4 PASS / G2 INFORMATIONAL FAIL (D11 DSR 0/95 구조적 unattainable). D10 = archive 확정 (supersede 없음). DGT registry 미합류 유지.
- **Phase 0.11.c** (Strategy-Specific Backtest Visualization Renderers) 정식 종료 — 라운드 #25 (2026-05-13, ADR 0009 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = permanent.
- **Phase 0.11.d** (Asset-Specific Strategy Differentiation Diagnosis & Design) 정식 종료 — 라운드 #26 (2026-05-13, ADR 0010 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = deferred reference. 본질 = *분석 phase 의 분석 phase*. D11 AND-gate 4/4 충족 — 후속 결정 라운드 진입 자격 완성.
- **Phase 0.11.e** (Dynamic Adjustment Proposal Engine L2/L3) 정식 종료 — 라운드 #27 (2026-05-14, ADR 0011 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = 5th ring 영구 유지 (D13). 신규 5th ring `src/research/dynamic_adjustment/` 10 파일 (~1403 LOC) + 141 tests (regression zero). §1.6 Design Contract 6 invariant **측정 가능 verification** + D14 structural constraints (12주 / ±30% / cooldown) + D15 governance 박제. **Phase 1 진입 ready 선언** — ADR 0012 D16 (ii) 5/6 충족 (잔여 = paper trading + NTP).
- **Phase 0.11.f** (DGT Paper-Faithful + Adaptive Hybrid + Multi-Asset Portfolio) 정식 종료 — 라운드 #28 (2026-05-15, ADR 0013 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = 5th ring 영구 (permanent-research-only). 4 runner (dynamic/adaptive/paper/paper_adaptive) + multi-asset portfolio B&H 벤치마크. 핵심 발견: **MDD 14-16% 일관성** (시장 regime/종목 수 무관) + Hyb-Daily 최적 DGT 구성 + 상승장 B&H 압도적 우위 (DGT 구조적 한계). 75 new tests (173 total DGT tests), inner ring 변경 zero.
- **Phase 0.11.g** (DGT Rebalancing Alpha — Core-Satellite + Asymmetric Grid) 정식 종료 — 라운드 #29 (2026-05-17, ADR 0014 §3). G1 PASS / **G2 FAIL** (H1 alpha ≤ 0, H2 monotonic). Lifecycle = 5th ring 영구 (permanent-research-only). Core-Satellite runner + Asymmetric Grid runner + 16-config sweep CLI. 핵심 발견: **리밸런싱 알파 없음** (bull -6~-12%, bear 근소 음수) + 비대칭 grid 하락장 MDD 23-25% (18% hard stop 초과) + Phase 1 권고: 정적 배분, DGT = MDD 방어 전용. 28 new tests (1551 total), inner ring 변경 zero.
- **Phase 0.11.h** (DGT Backtest Report Chart Upgrade — Candlestick + Volume) 정식 종료 — (2026-05-17, ADR 0015 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = permanent. 신규 `src/research/dgt/_candles.py` (공유 `_draw_candles`/`_draw_volume` helper) + `kakao_dgt_backtest.py` + `_dgt_renderer.py` 캔들+거래량 2-panel 전환 + bar-count-adaptive width (`min(40,max(14,n/55))`). ADR 0009 D4 evolution (not supersede) — mplfinance 미사용, manual matplotlib, Option A synthesis. 24 new tests (1575 total), inner ring 변경 zero.
- **Phase 0.11.i** (Interactive DGT Charts — lightweight-charts) 정식 종료 — (2026-05-17, ADR 0016 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = permanent (interactive) + archival-with-sunset (static matplotlib). vendored `lightweight-charts.standalone.production.js` (~50 KB, offline) + `_interactive_chart.py` HTML builder + `kakao_dgt_backtest.py` + `_dgt_renderer.py` interactive 전환 + `fmt` kwarg Protocol Option (iii). ADR 0006 §14.4 Option C + ADR 0009 D4(b) 역전 (research-scoped). plotly/narwhals uninstalled. 75 new tests (1650 total), inner ring 변경 zero.
- **Phase 0.11.j** (DGT Interactive Chart Improvements — time-varying grid + toggles + Trade Logs) 정식 종료 — (2026-05-18, ADR 0017 §3). **게이트 4/4 PRIMARY PASS**. Lifecycle = 5th ring 영구. 신규 `src/research/dgt/_grid_reconstruction.py` (`_reconstruct_grid_envelope` — ATR/ADR branch, Decimal-only) + `_interactive_chart.py` + `kakao_dgt_backtest.py` 수정. ADR-measure correction (adaptive_cfgs gap 버그 fix) + ADR 0016 §12.4 #6 CLOSED. 64 new tests (1716 total), inner ring 변경 zero.
- **Phase 0.11.k** (DGT On-Breach 전략 + Entry Controls — option A) 정식 종료 — (2026-05-21, ADR 0018 §1+§3). **G1/G3/G4 PASS / G2 REGIME-SPLIT** (5y 분산 멀티 risk-adjusted PASS — On-Breach-5%+D+B 가 처음으로 B&H 를 Sharpe·Calmar·MDD 상회 / 1y 강세장 FAIL — B&H +186% vs DGT +38%). Lifecycle = 5th ring 영구 (registry 미합류). 사용자 주도 인터랙티브 리뷰 → 반복 개선. `_DGTDynamicRunner` opt-in 플래그 4종 (profit_guard / adaptive ADR-k / flat_allocation / max_invested_pct, 기본 off → 회귀 zero) + `--strategy-set breach` 6전략 sweep + 멀티 인터랙티브/누적실현 버그 2건 수정. 핵심 재확인: 그리드 재중심 = 평단 이하 매도 원인 / DGT = MDD 방어·횡보 수확 도구, 추세장 수익 아님 (ADR 0014 정합). 12 new tests (1716→1728), inner ring 변경 zero.
- Phase 1 진입 결정 대기.

### 원문 — 완료 phase 인덱스 테이블

(`docs/roadmap.md` "현재 상태" 테이블과 1:1 중복 — roadmap.md 가 정본이므로
verbatim 재수록 생략. 당시 CLAUDE.md §14 테이블 = Phase 0 ~ 0.11.k 22 rows,
컬럼 = Phase / 종료일 / 본질 / 결과 / ADR / 회고.)

**핵심 학습** (Phase 0.7 ~ 0.9, ADR 0005 §9.6.2 박제):
**자산군 분산 = H3 회복의 충분 조건** (3 회 반복 검증). 단일 자산군 (전부 주식
/ 전부 채권) 은 분산 효과 약화 → H3 FAIL 패턴. Phase 0.7.3 (주식+골드) =
시리즈 첫 3/3 PASS. "PriceDropStrategy + 분산이 본질" 정신 박제.
→ 이 학습은 CLAUDE.md §14 에 1줄로 압축 유지.

---

## 제거 2: §16 "Phase 1 호환성 의식" 전체

**만료 사유**: §16 헤더 자체 조건 = "분석 phase + Phase 1 진입 전까지 적용".
ADR 0012 박제 (commit `e066554`) + Phase 1.1 (ADR 0019~0021) + Phase 1.x
(ADR 0022~0023) 진입으로 적용 기간 종료. §16.4 트리거 항목은 ADR 0012 가
정본으로 박제 완료. §16.1 의식 항목 중 살아있는 정신 (partial fill 차단,
reconciliation 전체 정지) 은 CLAUDE.md §4.4 / §11.2 규범 규칙으로 이미 존재.

### 원문 — §16 (2026-05-21 시점 verbatim)

> **조건부 룰**. Phase 0.10 시리즈 (0.10 ~ 0.10.bb) 정식 종료 (라운드 #22,
> ADR 0006 §18 박제, 2026-05-11) 후 사용자 분석 phase 동안 본 §16 적용.
> Phase 1 진입 결정 보류 — 그동안 reporting layer 외 코드 변경 zero +
> Phase 1 호환성 의식 유지. Phase 0.11 결정은 다음 session.
>
> 선행 phase 별 의식은 각 phase 의 ADR (0002 ~ 0006) 에 박제. 본 §16 은
> Phase 1 진입까지의 _현재_ 의식만 유지.

#### 16.1 패턴 (의식 — 코드 추가는 금지)

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

#### 16.2 작성 금지

§14 "Phase 1 진입 전 작성 금지 (통합 목록)" 참조. 완료 sub-step
(Phase 0.7 ~ 0.10.bb) 의 🔒 작성 경계 / ❌ 거부 결정은 ADR 0003 ~ 0006
박제가 정본 — 인용 시 해당 ADR 직접 참조:

- Phase 0.7 박제 → ADR 0003 (§15 ~ §19)
- Phase 0.8 박제 (SupportLevel 보존 + cooldown 거부) → ADR 0004 §7
- Phase 0.9 박제 (개별 주식 인프라 + 자산군 분산 일반화) → ADR 0005
- Phase 0.10 박제 (reporting layer + 가독성 + per-symbol + cleanup) → ADR 0006 §3 ~ §18

#### 16.3 의심 시 가이드

Mock 환경 + Phase 0.7.3 baseline (069500 + 132030, EQUAL,
PriceDropStrategy) 비교 가정 유지. 사용자 확인 없이 호가 가변 / 거래세
/ KIS API / 손절 / 텔레그램 인터페이스 짜기 금지 (CLAUDE.md §13.3
"친절한 추가 금지" 정신). 검토 필요한 영역에는 `# Phase 1 ADR 박제 후
검토` 주석 추가.

#### 16.4 Phase 1 ADR 0012 트리거 항목

> 재번호 history: 이전 가칭 = ADR 0007 (Phase 0.11.a DGT 점유로 stale)
> → ADR 0008 (Phase 0.11.b DGT tuning 점유로 stale) → **ADR 0012**
> (ralplan #28, commit `e066554` 박제). 본 §16.4 재번호 정정 = Phase
> 0.11.e.5 follow-up commit (A), ADR 0011 §1.9 + §3.5 R7 mitigation 정합
> (2026-05-14).
>
> 하위 재번호 (Phase 1.1 Stage 0.2, 2026-05-21): D17 DB 마이그레이션 ADR
> 가칭 **0013 → ADR 0019**. 0013 은 Phase 0.11.f (ADR 0013) 가 점유, 0019
> free 확정 (0001~0018 존재). 0007→0008→0012 와 동일한 "가칭 번호가 후속
> Phase 점유로 stale" 패턴 — 트리거 항목 (5) DB 마이그레이션은 ADR 0019
> 로 박제. ADR 0012 D17 / §1.8 1.1.1.c 정합 갱신.

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

## 제거 3: §14 "Phase 1 진입 전 작성 금지 (통합 목록)" 원문

만료된 "— Phase 1" 항목 (KIS 어댑터 / 손절 / 텔레그램 / partial fill 등 —
ADR 0012/0019~0023 으로 Phase 1 진입·박제 완료) 은 해당 ADR 이 정본.
현재도 유효한 금지/보존 항목은 CLAUDE.md §14 에 압축 유지.

### 원문 (2026-05-21 시점 verbatim)

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
- 그리드 트레이딩 — Phase 0.11.a 완료 (2026-05-12, ADR 0007 §3, D10 = archive). 분봉 DGT 재검토 = ~~Phase 1 ADR 0012 진입 후 별도 결정 라운드~~ → **ADR 0023 (2026-05-30 박제)** 정본. ADR 0022 §13 일봉 grid-live 인프라 = 코드 보존 + 운영 동결 (ADR 0023 D5/D17).
- 종목 선정 자동화 / 박영옥 가치주 자동 식별 — Phase 2+
- 일중 데이터 (분봉 / 틱) — Phase 0 ~ 0.10 = 일봉 (pykrx) only
- 보존 (변경 금지, 회귀 invariant): `PriceDropStrategy` / `SupportLevelStrategy` /
  `SupportSlot` / `src/domain/indicators/` / Phase 0.10 reporting layer
  (TradeView / DrawdownEpisode / Renderer Protocol / SevenSplit slot palette /
  StrategyInfo / risk_metrics) — sub-step 박제 후 정본은 ADR 0004 §7.4.2 +
  ADR 0006 §3~§18
- "추후 Phase 1 확장 가능하게" 만든 unused parameter — CLAUDE.md §13.3
