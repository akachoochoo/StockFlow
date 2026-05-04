# Phase 0.7.2 — 5-year multi-asset 자본 배분 정책 비교 결과

> Raw output from `scripts/analyze_phase_0_7_2.py` on the 3 정책 yaml
> (`strategies-0.7.2-{equal,inv-vol,vol}.yaml`). Recorded 2026-05-05
> from `KRX_069500_2019-2024.csv` + `KRX_214980_2019-2024.csv` (1231
> trading days, 2020-01-02 ~ 2024-12-30, initial capital 100,000,000
> KRW). 자본 배분 정책 = ADR 0003 §16.1 (균등 / 역변동성 / 정변동성).
>
> ADR §16.14 (4b.4 회귀 invariant + 산식 검증) 산출물의 narrative
> retrospective 는 `phase-0.7.2.md` (0.7.2.f) 에 작성.

---

## Reproduction

```bash
mkdir -p /tmp/phase072

# EQUAL (Phase 0.7.1 회귀 invariant 검증)
uv run python scripts/run_phase_0_7_2_backtest.py \
    --config config/strategies-0.7.2-equal.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 214980=data/historical/KRX_214980_2019-2024.csv \
    --start 2020-01-02 --end 2024-12-30 --capital 100000000 \
    --json > /tmp/phase072/equal.json

# INV_VOL (역변동성 가중)
uv run python scripts/run_phase_0_7_2_backtest.py \
    --config config/strategies-0.7.2-inv-vol.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 214980=data/historical/KRX_214980_2019-2024.csv \
    --start 2020-01-02 --end 2024-12-30 --capital 100000000 \
    --json > /tmp/phase072/inv_vol.json

# VOL (정변동성 가중)
uv run python scripts/run_phase_0_7_2_backtest.py \
    --config config/strategies-0.7.2-vol.yaml \
    --csv 069500=data/historical/KRX_069500_2019-2024.csv \
    --csv 214980=data/historical/KRX_214980_2019-2024.csv \
    --start 2020-01-02 --end 2024-12-30 --capital 100000000 \
    --json > /tmp/phase072/vol.json

# 분석
uv run python scripts/analyze_phase_0_7_2.py \
    /tmp/phase072/equal.json \
    /tmp/phase072/inv_vol.json \
    /tmp/phase072/vol.json
```

---

## Phase 0.7.1 invariant 검증 (ADR §16.13.6)

EQUAL 정책 (allocation_policy=EQUAL) 결과 vs `phase-0.7.1-results.md`
박제값 (허용 오차 < 1e-4):

| 지표 | EQUAL 측정값 | Phase 0.7.1 baseline | 차이 | 판정 |
|---|---:|---:|---:|---|
| Total return % | 5.2514 | 5.2514 | 0.0000 | PASS |
| CAGR % | 1.0541 | 1.0541 | 0.0000 | PASS |
| Max drawdown % | -7.9487 | -7.9487 | 0.0000 | PASS |
| Sharpe ratio | 0.3258 | 0.3258 | 0.0000 | PASS |
| Calmar ratio | 0.1326 | 0.1326 | 0.0000 | PASS |

**PASS** — 5 지표 1e-4 오차 이내 정확 일치. Phase 0.7.1 회귀 invariant
보존 (override None default → 단일 strategy_config fallback, ADR §16.13.9).

---

## 4-way Comparison

```
===========================================================
Phase 0.7.2 4-way comparison (ADR §16.14)
===========================================================
Metric              Phase 0.7.1    EQUAL  INV_VOL       VOL
-----------------------------------------------------------
Total return %           5.2514   5.2514   1.6440   13.3791
CAGR %                   1.0541   1.0541   0.3346    2.6060
Max drawdown %          -7.9487  -7.9487  -0.1418  -22.5027
Sharpe ratio             0.3258   0.3258   4.5321    0.3012
Calmar ratio             0.1326   0.1326   2.3592    0.1158
Capital turnover         0.1633   0.1633   0.0607    0.4062
Avg capital util %        15.60    15.61    14.27     30.22
Cumulative sells             13       13       13        13
===========================================================
```

`avg_capital_util` 산정 (ADR §2.2.6 옵션 A — 사용자 결정 2026-05-05):
`per_asset_budget = initial_capital / N_assets` (균등 분모). INV_VOL/VOL
시 정책-aware 산정 거부.

---

## Gate verdicts (ADR §16.2)

```
================================================================================
Gate evaluation (ADR §16.2: H1 >= 15.6% / H2 >= 5.25% / H3 >= 0.33, >= 2 of 3)
================================================================================
Policy         H1 util      H2 ret   H3 Sharpe   Pass  Verdict
--------------------------------------------------------------------------------
EQUAL           15.61✓       5.25✓     0.3258✗  2/3  PASS
INV_VOL         14.27✗       1.64✗     4.5321✓  1/3  FAIL
VOL             30.22✓      13.38✓     0.3012✗  2/3  PASS
```

**Final verdict — EQUAL + VOL 2 정책 게이트 통과**.

---

## Key observations

1. **회귀 invariant 자동 보존 — 옵션 C1 (BacktestRunner override) 패턴
   검증 ✅**. ADR §16.13.9 의 `per_asset_strategy_overrides=None` default
   → 단일 strategy_config fallback. EQUAL 정책은 yaml `per_split_amount`
   그대로 적용 → Phase 0.7.1 5 지표 완전 일치 (0.0000 차이). 옵션 C1
   설계의 정합성 입증.

2. **VOL 정책 — 채권 비중 ↓ → return ↑, 그러나 Sharpe ↓**. VOL 결과
   (return 13.38% / MDD -22.50% / Sharpe 0.30) 는 사실상 069500 단일
   자산 (Phase 0.5 F: return 9.42% / MDD -15.90% / Sharpe 0.30) 보다
   약간 향상. 단순히 채권 commit 거의 zero (1:142 비율) → 069500 의
   100% 비중에 가까움. **자산군 분산의 위험 관리 효과 반쯤 잃음** (MDD
   -22.50% 로 확대).

3. **INV_VOL 정책 — Sharpe 4.53 압도적, 그러나 H1/H2 미달**. INV_VOL
   결과 (return 1.64% / MDD -0.14% / Sharpe 4.53) 는 채권 ETF 비중
   ~99% (실측 1:136) → 실질적으로 채권 단일 운용. 절대 return 매우 낮음.
   "Sharpe 만으로 게이트 통과" 시나리오 ≥2/3 임계로 차단됨 (§16.2 의
   Sharpe 단독 통과 차단 정신 정합).

4. **EQUAL = baseline 자체 — 정책 자체의 효과 측정상 의미 없음**.
   EQUAL 정책의 게이트 통과 (2/3) 는 Phase 0.7.1 baseline 의 자기 동치
   — 새로운 정보 zero. 사실상 게이트 통과 정책은 **VOL 만**.

5. **H1 (자본 활용) 측정 한계 — INV_VOL 14.27% 부근 baseline 미달**.
   INV_VOL 의 채권 commit 비중 압도적이지만 균등 분모 (50M) 기준
   util > 100% 가능. 실측 14.27% 로 baseline 15.60% 보다 1.33pp 낮음.
   원인: 채권 ETF 의 5% drop 트리거 거의 미발화 (§14.5.2 Phase 0.7.1
   관찰 그대로) → 실제 commit 누적 미달. H1 산정 (옵션 A 균등 분모)
   의 의미상 INV_VOL 의 "채권 commit 비중 ↑" 효과를 자연스럽게 반영
   못 함.

---

## H3 임계 정밀도 발견 (2026-05-05)

ADR §16.2 박제 H3 임계 = `Sharpe ≥ 0.33` (반올림 박제값). 그러나 Phase
0.7.1 baseline 정확값 = `0.3258`. 즉 **임계가 baseline 보다 strict**.

영향:
- EQUAL Sharpe 0.3258 — baseline 정확 일치이지만 임계 0.33 strict 미달
- VOL Sharpe 0.3012 — 미달

→ EQUAL/VOL 게이트에서 H3 ✗ 처리 (각 2/3 → strict 임계로 1/3 가능성
있었음). 결과적으로 H1/H2 통과로 "≥2 of 3" 충족하여 PASS 처리됨 — 그러나
임계 정밀도 명시 박제 필요.

후속 옵션 (0.7.2.f 회고에서 결정):
- (i) §16.2 임계 0.33 → 0.3258 (정확값) 정밀화 — baseline 자기 동치 보장
- (ii) §16.2 임계 그대로 — strict baseline 의미 (개선 입증 요구)
- (iii) 임계 정의 명시화 — "≥ 0.33 (반올림, baseline 0.3258 동치 인정)"

---

## 후속 권고

1. **0.7.2.f narrative 회고 진입** — 본 결과의 strategic 해석:
   - VOL 만 의미 있는 게이트 통과 — 그러나 자산군 분산 효과 반쯤 잃음
   - Phase 0.7.3 (종목 다양화) 진입 시 정책-자산 부정합 (§6.1 후보 #1)
     해결 가능 — 다른 변동성 자산 (골드 / 부동산 등) 채권 대체
   - INV_VOL 의 압도적 Sharpe 는 "안정 자산 단독 운용" 의 극한 — 7-split
     세븐스플릿 가치 자체 부정 (1 split 으로 충족)
2. **H3 임계 정밀도 후속 결정** (§16.2) — 0.7.2.f 박제 시
3. **Phase 0.7.3 진입 결정 라운드 #7** — §15.5.1.C 진입 경로 정합 +
   본 §16.14 결과 반영

---

## 다음 단계 진입 체크포인트

- [x] 백테스트 3 회 실행 (EQUAL / INV_VOL / VOL) — 0.7.2.b.4
- [x] 분석 스크립트 (`analyze_phase_0_7_2.py`) — 0.7.2.d
- [x] 본 results.md 박제 — 0.7.2.e
- [ ] ADR §16.X 박제 (게이트 결과 + invariant + final verdict) — 0.7.2.e
      commit 시 ADR 갱신
- [ ] `phase-0.7.2.md` narrative 회고 — 0.7.2.f
- [ ] 라운드 #7 결정 (Phase 0.7.3 진입 / 게이트 정밀화 / 기타)
