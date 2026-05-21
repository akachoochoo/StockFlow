# Phase 1.1 Stage 1 — 작업 1.2: 손절(추가매수 차단) 임계 비교 결과

> ADR 0012 D2 (b') = 평가손 ≤ -X% 도달 종목은 그날 **추가 매수만**
> 차단 (매도 / ProfitTargetSell 정상, 자동매도 zero).
> 구현 = research-scope ``_StopLossBuyWrapper`` (도메인 변경 zero).
> production ring (src/) 변경 zero — BacktestRunner 내부 루프 미러링.
> **확정 default: -20% 유지** (사용자 결정 2026-05-22, Stage 1.1.b — backtest inert 확인 후 ADR 0012 D2 기본값 유지).

## Faithfulness gate

- no-SL 미러 루프 vs `BacktestRunner(...).run()` baseline: **PASS ✅**
- 상세: canonical=(fv=115020106, cagr=2.417933413153636245140248000, mdd=-8.208560739215761593850065942, sharpe=0.5439051556963100115287141076, calmar=0.2945624074634846885571195362) mirror=(fv=115020106, cagr=2.417933413153636245140248000, mdd=-8.208560739215761593850065942, sharpe=0.5439051556963100115287141076, calmar=0.2945624074634846885571195362)

## 고정 조건

- 윈도우: `2019-01-02` ~ `2024-12-30` (가용 전 구간 교집합)
- 초기자본: `100,000,000` KRW (0.7.3 baseline 동일)
- 자산: 069500 (KODEX 200) + 132030 (KODEX 골드선물(H)), EQUAL allocation
- 고정 파라미터 (0.7.3 baseline + 작업 1.1 baseline): drop_threshold_pct=5 / max_split_count=7 / per_split_amount=5,000,000 / max_split_per_day=1 / profit_target_pct=10 / reentry=hybrid cooldown=60
- 변수: `stop_loss_pct ∈ {no-SL, 15, 20, 25}` (추가매수 차단 임계)

## 컬럼 정의

- **차단 횟수**: 평가손 ≤ -X% 조건이 발동해 래퍼가 매수를 short-circuit 한 횟수.
- **유효 차단**: 그 중 inner `PriceDropStrategy` 가 실제로 매수를 냈을(= 결과를 바꾼) 횟수. **유효 차단 = 0 이면 해당 SL 임계는 본 윈도우 / 정책에서 inert** (no-SL 과 결과 동일).

## 비교 표

| 손절 임계 | 최종가치 (KRW) | Total Return % | CAGR % | MDD % | Sharpe | Calmar | 총 매도 | 차단 횟수 | 유효 차단 |
|---|---|---|---|---|---|---|---|---|---|
| no-SL | 115,020,106 | 15.0201 | 2.4179 | -8.2086 | 0.5439 | 0.2946 | 31 | 0 | 0 |
| -15% | 115,020,106 | 15.0201 | 2.4179 | -8.2086 | 0.5439 | 0.2946 | 31 | 366 | 0 |
| -20% | 115,020,106 | 15.0201 | 2.4179 | -8.2086 | 0.5439 | 0.2946 | 31 | 182 | 0 |
| -25% | 115,020,106 | 15.0201 | 2.4179 | -8.2086 | 0.5439 | 0.2946 | 31 | 42 | 0 |

## 재현 커맨드

```bash
uv run python scripts/run_phase_1_1_b_stop_loss.py \
    --config config/strategies-0.7.3.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 132030=data/historical/KRX_132030_2019-2024.csv \
    --start 2019-01-02 --end 2024-12-30 --capital 100000000 \
    --out-dir docs/research/phase-1.1.b
```

## 결정 (확정)

- **손절(추가매수 차단) 임계 default = -20% 유지** (사용자 결정 2026-05-22). backtest inert(무해) + 라이브 추가매수 차단/텔레그램 매도검토 경고 안전장치 성격. ADR 0012 D2 (b') 기본값 확정.
- **이상치 주의**: 0.7.3 baseline (drop=5% / max_split_per_day=1 / hybrid cooldown=60) 에서는 모든 SL 임계의 **유효 차단 = 0** — 즉 손실이 임계에 도달한 날에는 strategy 가 이미 매수하지 않는다 (일일 1회 매수 cap + cooldown + drop trigger 가 선행 억제). 따라서 본 정책에서 SL 추가매수 차단은 결과를 바꾸지 못함 (모든 지표 no-SL 동일). SL 의 효용 검증은 더 공격적인 매수 정책 (큰 max_split_per_day / 짧은 cooldown / 작은 drop) 에서 재평가 필요 — 사용자 결정 항목.

