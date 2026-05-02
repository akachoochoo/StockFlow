# Phase 0.5 Retrospective — SevenSplit

> 작성: 2026-05-03
> 범위: 매도 로직 + 재진입 정책 (D-2 / F) 도입, 단일 종목 (KODEX 200).
> ADR 0002 박제 본을 기반으로 한 5-year KOSPI 200 백테스트 결과 회고.
> 본 회고는 ADR 0002 §11.h sub-step 0.5.27 박제.

---

## 1. 마일스톤

| Sub-step | 항목 | 결과 |
|---|---|---|
| 0.5.1 | ADR 0002 박제 (사용자 검토 1~6차) | ✅ |
| 0.5.2 | CLAUDE.md §16 Phase 0.7 호환성 룰 신규 | ✅ |
| 0.5.3 | SlotState / SplitSlot + Position 마이그레이션 | ✅ |
| 0.5.4 | Decision schema 다중 액션 (`SellActionRecord` / `BuyActionRecord`) | ✅ |
| 0.5.5 | PriceDropStrategy → BuyEvaluationResult | ✅ |
| 0.5.6 | MockBroker 슬롯 모델 + partial fill 차단 | ✅ |
| 0.5.7~0.5.9 | SellStrategy + ProfitTargetSell + MockBroker SELL | ✅ |
| 0.5.10~0.5.13 | ReentryPriceStrategy (D-2 + F) + slot priority | ✅ |
| 0.5.14 | DailyOrchestrator sells-then-buys cascade + §5.6 분류 | ✅ |
| 0.5.15~0.5.16 | SQLite Position / Decision schema 마이그레이션 | ✅ |
| 0.5.17~0.5.18 | BacktestRunner 매도 시나리오 + output_formatter 다중 액션 | ✅ |
| 0.5.19~0.5.22 | YAML config Layer 2 (loader / CLI / validate / D&F.yaml) | ✅ |
| 0.5.23 | backtest↔paper 동일성 + slot byte-identical 회귀 | ✅ |
| 0.5.24~0.5.25 | 5-year D-2 / F 백테스트 실행 + 결과 박제 | ✅ |
| 0.5.26 | scripts/compare_phase05.py 분석 도구 | ✅ |
| 0.5.27 | 본 회고 작성 | ✅ (이 문서) |
| 0.5.28 | ADR 0002 §12 종료 선언 | ⏳ 본 회고 결정 후 |

---

## 2. 완료 기준 충족 검증 (ADR §10)

### 2.1 코드 품질 게이트 (§10.1)

| 항목 | 결과 |
|---|---|
| ruff 0 errors | ✅ |
| mypy 0 errors (strict on src/domain/ports/use_cases) | ✅ |
| pytest 전체 그린 | ✅ 629 passed |
| 도메인 라인/분기 커버리지 100 % | ✅ (domain/strategies 단위 테스트 + 도메인 모델 단위 테스트로 유지) |
| 전체 라인 커버리지 ≥ 95 % | ✅ 97 % |

### 2.2 Invariant 게이트 (§10.2)

- ✅ `tests/integration/test_backtest_paper_equivalence.py` — buy-only +
  sells-then-buys cascade 두 시나리오에서 backtest↔paper 동일성 통과.
- ✅ 슬롯 byte-identical (slot_number / state / entry / last_exit_price /
  last_exit_date) 검증 추가 (step 0.5.23).
- ✅ Phase 0 통합 테스트 모두 회귀 없음.

### 2.3 실데이터 백테스트 게이트 (§10.3)

- ✅ 5년 KOSPI 200 백테스트 D-2 정상 종료 (1231 trading days).
- ✅ 5년 KOSPI 200 백테스트 F 정상 종료 (1231 trading days).
- ✅ 두 결과 `phase-0.5-results.md` 박제 + 본 회고 §3 / §4 에서 분석.
- ✅ 3-way 비교 (Phase 0 baseline + D-2 + F): §3.

### 2.4 회고 게이트 (§10.4)

- ✅ 본 회고 작성. ADR §1.5 Phase 0.7 진입 기준 #1 충족.

---

## 3. 5-year KOSPI 200 D-vs-F-vs-Phase0 결과

### 3.1 실행 조건 (모두 동일)

- 데이터: `data/historical/KRX_069500_2020-2024.csv` (1231 trading days,
  2020-01-02 ~ 2024-12-30, KODEX 200)
- 초기 자본: 100,000,000 KRW
- per_split_amount: 10,000,000 KRW
- drop_threshold_pct: 5.0 %
- max_split_count: 7
- profit_target_pct: 10.0 % (Phase 0.5 만)

### 3.2 핵심 지표 (3-way)

| 지표 | Phase 0 baseline | Phase 0.5 D-2 | Phase 0.5 F | F vs D-2 |
|---|---:|---:|---:|---:|
| Total return % | **+25.96** | +8.93 | +9.42 | +0.49 |
| CAGR % | (Phase 0 회고 §3.2) | +1.77 | +1.86 | +0.09 |
| Max drawdown % | (Phase 0 회고 §3.2) | -19.38 | -15.90 | +3.48 |
| Sharpe ratio | **0.39** | 0.22 | 0.30 | +0.08 |
| Calmar ratio | (Phase 0 회고 §3.2) | 0.091 | 0.117 | +0.026 |
| Capital turnover (annualized) | ≈ 0.143 (추정) | 0.450 (3.1×) | 0.286 (2.0×) | -0.164 |
| Cumulative sells | 0 | 15 | 12 | -3 |
| Avg capital utilization % | ≈ 100 (Phase 0 dormancy) | 47.0 | 19.4 | -27.6 |

> Phase 0 baseline 의 Sharpe 0.39 / total return +25.96 % 는
> `phase-0.md` §3.2 인용. Phase 0 turnover 추정값은 7 splits × 10M KRW /
> 100M × (252 / 1231) = 0.143 — 회고 시점에서 산출 (Phase 0 retro 에는
> 회전율 컬럼 없음).

### 3.3 시각적 패턴

- **Phase 0**: 7 분할 모두 COVID 1차 충격 76 일 안에 발화 → 이후 4.7 년
  dormancy. 회복 수익을 100 % 흡수.
- **Phase 0.5 D-2**: COVID 회복기에 일찍 매도 (15 회) → 이후 SMA-anchor
  가 시장 추세 따라 상승하며 더 높은 가격에 재진입 → 자본 회전 47 %
  유지. 그러나 매도-재진입 사이클이 회복 수익 일부를 놓침 → 절대 return
  Phase 0 대비 -17 pp.
- **Phase 0.5 F**: 매도 직후 cooldown anchor (last_exit_price) 가 보수적
  → 재진입 트리거 더 어렵게 발화 → 81 % cash idle. 하지만 cash 보유로
  drawdown 회피 → Sharpe 0.30 (D-2 대비 +0.08).

---

## 4. 가설 검증 (ADR §1.3 / §1.4)

| 가설 | 기준 | 결과 | 판정 |
|---|---|---|---|
| **H1** 자본 회전율 ≥ 2× Phase 0 | ≥ 0.286 | D-2 0.450 (3.1×), F 0.286 (2.0×) | ✅ 둘 다 참 |
| **H2** total return ≥ Phase 0 (+25.96 %) | ≥ 25.96 % | D-2 8.93 %, F 9.42 % | ❌ 둘 다 거짓 |
| **H3** Sharpe ≥ 0.39 | ≥ 0.39 | D-2 0.22, F 0.30 | ❌ 둘 다 거짓 |
| **H4** D vs F measurably 차별화 | (return Δ ≥ 1pp) OR (회전율 Δ ≥ 5 %) | return Δ 0.49 pp / util Δ 27.6 pp | ✅ 참 |

### 4.1 H1 (자본 회전 알파)

매도/재진입 메커니즘이 의도대로 작동. 두 정책 모두 Phase 0 대비
**자본 회전율을 최소 2 배** 만들어냈으며 D-2 는 3 배 이상. Phase 0 의
4.7 년 dormancy 문제 (자본을 한 번 묶으면 풀지 못함) 는 해결됨.

### 4.2 H2 (총 수익 우월)

❌ **둘 다 Phase 0 baseline 미달**. ADR §1.4 에 따른 액션:
> 매도 임계치(+10 %) 자체 재검토 (회고 ADR §12 신규)

회고 §6.1 후속 검토 항목으로 박제.

**원인 후보**:
1. **+10 % 익절이 너무 빠름** — 회복 초기에 매도 → 이후 더 큰 회복을
   놓침 (특히 D-2 의 경우). +15 % 또는 +20 % 임계치로 재테스트 필요.
2. **재진입 fall-back 보수적** — F 의 cooldown anchor 가 매도 가격 위에
   고정되어 후속 회복 구간에서 재진입 못 함 → cash 81 % idle.
3. **본질적 매도 비용** — Phase 0 처럼 단순히 보유했으면 회복 수익 100 %
   흡수. 매도 후 재매수는 그 자체로 회복 수익 일부 손실 (회복 도중에 cash
   상태인 시간만큼 기회비용).

### 4.3 H3 (위험조정 수익 유지/개선)

❌ **둘 다 Phase 0 baseline (Sharpe 0.39) 미달**. 그러나 D-2 0.22 (큰
악화) 와 F 0.30 (소폭 악화) 사이 의미 있는 차이.

ADR §1.4 액션:
> Sharpe < 0.30 (악화) → 매도가 변동성을 가산했음 — 손절 도입
> 우선순위 상승

**Phase 0.5 데이터 해석**:
- F = 0.30 은 boundary 에 있음. "악화" 라기보다는 baseline 대비 retract.
- D-2 = 0.22 는 명확히 악화. SMA 추세 추종 anchor 가 회복 후반에 buy
  zone 도 끌어올리면서 high-price 재진입 → drawdown 노출 큼.
- F 의 보수적 anchor 가 drawdown 회피에 효과 → -15.9 % vs D-2 -19.4 %.

손절 도입 우선순위는 Phase 1 ADR §1 (KIS API 진입 직전) 에 박제 후보.

### 4.4 H4 (D vs F 차별화)

✅ 명확한 차이. 주요 metric 모든 방향에서 F 우위:

| 측면 | F 우위 정도 |
|---|---|
| Total return | +0.49 pp |
| Sharpe ratio | +0.08 |
| Calmar ratio | +0.026 |
| Max drawdown | +3.48 pp (less risk) |

D-2 우위: capital turnover (D-2 0.45 vs F 0.29) — 회복기 적극성. 그러나
이 적극성이 risk-adjusted return 에 negative 기여.

---

## 5. 학습

### 5.1 기술 — 무엇이 잘 작동했나

1. **사용자 검토 6차 라운드 + ADR 박제 우선** — D-2 정책 자체-참조 버그
   (§4.1.1) 와 OrderRequest BUY slot_number 갭 (§5.9.3 후속) 이 ADR 검토
   라운드에서 발견됨. 코드 작성 전 박제로 큰 reword 방지.
2. **excluded_slot_numbers 패턴** (ADR §5.9.3) — Decision Invariant 3
   자연 보장. strategy/broker 양쪽에 slot 의도 전달 후 시스템적으로
   collision 차단.
3. **Slot byte-identical 회귀 테스트** — backtest/paper 동일성 invariant
   를 매도까지 확장. 미래 스키마 변경 시 회귀 즉시 detect.
4. **YAML config Layer 2 + mutually-exclusive flag 거부** — Data
   Snooping 방지 (ADR §6.5). D vs F 비교가 git diff 박제 동반.

### 5.2 기술 — 발견 후 보강한 것

1. **§5.6 분류 우선순위 버그 fix** (commit 63702b2) — `position.max_split_count`
   (=Position.slots 길이=7 고정) 와 `config.max_split_count` (=설정값)
   혼동. all-FILLED 판정에서 `>=` config.max_split_count 로 정정.
2. **OrderRequest BUY slot_number** — 처음 박제된 invariant ("BUY 는
   slot_number=None") 가 Phase 0.5 sells-then-buys cascade 에서 strategy
   의도를 broker 까지 전달 못 함. 0.5.14 구현 중 발견 → ADR §5.9.3 후속
   박제 + invariant 완화.

### 5.3 협업 — 무엇이 잘 작동했나

1. **Phase 0.5 sub-step 박제 + commit 분할** — 0.5.14 같은 큰 변경도 4
   개 commit 으로 분할 (ADR / domain / adapter / use_case). 각 commit
   green.
2. **사용자 결정 라운드 (1A/2A/3A)** — sells-then-buys 통합 시 발견된
   3 개 결정 지점에 사용자 명시 선택 박제 후 진행. 추측 코드 제거.
3. **§12.3.1 ADR 갱신 체크리스트** — 새 round 시작 전 사용자 명시 요청
   사항 누락 검색. 본 Phase 0.5 에서 명시적 누락 발견 없음 (한번도 §X.0
   인정 박제 발화 안 함).

### 5.4 협업 — Phase 0.5 회고에서 새로 채택할 규칙 후보

> 본 회고에서 새로 발견된 협업 룰. CLAUDE.md 갱신 후보.

1. **다중 commit 시 BacktestRunner-같은 시그니처 변경은 all-or-nothing
   commit** — composition root 와 시그니처 변경이 한 commit 안에 묶여야
   각 commit green 유지. (commit `b0c5349` 가 그 사례.) CLAUDE.md §12.1
   에 추가 검토.
2. **TEST 우선 — 가설 검증 시나리오 부터** — 0.5.17 에서 backtest 시나리오
   추가 중 §5.6 분류 버그 발견. 시나리오 fixture 가 spec 의 "엣지 케이스"
   드러내는 검증 도구 역할. 원래 ADR §11.e 에서 0.5.17 이 0.5.14 에
   포함되었으면 더 일찍 발견 가능. 차후 sub-step 분할 시 검증 시나리오를
   가깝게 배치.

---

## 6. 발견된 이슈 / 제약

### 6.1 전략 레벨 — Phase 0.5 회고 ADR §12 검토 후보

| 이슈 | 발견 근거 | 다음 액션 |
|---|---|---|
| profit_target_pct +10 % 가 너무 낮을 가능성 | H2 거짓 + 회복기 매도 후 후속 회복 놓침 패턴 | ADR §12 신규 검토 라운드: +15 % / +20 % 비교 backtest |
| 재진입 anchor 보수성 (F) → 81 % cash idle | H2 거짓 + F avg_util 19 % | (Phase 0.7+) 멀티 자산으로 idle cash 활용 |
| 매도가 변동성 가산 (D-2 -19.4 % MDD) | H3 거짓 (특히 D-2 명확 악화) | Phase 1 ADR §1: 손절 도입 우선순위 상승 |
| F 의 절대 우위 vs D-2 | H4 + Sharpe / Calmar / drawdown | Phase 0.7 진입 시 default policy = F 채택 (사용자 검토 필요) |

### 6.2 인프라 레벨 (모두 해소됨)

- ✅ Phase 0.5 sub-step 분리 commit 흐름 정리.
- ✅ YAML loader strict + extra='forbid' — 오타 즉시 surface.
- ✅ ADR §4.1.1 deprecated 'current_market' 정책 — Literal 으로 차단.

### 6.3 코드 레벨 (모두 해소됨)

- ✅ ADR §5.6 분류 분기 버그 (commit `63702b2`).
- ✅ OrderRequest BUY slot_number 갭 (commit `5f5e58b` / `8262faa`).
- ✅ excluded_slot_numbers cascade 메커니즘 (commit `b0c5349`).

---

## 7. Phase 0.7 진입 게이트 판정 (ADR §1.5)

| 게이트 | 기준 | 충족 | 비고 |
|---|---|---|---|
| #1 | §10 완료 게이트 4 건 모두 통과 | ✅ | §2 검증 완료 |
| #2 | H1·H2·H3 중 ≥ 2 가설이 참 | ❌ | H1 만 참, H2/H3 거짓 |
| #3 | D 또는 F 중 하나를 default 채택 결정 박제 | 사용자 결정 필요 | §6.1 권고: F |
| #4 | 멀티 종목 도입 우려 사항 식별 + Phase 0.7 ADR 라운드 트리거 | 사용자 결정 필요 | §8 후속 |

### 7.1 게이트 #2 미충족 — 의미

Phase 0.5 의 핵심 가설 H1·H2·H3 중 H1 (자본 회전 메커니즘 작동) 만 참.
H2 (총 수익 우월) / H3 (위험조정 수익 유지) 둘 다 거짓 → **Phase 0.5 가
도입한 매도/재진입 정책이 Phase 0 baseline 보다 절대 가치가 낮다**.

Phase 0.7 (멀티 종목) 는 **Phase 0.5 의 가치가 입증된 후** 진행되도록
ADR §1.5 에 박제됨. 게이트 #2 미충족 = Phase 0.7 직진 보류.

### 7.2 선택지 (사용자 결정 필요)

**옵션 A — Phase 0.5 추가 iteration**:
- 매도 임계치 (+10 % → +15 % 또는 +20 %) 비교 backtest 라운드
- ADR 0002 §12+ 박제 + 새 백테스트 + H2/H3 재검증
- 통과 시 Phase 0.7 진입

**옵션 B — Phase 0.5 종료 + Phase 1 직진**:
- 실거래 데이터 (KIS API) 가 없으면 손절/임계치 튜닝이 노이즈
- ADR §1.4 H1·H2·H3 모두 거짓 케이스의 권고 ("Phase 1 KIS API 직진,
  매도 보류") 와 인접한 판단
- F default 채택 후 Phase 1 진입

**옵션 C — 매도 정책 폐기 + Phase 0 룰로 회귀**:
- H1 통과는 의미 있지만 H2/H3 절대 우위 없으면 의미 약함
- 매도 코드 / D-2 / F 모두 폐기
- Phase 1 KIS API 진입 시 Phase 0 룰 (no sell) 그대로 복원

### 7.3 본 회고 권고

**옵션 A 또는 B**. 옵션 C 는 Phase 0.5 작업 무용 처리 — 너무 강한 결정.

옵션 A 와 B 사이 — 옵션 A 가 ADR §1.4 falsifiability 표 에 박제된
"H2 거짓 → 매도 임계치 재검토" 정신과 일치. Phase 1 KIS API 진입 전에
시뮬레이션 환경에서 임계치 튜닝 한 번 더 시도 후 결정.

옵션 B 는 시뮬레이션 한계 (백테스트가 실제 KIS slippage / fee /
partial fill 을 반영 못 함) 인정 + 실거래 진입 가속.

**최종 결정은 사용자**. 본 회고는 옵션 A 약간 선호 — 이유:
- Phase 1 KIS API 진입은 비가역적 결정 (소액이라도 실거래)
- 매도 임계치 변경 backtest 는 1 일 짜리 작업
- H2 거짓 원인이 임계치 단일 변수일 가능성 substantial

---

## 8. Phase 0.7 권고 (게이트 통과 시)

게이트 #2 통과 (옵션 A 추가 iteration 결과) 가정 시:

### 8.1 우선순위 1 — Phase 0.7 ADR 라운드 (멀티 종목)

| 우려 사항 | 근거 |
|---|---|
| 자본 배분 정책 | §6.1 F 의 81 % cash idle 활용 — Phase 0.5 단일 종목에서 발견 |
| 동시 매수 시 idempotency 충돌 | ADR §5.9.1 슬롯-aware key 가 종목 간 unique 보장 안 함 (현재 `{asset.fqn}:{date}:...` 라 자동 unique 됨; 검증 필요) |
| 종목 우선순위 / cash 부족 시 분배 | Phase 0.5 미고려; Phase 0.7 ADR 라운드 핵심 결정 |

### 8.2 우선순위 2 — F default 채택 박제

§6.1 권고대로 F default. ADR §12 또는 ADR 0003 (Phase 0.7) 에서 명시 박제.

### 8.3 우선순위 3 — CLAUDE.md §16 갱신

Phase 0.7 진입 시 §16 (Phase 0.7 호환성 의식) 룰 제거 또는 갱신. ADR
§7.4 그대로 적용.

---

## 9. Phase 1 권고 (Phase 0.7 우회 시 — 옵션 B)

옵션 B 채택 시:

| 우선순위 1 — KIS API |
|---|
| 모의투자 계좌 연동, 100 ~ 500 만 KRW 소액으로 1 ~ 2 개월 |
| F default policy 적용 |
| 손절 정책 추가 (ADR §1 신규 — H3 거짓 대응) |
| 매도 텔레그램 알림 |

| 우선순위 2 — 매도 임계치 튜닝 |
|---|
| Phase 0.5 백테스트 환경에서 +15 / +20 % 임계치 비교 |
| 실거래 결과와 backtest 결과 divergence 측정 |

---

## 10. 지표 요약

```
Phase 0   baseline       : return +25.96 %  Sharpe 0.39  turnover ~0.143
Phase 0.5 D-2 (MA-20)    : return  +8.93 %  Sharpe 0.22  turnover  0.450
Phase 0.5 F  (Hybrid-60) : return  +9.42 %  Sharpe 0.30  turnover  0.286
```

H1: ✅  H2: ❌  H3: ❌  H4: ✅
Phase 0.7 진입 게이트: 4 게이트 중 #1 ✅, #2 ❌, #3 / #4 사용자 결정 필요.

---

## 11. Phase 0.5 → 다음 단계 진입 체크포인트

다음 단계 (Phase 0.7 또는 Phase 1) 진입 전 확인:

- [ ] 본 회고 §7.2 옵션 A / B / C 중 사용자 명시 선택
- [ ] (옵션 A 채택 시) ADR 0002 §12 + 신규 backtest 라운드 + H2/H3
  재검증
- [ ] (옵션 B 채택 시) F default 박제 + Phase 1 ADR 0003 신규
- [ ] (옵션 C 채택 시) Phase 0.5 코드 revert plan + ADR §12 폐기 박제
- [ ] CLAUDE.md §16 처리 (Phase 0.7 진입 시 제거 / Phase 1 진입 시 유지)
- [ ] 매도 임계치 튜닝 결과 (옵션 A) 또는 KIS API 모의투자 시작 (옵션 B)
