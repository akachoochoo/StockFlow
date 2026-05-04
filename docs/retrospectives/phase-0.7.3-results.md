# Phase 0.7.3 — 5-year multi-asset 종목 다양화 (주식 + 골드) 결과

> Raw output from `scripts/run_phase_0_7_2_backtest.py` on
> `config/strategies-0.7.3.yaml` (ADR 0003 §18 / §18.12 / §18.13). Recorded
> 2026-05-05 from `KRX_069500_2019-2024.csv` + `KRX_132030_2019-2024.csv`
> (1231 trading days, 2020-01-02 ~ 2024-12-30, initial capital 100,000,000
> KRW). 종목 2 종 (069500 KODEX 200 + 132030 KODEX 골드선물(H)) /
> EQUAL allocation / 정책 동일성 강제 (§7.3).
>
> ADR §18.14 (0.7.3.d 백테스트 + inline verification) 산출물의 narrative
> retrospective 는 `phase-0.7.3.md` (0.7.3.f) 에 작성.

---

## Reproduction

```bash
mkdir -p /tmp/phase073

# 백테스트 실행 (run_phase_0_7_2_backtest.py 재사용 — 옵션 C 정신)
uv run python scripts/run_phase_0_7_2_backtest.py \
    --config config/strategies-0.7.3.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 132030=data/historical/KRX_132030_2019-2024.csv \
    --start 2020-01-02 --end 2024-12-30 --capital 100000000 \
    --json > /tmp/phase073/equal.json

# inline verification (analyze_phase_0_7_2 helpers 재사용 — 옵션 B 정신)
uv run python -c "
import json, sys
sys.path.insert(0, 'scripts')
from analyze_phase_0_7_2 import summarize, phase_0_7_1_baseline
from decimal import Decimal
GATE_H3_PRECISE = Decimal('0.3258')
p073 = summarize('Phase 0.7.3', json.load(open('/tmp/phase073/equal.json')), n_assets=2)
baseline = phase_0_7_1_baseline()
# (지표 비교 + 게이트 평가 — §18.14 박제 결과)
"
```

---

## Phase 0.7.1 baseline 비교

| 지표 | Phase 0.7.1 baseline | Phase 0.7.3 (주식 + 골드) | diff |
|---|---:|---:|---:|
| Total return % | 5.2514 | **13.2280** | **+7.9766** |
| CAGR % | 1.0541 | **2.5779** | **+1.5238** |
| Max drawdown % | -7.9487 | -8.2737 | -0.3250 |
| Sharpe ratio | 0.3258 | **0.5255** | **+0.1997** |
| Calmar ratio | 0.1326 | **0.3116** | **+0.1790** |
| Capital turnover | 0.1633 | **0.3270** | **+0.1637** |
| Avg capital util % | 15.60 | **34.37** | **+18.77** |
| Cumulative sells | 13 | **28** | **+15** |

(굵은 글씨 = 개선. MDD 만 미세 악화.)

---

## Gate verdict (ADR §18.4 — Phase 0.7.1 baseline + H3 정확값)

| 가설 | 임계 | Phase 0.7.3 | 판정 |
|---|---|---:|---|
| **H1** util ≥ 15.6% | 15.6 | 34.37 | ✅ PASS (+18.77pp) |
| **H2** return ≥ +5.25% | 5.25 | 13.23 | ✅ PASS (+7.98pp) |
| **H3** Sharpe ≥ 0.3258 (정확값, §17.3 학습) | 0.3258 | 0.5255 | ✅ PASS (+0.1997) |
| **통과** | ≥ 2/3 | **3/3** | **✅ PASS** |

**Final verdict — Phase 0.7.3 게이트 전체 통과 (3/3)**.

---

## Key observations

1. **자산군 분산 가치 정합 ✅ — 정책-자산 부정합 처방 검증**. Phase 0.7.2
   회고 §6.1 후보 #1 (채권 ETF 의 5% drop 트리거 미발화 → 자본 dormancy)
   처방으로 채권 → 골드 교체 적용. 결과: 자본 활용률 15.60% → 34.37%
   (+18.77pp), 매도 횟수 13 → 28 (+15회). **정책 동일성 (§7.3) 보존하면서
   자산-정책 부정합 해소** — Phase 0.7.2 §17.4 분리 박제의 "정책 효과
   측정 통과" 의미 (VOL 단일 회귀) 와 본질적으로 다른 길.

2. **모든 핵심 지표 ↑ — return / Sharpe / Calmar / Capital util 동시
   개선**. return +7.98pp / Sharpe +0.1997 / Calmar +0.1790 / Capital
   util +18.77pp 모두 명확. 기존 Phase 0.7.2 의 EQUAL (= Phase 0.7.1
   baseline 자기 동치) / VOL (069500 단일 회귀, MDD -22.50%) / INV_VOL
   (Sharpe 4.53 만, return 1.64%) 의 trade-off 제약을 모두 우회.

3. **MDD 미세 악화 (-0.33pp) — 골드 변동성의 자연 결과**. 채권 ETF
   (214980, 변동성 ~1/10 주식) 대비 골드 (132030, 변동성 ~중) 의 변동성
   자연 반영. 그러나 절대 수치 -0.33pp 는 무시할 수준. Sharpe / Calmar
   양쪽 큰 폭 개선이 trade-off 충분히 보상.

4. **자본 회전율 ↑↑ (0.1633 → 0.3270, 2배) — 골드의 활발한 사이클**.
   골드의 5% drop / 10% target 빈번 발생 → 매수-매도 사이클 활발.
   Phase 0.7.1 의 채권 dormancy 와 정반대.

5. **자산 비중 EQUAL 유지의 의미 — 정책 차원 통제 보존**. Phase 0.7.2
   의 INV_VOL/VOL 검증 (자본 비중 변경) 결과 baseline 보존 시도와 다른
   직교 차원 변경. EQUAL default 그대로 (변수 통제 §18.5) → 종목 조성
   변경 1 차원 효과 측정.

---

## 후속 권고

1. **0.7.3.f narrative 회고 진입** — 본 결과의 strategic 해석:
   - 채권 → 골드 교체가 정책-자산 부정합 처방의 결정타
   - Phase 0.7.4 (가칭) 부동산 / 인프라 분산 후속 박제 (§18.12.4) 의
     의미 — 본 결과 (주식 + 골드) 가 충분한지, 추가 자산군이 필요한지
     검토
   - 라운드 #9 트리거 — Phase 0.7 종료 결정 (§15.5.1.C 진입 경로 정합)
2. **Phase 0.7 종료 결정 라운드** — 본 §18.14 결과로 §15.5.1.C 의 "Phase
   0.7 종료 결정" 진입 가능. 게이트 통과 (3/3) 시 Phase 0.8 (지지선)
   직진 권고.
3. **§14.7 γ (자산별 다른 정책)** — 본 결과로 정책 동일성 (§7.3) 으로
   충분함이 입증됨. γ 는 Phase 0.7.4+ 또는 Phase 0.8+ 후속 검토 (변수
   증가 trade-off 인정 시).

---

## 다음 단계 진입 체크포인트

- [x] 백테스트 실행 (069500 + 132030 / EQUAL) — §18.14
- [x] inline verification + 게이트 평가 — §18.14
- [x] 본 results.md 박제 — 0.7.3.e
- [ ] `phase-0.7.3.md` narrative 회고 — 0.7.3.f (다음 단계)
- [ ] 라운드 #9 결정 — Phase 0.7 종료 결정 라운드 (§15.5.1.C 진입 경로
      후속)
- [ ] CLAUDE.md / roadmap 갱신 — Phase 0.7 종료 / Phase 0.8 진입 시점에
      일괄
