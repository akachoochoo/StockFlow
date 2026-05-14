# Phase 0.11.f Retrospective — DGT Paper-Faithful + Adaptive Hybrid + Multi-Asset Portfolio

> Date: 2026-05-15
> ADR: 0013
> Lifecycle: permanent-research-only (5th ring retention)

---

## Phase Essence

DGT 연구 오버레이 확장: 논문 충실 구현 + ATR-adaptive k hybrid + 다종목
포트폴리오 백테스트 + B&H 벤치마크 비교를 통한 "Hyb-Daily = 최적 DGT 구성"
결론 + "MDD 14-16% 일관성" 핵심 발견 박제.

---

## Sub-step Progression

| Sub-step | 내용 | 결과 |
|----------|------|------|
| 0.11.f.1 | ADR 0013 S1+S2 (decisions + experiment data) | D1~D10 결정 + 실험 데이터 테이블 박제 |
| 0.11.f.2 | Minimal fixes + unit tests (4 runners) | R2 dead vars + R3 pykrx lazy + R6 type fix + 51 tests |
| 0.11.f.3 | CLI structural tests | 17 tests (pykrx-free) + 7 namespace isolation |
| 0.11.f.4 | ADR S3 + retrospective + CLAUDE.md/roadmap | 본 문서 |

---

## Gate Results

| Gate | Verdict |
|------|---------|
| G1 (Runner tests + regression zero) | **PASS** — 75 new tests, 173 total, 0 failures |
| G2 (CLI structural) | **PASS** — 17 tests, pykrx-free |
| G3 (ADR 0013) | **PASS** — S1+S2+S3 complete |
| G4 (Retrospective + CLAUDE.md + namespace) | **PASS** |

---

## Key Findings

### F1. Hyb-Daily = Optimal DGT Configuration
- ATR x 1.0, k=[0.5%, 5%], daily rebalance, m=n//2
- 모든 DGT 변형 중 가장 우수한 수익/위험 균형

### F2. MDD 14-16% Consistency (가장 중요)
- 시장 regime (상승/하락), 종목 수 (1/4/10/20) 무관
- B&H MDD는 27-34%로 약 2배 높음

### F3. 상승장에서 B&H 압도적 우위 (DGT 구조적 한계)
- DGT는 grid level 통과 시 매도 → 상승 수익 조기 실현
- 4종목 상승장: B&H +270% vs Hyb-Daily +63%

### Invalidation Catalog
- **D3**: Slope/trend 기반 k 조정 — ATR 중복, lagging, 과보정
- **D4**: On-breach rebalancing 단독 — 하락장 매수 연쇄
- **X3**: Narrow grid (k<1%) — 과다 거래 + 비용 증가

---

## Scope vs Original Plan

| Item | Original 0.11.f (R2) | Actual |
|------|----------------------|--------|
| Files | 3 (~1090 LOC) | 5 (~2014 LOC) |
| Tests target | 27+ | 75 (achieved) |
| Runners | dynamic + adaptive | + paper + paper_adaptive |
| CLI | 618 LOC | 1030 LOC (multi-asset, B&H, per-stock charts) |
| Key finding | adaptive k improvement | MDD 14-16% consistency across ALL regimes |

---

## What Went Well

1. **실험 선행, 박제 후행** — 코드 완성 후 테스트/ADR 작성으로 효율적 진행
2. **무효화 카탈로그** — 실패한 접근법(slope, on-breach, narrow grid) 정식 문서화로 반복 방지
3. **다종목 포트폴리오 실험** — Phase 0.11.a/b 의 단일 종목 한계 극복
4. **B&H 벤치마크** — DGT 의 실질적 가치 (MDD 방어) 와 한계 (상승장 수익) 명확화

## What Could Improve

1. **R1 dedup 미수행** — `_maybe_buy`/`_maybe_sell` ~400 LOC 중복이 4 runner 에 잔존
2. **CLI 명칭** — `kakao_dgt_backtest.py` 는 범용화 완료됐으나 이름 미변경 (R5 defer)
3. **상승장 전략 부재** — DGT 가 B&H 를 상승장에서 이길 수 없다는 구조적 한계 발견했으나 대안 미검증

---

## Future Directions

1. **상승장 수익성 개선 탐색**
   - Hybrid B&H + DGT (자본 분할)
   - Regime 감지 + 전략 전환
   - 비대칭 grid (매도 grid 넓게)
   - Trailing stop 매도
   - Position sizing 비대칭

2. **R1 `_trade_ops.py` 추출** — Phase 0.11.g 후보

3. **분봉 DGT** — Phase 1 ADR 0012 진입 후 별도 결정 라운드

---

## Statistics

- New code: 5 files, ~2014 LOC (all 5th ring)
- New tests: 75 (6 test files)
- Total DGT tests: 173
- Decisions: D1~D10 (3 accepts, 3 invalidations, 4 operational)
- Inner ring changes: zero
- Regression: zero
- Commits: sub-step 0.11.f.1~f.4 bundled
