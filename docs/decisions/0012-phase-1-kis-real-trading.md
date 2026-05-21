# ADR 0012 — Phase 1: KR 주식 실거래 (KIS API 소액 운영)

> **Status**: §1 박제 완료 (ralplan #28 Round 2 APPROVE-WITH-RESERVATIONS, 2026-05-12 — Round 1 ITERATE 24 patches + Round 2 2 BLOCKING 수치 정정 + G1 MINOR 정정). Phase 1.1 진입 = D16 (i)~(vi) 6 조건 *모두* 충족 후 + Phase 0.11.b/c/d/e sub-step .2~.5 실행 완료 + 별도 2 commit (§16.4 + §16.1 항목 #2) + Phase 1 entry decision 라운드 #29 (가칭, KIS API 문서 검토) 후.
> **Date**: 2026-05-12 (draft) / 2026-05-12 (§1 Round 1 ITERATE 24 patches 흡수 + Architect critical findings + Critic 독립 발견 4 + 5 Missing gaps + 2 Ambiguity + Open Q 별도 결정 라운드 박제) / 2026-05-12 (§1 Round 2 APPROVE-WITH-RESERVATIONS + 2 BLOCKING 수치 정정 (G2.1~G2.3 자본/기간 + D6 (ii) 40회) + G1 MINOR 정정 ((i)~(vi) 6 조건)) / `<TBD>` (§3 박제 + 별도 2 commit §16.4 + §16.1 항목 #2 정정).
> **Supersedes**: 없음. ADR 0003 §19.4 + ADR 0004 §7.4.2 "종목별 다른 정책 보류" 조건부 supersede 가능 (D8 채택 시, ADR 0010 §3 회고 정합).
> **Related**:
> - **CLAUDE.md preamble** — "실계좌가 연결될 자동매매 시스템. 한 번의 버그가 돈으로 직결" + "'동작하는 것 같다' ≠ '안전하다'".
> - **CLAUDE.md §16.4** — Phase 1 ADR 0012 (재번호) 트리거 9 결정 항목 (ADR 0011 §1.9 박제, 본 ADR 진입 시점 = 0.11.e.5 회고 후 별도 commit 으로 정정 박제 후 진입).
> - ADR 0001 (Phase 0) — Mock + paper trading 정본.
> - ADR 0002 §3 (partial fill 차단 정신) + §12.4 (손절 정책 + 매도 임계 보류).
> - ADR 0003 §8.6 (전체 kill switch) + §19.4 (종목별 다른 정책 보류).
> - ADR 0004 §7.3.2 (cooldown 거부 박제).
> - ADR 0005 §1.9 (Phase 1 KIS API + 손절 + 거래세 / 수수료) + §10.6.3 (Phase 1 후보).
> - ADR 0008 §1.7 (D11 D10 supersede 가능성) — DGT promote/archive 영향.
> - ADR 0009 §1.4 G2 (comparison mode) — 실거래 의사결정 시각 진단 인프라.
> - ADR 0010 §1.3 D3/D4 (자산-전략 결합 후보 / sell strategy 차별화) — D8 종속.
> - **ADR 0011 §1.6 Design Contract 6 invariant + D14 ProposalHistory + D15 governance** — 본 phase 운영 중 파라미터 변경 / 전략 교체 / 종목 변경 의무 흡수.
> - `docs/multi-asset-trading-system-design.md` §11 (KIS API spec) + §8 (안전장치).
> **Execution order**: ADR 0008/0009/0010/0011 §1 박제 commit 완료 (라운드 #24~#27, 2026-05-12 완료) + 0.11.b/c/d/e sub-step .2~.5 실행 완료 + 0.11.e.5 회고 commit + 별도 2 commit ((A) §16.4 ADR 0008→0012 재번호 (B) §16.1 항목 #2 정정) 완료 후 본 ADR §1 박제 진입.

---

## 1. Decision Drivers (ralplan #28 라운드 1 박제 대상)

### 1.1 사용자 spec verbatim

**Phase 1 정의 (ADR 0001 + CLAUDE.md §14 + 다음 phase trajectory 정합)**:

> "KR 주식 실거래 (KIS API 소액). 100~500만원 소액. 차단기 비활성, 룰만 검증. 1~2개월 운영." (CLAUDE.md §14 "Phase 1 (예정, 가칭) — KR 주식 실거래 (소액)")

**사용자 명시 2026-05-12 (ralplan #28 진입 시)**:

> "ralplan #28 (0012/Phase 1 — KIS 실거래) 진입, 최종 진행전에 주의 사항 모두 숙지 하고 시작하길 바래"

본 ADR §1 박제 의무 = Phase 1 진입 전 *모든 주의 사항* 의 정본 박제 + entry readiness audit.

### 1.2 Phase 0.11.b/c/d/e 산출 흡수 + CLAUDE.md §16.4 9 트리거 항목 정합

**Phase 0.11 4 ADR 박제 사이클 완료 (2026-05-12)** — ralplan #24~#27:

| ADR | Phase | 본 phase 흡수 |
| --- | --- | --- |
| 0008 | 0.11.b DGT Parameter Tuning | D11 trigger 결과 (DGT promote/archive) → 본 phase 자산 universe 결정 (D11) 입력 |
| 0009 | 0.11.c Visualization Renderers | comparison mode + `_align_results_for_overlay` → 본 phase 실거래 의사결정 시각적 진단 인프라 (D14 모니터링 입력) |
| 0010 | 0.11.d Asset-Specific Diagnosis | D3 (4 후보 trade-off + 현재 구현 상태) + D4 (sell strategy 차별화 3 후보) → 본 phase D8 (종목별 다른 정책) 결정 입력 + D9 (cooldown) supersede 시나리오 |
| 0011 | 0.11.e Dynamic Adjustment L2/L3 | §1.6 6 invariant (시스템은 제안만 / Reflexive overfitting / ADR 박제 차단 / §13.3 / sell strategy 종속) + D14 ProposalHistory + D15 governance → 본 phase 운영 중 파라미터/전략/종목 변경 의무 흡수 (D13) |

**CLAUDE.md §16.4 9 트리거 결정 항목** (Phase 1 ADR 진입 시 박제 의무, ADR 0011 §1.9 명시):

1. KIS API 어댑터 (BrokerPort / MarketDataPort 구현) → **D1**
2. 손절 정책 — H3 거짓 대응 (ADR 0002 §12.4.2) → **D2**
3. 텔레그램 알림 (의사결정 / 매도 / Reconciliation 불일치) → **D3**
4. 종목별 vs 전체 kill switch / 자산 격리 정지 (ADR 0003 §8.6 후속) → **D4**
5. partial fill 처리 ADR → **D5**
6. 모의투자 → 실거래 전환 게이트 → **D6**
7. 매도 임계치 +15 / +20 % 비교 backtest (ADR 0002 §12.4.1 보류) → **D7**
8. 종목별 다른 정책 허용 여부 (ADR 0003 §7.3 / §19.4 보류, ADR 0010 D3 종속) → **D8**
9. SupportLevelStrategy + cooldown 도입 검토 (ADR 0004 §7.3.2 거부 박제 인용 후 결정) → **D9**

**추가 결정 항목** (Phase 1 특수 — §14 9 항목 외):

10. **자본 규모** (CLAUDE.md §14 "100~500만원 소액") → **D10**
11. **자산 universe** (Phase 0.7.3 baseline 069500+132030 EQUAL vs 확장) → **D11**
12. **안정화 기간** (CLAUDE.md §14 "1~2개월 운영") → **D12**
13. **0.11.e D14 ProposalHistory + structural constraints 진입** (운영 중 변경 governance) → **D13**
14. **모니터링 + Reconciliation 주기** (CLAUDE.md §11.2) → **D14**
15. **비상 대응 (kill switch / halt protocols)** (CLAUDE.md §11.1 + ADR 0003 §8.6) → **D15**
16. **진입 시점 readiness audit** (0.11.b/c/d/e sub-step .2~.5 실행 완료 + 별도 2 commit 완료 + paper trading 무사고 운영) → **D16**

### 1.3 Decision Questions (D1~D20, ralplan #28 박제 대상 — Round 1 ITERATE 후 D17~D20 신규)

> 본 절은 **skeleton**. ralplan #28 Round 1 Critic/Architect 가 D 항목을 추가/병합/거부할 수 있음. 본 phase 의 *모든 D 결정* 은 §1.1 사용자 명시 "주의 사항 모두 숙지" 정합 — 각 결정의 cascading 영향 surface + risk profile 박제 의무.

#### CLAUDE.md §16.4 9 트리거 항목

- **D1** — **KIS API 어댑터 구현 범위 — read/write endpoint 2 단계 분할** (Round 1 ITERATE Patch 1):

  **(c-read) 우선 구현 + 안정화**: `BrokerPort.get_balance()` + `BrokerPort.get_positions()` + `BrokerPort.get_order_status()` + `MarketDataPort.get_price()` + `MarketDataPort.get_ohlcv()` (일봉 only, pykrx fallback 보존) + `MarketDataPort.is_market_open()` + `MarketDataPort.next_market_close()` — KIS API 인증/응답 schema 안정성 확보. paper trading (D6 (iv-a) + (iv-b)) 기간 검증.

  **(c-write) read 안정화 후 구현**: `BrokerPort.place_order()` + `BrokerPort.cancel_order()` — write 진입은 (c-read) 무사고 5 영업일 후 + KIS schema validation 통과 후.

  거부: (a) BrokerPort 만 = MarketDataPort = pykrx 유지 → 실거래 의사결정 지연 (pykrx 15+ 분 lag). (b) BrokerPort + MarketDataPort 일봉만 = paper trading 정합 OK 이나 잔고 reconciliation 불가. 권고 default = **(c-read → c-write 단계 분리)** — 실계좌 write endpoint 버그 = 돈 손실 직결 차단.

- **D2** — **손절 정책 — -20% default 박제 + (b') 매도 권고 알림 신규** (Round 1 ITERATE Patch 2 + 3):

  | 후보 | 임계 | 자동 매도? | 추가 매수 정지? | 알림? | 채택? |
  | --- | --- | --- | --- | --- | --- |
  | (a) 손절 부재 | — | ❌ | ❌ | ❌ | ❌ — Phase 0~0.11 invariant 단순 보존, R4 mitigation 부재 |
  | **(b) -20% 추가 매수 정지** | **-20%** | ❌ | ✅ | ❌ | 부분 채택 — (b') 와 결합 |
  | **(b') -20% 추가 매수 정지 + 매도 권고 알림** | **-20%** | ❌ | ✅ | ✅ 텔레그램 사람 매도 검토 권고 | **✅ default 채택** |
  | (c) -20% 자동 매도 | -20% | ✅ | — | ✅ | ❌ — 0.11.e §1.6 #1 + CLAUDE.md §11.4 "자동 손절 안 함" invariant 위반 |

  **(b') 채택 근거**: 평가손 -20% 도달 시 (1) 추가 매수 *자동* 정지 + (2) 텔레그램 "사람 매도 검토 권고" 알림 (D3 (b) 인프라 활용). 자동 매도 = 절대 금지. 사람이 CLI `trading manual-sell <asset> <quantity>` 명시 명령 후 실행. **-20% default 근거**: Phase 0.9.2 MDD -37.65% (ADR 0005 §10.3) 의 약 절반 + Phase 0.7.3 MDD -14.2% 와 충분한 buffer (false trigger 방지) + 자본 200만원 시 -20% = 40만원 손실 한계 (자본 보존 trade-off). 1.1.1.b sub-step backtest (-15% / -20% / -25% 3 후보) 결과 흡수 후 정정 가능 (Phase 1.1 진입 전). **Stage 1.1.b backtest 결과 박제 (2026-05-22, `docs/research/phase-1.1.b/`)**: -15/-20/-25% 모두 본 윈도우/정책 (drop 5% + 일 1회 + cooldown 60 + 7-split) 에서 **inert** (유효 차단 0 — 손실 임계 도달일에 PriceDropStrategy 가 이미 매수 안 함; 4-run byte-identical, faithfulness gate PASS). → 손절-추가매수-차단은 backtest 최적화 불가 = **라이브 안전장치** 성격 (ADR 0014/0011 정신 정합). 사용자 결정 = **-20% 유지** (ADR 기본값 확정). SL 효용은 더 공격적 매수 정책 (큰 max_split_per_day / 짧은 cooldown / 작은 drop) 에서만 측정 가능.

- **D3** — **텔레그램 알림 도입 + 알림 종류 7 + 빈도 명시** (Round 1 ITERATE Patch 17, TBD 제거):

  **권고 default**: (b) 텔레그램 + Console 이중 (R8 mitigation 정합) — CLAUDE.md §14 "텔레그램 알림 — Phase 1" 정합. 외부 도구 (Grafana 등) = Phase 2+.

  **알림 종류 7 명시 박제**:
  | # | 종류 | 시점 | 레벨 | 비고 |
  | --- | --- | --- | --- | --- |
  | 1 | 매수 의사결정 실행 | 의사결정 cron 종료 직후 | INFO | 종목 / 수량 / 가격 / split_level |
  | 2 | 매도 체결 | 매도 cron 종료 직후 | INFO | 종목 / 수량 / 체결가 / 실현 P&L |
  | 3 | Reconciliation 불일치 | D14 일 2 회 reconciliation 시 | **CRITICAL** | hard halt 동반 (D15 (b) 정합) |
  | 4 | Kill switch 발화 | `TRADING_HALT=1` set 시 | **CRITICAL** | 사람 명시 / 자동 발화 모두 |
  | 5 | 손실 한도 도달 (D2 (b')) | 평가손 -20% 도달 시 | WARNING | 추가 매수 정지 + 사람 매도 검토 권고 |
  | 6 | KIS API outage / token 만료 | API 에러 발생 시 | ERROR | hard halt 동반 (D15 (c) 정합) + §1.10 시나리오 E |
  | 7 | 일일 요약 | 매일 종가 후 1회 | INFO | 당일 의사결정 / 잔고 / P&L / Reconciliation 결과 |

  **빈도**: 이벤트 발생 시 즉시 (1~6) + 매일 종가 후 1회 (7).

- **D4** — **Kill switch 분리 범위**: (a) 전체 kill switch 유지 (ADR 0003 §8.6 invariant), (b) 종목별 kill switch 도입 (CLAUDE.md §16.1 항목 #1 의식 → 코드 승격), (c) 자산 격리 정지 (자산 type 단위, ADR 0003 §8.6 후속). **권고 default**: **(a)** 전체 kill switch 유지 — Phase 1 안정화 우선, 종목별/자산별 격리는 Phase 2+ 위임 (Phase 1 안정화 6개월 후 데이터 기반 재검토). 후보 (b)/(c) 거부 사유 = cascading risk + Phase 1 단계 적합도 부족.

- **D5** — **Partial fill 처리 방식**: (a) Partial fill 차단 (ADR 0002 §3 정신 보존 — partial fill 발생 시 별도 차수 인정 안 함 + 100% 체결 시만 split_level 증가), (b) Partial fill 시 비례 할당 + split_level 분수 (예: 0.5), (c) Partial fill 시 잔여 quantity 재주문. **권고 default**: **(a)** — ADR 0002 §3 정신 그대로 + CLAUDE.md §4.4 "부분 체결은 별도 차수로 인정 안 함" 정합. 후보 (b)/(c) 거부 사유 = idempotency 위반 + reconciliation 복잡성 폭증.

- **D6** — **모의투자 → 실거래 전환 게이트 — Paper trading 2 단계 분할 + 측정 가능 형태** (Round 1 ITERATE Patch 4 + 5 + Ambiguity 1 해소):

  **권고 default**: 다음 5 조건 *모두* 충족 시 전환:

  - **(iv-a) KIS Mock server 무사고 5 영업일** (Round 1 ITERATE Patch 4 분할 (a)) — 로컬 Mock + KIS API schema 정합 검증 (Pydantic response model parse). Unit / integration test 수준 = idempotency_key + partial fill 차단 + Pydantic schema strict.

  - **(iv-b) KIS 모의투자 서버 무사고 5 영업일** (Round 1 ITERATE Patch 4 분할 (b)) — 실제 KIS paper trading API (`openapivts.koreainvestment.com`) e2e. 네트워크 지연 / rate limit / token 갱신 / 실 호가 반영 / KIS schema 실 응답 검증.

  - **(ii) 잔고 reconciliation 40 회 *모두* 일치** (Round 2 산술 정정 — paper trading 10 영업일 정합) — (iv-a) 5 영업일 + (iv-b) 5 영업일 = 10 영업일 동안 일 2 회 (D14) × 10 영업일 = **40 회 reconciliation 모두 mismatch zero**.

  - **(iii) 백테스트 vs 모의투자 의사결정 100% 동일성** (Round 1 ITERATE Ambiguity 1 명시 박제): **해석 = Decision 객체 일치** (동일 날짜 + 동일 가격 입력 시 동일 Decision 객체 (action / split_level / asset / quantity 모두 일치)). aggregate metric (수익/MDD) 동일성 *아님*. CLAUDE.md §7.4 "백테스트와 페이퍼 트레이딩 결과가 일치" 정신 + 개별 의사결정 unit 수준.

  - **(iv) Kill switch 자동화 검증** (Round 1 ITERATE Patch 5 정합 측정 가능 형태): (a) `pytest -k kill_switch_halts_immediately` — `TRADING_HALT=1` set 시 cron 진입 즉시 sys.exit, (b) 모의투자 서버에서 환경변수 수동 set 후 cron 실행 → 진입 차단 검증, (c) 텔레그램 알림 # 4 (Kill switch 발화) 수신 확인.

  - **(v) 텔레그램 알림 100% 수신율** (Round 1 ITERATE Patch 5): paper trading 기간 ((iv-a) 5일 + (iv-b) 5일 = 10 영업일) 동안 발생하는 *모든* 알림 (D3 7 종류) 의 발송 N 회 = 수신 N 회 (100% 수신율). "5 회" 임의 수치 제거. Console 출력과 텔레그램 수신 cross-check 의무.

  실거래 전환 후 자본 시작 = D10 default (200만원, Patch 6 정합).

- **D7** — **매도 임계치 비교 backtest 도입**: (a) 매도 임계 +10% 단일 (Phase 0.5 invariant 보존), (b) +10% / +15% / +20% 비교 backtest 후 채택 (ADR 0002 §12.4.1 보류 해소), (c) 자산별 차별화 (ADR 0010 D3 (i) Mapping 진입 시). **권고 default**: **(b)** — Phase 1 진입 전 별도 sub-step (1.1.1.a) 으로 backtest 실행 + 결정 박제. 후보 (c) = D8 (ADR 0010 D3) 채택 시 cascading 흡수. **Stage 1.1.a backtest 결과 박제 (2026-05-22, `docs/research/phase-1.1.a/`)**: +10/+15/+20% 비교 (069500+132030 EQUAL, 2019–2024) → 사용자 채택 = **+15%** (risk-adjusted Sharpe 0.688 ≈ +20% 0.694, regime 민감도 낮음; +10% 대비 Sharpe/Calmar 우위). ADR 0002 §12.4.1 보류 해소, (b) 완료. Caveat: 단일 강세장 윈도우 — regime 전환 시 재검증. **적용 시점**: Phase 1 trading config (paper 셋업, Stage 4) 에 `profit_target_pct: 15` 로 wiring (현 시점 production config 변경 zero — 결정만 박제).

- **D8** — **종목별 다른 정책 허용 여부 (ADR 0010 D3 종속)**: ADR 0010 §3 회고 commit 시 D3 결정 (4 후보 중 1 선택 또는 보류) → 본 phase D8 입력. (a) ADR 0010 D3 (i) Mapping 채택 → 본 phase D8 = 채택 (`per_asset_strategy_overrides` 활용), (b) ADR 0010 D3 (ii) AssetContext 채택 → 본 phase D8 = composition.py 변경 (Phase 1 안정화 후 promote), (c) ADR 0010 D3 보류 → 본 phase D8 = 보류 (Phase 0.7.3 baseline 동일 정책 유지). **권고 default**: **(c)** ADR 0010 D3 보류 권장 (Phase 1 안정화 우선) + 안정화 6개월 후 promote 재검토.

- **D9** — **SupportLevelStrategy + cooldown 도입 (ADR 0004 §7.3.2 거부 박제 인용)**: ADR 0004 §7.3.2 "cooldown 거부 + SupportLevelStrategy 보존" 박제 인용 후 결정. (a) ADR 0004 §7.3.2 거부 그대로 보존 (Phase 0.7.3 baseline PriceDropStrategy 단독 유지), (b) SupportLevel 도입 (멀티 종목 결합, ADR 0004 §1.10) + cooldown 도입, (c) SupportLevel 보존 + cooldown 별도 검토. **권고 default**: **(a)** ADR 0004 §7.3.2 거부 그대로 — Phase 1 안정화 우선. SupportLevel = code 보존 (ADR 0005 §11.2 SupportLevelStrategy 보존 정합) + cooldown = Phase 1 안정화 후 별도 backtest 실행 후 결정.

#### Phase 1 특수 결정 항목

- **D10** — **자본 규모 — 200만원 시작** (Round 1 ITERATE Patch 6):

  | 후보 | 시작 자본 | 1 split 자본 비중 | 단계별 확대 | 채택? |
  | --- | --- | --- | --- | --- |
  | (a) 100만원 시작 | 100만원 | 약 7.1만원 (자본 7.1%) — Phase 0.7.3 비율 정합 but 절대 금액 과소 → KIS 최소 주문 금액 제약 + 호가 단위 반올림 시 매수 불가 risk | 100→200→300→500 | ❌ |
  | **(a-rev) 200만원 시작** | **200만원** | **약 14.3만원 (자본 7.1%)** — 069500 약 3.5만원 × 3~4주 + 132030 약 1.7만원 × 8~9주 = 실거래 최소 유의 단위 | **200→300→500 (D12 정합)** | **✅ default** |
  | (b) 500만원 단일 | 500만원 | 약 35.7만원 (자본 7.1%) | ❌ 단계별 confidence 부재 | ❌ |
  | (c) 300만원 중간값 | 300만원 | 약 21.4만원 (자본 7.1%) | ❌ 초기 risk capital 과다 | ❌ |

  **단계별 확대 (D12 정합)**: 200만원 5 영업일 무사고 → 300만원 10 영업일 무사고 → 500만원 10 영업일 무사고. 100만원 거부 사유 = ETF 주문 가능 최소 단위 미달.

- **D11** — **자산 universe (ADR 0008 D11 결과 + ADR 0010 D8 흡수)** (Round 1 ITERATE NON-BLOCKING — DGT promote = Phase 1.2 위임 명시):

  - **(a) Phase 0.7.3 baseline 069500 + 132030 EQUAL 그대로 채택** (default) — H1+H2+H3 3/3 PASS 입증 자산군 분산 (주식+골드). Phase 1.1 안정화 우선.
  - **(c) ADR 0008 D11 trigger 충족 시 DGT 합류 후보 = Phase 1.2 위임 명시 박제** — ADR 0008 §3 회고 commit (0.11.b.5 종료 시점) + D11 trigger 결과 (DGT promote/archive) 박제 후 *Phase 1.2 진입 결정 라운드* 에서 재검토. Phase 1.1 진입 시점에는 D11 (a) 단독 확정.
  - 거부: (b) Phase 0.9.2 5 종 = MDD -37.65% (ADR 0005 §10.3) Phase 1 risk 부적합.

- **D12** — **안정화 기간 — 35 영업일 (약 7주) 정확 일수 박제** (Round 1 ITERATE Patch 7, CLAUDE.md §14 "1~2개월" 정합):

  **(c-rev) Phase 1.1 안정화 = 총 35 영업일** (약 7 주):
  - paper trading: 10 영업일 = (iv-a) KIS Mock 5 + (iv-b) KIS 모의투자 서버 5 (D6 정합)
  - 200만원 실거래: 5 영업일 무사고 (G2.1)
  - 300만원 실거래: 10 영업일 무사고 (G2.2)
  - 500만원 실거래: 10 영업일 무사고 (G2.3)
  - 총: 10 + 5 + 10 + 10 = **35 영업일** ≈ 7 주

  CLAUDE.md §14 "1~2개월" 의 하한 (1개월 ≈ 20 영업일) + paper trading 2주 = 약 7 주 ≈ 1.75 개월 정합.

- **D13** — **Phase 1.1 변경 zero invariant + 비상 변경 4 사유 명시 + ProposalHistory read-only 모드** (Round 1 ITERATE Patch 8 + Ambiguity 2 해소):

  **(a-rev) Phase 1.1 안정화 = 변경 zero invariant + 비상 변경 4 사유**:

  - **변경 zero 범위** (Ambiguity 2 명시 박제): `src/` 코드 + `config/strategies.yaml` 변경 zero. **CLAUDE.md 이하 문서 정정은 별도 commit 으로 허용** (CLAUDE.md 오타 / typo / 회고 박제 commit 등). 본 ADR 0012 §3 회고 commit + CLAUDE.md §16.4 정정 commit 도 변경 zero invariant 위반 아님.

  - **비상 변경 4 사유 명시 박제**: 다음 4 사유 외 Phase 1.1 동안 변경 절대 불가:
    1. **Kill switch 발화** (CLAUDE.md §11.1) — `TRADING_HALT=1` 사람 명시 set 후 변경 적용.
    2. **Reconciliation 불일치 hard halt** (CLAUDE.md §11.2) — Mismatch 발견 시 hard halt + 사람 개입 대기 + 분석 후 변경 적용.
    3. **KIS API 시그니처 변경** (§1.6 #4 정합) — Pydantic schema parse 실패 시 paper trading 재검증 의무 + 변경 적용.
    4. **단일 종목 손실 한도 도달** (D2 (b') 정합) — 평가손 -20% 도달 + 사람 매도 검토 권고 알림 수신 + 사람 명시 매도 명령 / 추가 매수 정지 외 변경.

  - **ProposalHistory read-only 모드** (Round 1 ITERATE Patch 8 + ADR 0011 D14 정합): Phase 1.1 동안 `ProposalHistory` = **read-only 모드** — trigger 발화 시 NULL proposal 누적 허용 (cumulative drift 검증 데이터 보유) + `Proposal.state == APPLIED` 전이 **차단** (변경 zero invariant 정합). Phase 1.2 진입 시점에 누적된 NULL proposal 분석 + APPLIED 전이 허용 결정 라운드.

  **(b) ad-hoc 변경 허용 거부 사유**: Phase 1.1 안정화 본질 (코드 변경 zero invariant) 와 충돌. ADR 0011 §1.6 #1 정합 = 자동 적용 절대 금지 — ad-hoc 도 사람 명시 ADR 박제 후만 가능.

- **D14** — **모니터링 + Reconciliation 주기 + NTP 동기화 검증 + Cron 실행 시간 명시** (Missing Gap 1 + 4 흡수):

  **Reconciliation 주기 (a) 매일 시작 + 종료 = 2 회 채택**:
  - 시작 cron (08:30 KST = 23:30 UTC) — 장 개시 30분 전 야간 정산 후 잔고 일치 확인.
  - 종료 cron (15:50 KST = 06:50 UTC) — 장 마감 20분 후 (체결/정산 reflect 시간 확보, KIS API rate limit + 정산 지연 정합) 당일 의사결정 / 체결 / reconciliation.
  - 불일치 시 hard halt (CLAUDE.md §11.2 정합, D15 (b)).

  **NTP 동기화 검증 의무 박제** (Missing Gap 1, CLAUDE.md §3.3 정합):
  - 매 cron 진입 시작 시 NTP 동기화 상태 검증 (`pytest -k ntp_sync_within_1_second` 같은 자동 enforcement). 1초 이상 차이 시 cron 진입 차단 + 텔레그램 알림 # 6 (KIS API outage / token 만료 카테고리 확장).
  - Verification: `bash scripts/check_ntp_sync.sh` 신규 + cron 진입 hook.

  **Cron 실행 시간 정확 명시** (Missing Gap 4):
  - 의사결정 cron = 매 영업일 15:50 KST (장 마감 후 20분, KIS 정산 시간 정합).
  - L2/L3 evaluation cron (ADR 0011 D2 (b) 주간) = 토요일 09:00 KST (UTC 00:00, 일요일 전 의사결정 검토 시간 확보, ADR 0011 D2 (b) 토요일 UTC 00:00 정합).
  - Reconciliation cron 시작 = 매 영업일 08:30 KST / 종료 = 매 영업일 15:50 KST (의사결정 cron 과 동일 trigger, 격리 단계 — Reconciliation 우선 + 의사결정 후행).

- **D15** — **비상 대응 (kill switch + halt protocols)**: (a) `TRADING_HALT=1` 환경변수 단독 (CLAUDE.md §11.1 정합), (b) (a) + Reconciliation mismatch 자동 halt + 사람 개입 대기 (CLAUDE.md §11.2 정합), (c) (b) + KIS API outage / rate limit 시 자동 halt. **권고 default**: **(c)** — Phase 1 의 실계좌 = 모든 외부 의존성 실패 시 halt 가 안전. 자동 복구 / 자동 재시도 절대 금지.

- **D16** — **진입 시점 readiness audit + NTP 검증 + (iv) 2 단계 분할** (Round 1 ITERATE Patch 9 + Missing Gap 1):

  본 ADR §1 박제 commit 후 *Phase 1.1 실거래 진입* 의무 조건:

  - (i) ADR 0008/0009/0010/0011 §1 박제 commit 완료 (라운드 #24~#27, 2026-05-12 완료) ✅
  - (ii) Phase 0.11.b/c/d/e sub-step .2~.5 실행 완료 (코드 + tests + 회고 + 게이트 판정 박제) — **미진행 (현 시점)**
  - (iii) 0.11.e.5 회고 commit 후 **별도 2 commit (fold 금지)** 완료:
    - (A) CLAUDE.md §16.4 ADR 0008→0012 재번호 정정
    - (B) §16.1 항목 #2 정정 (옵션 Z, ADR 0010 §3 회고 권고 정합) — **미진행**
  - **(iv-a) KIS Mock 무사고 5 영업일** (Round 1 ITERATE Patch 4 + Patch 9 분할) — **미진행**
  - **(iv-b) KIS 모의투자 서버 무사고 5 영업일** — **미진행**
  - **(v) D6 entry gate 5 조건 *모두* 충족** (D6 (ii)/(iii)/(iv)/(v) verbatim 박제) — **미진행**
  - **(vi) NTP 동기화 검증 통과** (Missing Gap 1, CLAUDE.md §3.3) — `scripts/check_ntp_sync.sh` 신규 + cron 진입 시 NTP 차이 ≤ 1 초 보장. Phase 1.1 첫 cron 진입 전 수동 검증 + 자동 hook 박제.

  **권고 default**: (i)~(vi) *모두* 충족 후 Phase 1.1 실거래 진입 (자본 200만원, D10 정합). 미충족 시 본 ADR §1 박제 = informational draft only, 실거래 진입 불가. 본 ADR §1 박제 commit 자체는 (i) 충족 후 가능 (skeleton 박제 의무).

#### Phase 1 특수 추가 결정 (Round 1 ITERATE Missing Gaps + Open Q 박제)

- **D17** — **DB 마이그레이션** (Missing Gap 2, ADR 0002 §3.4 정합): Phase 0 SQLite schema 와 Phase 1 schema 호환성 + idempotency_key + KIS order ID 필드 추가 + 거래세 / 수수료 필드 추가. **권고 default**: 별도 ADR (**ADR 0019** — 재번호: 가칭 0013 은 Phase 0.11.f 가 점유, 0019 free 확정 2026-05-21 Stage 0.2; Phase 1.1 sub-step 1.1.2 진입 시점 박제) — 본 ADR scope 외. ADR 0019 진입 trigger = D17 의 마이그레이션 스크립트 작성 + 검증 + 백업 / rollback 절차 박제 의무. ADR 0002 §3.4 인용 정본. 컬럼 형태 (tax / commission 분리 vs 통합) 는 D20 Open Q #29 결과 흡수 후 확정 (provisional).

- **D18** — **`develop`/`main` Git workflow 분리** (Missing Gap 3, ADR 0001 §1.5 정합): Phase 1+ 실거래 진입 시 develop/main 분리 + PR review 룰 도입. **권고 default**: (a) Phase 1.1 진입 시점에 develop branch 신규 생성 + main = 실거래 운영 branch + PR review 의무 (사용자 self-review or 외부 reviewer). (b) 별도 commit (fold 금지) 으로 git workflow 변경 박제. ADR 0001 §1.5 인용 정본 + 본 ADR §3 회고 시 검증.

- **D19** — **자본 확대 실패 시 rollback 경로** (Missing Gap 5): D10 200→300→500 단계별 확대 중 무사고 위반 발생 시 대응:
  - **(a) Rollback (이전 단계 자본 복귀)** 권고 default — 200→300 무사고 위반 시 200만원 복귀 + 5 영업일 추가 무사고 운영 후 300만원 재진입. 누적 회수 ≥ 3 회 무사고 위반 시 Phase 1.1 종료 + 회고 commit + Phase 1.2 진입 결정 라운드.
  - (b) 정지 (Phase 1.1 종료) — 가장 strict 이나 누적 cost 과다.
  - (c) 재평가 (사람 명시) — 사용자 결정 영역, ad-hoc.

  Rollback 정의: 자본 단위 복귀 + 잔여 포지션 청산 (사람 명시) + ProposalHistory NULL proposal 박제 (rollback trigger 기록).

- **D20** — **KIS API Open Question 별도 결정 라운드 박제** (사용자 결정 2026-05-12: Round 2 이전 KIS API 문서 검토 후 별도 결정):
  - Phase 1.1 sub-step 1.1.2 (KIS API 어댑터 구현) 진입 시 KIS API 명세서 검토 후 별도 결정 라운드 박제 의무:
    - **Open Q 1**: KIS 종목 코드 형식 (ETF 6 자리 default) — KIS Mock 및 모의투자 서버 응답으로 검증.
    - **Open Q 2**: KIS 모의투자 서버 partial fill 시뮬레이션 여부 — KIS 문서 + 모의투자 서버 실증 5 영업일 (D6 (iv-b)).
    - **Open Q 3**: pykrx vs KIS API 데이터 불일치 시 정본 — D1 (c-read) MarketDataPort 일봉 = KIS 정본 채택 (Phase 0 invariant 보존 — pykrx fallback 도 허용 단, 실거래 의사결정 = KIS 정본).
    - **Open Q 4**: G2 "무사고" 해석 — 사용자 결정 ("Round 2 이전 KIS API 문서 검토 후 별도 결정") → 본 ADR §1 박제 commit 후 / sub-step 1.1.4 (entry readiness audit) 진입 전 별도 라운드 박제 의무.
  - **권고 default**: 본 ADR §1 박제 commit 후 *Phase 1 entry decision 라운드 #29* (가칭) 신규 — KIS API 문서 검토 + Open Q 4 결정 + D16 (vi) NTP 검증 + entry readiness 최종 audit.
  - **✅ 해소: ADR 0020 (2026-05-22, Phase 1.1 Stage 2.0)** — KIS 공개문서 research 후 Open Q 1~4 박제: (1) PDNO 6자리 숫자 문자열 직접 매핑, (2) 모의투자 partial fill 시뮬 실증 보류(Stage 7) + D5(a) 차단 유지, (3) KIS 정본 + pykrx fallback, (4) "무사고" = **운영/무결성 사고만** (P&L 손실·-20% 손절 발동은 사고 아님 — Phase 1.1 = 시스템 정확성 검증). KIS API 스펙(엔드포인트/TR_ID/필드) 1차 박제 = ADR 0020 §2. D16 (vi) NTP 검증 + entry readiness audit = Stage 3/7 (별도). 실응답 검증 = 계정 발급 후 Stage 4/7.

### 1.4 Gates G1~G4 (success criterion, ralplan #28 박제 대상)

본 phase 의 게이트는 *Phase 1 entry readiness audit* + *Phase 1.1 안정화 운영 성공 기준* 으로 분리:

- **G1 (PRIMARY) — Phase 1 entry readiness audit**: **D16 (i)~(vi) 6 조건** *모두* 충족 박제 (Round 2 Critic MINOR 정정 — D16 본문 / sub-step 1.1.4 / closing summary 정합). 측정: `git log` + sub-step commit hash 박제 + paper trading log (KIS Mock 5일 + KIS 모의투자 서버 5일) + D6 5 조건 verbatim 박제 + NTP 동기화 검증 (`scripts/check_ntp_sync.sh` 통과).

- **G2 (PRIMARY) — Phase 1.1 안정화 운영 성공 기준** (D10/D12 update 정합 — Round 2 Architect 수치 정정 박제):
  - **G2.1** — **200만원 5 영업일** 무사고 운영 (D10 200만원 시작 + D12 5 영업일 정합).
  - **G2.2** — **300만원 10 영업일** 무사고 운영.
  - **G2.3** — **500만원 10 영업일** 무사고 운영.
  - **G2.4** — Phase 1.1 종료 (paper 10 + 실거래 25 = 총 35 영업일) 후 Phase 1.2 진입 결정 라운드.

  "무사고" 정의:
  - (a) Reconciliation 불일치 zero.
  - (b) Kill switch 발화 zero (사람 명시 외).
  - (c) KIS API outage 시 hard halt 정상 동작.
  - **(d) 백테스트 vs 실거래 의사결정 동일성 — Phase 1.1 매일 자동 감시** (Round 1 ITERATE Patch 16, D6 (iii) 일회성 → 지속 감시 승격, CLAUDE.md §7.4 정신):
    - **Mechanism**: 매일 cron 종료 후 당일 의사결정 입력 (price / position / config) 으로 백테스트 1일 실행 → 실거래 의사결정 (Decision 객체) 과 diff → 불일치 로그 + 텔레그램 알림 (D3 # 7 일일 요약 통합).
    - **Threshold**: 일일 불일치 > 5% → 텔레그램 WARNING + 사람 분석. 누적 (rolling 5 영업일) 불일치 > 5% → hard halt + 사람 개입 대기 (D15 (b) 정합).
    - "약간의 슬리피지 허용" 명시 — KIS 실 호가 반올림 + 정산 타이밍 차이로 ±1~2% 수준 동일성. 5% 임계는 호가 반올림 buffer + 거래세/수수료 차이 흡수.

- **G3 (PRIMARY) — ADR header + 회고 + 0.11.e D14 ProposalHistory 누적 + Phase 1.2 진입 결정 박제**: G2.4 종료 시점에 Phase 1.2 진입 결정 라운드 + 다음 trajectory (자본 확대 / 자산 확대 / Phase 2 진입 결정) 박제.

- **G4 (PRIMARY) — 회귀 invariant 보존**: 0.11.a 1050+ tests + 0.11.b namespace 14 tests + ADR 0006 reporting + Phase 0.7.3 baseline + CLAUDE.md §14/§16 + 0.11.e Design Contract 6 invariant 모두 trivially 보존. 측정: `pytest` 전체 통과 + `bash scripts/check_namespace.sh` 통과 + 0.11.e §1.6 6 verification command 통과.

### 1.5 Risks (R1~R10, ralplan #28 박제 대상 — Round 1 ITERATE 후 R10 신규)

- **R1 (CRITICAL) — 버그 → 돈 손실 직결**. CLAUDE.md preamble + §0 + §2 + §13 정합. Mitigation: D6 entry gate 5 조건 + G2 단계별 무사고 운영 + D14 일 2 회 reconciliation + D15 (c) 자동 halt + 0.11.e Design Contract 6 invariant 의 *정신* 보존 hard (D15 governance).

- **R2 (CRITICAL) — Partial fill / 주문 idempotency / Reconciliation mismatch**. KIS 는 partial fill 발생 가능 (CLAUDE.md §16.1 항목 #3 정합). Mitigation: D5 (a) Partial fill 차단 + ADR 0002 §3 정신 + 모든 주문에 idempotency_key 의무 (CLAUDE.md §4.1) + D14 매일 reconciliation + Mismatch hard halt (D15 (b)).

- **R3 (HIGH) — KIS API 신뢰성 risk**. Outage / rate limit / 시그니처 변경 / 인증 만료. Mitigation: D15 (c) 자동 halt + 사람 명시 재시작 + KIS API 변경 시 paper trading 우선 재검증 의무 (§1.6 Phase 1 Operating Contract #4).

- **R4 (HIGH) — 손절 부재 → 단일 종목 MDD 누적**. ADR 0002 §12.4.2 박제 + CLAUDE.md §11.4 정합. Mitigation: D2 (b) 채택 — 평가손 -X% 도달 시 추가 매수 정지 + 사람 개입 대기. 자동 손절 절대 금지 (0.11.e §1.6 #1 정합).

- **R5 (MEDIUM) — 자본 규모 / risk capital 한계**. 100만원 초기 = 단일 종목 1 split 약 14만원 (069500 7-split). Mitigation: D10 (a) 단계별 확대 + G2 단계별 무사고 운영 + 사용자 명시 자본 변경 의무.

- **R6 (MEDIUM) — 모니터링 부재 → 의사결정 누락**. Mitigation: D3 (b) 텔레그램 알림 + D14 일 2 회 reconciliation + ADR 0009 visualization comparison mode (실거래 의사결정 시각적 진단).

- **R7 (MEDIUM) — Phase 0~0.11 invariant 위반 risk**. Mitigation: G4 회귀 invariant + 0.11.e Design Contract 6 invariant 정신 보존 + D13 (a) Phase 1.1 변경 zero invariant.

- **R8 (LOW) — 텔레그램 dependency**. 텔레그램 outage 시 알림 미수신. Mitigation: D3 (b) 텔레그램 + Console 이중 (Phase 0 Console invariant 보존). D14 Reconciliation 은 텔레그램 의존 없음.

- **R9 (MEDIUM — Round 1 ITERATE Patch 15 severity 상향) — KIS API 비용 / 거래세 / 수수료 모델링 + KoreanMarketCostModel 적용 경로**. CLAUDE.md §14 "거래세 / 수수료 모델링 — Phase 1+" + ADR 0005 §1.13 + 0.11.a `KoreanMarketCostModel` (ADR 0007 §2) 활용. **현 상태**: `_KoreanMarketCostModel` 은 `src/research/dgt/cost_model.py` (5th ring, underscore prefix) — production rings (`src/adapters/kis/`) 에서 직접 import 불가 (CLAUDE.md §1.1 ring boundary). **Mitigation 2 후보**:
  - **(a) `KoreanMarketCostModel` 을 `src/domain/` 으로 promote** — cost model = 도메인 지식, Phase 1.2 backtest 정합 시 검토.
  - **(b) `src/adapters/kis/` 에서 KIS API 의 실 수수료/세금 응답 사용 (default)** — KIS 체결 응답에 거래세 + 수수료 명시 + Reconciliation 시 cross-check. backtest 측은 `_KoreanMarketCostModel` (5th ring) 유지 + 실거래는 KIS 정본.

  **권고 default = (b)** — KIS 정본 수용 + backtest vs 실거래 차이는 G2 (d) 지속 감시로 5% 임계 buffer (R9 mitigation 정합). (a) promote 는 Phase 1.2 backtest 정합 시 별도 결정 라운드.

- **R10 (MEDIUM) — KIS API 인증 정보 보안** (Round 1 ITERATE Patch 14, 신규 risk):
  - **appkey + appsecret** = `.env` 파일 (CLAUDE.md §9.3 정합) + `.gitignore` 강제. 본 phase 진입 전 `.env.example` 신규 박제 + `.env` 실제 값 = 사용자 명시 수동 박제 (commit 절대 금지).
  - **access_token** = 런타임 메모리 only (파일 / DB 저장 절대 금지) + 24 시간 유효 + 갱신 실패 시 hard halt (§1.10 시나리오 E 정합).
  - **로그 출력 시 CLAUDE.md §8.3 "민감 정보 로깅 금지" 정합** — `appkey[:4]***` 형식 + access_token 전체 mask.
  - **Verification**: `pytest -k kis_credentials_not_logged` — 로그 출력에 appkey/appsecret/access_token 전체 노출 zero 검증. `pytest -k env_file_not_committed` — `.env` 가 `.gitignore` 등록 검증.

### 1.6 Phase 1 Operating Contract (CRITICAL strict — 0.11.e §1.6 패턴 + 실거래 추가, 정신 supersede 불가)

본 phase 운영 중 모든 코드는 다음 contract 를 만족해야 함. **정신 (spirit) supersede 불가 — ADR 0011 D15 governance 정합**. Amendment 는 문구 정밀화 / 측정 가능 형태 추가만 허용.

1. **실계좌 = 돈** — 자동 catch-up / 자동 손절 / 자동 변경 적용 / 자동 재시도 / 자동 복구 **절대 금지**.
   - **Verification**: `pytest -k auto_recovery_blocked` — 모든 외부 외부 실패 시 hard halt + 사람 명시 재시작 강제.

2. **모든 의사결정 = 사람 사전 승인 + ADR 박제 + 0.11.e D6 4-state 머신 정합** — Phase 1.1 안정화 동안 (D13 (a)) 의 *비상 변경* 도 사람 명시 ADR 박제 후 적용.
   - **Verification**: `pytest -k phase_1_change_requires_adr` — Phase 1.1 동안 `git diff config/strategies.yaml` 또는 `git diff src/domain/strategies/` 발생 시 ADR 박제 검증 강제.

3. **Reconciliation 불일치 = hard halt + 사람 개입 대기** — 자동 복구 절대 금지 (CLAUDE.md §11.2 정합).
   - **Verification**: `pytest -k reconciliation_mismatch_halts` — Mismatch 발생 시 `TRADING_HALT=1` 자동 set + 다음 cron 실행 차단.

4. **KIS API 시그니처 변경 = paper trading 우선 재검증 + ADR 박제 후 실거래 진입** (Round 1 ITERATE Patch 10 구체화).
   - **Verification (구체화)**:
     - (a) KIS API 응답에 대한 **Pydantic response model 정의** (`src/adapters/kis/models.py` 신규) — Balance / Position / OrderResult / OHLCV 4 endpoint.
     - (b) `pytest -k kis_api_schema_validation` — Mock response 와 Pydantic model strict parse 정합 test.
     - (c) **런타임**: KIS API 응답이 Pydantic model parse 실패 시 **hard halt** + 텔레그램 알림 (D3 # 6) + `TRADING_HALT=1` 자동 set.
     - (d) schema 변경 = paper trading 재검증 의무 (Patch 4 (iv-a) 재실행).

5. **Partial fill = 별도 차수 인정 안 함** (ADR 0002 §3 정신 그대로 + D5 (a) 채택).
   - **Verification**: `pytest -k partial_fill_blocks_split_level` — Partial fill 발생 시 split_level 증가 zero.

6. **0.11.e §1.6 6 invariant 정신 그대로 상속 + Phase 0.11.x "production rings 변경 zero" invariant 해제 명시** (Round 1 ITERATE Patch 11) + D14 ProposalHistory + D15 governance.
   - **0.11.e §1.6 6 invariant 정신 상속** (정신 변경 zero, 문구는 본 §1.6 #1~#5 로 Phase 1 특수성 반영 승격).
   - **Phase 0.11.x "production rings 변경 zero" invariant 해제 명시 박제**: Phase 0.11.x invariant 는 *Phase 0.11.x scope only*. Phase 1 본질 = production rings 진입이므로 `src/adapters/kis/` (4-ring) + `src/adapters/telegram/` (4-ring, D3 (b) 채택 시) + `src/use_cases/reconciliation/` (3-ring, D14) + `src/cli/halt.py` (2-ring, D15) = 명시적 해제. **0.11.e D15 governance 의 "정신 변경 = L4 trigger" 와 모순 zero** — 정신 변경 아닌 *phase 본질 차이* (Phase 1 정의 자체가 실계좌 = production rings 진입).
   - **Verification**: ADR 0011 §1.6 6 verification command (`pytest -k proposal_auto_apply_blocked` / `reflexive_data_isolation` / `adr_enforcement_blocks_apply` / `trigger_signal_enum_exhaustive` / `sell_proposal_blocked_without_adr0010` / 6번째 sell + grep rule) 전부 통과 의무 유지 + D14 ProposalHistory cumulative drift bound (±30%) 통과 + Phase 1 신규 verification (§1.6 #1~#5) 추가.

7. **CLAUDE.md preamble "동작하는 것 같다 ≠ 안전하다" 정신 보존** — 본 phase 의 모든 결정은 *안전 우선* + *수익 후순위* (Round 1 ITERATE Patch 12 verification 면제).
   - **Verification (정성적 invariant — pytest command 부재 인정)**: Phase 1.1 회고 (G2.4 종료 시점, sub-step 1.1.6) 시 사람이 "모든 결정이 안전 우선이었는가" 자기 평가 + verbatim 박제 의무. ADR 0012 §3 회고 commit 시 §1.6 #7 자기 평가 박제 필수.

### 1.7 Lifecycle

- **Phase 1.1 (안정화 운영, 2 개월)** — D10 (a) 자본 단계별 확대 + D12 (c) 단계별 안정화 + D13 (a) 변경 zero invariant + G2 단계별 무사고 운영.
- **Phase 1.1 종료 결정 라운드** (G2.4 종료 시점) — Phase 1.2 진입 결정 (자본 확대 / 자산 확대 / 새 결정 항목) 박제.
- **Phase 1.2 ~ 1.N** — Phase 1.1 안정화 완료 후 단계별 확장 (자본 / 자산 / 운영 기간). 각 phase 진입 시 ralplan 라운드 + ADR 박제.
- **Phase 2 진입 결정 라운드** — Phase 1 안정화 6개월 (cumulative) 후 Phase 2 (AI 차단기) 진입 결정. ADR 0011 D13 (ii) 정합 — L1 차단기 구현 후 0.11.e D14 ProposalHistory promote 후보.

**Staleness tripwire**: Phase 1.1 운영 중 KIS API 시그니처 변경 / pykrx 데이터 변경 / Phase 0.11 코드 변경 시 본 ADR §1 박제 시그니처 cross-check 의무.

### 1.8 Sub-step roadmap (D 결정 후 박제)

| Sub-step | 본질 | 산출 (예상) |
| --- | --- | --- |
| 1.1.1 | D1~D20 결정 + ADR §1 박제 + roadmap (본 ralplan #28 산출) | ADR 0012 §1 commit |
| 1.1.1.a | D7 매도 임계 비교 backtest (+10% / +15% / +20%, ADR 0002 §12.4.1 보류 해소) | backtest 결과 박제 + 매도 임계 default 박제 |
| 1.1.1.b | D2 손절 임계 backtest (-15% / -20% / -25%, ADR 0002 §12.4.2 보류 해소) | backtest 결과 박제 + 손절 임계 default 박제 |
| 1.1.1.c | D17 DB 마이그레이션 ADR (**ADR 0019**) 별도 박제 + 마이그레이션 스크립트 + 백업/rollback 절차 (로드맵 Stage 4.5 = write 이전 hard gate) | ADR 0019 §1 commit + 스크립트 |
| 1.1.1.d | D18 `develop` branch 신규 생성 + main = 실거래 운영 분리 + PR review 룰 박제 별도 commit | `develop` branch + git workflow 변경 박제 |
| 1.1.1.e | D20 Open Q 별도 결정 라운드 (가칭 ralplan #29) — KIS API 문서 검토 + Open Q 1~4 결정 + G2 "무사고" 해석 + NTP 검증 | 별도 결정 commit |
| 1.1.2 | KIS API 어댑터 구현 (D1 c-read 우선 + c-write 후행) — BrokerPort + MarketDataPort + Pydantic schema + 인증 보안 (R10) | `src/adapters/kis/` 신규 + Mock 정합 + `models.py` Pydantic + `.env.example` |
| 1.1.3 | 손절 정책 (D2 (b')) + Partial fill (D5) + Kill switch (D4) + 텔레그램 (D3 7 종류) + Reconciliation (D14 일 2회 + NTP) + 비상 대응 (D15) + ProposalHistory read-only (D13) + 백테스트 vs 실거래 지속 감시 (G2 (d)) 구현 | `src/domain/strategies/stop_loss.py` (D2 채택 시) + `src/adapters/telegram/` + `src/use_cases/reconciliation/` + `src/cli/halt.py` + `scripts/check_ntp_sync.sh` |
| 1.1.4 | 모의투자 → 실거래 전환 게이트 (D6 5 조건 + (iv-a) KIS Mock 5일 + (iv-b) KIS 모의투자 서버 5일) 검증 + D16 entry readiness audit ((i)~(vi) 모두 충족) | Paper trading 10 영업일 무사고 + D6 5 조건 모두 충족 박제 + D16 (vi) NTP 검증 통과 |
| 1.1.5 | Phase 1.1 실거래 운영 (D10 200→300→500 단계별 + D12 35 영업일 + D13 변경 zero + D19 rollback 경로) | 운영 로그 + 일 2 회 reconciliation + G2.1~G2.4 단계별 무사고 + ProposalHistory NULL proposal 누적 |
| 1.1.6 | 회고 + ADR §3 박제 + Phase 1.2 진입 결정 라운드 (G3) + §1.6 #7 사람 자기 평가 박제 | `docs/retrospectives/phase-1.1.md` + ADR 0012 §3 commit |

### 1.9 References

- **CLAUDE.md preamble** — 실계좌 + "동작하는 것 같다 ≠ 안전하다" + 본 ADR 의 *모든* 결정의 정신.
- **CLAUDE.md §0** — 작업 시작 전 체크리스트 (Phase 범위 / 인터페이스 변경 / 외부 의존성).
- **CLAUDE.md §2** — 돈 관련 규칙 (Decimal / 통화 명시).
- **CLAUDE.md §3** — 시간 관련 규칙 (UTC + 주입).
- **CLAUDE.md §4** — 주문 처리 규칙 (idempotency_key / 지정가 / 타임아웃 / partial fill).
- **CLAUDE.md §5** — 데이터 검증 규칙 (외부 데이터 검증 / 가격 이상치).
- **CLAUDE.md §6** — 예외 처리 규칙 (DomainError / ExternalSystemError / IntegrityError).
- **CLAUDE.md §7** — 테스트 규칙 (백테스트 vs 페이퍼 동일성 — D6 entry gate (iii) 정합).
- **CLAUDE.md §8** — 로깅 규칙 (의사결정 reasoning JSON / 민감 정보 차단).
- **CLAUDE.md §10.1** — 단일 프로세스 cron + 중복 실행 방지.
- **CLAUDE.md §11.1** — Kill switch (`TRADING_HALT=1`).
- **CLAUDE.md §11.2** — Reconciliation (자동 수정 금지 + 사람 개입 대기).
- **CLAUDE.md §11.3** — 자동 catch-up 금지.
- **CLAUDE.md §11.4** — 손실 한도 / 자동 손절 안 함.
- **CLAUDE.md §13.3** — 친절한 추가 금지.
- **CLAUDE.md §14** — Phase 1 진입 전 작성 금지 통합 목록 + Phase 1 정의.
- **CLAUDE.md §16.4** — Phase 1 ADR 0012 트리거 9 항목 (재번호 박제 정합).
- ADR 0001 (Phase 0) — Mock + paper trading + idempotency_key + 지정가 + 백테스트 vs 페이퍼 동일성.
- ADR 0002 §3 (Partial fill 차단 정신) + §12.4 (손절 + 매도 임계 보류).
- ADR 0003 §8.6 (전체 kill switch) + §19.4 (종목별 다른 정책 보류).
- ADR 0004 §7.3.2 (cooldown 거부 박제) + §7.4.2 (Phase 0.9 default PriceDropStrategy).
- ADR 0005 §1.9 (Phase 1 KIS API + 손절 + 거래세) + §10.6.3 (Phase 1 후보).
- ADR 0006 (Phase 0.10 reporting layer — D14 모니터링 시각 진단 인프라).
- ADR 0007 (Phase 0.11.a) — 5-ring namespace + `KoreanMarketCostModel`.
- ADR 0008 (Phase 0.11.b) — DGT optimization + D11 trigger 결과 (D11 자산 universe 입력).
- ADR 0009 (Phase 0.11.c) — Visualization comparison mode (D14 모니터링 시각 진단).
- ADR 0010 (Phase 0.11.d) — 자산-전략 결합 진단 (D8 종속) + AssetContext 기존재 발견 (§16.1 항목 #2 정정).
- **ADR 0011 (Phase 0.11.e)** — §1.6 6 invariant + D14 ProposalHistory + D15 governance (본 phase D13 + §1.6 정합).
- `docs/multi-asset-trading-system-design.md` §1 (LLM 한계) + §8 (안전장치) + §11 (KIS API spec).
- `src/adapters/mock/` — Phase 0 Mock 정본 (D1 KIS 어댑터의 시그니처 입력).
- `src/use_cases/daily_orchestrator.py` — Phase 0~0.11 의사결정 cycle 정본.

### 1.10 Pre-mortem (deliberate mode 의무, 0.11.a §1.12 / 0.11.b §1.10 / 0.11.c §1.10 / 0.11.d §1.10 / 0.11.e §1.10 패턴 계승)

**시나리오 A — KIS API outage 중 주문 미체결 + Reconciliation mismatch**:
- 발생: KIS API outage 시 주문 timeout → DB 에 PENDING 저장 → 다음 cron 진입 시 KIS API 복구 → 주문 상태 조회 → 이미 체결됨 발견. 그러나 DB 와 KIS 잔고 불일치 (수량 / 평단 / split_level).
- 원인: D5 partial fill 차단 + D14 일 2 회 reconciliation 누락 + KIS API 의 비결정성.
- Mitigation: §1.6 #3 Reconciliation mismatch hard halt + §1.6 #1 자동 복구 금지 + 사람 명시 재시작 + KIS `get_order_status(idempotency_key)` 의무 (CLAUDE.md §4.3 정합).

**시나리오 B — 손절 부재 → 단일 종목 MDD -50%**:
- 발생: 069500 평가손 -30% 도달 → 추가 매수 발화 (PriceDropStrategy) → -50% 도달 → 단일 종목 자본 50% 손실.
- 원인: D2 (a) 손절 부재 / (b) -X% 추가 매수 정지 임계 미명시.
- Mitigation: D2 (b) 채택 + 임계 명시 (-20% default 권고, 1.1.1.b sub-step backtest 박제) + §1.6 #1 자동 손절 금지 (사람 개입 대기).

**시나리오 C — Partial fill 처리 미흡 → split_level 잘못 증가 → 잔고 불일치**:
- 발생: KIS partial fill 발생 (예: 10주 주문 → 7주 체결) → D5 (a) 차단 의무 무시 → split_level 1 증가 → 다음 cycle 추가 매수 미발화 → 자본 활용 비효율 + DB vs KIS 잔고 불일치.
- 원인: D5 (a) 차단 enforcement 부재.
- Mitigation: §1.6 #5 verification (`pytest -k partial_fill_blocks_split_level`) + KIS 잔여 quantity 별도 cancel 의무 + ADR 0002 §3 정신 그대로.

**시나리오 D — 텔레그램 dependency → 알림 실패 → 사람 인지 부재**:
- 발생: 텔레그램 API outage → 알림 미수신 → 사람이 Reconciliation mismatch / Kill switch 인지 못함 → 6시간 후 알림 발견.
- 원인: D3 (b) 텔레그램 단독 + Console 미사용.
- Mitigation: D3 (b) 텔레그램 + Console 이중 (Phase 0 Console invariant 보존) + D14 일 2 회 reconciliation 시 텔레그램 + Console 둘 다 출력 + R8 mitigation.

**시나리오 E — KIS API access_token 만료 → 갱신 실패 → 주문 timeout → Reconciliation 폭주** (Round 1 ITERATE Patch 13 신규):
- 발생: KIS access_token (24 시간 유효) 만료 시점에 cron 실행 → token 갱신 API 호출 실패 (KIS 서버 점검 / 네트워크) → 주문 API 401 응답 → `place_order` timeout → DB PENDING 저장 → 다음 cron 실행 시 token 여전히 만료 → 반복 → Reconciliation 불일치 폭주.
- 원인: token 갱신 실패 시 hard halt mechanism 부재 + token 유효성 사전 검증 부재.
- Mitigation:
  - (a) **token 갱신 실패 = hard halt** (§1.6 #1 자동 복구 금지 + D15 (c) 정합) + 사람 명시 token 재발급 + `BrokerPort.get_order_status()` (read-only) 호출 통한 기존 PENDING 주문 상태 확인 + 사람 명시 재시작.
  - (b) **token 유효성 사전 검증** — 매 cron 진입 시작 시 `BrokerPort.get_balance()` (read-only, D1 (c-read) 정합) 호출로 token 유효 확인. 실패 시 주문 진입 전 halt.
  - (c) 텔레그램 알림 # 6 (KIS API outage / token 만료) 즉시 발송 + Console 이중 (R8 mitigation).

### 1.11 Expanded Test Plan (deliberate mode 의무, 0.11.a §1.13 / 0.11.b §1.11 / 0.11.c §1.11 / 0.11.d §1.11 / 0.11.e §1.11 패턴 계승)

본 phase = **실계좌 = 돈** → 다른 phase 보다 정밀 + entry gate 4-tier 모두 강제 + 0.11.e §1.6 6 verification command 전체 통과 의무.

| 계층 | 대상 | 검증 항목 |
| --- | --- | --- |
| Unit | KIS API 어댑터 (D1) + 손절 정책 (D2) + Partial fill 차단 (D5) + Kill switch (D4) + Reconciliation (D14) | (a) BrokerPort / MarketDataPort 시그니처 정합 (Mock 정본 invariant) / (b) D2 (b) 평가손 -X% 도달 시 추가 매수 차단 / (c) D5 (a) partial fill 발생 시 split_level 증가 zero / (d) Kill switch `TRADING_HALT=1` 즉시 sys.exit / (e) Reconciliation mismatch 자동 halt |
| Integration | 백테스트 + Mock + KIS Mock 동일성 (Phase 0 invariant) + 0.11.e §1.6 6 verification | (a) 백테스트 vs 페이퍼 trading 100% 동일성 (D6 entry gate (iii)) / (b) 0.11.e §1.6 6 verification command 전부 통과 (auto apply blocked / reflexive data isolation / adr enforcement / trigger signal enum / sell proposal blocked / proposal history constraints) / (c) idempotency_key 의무 (모든 주문) |
| E2E | Paper trading 10 영업일 무사고 ((iv-a) KIS Mock 5일 + (iv-b) KIS 모의투자 서버 5일) + 실거래 200만원 5 영업일 무사고 (G2.1, D10/D12 정합) | (a) D6 entry gate 5 조건 모두 충족 + 40 회 reconciliation 일치 / (b) 백테스트 vs 실거래 의사결정 동일성 (Decision 객체 일치 — G2 (d) 정합) / (c) 거래세 / 수수료 정확 박제 (R9 (b) KIS 실 응답 정합) |
| Observability | 모니터링 (D3 텔레그램 + Console + ADR 0009 visualization) + KIS API rate limit / outage 감지 + figure-leak invariant | (a) 텔레그램 + Console 이중 알림 / (b) ADR 0009 comparison mode 실거래 시각 진단 / (c) KIS API outage 시 hard halt + 사람 명시 재시작 / (d) `bash scripts/check_namespace.sh` 통과 (production rings 변경 surface — `src/adapters/kis/` 신규 4-ring 진입 명시) / (e) `plt.get_fignums() == []` figure-leak (ADR 0006 §17.8 패턴) |

**신규 test 추가량 추정**: ~100-150 tests (unit 60 + integration 30 + e2e 20 + observability 20). 회귀 invariant: 0.11.a 1050+ tests + 0.11.b namespace 14 tests + ADR 0006 reporting layer tests + Phase 0.7.3 baseline + 0.11.e §1.6 6 verification 모두 보존. **production rings 변경 surface**: `src/adapters/kis/` 신규 4-ring 진입 (Phase 1 의 명시 영역) + `src/adapters/telegram/` (D3 (b) 채택 시) + `src/use_cases/reconciliation/` (D14) + `src/cli/halt.py` (D15) — Phase 0.11.x 의 "production rings 변경 zero" invariant 는 **본 phase 진입 시 명시적으로 해제** (Phase 1 의 본질).

---

## 2. Round 2 종료 박제 + Phase 1.1 구현 로드맵 consensus 라운드

> 본 §2 는 두 단계 박제: (2.1) ralplan #28 Round 2 종료 (2026-05-12, §1 amendments 흡수 확인) + (2.2~2.4) Phase 1.1 구현 로드맵 consensus 라운드 (2026-05-21, Stage 0.1). D1~D20 default 결정은 §1 에서 확정 — 본 §2 는 *구현 순서/구조/게이트* 박제만 추가하며 default 를 재론하지 않는다.

### 2.1 ralplan #28 Round 2 종료 (2026-05-12)

- **Verdict**: APPROVE-WITH-RESERVATIONS (Architect + Critic).
- **흡수된 amendments (§1 반영 완료)**:
  - 2 BLOCKING 수치 정정 — (a) G2.1~G2.3 자본/기간 (200만 5일 / 300만 10일 / 500만 10일), (b) D6 (ii) reconciliation 40 회 (paper 10영업일 × 일 2회).
  - G1 MINOR 정정 — D16 진입 조건 (i)~(vi) 6 조건 (본문 / sub-step 1.1.4 / closing summary 정합).
- **Reservations**: 구현 순서 / 스키마 / 게이트 측정가능성 → §2.2 구현 로드맵 라운드에서 해소.

### 2.2 Phase 1.1 구현 로드맵 consensus 라운드 (2026-05-21)

사용자 명시 "Phase 1 진입 검토" → ralplan deliberate-mode consensus. D1~D20 default 를 *구현 순서·파일 구조·테스트 전략·게이트·리스크 완화* 로 번역.

- **흐름**: Planner → Architect (AGREE-WITH-CHANGES) → Critic (ITERATE: 2 BLOCKING + 5 MAJOR) → 수정 → Architect (1차 blocker 4 RESOLVED, 신규 BLOCKING 1) → 수정 → Critic (**APPROVE**). 2 iterations.
- **산출 아티팩트**: `.omc/plans/phase-1.1-kis-real-trading-roadmap.md` (Option C — read-before-write 를 파일 작성 순서로 강제하는 10-Stage 로드맵). `.omc/` 는 gitignored 이므로 **본 §2.3 가 정본 박제**.
- **채택 = Option C**: write 메서드를 read 무사고 5영업일 게이트 통과 전까지 *작성하지 않음* → "write 조기 진입" pre-mortem 을 규율 아닌 구조로 차단. (거부: Option A 순차 strict = read/write 분리를 작업자 규율에 위임 / Option B 안전장치 우선 = recon/halt 이 KIS read 응답을 입력으로 받아 의존 역행.)

### 2.3 구현 라운드 build-sequence amendments (D default 재론 아님)

consensus 가 ADR 0012 §1.8 sub-step 표만으로는 드러나지 않은 결함을 박제:

1. **[BLOCKING→해소] DB 마이그레이션 실행 누락**: `OrderResult` / `orders` 테이블에 tax/commission 컬럼 부재 (`db.py` "no Alembic"; tax/commission 은 5th ring `research/dgt` 에만 존재 = 도달 불가). write·비용 교차검증이 존재하지 않는 컬럼을 소비 → 첫 실거래 체결 시 잔고 불일치 risk. → **신규 Stage 4.5 (Schema Migration, ADR 0019)** = write (Stage 5) 이전 hard gate. ADR 0019 §1 + `orders` DDL `tax`/`commission` + migrate 스크립트 + 백업 + rollback + 게이트 3종.
2. **[BLOCKING→해소] D6 (iii)/G2 (d) "Decision 객체 일치" 충족 불가능**: 라이브 `as_of=self._clock()` 실시각 + 라이브 가격 vs 백테스트 고정 날짜 → `Decision == Decision` 항상 False (`timestamp`/`reasoning` 차이). → **구조적 projection 으로 재정의**: `proj(d) = (skip_reason, sorted((slot_number, filled_quantity) for sell_actions), buy = (slot_number, split_level_after, filled_quantity, round_to_tick(target_price)) | None)`, 제외 = `{timestamp, reasoning, per-action {reasoning, filled_price, order_id}}`. 게이트 = `decision_equivalence_excludes_timestamp_and_live_price` (raw `==` 실패 + skip⇔빈 액션 불변 + sell canonical sort 동시 증명). "기록된 라이브 종가 재사용 (re-fetch 금지)" 결정론.
3. **[MAJOR→해소] 도메인 모델 additive 허용 범위 명시**: 변경 zero invariant (D13) = Stage 8 운영 윈도우 룰. Stage 0–7 build 동안 domain 모델 **additive 확장** (`OrderResult.tax/commission`) 은 ADR 0019 하 허용 (Port 시그니처 불변).
4. **[MAJOR→해소] D18 develop/main 분리 = Stage 0.4** build order 배치 (Stage 5 write 진입 선행).
5. **[MAJOR→해소] write-absence 단일 메커니즘**: write 메서드 = `KISBroker` 에 *부재* (NotImplementedError placeholder 도 두지 않음 — placeholder/부재 양립 모호 제거). 게이트 = `kis_write_endpoints_absent_before_read_gate` = `not hasattr(...)`.
6. **[MAJOR→해소] staleness tripwire N=20영업일**: Stage 1.2 손절 backtest 박제 후 20영업일 초과해서 Stage 6.1 손절 코드 작성 도달 시, default 를 fresh backtest 로 재검증 (시장 regime 변화 방지).
7. **[MAJOR→해소] 테스트 selector↔개수 매핑** 140 (Unit 70 / Integration 30 / E2E 20 / Observability 20), 안전 invariant (kill switch / recon halt / NTP / partial fill / credentials / lock / PENDING / 이상치) 누락 selector 없음.
8. **[gaps→해소]**: G-a rollback 테스트 게이트 (`rollback_reverts_capital_tier` + runbook 체크리스트) / G-c PENDING-recovery (Stage 2.5 read `get_order_status` + Stage 5.2 write timeout) / G-d lock-file (기존 `src/cli/safety.py:lock_file` wiring, 신규 구현 아님) / G-e 가격 이상치 ±30% skip (기존 `InvalidPriceError`/`DataIntegrityError` 재사용).

### 2.4 Ordering-note 해소 (순환 차단)

로드맵 §6 Ordering note (§2 ↔ 로드맵 순환 방지) 판정: 본 라운드 amendments 는 **D1~D20 default 결정을 변경하지 않는다** — 구현 순서 / 구조 / 게이트 / 테스트 측정법만 박제. §1 에 대한 유일한 touch = D17 ADR 번호 정정 (0013→0019, docs hygiene, Stage 0.2). 따라서 "§2 가 로드맵을 바꾸면 재검토" 순환은 **미발화** — 로드맵은 §1 의 downstream translation 이며 Stage 1+ (build) 진입 자격 충족. **실거래 ON 은 여전히 D16 (iv-a)~(vi) 게이트 (Stage 7/8) 뒤 — §1 불변.**

---

## 3. `<TBD: Phase 1.1 종료 회고 commit 시 박제 — G2.4 게이트 판정 + Phase 1.2 진입 결정 라운드 박제 + Phase 2 진입 결정 trigger>`

---

**본 ADR §1 Round 1 ITERATE 24 patches 흡수 완료 (ralplan #28 라운드 #28, 2026-05-12) — 13 BLOCKING + 4 NON-BLOCKING + 5 Missing + 2 Ambiguity. Round 2 Architect + Critic APPROVE 대기. Phase 1.1 실거래 진입 시점 = D16 (i)~(vi) *모두* 충족 후 (특히 0.11.b/c/d/e sub-step .2~.5 실행 완료 + 별도 2 commit 완료 + (iv-a) KIS Mock 5일 + (iv-b) KIS 모의투자 서버 5일 + D6 entry gate 5 조건 + NTP 검증). 본 phase 의 *모든* 결정은 사용자 명시 "주의 사항 모두 숙지" 정신 정합 — CLAUDE.md preamble "실계좌가 연결될 자동매매 시스템. 한 번의 버그가 돈으로 직결" 의 정본 박제. 핵심 추가 박제 (Round 1 ITERATE 흡수): D14 ProposalHistory read-only 모드 (Phase 1.1 변경 zero invariant 정합) / §1.6 #6 production rings 변경 zero invariant 해제 명시 (Phase 1 본질 = production rings 진입, 0.11.e D15 governance 정신 변경 아닌 phase 본질 차이) / §1.10 시나리오 E (KIS access_token 24h 만료) / R10 KIS 인증 보안 (appkey/appsecret/access_token mask + .env + .gitignore) / G2 (d) 백테스트 vs 실거래 의사결정 지속 감시 (5% 임계, 누적 hard halt) / D17~D20 신규 (DB 마이그레이션 별도 ADR / develop-main 분리 / 자본 rollback 경로 / KIS API Open Q 별도 결정 라운드 #29 가칭).**
