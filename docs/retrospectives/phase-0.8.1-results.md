# Phase 0.8.1 — SupportLevelStrategy 5-year 백테스트 결과

> Raw output from `scripts/run_phase_0_8_1_backtest.py` on
> `config/strategies-0.8.1.yaml` (ADR 0004 §1 / §2 / §5 / §6). Recorded
> 2026-05-05 from `KRX_069500_2019-2024.csv` + `KRX_132030_2019-2024.csv`
> (1231 trading days, 2020-01-02 ~ 2024-12-30, initial capital
> 100,000,000 KRW, 2019 lookback warmup 246 거래일). 종목 2 종 (069500
> KODEX 200 + 132030 KODEX 골드선물(H)) / EQUAL allocation /
> SupportLevelStrategy (slot 1~5 = first-buy / MA5 / MA10 / MA20 /
> recent_high(60)) / profit_target=10% / reentry 무 (cooldown 무).
>
> 본 results.md 의 narrative retrospective 는 `phase-0.8.1.md` (0.8.h)
> 에 작성. 게이트 평가 + ADR 결정 라운드는 0.8.g sub-step.

---

## Reproduction

```bash
mkdir -p /tmp/phase081

# Phase 0.7.3 baseline 회귀 (price_drop) — 동일 script 로 invariant 검증
uv run python scripts/run_phase_0_8_1_backtest.py \
    --config config/strategies-0.7.3.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 132030=data/historical/KRX_132030_2019-2024.csv \
    --start 2020-01-02 --end 2024-12-30 --capital 100000000 \
    --json > /tmp/phase081/baseline_073.json

# Phase 0.8.1 SupportLevelStrategy
uv run python scripts/run_phase_0_8_1_backtest.py \
    --config config/strategies-0.8.1.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 132030=data/historical/KRX_132030_2019-2024.csv \
    --start 2020-01-02 --end 2024-12-30 --capital 100000000 \
    --json > /tmp/phase081/support_level.json

# inline verification (analyze_phase_0_7_2 helpers 재사용)
uv run python -c "
import json, sys
sys.path.insert(0, 'scripts')
from analyze_phase_0_7_2 import summarize
b = summarize('Phase 0.7.3 baseline (re-run)', json.load(open('/tmp/phase081/baseline_073.json')), n_assets=2)
s = summarize('Phase 0.8.1 (SupportLevelStrategy)', json.load(open('/tmp/phase081/support_level.json')), n_assets=2)
# (지표 비교 + 게이트 평가)
"
```

---

## Phase 0.7.3 baseline 회귀 invariant 검증 (script 변경 zero-impact)

`run_phase_0_8_1_backtest.py` 의 buy_strategy 분기 (price_drop → [start,
end] 필터 / support_level → 2019 lookback 포함) 로 Phase 0.7.3 baseline
재현 가능:

| 지표 | 기존 baseline (`phase-0.7.3-results.md`) | 신규 script 재실행 | 일치 |
|---|---:|---:|---|
| Total return % | 13.2280 | 13.2280 | ✅ |
| Sharpe ratio | 0.5255 | 0.5255 (0.52548...) | ✅ |
| Capital turnover | 0.3270 | 0.3270 | ✅ |
| Max drawdown % | -8.2737 | -8.2737 | ✅ |
| Avg capital util % | 34.37 | 34.37 | ✅ |

→ 회귀 invariant 보존. SupportLevelStrategy 통합 cascade 가
PriceDropStrategy 경로에 영향 zero (ADR 0004 §5.9.1 박제).

---

## Phase 0.7.3 baseline vs Phase 0.8.1 비교

| 지표 | Phase 0.7.3 baseline | Phase 0.8.1 (SupportLevelStrategy) | diff |
|---|---:|---:|---:|
| Total return % | 13.2280 | **14.0586** | **+0.8306** |
| CAGR % | 2.5779 | **2.7392** | **+0.1613** |
| Max drawdown % | -8.2737 | **-21.2815** | **-13.0078** |
| Sharpe ratio | 0.5255 | **0.2679** | **-0.2576** |
| Calmar ratio | 0.3116 | **0.1287** | **-0.1829** |
| Capital turnover | 0.3270 | **0.4188** | **+0.0918** |
| Avg capital util % | 34.37 | **44.35** | **+9.98** |
| Cumulative sells | 28 | **33** | **+5** |

(굵은 글씨 = 본질적 변화. 4 지표 개선 (return / CAGR / turnover / util)
vs 3 지표 악화 (MDD / Sharpe / Calmar)).

---

## Gate verdict (ADR §1.6.2 strict — Phase 0.7.3 baseline 정확값)

| 가설 | 임계 | Phase 0.8.1 | 판정 |
|---|---|---:|---|
| **H1** Capital turnover ≥ 0.3270 | strict | 0.4188 | ✅ PASS (+0.0918) |
| **H2** Total return % ≥ 13.2280 | strict | 14.0586 | ✅ PASS (+0.8306pp) |
| **H3** Sharpe ratio ≥ 0.5255 | strict | 0.2679 | ❌ **FAIL** (-0.2576) |
| **통과** | ≥ 2/3 | **2/3** | **✅ PASS** |

**Final verdict — Phase 0.8.1 게이트 통과 (2/3)** — H1 (자본 회전) +
H2 (절대 수익) 통과, H3 (위험조정 수익) 미달.

---

## Key observations

1. **자본 회전 활발화 입증** (H1 PASS, +0.0918) — SupportLevelStrategy
   의 indicator-based 트리거가 PriceDropStrategy 의 anchored 트리거 대비
   더 빈번히 발화. cumulative sells 28 → 33 (+5), util 34.37% → 44.35%
   (+9.98pp). 매도 사이클 활발 → 자본 재투입 빈도 ↑.

2. **절대 수익 미세 개선** (H2 PASS, +0.8306pp) — return 13.23% →
   14.06% (+0.83pp). 자본 회전 활발성이 작은 폭의 누적 수익 개선으로
   이어짐. CAGR 도 2.58% → 2.74% (+0.16pp) 동일 방향.

3. **위험 조정 수익 큰 폭 악화** (H3 FAIL, -0.2576) — Sharpe 0.5255 →
   0.2679 (-0.26). Calmar 도 0.3116 → 0.1287 (-0.18) 동일 방향. **MDD
   -8.27% → -21.28% (-13.01pp)** 큰 폭 악화가 위험조정 지표 둘 다
   끌어내림.

4. **MDD 악화 = whipsaw 위험 발현** (ADR §4.3.3 박제) — Phase 0.8.1 의
   "cooldown 무 + indicator-based 트리거" trade-off. MA 이탈 직후 회복
   시 매도 / 즉시 재매수 사이클 + 주가 추가 하락 시 모든 슬롯 채워진
   상태에서 추가 매수 불가 → 손실 누적 가능성.

5. **Phase 0.7.2 VOL 정책 학습 정합** — return/turnover ↑ + MDD/Sharpe
   ↓ 의 trade-off 패턴은 Phase 0.7.2 VOL (정변동성) 정책 결과와 매우
   유사 (ADR 0003 §17.4 박제). 자본 회전 활성화 의 비용으로 위험
   분산 약화.

6. **종목 분산 효과 검증 — 069500 + 132030 (주식 + 골드)** — Phase
   0.7.3 baseline 의 자산군 분산 가치 (채권 → 골드 교체) 는 SupportLevelStrategy
   환경에서도 동일 — 그러나 cooldown 무 + 트리거 빈도 ↑ 가 분산 효과
   를 일부 상쇄.

---

## 후속 권고 (0.8.g 진입 시 결정 라운드)

1. **0.8.g sub-step (게이트 평가 + 결정 라운드)**:
   - 게이트 통과 (2/3) 의 의미 해석 — Phase 0.7.3 의 "3/3 strict pass"
     대비 약한 통과. H3 미달의 strategic 의미 박제.
   - Phase 0.8.2 (단기 매매 +3~5%) 진입 vs 보류 — H3 미달 상황에서
     변수 추가가 기여할지 검토.
   - Phase 0.8.x (cooldown 도입 / whipsaw 완화) 검토 라운드 — H3 미달
     처방.

2. **MDD 악화 처방 후보**:
   - cooldown 도입 (Phase 0.8.x): 매도 후 N 일 재트리거 차단 — whipsaw
     완화
   - 슬롯별 차등 tolerance (Phase 0.8.x): MA5 -1%, MA20 -3% 등 —
     트리거 빈도 조정
   - 슬롯 5 정교화 (Phase 0.8.x): 단순 N일 max → "돌파 후 되돌림"
     패턴

3. **Phase 0.9+ 영향 박제** — Phase 0.8.1 결과는 ETF 분산 환경에서의
   기술적 분석 패러다임 검증. Phase 0.9 (개별 주식) 진입 시 본 결과
   해석 (자본 회전 ↑ / 위험조정 ↓) 를 baseline 으로 사용 가능.

---

## 다음 단계 진입 체크포인트

- [x] config/strategies-0.8.1.yaml 박제 — 0.8.f.1
- [x] scripts/run_phase_0_8_1_backtest.py 박제 — 0.8.f.1
- [x] Phase 0.8.1 백테스트 실행 + Phase 0.7.3 baseline 회귀 검증 — 0.8.f.1
- [x] 본 results.md 박제 — 0.8.f.2
- [ ] ADR 0004 §6 박제 (decisions + 실행 결과) — 0.8.f.2
- [ ] `phase-0.8.1.md` narrative 회고 — 0.8.h (다음 단계)
- [ ] 게이트 결과 박제 + 라운드 #X 결정 (Phase 0.8.2 / 0.8.x / Phase 0.9
      진입 결정) — 0.8.g
- [ ] CLAUDE.md / roadmap 갱신 — 라운드 결정 후 일괄
