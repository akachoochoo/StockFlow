# Phase 0.5 — 5-year KOSPI 200 D-vs-F backtest results

> Raw output from `scripts/compare_phase05.py` on the strategies-D.yaml /
> strategies-F.yaml configs (ADR 0002 §8). Recorded 2026-05-03 from the
> KRX_069500_2020-2024.csv historical fixture (1231 trading days,
> 2020-01-02 ~ 2024-12-30, initial capital 100,000,000 KRW).
>
> This file is the §11.g step 0.5.24 / 0.5.25 박제 — the narrative
> retrospective (Phase 0 baseline comparison + hypothesis verdicts +
> Phase 0.7 recommendations) lives in `phase-0.5.md` (step 0.5.27).

## Reproduction

```bash
trading backtest --config config/strategies-D.yaml \
    --csv data/historical/KRX_069500_2020-2024.csv \
    --start 2020-01-02 --end 2024-12-30 \
    --capital 100000000 --json > /tmp/D.json

trading backtest --config config/strategies-F.yaml \
    --csv data/historical/KRX_069500_2020-2024.csv \
    --start 2020-01-02 --end 2024-12-30 \
    --capital 100000000 --json > /tmp/F.json

uv run python scripts/compare_phase05.py /tmp/D.json /tmp/F.json \
    --d-label "D-2 (MA-20)" --f-label "F (Hybrid-60)"
```

## Comparison table

```
=============================================================
Phase 0.5 Policy comparison (ADR 0002 §8)
=============================================================
Metric              D-2 (MA-20)  F (Hybrid-60)          F - D
-------------------------------------------------------------
Trading days               1231           1231              0
Total return %           8.9294         9.4229         0.4935
CAGR %                   1.7678         1.8620         0.0943
Max drawdown %         -19.3807       -15.9017         3.4790
Sharpe ratio             0.2153         0.2977         0.0824
Calmar ratio             0.0912         0.1171         0.0259
Capital turnover         0.4497         0.2862        -0.1634
Cumulative sells             15             12             -3
Avg capital util         0.4699         0.1940        -0.2759
```

## Hypothesis verdicts (ADR §1.3 / §1.4)

Phase 0 baseline (from `docs/retrospectives/phase-0.md`):
- Total return: +25.96 %
- Sharpe ratio: 0.39
- Capital turnover (estimated from 7 splits × 10M / 100M × 252/1231): ≈ 0.143

| 가설 | 기준 | D-2 | F | 결과 |
|---|---|---|---|---|
| **H1** 자본 회전율 ≥ 2× baseline (≥ 0.286) | 0.286 | 0.4497 (3.1×) | 0.2862 (2.0×) | ✅ 둘 다 참 |
| **H2** total return ≥ Phase 0 baseline (+25.96 %) | 25.96 | 8.93 | 9.42 | ❌ 둘 다 거짓 |
| **H3** Sharpe ≥ 0.39 | 0.39 | 0.22 | 0.30 | ❌ 둘 다 거짓 |
| **H4** D vs F measurably 차별화 | (return ≥ 1pp OR 회전율 ≥ 5%) | return Δ 0.49pp, util Δ 27.6pp | — | ✅ 참 |

H1 통과, H4 통과 → 매도/재진입 도입은 **자본 회전 측면에서 의도대로 작동**.
그러나 H2/H3 둘 다 거짓 → **Phase 0 baseline 의 +25.96% 총수익을 둘 다
달성하지 못함**. ADR §1.4 falsifiability 표 매핑:
- H2 거짓 → 매도 임계치(+10 %) 자체 재검토 (Phase 0.5 회고 §12 신규
  검토 후보)
- H3 거짓 → 매도가 변동성을 가산했을 가능성 — Phase 1 손절 도입
  우선순위 상승

## Key observations

1. **F (Hybrid-60) 가 D-2 (MA-20) 우위** — Sharpe (0.30 vs 0.22),
   Calmar (0.117 vs 0.091), Max drawdown (-15.9 vs -19.4 %) 모두 F.
   total return 도 F 가 +0.49pp 우위. 단, 절대값 모두 Phase 0 baseline
   대비 약화.

2. **D-2 의 자본 회전 적극성** — D-2 평균 자본 활용률 47.0 %,
   F 19.4 %. D-2 는 SMA anchor 가 시장 추세 따라 움직이며 buy zone 도
   상승 → 더 적극적인 재진입. F 의 last_exit anchor 는 매도 직후 보수적
   재진입을 유지 → 자본 회수 후 19 % 만 재배치, 81 % 는 cash.

3. **F 의 cash 보유가 우위 원인일 가능성** — 2020 COVID 충격 회복기에
   포지션 100 % 이던 Phase 0 가 회복 수익 전부 흡수 (+25.96 %). Phase
   0.5 매도 후 cash 보유 비중이 높아진 두 정책 모두 회복 수익 일부를
   놓침. F 가 cash 비중 더 큰 데도 return 더 높음 → drawdown 회피
   효과 (Sharpe 우위) 가 cash idle cost 보다 큼.

4. **15 vs 12 sell trigger — D-2 가 약간 더 자주 익절**. 그러나 sell
   횟수와 총 수익은 비례 안 함 (D-2 가 sell 3 건 더 많은데 return 은
   낮음).

## Phase 0.5 결론 후보 (회고 §12 검토용)

H1·H4 통과로 Phase 0.5 기본 가설은 부분 성립. 그러나 H2/H3 미달로
Phase 0.5 매도/재진입 정책의 절대 가치는 Phase 0 baseline 대비 약화.

검토 가능한 다음 행동:
1. **F default 채택** — H4 차별화 + F 우위 (Sharpe / Calmar / drawdown)
   + cooldown 정책의 박영옥 원전 적합성. Phase 0.7 진입 시 default.
2. **매도 임계치 +10 % 재검토** — H2 미달이 임계치 너무 낮아서 (회복
   초기 매도 → 후속 회복 놓침) 일 수 있음. +15 % / +20 % 비교 검토를
   Phase 0.5 회고 §12 추가 결정 라운드로 검토.
3. **손절 도입 검토** — H3 미달이 매도가 변동성 가산했음을 시사. Phase
   1 진입 직전 ADR 라운드에 추가.
4. **F 의 cash idle 활용** — 81 % cash 비중을 다른 자산 (Phase 0.7
   멀티 자산) 또는 채권 / 단기 예치로 활용 검토. Phase 0.7+ 에서.

상세 narrative + Phase 0.7 진입 게이트 판정은 `phase-0.5.md` 회고
문서 (step 0.5.27) 에서.
