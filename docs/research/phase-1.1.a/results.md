# Phase 1.1 Stage 1 — 작업 1.1: 매도 임계 비교 결과

> Phase 1 (ADR 0012 가칭) 진입 전 정량 근거 박제.
> production ring (src/) 변경 zero — BacktestRunner 직접 사용.
> **확정 default: +15%** (사용자 결정 2026-05-22, Stage 1 human-approval 지점).

## 고정 조건

- 윈도우: `2019-01-02` ~ `2024-12-30` (가용 전 구간 교집합, EQUAL lookback 불필요)
- 초기자본: `100,000,000` KRW (0.7.3 baseline 동일)
- 자산: 069500 (KODEX 200) + 132030 (KODEX 골드선물(H)), EQUAL allocation
- 고정 파라미터 (0.7.3 baseline): drop_threshold_pct=5 / max_split_count=7 / per_split_amount=5,000,000 / max_split_per_day=1 / reentry=hybrid cooldown=60
- 변수: `profit_target_pct ∈ {10, 15, 20}` 만 변경

## 비교 표

| profit_target_pct | 최종가치 (KRW) | Total Return % | CAGR % | MDD % | Sharpe | Calmar | 총 매도 |
|---|---|---|---|---|---|---|---|
| 10 | 115,020,106 | 15.0201 | 2.4179 | -8.2086 | 0.5439 | 0.2946 | 31 |
| 15 | 119,123,721 | 19.1237 | 3.0328 | -8.8523 | 0.6881 | 0.3426 | 25 |
| 20 | 126,465,846 | 26.4658 | 4.0903 | -9.8375 | 0.6938 | 0.4158 | 28 |

## 재현 커맨드

```bash
uv run python scripts/run_phase_1_1_a_sell_threshold.py \
    --config config/strategies-0.7.3.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 132030=data/historical/KRX_132030_2019-2024.csv \
    --start 2019-01-02 --end 2024-12-30 --capital 100000000 \
    --out-dir docs/research/phase-1.1.a
```

## 결정 (확정)

- **매도 임계 default = +15%** (사용자 결정 2026-05-22, Stage 1 human-approval 지점).
- 근거: risk-adjusted (Sharpe 0.688 ≈ +20% 0.694) 거의 동률이면서 regime 민감도 낮음 + +10% 대비 Sharpe/Calmar 모두 우위. ADR 0002 §12.4.1 +15/+20% 비교 보류 해소 + ADR 0012 D7 (b) 완료.
- **Caveat (박제)**: 2019–2024 단일 회복/강세장 윈도우 (포트 MDD -8%). Phase 0.11.k regime-split 교훈상 횡보/하락장에서는 +15% 가 +20% 대비 조기 실현으로 risk-adjusted 유리할 수 있으나 절대 수익은 낮아질 수 있음. regime 전환 신호 시 재검증 (ADR 0011 ProposalHistory trigger 후보).

