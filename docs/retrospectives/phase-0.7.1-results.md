# Phase 0.7.1 — 5-year multi-asset (069500 + 214980) backtest results

> Raw output from `scripts/analyze_phase_0_7_1.py` on the
> `strategies-0.7.1-F.yaml` config (ADR 0003 §13.6.4). Recorded 2026-05-03
> from `KRX_069500_2020-2024.csv` + `KRX_214980_2020-2024.csv` (1231 trading
> days, 2020-01-02 ~ 2024-12-30, initial capital 100,000,000 KRW, per-asset
> budget 50,000,000 KRW).
>
> Narrative retrospective + Phase 1 진입 결정 권고 lives here.
> ADR §13.7 박제 (정량 결과 + 게이트 + 결정 근거) is the formal record.
> 본 파일은 sub-step 0.7.1.h 산출물. Narrative retrospective (0.7.1.i) 는
> 부모 세션에서 작성.

---

## Reproduction

```bash
mkdir -p /tmp/phase071

# Phase 0.5 F 재실행 (0.7.1 code invariant 검증)
trading backtest --config config/strategies-F.yaml \
    --csv data/historical/KRX_069500_2020-2024.csv \
    --start 2020-01-02 --end 2024-12-30 \
    --capital 100000000 --json > /tmp/phase071/phase05_F.json

# Phase 0.7.1 multi 신규 실행
trading backtest --config config/strategies-0.7.1-F.yaml \
    --csv 069500=data/historical/KRX_069500_2020-2024.csv \
    --csv 214980=data/historical/KRX_214980_2020-2024.csv \
    --start 2020-01-02 --end 2024-12-30 \
    --capital 100000000 --json > /tmp/phase071/phase071_multi.json

# 분석
uv run python scripts/analyze_phase_0_7_1.py \
    /tmp/phase071/phase05_F.json \
    /tmp/phase071/phase071_multi.json
```

---

## Phase 0.5 F invariant 검증 (ADR §13.6.4 G)

0.7.1 code 재실행 결과 vs `phase-0.5-results.md` 박제값 (허용 오차 < 1e-4):

| 지표 | 0.7.1 code 재실행 | §13.6.4 G 박제값 | 차이 | 판정 |
|---|---:|---:|---:|---|
| Total return % | 9.4229 | 9.4229 | 0.0000 | PASS |
| CAGR % | 1.8620 | 1.8620 | 0.0000 | PASS |
| Max drawdown % | -15.9017 | -15.9017 | 0.0000 | PASS |
| Sharpe ratio | 0.2977 | 0.2977 | 0.0000 | PASS |
| Calmar ratio | 0.1171 | 0.1171 | 0.0000 | PASS |
| Capital turnover | 0.2862 | 0.2862 | 0.0000 | PASS |
| Cumulative sells | 12 | 12 | 0 | PASS |
| Avg capital util | 0.1940 | 0.1940 | 0.0000 | PASS |

**PASS** — 8 지표 모두 박제값과 완전 일치. 0.7.1 refactor regression 없음.

---

## 3-way Comparison

```
==========================================================================================
Phase 0.7.1.h 3-way comparison (ADR §2.2.5)
==========================================================================================
Metric                          Phase 0      Phase 0.5 F      Phase 0.7.1   Delta vs 0.5 F
                             (baseline)      (single, F)       (multi, F)
------------------------------------------------------------------------------------------
Total return %                  25.9600           9.4229           5.2514          -4.1715
CAGR %                           4.8400           1.8620           1.0541          -0.8079
Max drawdown %                 -27.5700         -15.9017          -7.9487          +7.9530
Sharpe ratio                     0.3900           0.2977           0.3258          +0.0281
Calmar ratio                     0.1800           0.1171           0.1326          +0.0155
Capital turnover                 0.1430           0.2862           0.1633          -0.1229
Avg capital util %                 69.9             19.4             15.6             -3.8
Cumulative sells                      0               12               13               +1
==========================================================================================
```

Phase 0 baseline: `docs/retrospectives/phase-0.md` §3.2 인용 (100M KRW,
no-sell). Phase 0.5 F: live re-run (invariant PASS). Phase 0.7.1:
신규 실행 (069500 + 214980, per-asset budget 50M).

---

## Hypothesis verdicts (ADR §2.2.5)

| 가설 | 임계 | Phase 0.7.1 multi 결과 | 판정 |
|---|---|---|---|
| **H1** 자본 활용 >= 48.5% | 48.5% | 15.6% | **FAIL** |
| **H2** total return >= +25.96% | 25.96% | +5.25% | **FAIL** |
| **H3** Sharpe >= 0.39 | 0.39 | 0.3258 | **FAIL** |
| **통과 기준** | >= 2 참 | (0 참 / 3) | **FAIL** |

모든 게이트 미통과 (0 / 3). ADR §2.2.5 "≥ 2 거짓 → 사용자 결정 라운드 #5
(Phase 1 진입 보류 + 옵션 검토)" 분기 적용.

---

## Key observations

1. **MDD 대폭 개선 — 자산군 분산의 위험관리 효과 확인**. Phase 0.7.1
   multi MDD -7.95% vs Phase 0.5 F -15.90% (+7.95pp 개선). Phase 0
   baseline -27.57% 대비 +19.62pp. 채권 ETF (214980) 의 역상관 (-MDD 방향
   완충) 이 포트폴리오 변동성을 크게 낮춤. H3 (Sharpe 0.3258 vs 0.39)
   의 근접치도 이 MDD 개선 덕분 — MDD 개선에도 Sharpe 미달인 이유는
   return 동반 하락 때문.

2. **자본 활용률 오히려 하락 — 채권 ETF dormancy 가 주원인**. Phase 0.5 F
   단일 19.4% → Phase 0.7.1 multi 15.6%. 069500 단독으로는 Phase 0.5 F
   수준이지만, 214980 (단기채권 PLUS) 이 2020-01-02 부터 매우 일찍 매수
   트리거를 발화 (drop_threshold 5% 달성 가능 여부) 했지만 이후 채권의
   낮은 변동성으로 추가 분할 매수 거의 없음 + profit_target 10% 달성이
   채권에서는 극히 드묾 → 채권 자산의 자본이 초기 1 split 수준에서 대부분
   idle. per-asset budget 50M 기준으로 두 자산 평균 15.6%는 H1 기준
   48.5% 의 1/3 수준. 채권 ETF 에 동일 PriceDropStrategy / ProfitTargetSell
   정책 적용이 자산군 특성과 부정합.

3. **total return 하락 — 채권 ETF 의 낮은 수익률 희석**. 069500 단독으로는
   Phase 0.5 F 수준 (9.42%) 을 냈을 것이나, 214980 의 기여분이 매우 낮음
   (채권 ETF 의 5-year 절대 상승폭 자체가 작음). 포트폴리오 total return
   5.25% = 069500 기여분 + 214980 소폭 기여분. H2 미달의 근본 원인.

4. **정책-자산 부정합 (가장 중요한 관찰)** — PriceDropStrategy (5% 하락 트리거) +
   ProfitTargetSell (10% 목표가) 는 변동성이 낮은 채권 ETF 에는 사실상
   작동 안 함. 단기채권 ETF 의 연간 변동성은 주식 ETF 의 1/10 수준 →
   5% 하락도, 10% 상승도 5년간 거의 발생 안 함. ADR §7.3 "종목별 동일
   정책 강제 (변수 통제)" 는 인프라 검증 목적으로 옳았지만, 이 결과로
   "채권 ETF = 다른 정책 필요" 가 명확해짐. Phase 0.7.2+ ADR 결정 항목.

5. **Calmar 소폭 개선 (0.1171 -> 0.1326)** — MDD 대폭 감소가 CAGR 하락을
   부분 상쇄. 위험 대비 수익(Calmar = CAGR / |MDD|) 측면에서는 Phase 0.5 F
   대비 +1.55pp 개선. 분산의 위험 감소 효과가 수익 희석 비용보다 작지 않음
   을 시사 — 단, 절대 return 은 여전히 Phase 0 baseline 대비 대폭 미달.

---

## 후속 권고

모든 게이트 (H1/H2/H3) 미통과 → ADR §2.2.5 "≥ 2 거짓 → 사용자 결정
라운드 #5" 분기.

핵심 원인 분석:

- H1 FAIL (자본 활용 15.6% < 48.5%): 채권 ETF 에 주식형 전략 적용 →
  분할 매수 / 익절 발화 극히 드묾. 해결책 = 종목별 다른 전략 (Phase 0.7.2+
  ADR §7.3 후속) 또는 채권 자산 제거 후 다른 분산 방법 검토.

- H2 FAIL (return 5.25% < 25.96%): 채권 수익 희석 + Phase 0 dormancy
  premium 미회복. 단, Phase 0 baseline 은 COVID 회복 수익 100% 흡수 특수
  상황 — 직접 비교의 맥락 주의.

- H3 FAIL (Sharpe 0.3258 < 0.39): MDD 개선에도 return 동반 하락으로
  Sharpe 상승 한계. 0.39 에 근접 (0.0642 미달) — 069500 단독 Phase 0.5 F
  0.2977 대비 +0.0281 개선은 분산 효과 확인.

**사용자 결정 라운드 #5 검토 후보**:

| 옵션 | 내용 |
|---|---|
| A | Phase 0.7.2 진입 — 자본 배분 정책 변경 (균등 -> 채권 소비중 / 변동성 가중) |
| B | 채권 ETF 교체 — 변동성 더 높은 자산군 (e.g. TIGER 200 + KODEX 골드 or 부동산) |
| C | 종목별 다른 전략 허용 ADR (채권 = buy-and-hold / 주식 = PriceDropStrategy) |
| D | Phase 1 KIS API 직진 (MDD 개선 + Sharpe 근접치를 실거래 근거로 충분 판단) |

ADR §2.4 falsifiability 표 참조:
- H1 거짓 → Phase 0.7.2 자본 배분 정책 비교 (균등 → 가중).
- 모두 거짓 → Phase 1 진입 보류 → 사용자 결정 라운드 (옵션 C 회귀 가능성
  재논의).

---

## 다음 단계 진입 체크포인트

- [ ] ADR §13.7 박제 (부모 세션이 처리)
- [ ] 게이트 결과 사용자 검토 + 결정 라운드 #5
- [ ] 다음 sub-step (0.7.1.i 회고 작성) 또는 Phase 0.7.2 진입 결정
