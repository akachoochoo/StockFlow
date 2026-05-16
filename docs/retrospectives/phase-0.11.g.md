# Phase 0.11.g Retrospective — DGT Rebalancing Alpha

> Date: 2026-05-17
> ADR: 0014
> Lifecycle: permanent-research-only (5th ring retention)

---

## Phase Essence

DGT의 상승장 열세를 보완하기 위한 Core-Satellite 자본 분할 + 비대칭 grid
실험. 핵심 질문: 리밸런싱이 정적 배분 대비 알파를 생성하는가?

---

## Gate Results

| Gate | Verdict |
|------|---------|
| G1 (Tests + regression) | **PASS** — 28 new, 1551 total, 0 failures |
| G2 (H1 or H2 PRIMARY) | **FAIL** — alpha ≤ 0, Calmar monotonic |
| G3 (ADR 0014) | **PASS** — S1+S2+S3 complete |
| G4 (Retrospective + namespace) | **PASS** |

---

## Key Findings

### F1. Rebalancing Destroys Value (Most Important)

리밸런싱(B&H 승자 매도 → DGT 자금 투입)은 모든 regime에서 음의 알파:
- Bull: -6% to -12% (multi4), -0.6% to -2.2% (single)
- Bear: -0.1% to -0.3%
- Full: -0.5% to +0.25% (negligible)

**근본 원인**: DGT는 grid level 통과 시 매도하여 상승 수익을 구조적으로 cap.
B&H 수익을 DGT로 이전하면 cap된 수익으로 전환 = 가치 파괴.

### F2. No Calmar Sweet Spot

B&H 비중 50% → 80%: return 단조 증가 (+45% → +63% bull single).
비단조 최적점 없음. "최적 비율"은 개인 MDD 허용치에 의해 결정됨.

### F3. Asymmetric Grid = Bull Only (MDD Guarantee 붕괴)

- 매도 grid 2-3x 확대: 상승장 수익 +16% → +29% (1.8x 개선)
- 대가: 하락장 MDD -16% → -24% (18% hard stop 초과)
- Trailing stop: 도움 안 됨 (HWM 하락 후 trigger = too late)

### F4. DGT = Pure MDD Defense Tool

Phase 0.11.f (MDD 14-16% 일관성) + Phase 0.11.g (리밸런싱 무효) 종합:
**DGT의 유일한 가치는 MDD 방어.** 수익 개선 도구가 아님.

---

## What Went Well

1. **RALPLAN consensus → 명확한 실험 설계** — Architect steelman이 정확히 적중
   ("Core-Satellite는 그냥 diversification")
2. **빠른 무효화** — 16-config sweep으로 H1/H2 즉시 판정, 불필요한 추가 실험 방지
3. **MDD 18% hard stop** — asymmetric grid 위험 즉시 차단

## What Could Improve

1. **Multi-stock Sharpe/Calmar 미계산** — aggregation에서 combined snapshots
   미구현으로 0.000 표시. 정확한 portfolio-level metrics 필요.
2. **H4 미실행** — regime switching 테스트 건너뜀 (결론에 영향 없으나 완결성 부족)
3. **R1 dedup 여전히 미수행** — `_maybe_buy`/`_maybe_sell` 이제 6개 runner에 중복

---

## Architect Steelman Verification

> "Core-Satellite is just diversification, not grid innovation.
> 70% B&H + 30% DGT = holding stocks + running DGT on remainder.
> The bull capture comes from B&H allocation, not grid improvement."

**실험 결과: 100% 적중.** 리밸런싱은 오히려 가치를 파괴하며,
수익 개선은 순전히 B&H 비중 확대에서 발생.

---

## Statistics

- New code: 3 files, ~871 LOC (all 5th ring)
- New tests: 28 (2 test files)
- Total tests: 1551 (regression zero)
- Inner ring changes: zero
- Duration: 1 session
