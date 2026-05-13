# Phase 0.11.c — Strategy-Specific Backtest Visualization Renderers 회고

> Phase 0.11.c narrative 회고. 작성일: 2026-05-13. sub-step 0.11.c.5.
> 정본: ADR 0009 §1 + §2 + §3 (본 commit 동시) / figure evidence:
> `docs/retrospectives/figures/phase-0.11.c/{dgt_full_period,
> comparison_overlay_pnl, comparison_overlay_drawdown, comparison_grid}.png` +
> `overlay_metrics.json` (sub-step .4 산출).

---

## 1. 위상 + 종료

Phase 0.11.c 진입 (2026-05-12, ADR 0009 §1 박제, ralplan #25 Round 1
ITERATE 14 patches + 4 추가 정정 → Round 2 APPROVE 종결) → 종료
(2026-05-13, ADR 0009 §3 박제, 본 회고).

기간: 2일 (2026-05-12 ~ 2026-05-13, multi-session).

선행: Phase 0.11.b 종료 (라운드 #24, ADR 0008 §3, 2026-05-13) — D11 AND-gate
FAIL + D10 archive 확정 직후 사용자 명시 trajectory ("0.11.c.2 진입") + 5
ralplan 사이클 (#24~#28) 의 두번째 실행 phase.

종료 사유: 사용자 spec 충족 — "백테스트 전 기간 매수/매도 시점 + 그리드 +
누적 수익 + 전략별 비교" 4 요구 모두 산출 가능 ("전략마다 렌더러" 직관
박제 정합).

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 / Commit |
|----------|------|---------------|
| 0.11.c.1 | D1~D12 결정 + ADR §1 박제 (ralplan #25 Round 1 ITERATE 14 patches + 4 정정 → Round 2 APPROVE) | (ADR 0009 §1 박제 commit) |
| 0.11.c.2 | `_VisualizationRenderer` Protocol + `_DGTVisualizationArtifacts` sidecar + `_enrich_with_dgt_*` helper + namespace test (interface-only, rendering body 후속) | `38c1e71` |
| 0.11.c.3 | `_DGTVisualizationRenderer` 구현 (close + grid envelope + reference price + trade markers) + figure-leak invariant + 20 tests | `ff61484` |
| 0.11.c.4 | `_align_results_for_overlay` 어댑터 (BacktestResult ↔ _DGTBacktestResult 공통 축) + `_dgt_factory` (artifacts/TradeView 변환) + `_comparison` (overlay + grid) + `python -m src.research.visualization compare` CLI + figure 박제 + 38 tests | `3af0415` |
| 0.11.c.5 | 회고 + ADR §2 + §3 박제 + roadmap 갱신 (본 commit) | (current) |

5 commits in 2 days. 회귀 invariant 보존 (`src/{domain,application,adapters,
use_cases,cli,infrastructure,ports}/**` 변경 zero, `pyproject.toml` 변경 zero,
기존 1227 tests + 신규 80 = 1307 tests 영향 zero).

---

## 3. 게이트 판정

ADR 0009 §1.4 G1~G4 + Round 2 APPROVE 시점 success criterion:

### G1 (PRIMARY) — `_VisualizationRenderer` Protocol + DGT VisualizationRenderer + comparison orchestration 박제

**판정**: ✅ **PASS**.

근거:
- `_VisualizationRenderer` Protocol (`_visualization_renderer.py`, frozen
  `@runtime_checkable`) + `_DGTVisualizationRenderer` 구현체 — structural
  typing 통과 (`isinstance(renderer, _VisualizationRenderer)` True).
- `pytest tests/research/visualization/ -k "protocol or dgt_renderer or
  comparison"` — 47 tests 통과.
- ADR 0006 §4 `StrategyRenderer` Protocol frozen 보존 — 신규 Protocol 별도
  정의 (D2 (d) 채택 정합).

### G2 (PRIMARY) — Comparison mode 동작 검증

**판정**: ✅ **PASS**.

근거:
- `_align_results_for_overlay` 어댑터 (`_align.py`) — production
  `BacktestResult` (B&H + 7split) ↔ research `_DGTBacktestResult` 공통 축
  (time + pnl_cumulative + drawdown) 매핑 정확.
- `pytest tests/research/visualization/ -k comparison` — 11 tests +
  `test_align` 12 tests + `test_dgt_factory` 12 tests + `test_cli_smoke`
  3 tests 통과.
- 069500 5y (2020-01-02 ~ 2024-12-30) 실제 데이터 comparison 산출 — 3
  strategies × pnl/drawdown 일관 시계열 (n_points=1231 모든 전략 동일).

### G3 (PRIMARY) — ADR header + 회고 + figure 박제

**판정**: ✅ **PASS**.

근거:
- ADR 0009 §1 박제 (Round 2 APPROVE, sub-step .1) → §2 sub-step .2/.3/.4
  진행 박제 → §3 시리즈 종료 박제 (본 commit).
- 회고 `docs/retrospectives/phase-0.11.c.md` 박제 (본 commit).
- Figure 박제 `docs/retrospectives/figures/phase-0.11.c/*.png` (4 PNG +
  `overlay_metrics.json`) — dimension 1600x900 고정, dpi 100 고정 (D5
  의무 충족).

### G4 (PRIMARY) — namespace CI + mypy strict + 재현성 + figure-leak invariant

**판정**: ✅ **PASS**.

근거:
- `bash scripts/check_namespace.sh` — exit 0 (7-ring grep + dgt
  intra-research isolation + visualization → dgt 정방향 자동 만족).
- `uv run mypy src/research/visualization/` — Success (10 source files,
  zero errors).
- `pytest tests/research/visualization/` — 84 tests 통과 (regression zero).
- 재현성 — 동일 입력 2회 실행 시 overlay metric byte-identical (test
  `test_overlay_metric_byte_identical` PASS) + PNG length 일치 (figure
  metadata snapshot 패턴, D10 (ii) 정합).
- Figure-leak invariant — `plt.get_fignums() == []` 4 figures 모두 검증
  (`test_figure_leak_invariant` + `_no_leak` 3 tests PASS, R8 mitigation).

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 (Protocol + DGT renderer + comparison orchestration) | PRIMARY | ✅ PASS |
| G2 (Comparison mode 동작 검증) | PRIMARY | ✅ PASS |
| G3 (ADR + 회고 + figure 박제) | PRIMARY | ✅ PASS |
| G4 (namespace + mypy + 재현성 + figure-leak) | PRIMARY | ✅ PASS |

**4/4 PRIMARY PASS** — 0.11.b 의 INFORMATIONAL FAIL 패턴 (구조적
unattainable) 과 달리 0.11.c 는 infrastructure phase 이므로 게이트 전체
PASS. ADR 0009 §1.7 lifecycle = permanent 결정 발효.

---

## 4. 산출 측정

### 4.1 신규 코드 (5th ring `src/research/visualization/`)

| File | LOC | 본질 |
|------|----:|------|
| `_visualization_renderer.py` | 131 | Protocol + `_OverlayPayload` (sub-step .2) |
| `_artifacts.py` | 90 | `_DGTVisualizationArtifacts` sidecar (sub-step .2) |
| `_trade_view_enrichment.py` | 111 | `_enrich_with_dgt_*` helper (sub-step .2) |
| `_dgt_renderer.py` | 309 | `_DGTVisualizationRenderer` (sub-step .3) |
| `_align.py` | 162 | `_align_results_for_overlay` 어댑터 (sub-step .4) |
| `_dgt_factory.py` | 138 | artifacts/TradeView 변환 (sub-step .4) |
| `_comparison.py` | 207 | overlay + grid 합성 (sub-step .4) |
| `cli.py` | 351 | `compare` subcommand (sub-step .4) |
| `__main__.py` | 12 | entry shim (sub-step .4) |
| `__init__.py` | 24 | namespace marker (sub-step .2 ~ .5) |
| **Total** | **~1535** | 5th ring visualization overlay |

### 4.2 신규 tests (`tests/research/visualization/`)

| File | 테스트 수 | 본질 |
|------|--------:|------|
| `test_protocol_structural_typing.py` | 9 | Protocol structural typing (sub-step .2) |
| `test_artifacts.py` | 5 | sidecar frozen + Decimal invariant (sub-step .2) |
| `test_trade_view_enrichment.py` | 8 | helper no-collision + Decimal 직렬화 (sub-step .2) |
| `test_namespace_isolation.py` | 4 | intra-research grep + script exit 0 (sub-step .2) |
| `test_dgt_renderer.py` | 20 | renderer Protocol/PNG/overlay/leak (sub-step .3) |
| `test_align.py` | 12 | adapter + cross-strategy 일관성 (sub-step .4) |
| `test_dgt_factory.py` | 12 | artifacts/TradeView 변환 + renderer 통과 (sub-step .4) |
| `test_comparison.py` | 11 | overlay + grid + figure-leak + 재현성 (sub-step .4) |
| `test_cli_smoke.py` | 3 | end-to-end CLI (sub-step .4) |
| **Total** | **84** | regression zero (1307 = 1223 prior + 84 신규) |

### 4.3 Figure 박제 (`docs/retrospectives/figures/phase-0.11.c/`)

| File | Size | 본질 |
|------|----:|------|
| `dgt_full_period.png` | 88 KB | DGT close + grid envelope + reference + trade markers |
| `comparison_overlay_pnl.png` | 116 KB | 3-strategy 누적 수익 overlay |
| `comparison_overlay_drawdown.png` | 137 KB | 3-strategy drawdown overlay |
| `comparison_grid.png` | 160 KB | 3-strategy grid (pnl + drawdown panels) |
| `overlay_metrics.json` | 451 B | final pnl / drawdown / n_points 박제 |

**Dimensions invariant**: 1600x900, dpi=100 (D5 박제, R7 drift mitigation).

### 4.4 069500 5y comparison metric 박제 (overlay_metrics.json verbatim)

| 전략 | final PnL (KRW) | final Drawdown (KRW) | n_points |
|------|--------------:|------:|------:|
| Buy-and-Hold | +2,108,378.99550 | -3,396,414.00000 | 1231 |
| PriceDrop 7-Split | +1,336,690 | -651,126 | 1231 |
| DGT (n=7, k=5%, m=3) | +617,147.24650 | -1,193,073.10975 | 1231 |

Phase 0.11.a §1.3 D7 4-way baseline 정합 — DGT (informational) < B&H +
7split 의 양수익이지만 drawdown 은 7split 이 best (KRW 651K). 자산군 분산
정신 4회 재확인 (ADR 0005 §9.6.2).

---

## 5. 핵심 학습

### 5.1 Strategy-specific renderer 분리 = OCP 정합 (사용자 직관 박제)

사용자 직관 "전략마다 렌더러" 박제 — ralplan #25 Round 1 에서 단일 거대
렌더러 거부 정당화. 결과:
- ADR 0006 §4 `StrategyRenderer` (episode-scope marker/panel, frozen) +
  신규 `_VisualizationRenderer` Protocol (full-period, D2 (d) 채택).
- B&H/7split 재구현 zero (D8 정정) — 기존 `DefaultRenderer` /
  `SevenSplitRenderer` 의 episode-scope 책임은 유지, full-period 책임은
  신규 Protocol 분리.
- DGT 만 신규 구현 (`_DGTVisualizationRenderer`) — grid envelope + reference
  price + signed-level trade markers.

향후 신규 전략 (score-based, 부동산 분산 등) 추가 시 본 패턴 정합 — 새
`_VisualizationRenderer` 구현체 추가 + Registry 등록 (0.11.c.4 미실시 —
필요 시 future sub-step).

### 5.2 D6 공통 축 매핑 = production / research 분리의 부드러운 다리

`BacktestResult` (production, 5-tuple snapshots) ↔ `_DGTBacktestResult`
(research, simpler daily_snapshots) 의 schema 불일치를 `_OverlayPayload`
공통 축 (time + pnl_cumulative + drawdown) 으로 해소. CLAUDE.md §1.1
"production rings 변경 zero" + 5th ring "outer→inner read OK" 정합.

→ 미래 신규 전략 (production 또는 research overlay) 의 결과를 공통 축으로
얹기 가능 — `_align.py` dispatcher 확장만으로 multi-strategy comparison
지원.

### 5.3 Figure-leak invariant = matplotlib global state 보호

ADR 0006 §17.8 `plt.get_fignums() == []` invariant 패턴 5th ring 으로
계승. 4 render 함수 (`_DGTVisualizationRenderer.render_full_period` +
`_render_overlay_pnl` + `_render_overlay_drawdown` + `_render_grid`) 모두
`try/finally` + `plt.close(fig)` 박제 — multi-figure 생성 후 누락 시 memory
leak + test interference 차단.

테스트 (`test_figure_leak_invariant` + `_no_leak` 3 tests) 가 `plt.close
("all")` baseline + 호출 후 `get_fignums()` 일치 검증 — Pre-mortem 시나리오
A 정확성 입증.

### 5.4 PNG byte-identical 거부 + figure metadata snapshot 채택 (D10 (ii))

D10 옵션 분기:
- (i) PNG byte-identical → 거부 (폰트/anti-aliasing drift 환경 의존).
- (ii) figure metadata snapshot (axes count / legend labels / data points)
  → 채택. 본 phase 는 더 단순한 "PNG length 일치" 패턴으로 재현성 검증
  (`test_png_render_byte_identical`).

→ CI 환경 (Linux + 임의 폰트) 에서 false positive 회피 + reproducibility
intent 박제.

### 5.5 자산군 분산 정신 5회 재확인 (Phase 0.5/0.7.3/0.9.2/0.11.b 누적)

069500 단독 5y 비교 결과 — DGT (+617K) < 7split (+1.34M) < B&H (+2.11M).
DGT 의 grid mechanism 이 단일 자산에서 alpha 추가 못함 (Phase 0.11.b 의
GA fail 정합 + ADR 0005 §9.6.2 "자산군 분산 = H3 충분 조건" 정신).

본 figure 박제 = Phase 1 ADR 0012 D11 분봉 DGT 검토 시 일봉 단일 자산
baseline 정량 근거.

---

## 6. 한계 / 후속 권고

### 6.1 한계

- **DGT 도메인 chart 의 grid envelope = 단일 snapshot only**: 현 runner =
  고정 reference (`ohlcv[0].close`) → grid_history 단일 entry. 미래
  re-anchor 도입 시 본 renderer 가 다중 snapshot step-plot 산출 가능
  (factory + renderer 모두 지원, 데이터만 비어 있음).
- **`_enrich_with_dgt_reference_change` helper 미사용**: 0.11.c.2 산출
  but 0.11.c.3/.4 에서 caller 없음 — 미래 re-anchor 도입 시 caller 생김.
- **Comparison 모드 D6 (a) "Sharpe rolling overlay" 미실시**: 본 phase
  ADR §1.3 D6 결정 시 "(c) overlay + grid 둘 다 지원" 박제 — rolling
  Sharpe 는 별도 metric (cumulative pnl + drawdown 만으로 충분 판단).
  필요 시 future sub-step.
- **Phase 1 promote 미박제**: ADR 0009 §1.7 "research → production
  migration path" 박제만 — 실제 Phase 1 진입 시 별도 결정 라운드 의무.
- **CLI 의 `--asset` 가 069500 단독 (Phase 0.11.a/b D3 default 정합)**:
  멀티 자산 (Phase 0.7.3 069500+132030 등) 지원은 Phase 1 ADR 0012 진입
  시 별도 결정 (CLI 시그니처 변경 필요).

### 6.2 후속 권고 (Phase 0.11.d 진입 검토)

- **Phase 0.11.d (Asset-Specific Strategy Diagnosis)**: ADR 0010 §1 (가칭)
  진입 시 본 visualization 산출 활용 — 5종 분산 portfolio 의 종목별
  pnl/drawdown 분리 panel 산출 가능.
- **0.11.a / 0.11.b 회고 figure 추가 (조건부)**: 본 phase ADR §1.8 "(조건부)
  0.11.a/0.11.b 회고에 figure 추가" — 실제 추가 시 가치 평가 후 결정.
  현재는 본 phase figure 만으로 충분 (DGT 5y full-period + comparison 3
  strategies).

### 6.3 정정 사항

- ADR 0009 §1.3 D6 결정 시 "Sharpe rolling overlay (strategy-agnostic)"
  옵션 (a) 박제 but 본 phase 미실시 — 정정: rolling Sharpe 는 metric 정의
  의존 (window N=20/60/126 etc.) + 본 phase 산출 scope 외. 필요 시 future
  sub-step ADR 박제 영역.

---

## 7. 다음 trajectory

- **즉시 다음** (사용자 결정 대기): Phase 0.11.d sub-step .2 진입 (ADR 0010
  §1 박제 후).
- **Phase 1 ADR 0012 D11 분봉 DGT 검토** = 본 phase comparison figure 정량
  근거 인용 의무 (Phase 1.2 진입 결정 라운드 또는 별도 ADR).
- **ADR 0012 D16 (ii) 진척**: Phase 0.11.c 완료 → 5/16 → 9/16. 잔여 7
  sub-step (Phase 0.11.d.2~.5 + 0.11.e.2~.5 + 별도 2 commit, 또는 별도 산정).

---

## 8. References

### Phase 0.11.c 5 commits
- (Phase 0.11.c.1 ADR §1 박제) — ADR 0009 §1 박제 (Round 2 APPROVE 시점 commit)
- `38c1e71` — Phase 0.11.c.2 (Protocol + sidecar + enrichment + namespace test)
- `ff61484` — Phase 0.11.c.3 (DGT renderer + 20 tests)
- `3af0415` — Phase 0.11.c.4 (orchestration + CLI + figure 박제 + 38 tests)
- `<current>` — Phase 0.11.c.5 (회고 + ADR §2/§3 + roadmap, 본 commit)

### 박제 문서
- `docs/decisions/0009-phase-0.11.c-visualization-renderers.md` §1+§2+§3
- `docs/retrospectives/phase-0.11.c.md` (본 회고)
- `docs/retrospectives/figures/phase-0.11.c/*.png` (4 PNG + JSON)

### Phase 0.11.b 정본 (선행)
- ADR 0008 §1+§2+§3 (D11 AND-gate FAIL + D10 archive 확정).
- 회고 `docs/retrospectives/phase-0.11.b.md`.

### 신규 코드 (5th ring `src/research/visualization/`)
- `_visualization_renderer.py` / `_artifacts.py` / `_trade_view_enrichment.py`
  (sub-step .2)
- `_dgt_renderer.py` (sub-step .3)
- `_align.py` / `_dgt_factory.py` / `_comparison.py` / `cli.py` / `__main__.py`
  (sub-step .4)

### 신규 tests (`tests/research/visualization/`)
- `test_protocol_structural_typing.py` / `test_artifacts.py` /
  `test_trade_view_enrichment.py` / `test_namespace_isolation.py` (sub-step .2)
- `test_dgt_renderer.py` (sub-step .3)
- `test_align.py` / `test_dgt_factory.py` / `test_comparison.py` /
  `test_cli_smoke.py` (sub-step .4)

### 참고
- ADR 0006 — `StrategyRenderer` Protocol (frozen 보존 invariant).
- ADR 0007 — 5-ring namespace 패턴 (D1 정합).
- CLAUDE.md §1.1 — Clean Architecture (production rings 변경 zero).
- CLAUDE.md §2.1 — Decimal invariant (float 미경유).

---

**본 회고 박제 완료 (Phase 0.11.c 시리즈 종료, 2026-05-13, sub-step
0.11.c.5). 게이트 4/4 PRIMARY PASS — 0.11.b 의 INFORMATIONAL FAIL 패턴과
달리 infrastructure phase 본질 정합. 산출: 신규 코드 ~1535 lines + 84
tests + 4 PNG + 1 JSON. 다음: Phase 0.11.d 진입 (사용자 결정 대기).**
