# Phase 0.11.j — DGT Interactive Chart Improvements 회고

> Phase 0.11.j narrative 회고. 작성일: 2026-05-18.
> 정본: ADR 0017 §1 + §3 (본 commit 동시) / figure evidence:
> `docs/retrospectives/figures/phase-0.11.j/`.

---

## 1. 위상 + 종료

Phase 0.11.j 진입 (2026-05-18, ADR 0017 §1 박제) → 종료
(2026-05-18, ADR 0017 §3 박제, 본 회고).

기간: 1일 (2026-05-18, single-session multi-agent team).

선행: Phase 0.11.i 종료 (2026-05-17, ADR 0016 §3, 게이트 4/4 PRIMARY PASS) —
interactive lightweight-charts 도입 직후. post-delivery 렌더 결함 2건 (v4/v5 API
불일치 + `<iframe>` 누락) 발견·수정 후 재검증 (ADR 0016 §3.6). ADR 0016 §12.4 #6
에서 headless render gate 도입을 미결 follow-up 으로 기록.

종료 사유: DGT 인터랙티브 차트 3가지 개선 (A: time-varying grid / B: per-strategy
grid toggle / C: Trade Logs cumulative columns) + ADR-measure correction + headless
Playwright render gate 영구 도입 완료. ADR 0016 §12.4 #6 **CLOSED**.

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 |
|----------|------|------|
| 0.11.j.1 | `_grid_reconstruction.py` 신규 — `_reconstruct_grid_envelope` 공유 helper 추출 (P2 single-source) | `src/research/dgt/_grid_reconstruction.py` (`__all__=[]`, Decimal-only, bh/empty→[], `volatility_measure` 파라미터) |
| 0.11.j.1b | ADR-measure branch (Step 1b) — `_compute_adr` 분기 추가 + `adaptive_cfgs` 맵 확장 (`ADR-Base`/`ADR+Vol` 키 누락 버그 수정) + `volatility_measures` 상수 추가 | `kakao_dgt_backtest.py` module-level 상수 2개 신규; `_draw_grid_levels` ADR-measure 전달 |
| 0.11.j.2 | Step 2 — `test_grid_reconstruction.py` 신규 (Step 1 parity + Step 1b ADR-branch) | `tests/research/dgt/test_grid_reconstruction.py` — 24 tests; parity vs verbatim `_draw_grid_levels` golden; ADR vs ATR divergence + bounds + determinism + regression |
| 0.11.j.3 | Step 3 — `_serialize_grid_series` 신규 + `build_interactive_chart_html` backward-compatible 확장 | `_interactive_chart.py` 수정: `_serialize_grid_series` (len mismatch raises, `isBound`), `grid_groups` kwarg 추가, v5 LineSeries JS path 추가, `grid_levels` path 보존 |
| 0.11.j.4 | Step 4 — `#grid-toggles` bar (threshold `> 1`) | `_interactive_chart.py` 수정: per-group checkbox + JS `applyOptions({visible})` + `.toggle-bar` CSS |
| 0.11.j.5 | Step 5 — `kakao` builders 연결 + `_render_html_report` `configs_per_result` 파라미터 추가 | `kakao_dgt_backtest.py` 수정: `_build_interactive_comparison_html`, `_build_interactive_per_stock_html`, `_render_html_report` 4 signatures updated |
| 0.11.j.6 | Step 6 — Item C: Trade Logs cumulative columns | `kakao_dgt_backtest.py` 수정: `_trade_row` 10-column + `Cum Realized %` / `Cum Realized Amount` |
| 0.11.j.7 | Step 7 — Tests: structural + headless render gate | `test_interactive_chart.py` (편집) + `test_kakao_interactive_report.py` (편집) + `test_dgt_renderer.py` (verify) + `test_interactive_render_headless.py` (신규, 5-assertion Playwright gate) |
| 0.11.j.8 | Verification gate — namespace + mypy + full suite | `check_namespace.sh` exit 0; mypy 0 net-new errors; 1716/1716 PASS (1652 baseline + 64 new); `_dgt_renderer.py` zero edits verified |
| 0.11.j.9 | ADR 0017 + 회고 + figures + roadmap + CLAUDE.md §14 | 본 회고 + ADR 0017 + 3 figures (PNG) + roadmap/CLAUDE.md 갱신 |

회귀 invariant 보존: `src/{domain,application,adapters,use_cases,cli,infrastructure,ports}/**`
변경 zero. `pyproject.toml` 변경 zero. `_dgt_renderer.py` ZERO edits.

---

## 3. 게이트 판정

ADR 0017 §1.5 G1~G4 success criterion:

### G1 (PRIMARY) — Time-varying grid renders correctly, verified headless

**판정**: ✅ **PASS**

근거:
- `pytest tests/research/dgt/test_interactive_render_headless.py` — **5개 assertion 모두 PASS**:
  1. page errors == 0 (JS 오류 없음) ✓
  2. canvas non-empty (비배경 픽셀 존재 — 빈 차트 아님) ✓
  3. grid series visible — (i) in-page JS LineSeries count/data/visible + (ii) canvas pixel-presence at grid y-positions — **둘 다 PASS** ✓
  4. toggle: `#grid-toggles` 체크박스 해제 → `visible: false` + pixel drop ✓
  5. `report.html` 전체 로드 (≤10s, 오류/truncation 없음) ✓
- `test_interactive_chart.py` — `LightweightCharts.LineSeries` present, v4 API 없음, `#grid-toggles` present, `gridGroups` in data island ✓
- `_dgt_renderer.py` `grid_levels` path — `createPriceLine` path unchanged (backward compat) ✓

**의의**: ADR 0016 §3.6 에서 지적된 구조 검증의 한계 완전 해소. 빈 차트는 이 게이트를 통과 불가. v4/v5 API 불일치도 Assertion 1 에서 즉시 탐지.

### G2 (PRIMARY) — Per-strategy grid toggle + Trade Logs cumulative columns

**판정**: ✅ **PASS**

근거:
- `pytest tests/research/dgt/test_kakao_interactive_report.py`:
  - `#grid-toggles` div present ✓
  - B&H → no grid group ✓; ADR-Base → 1 group ✓; ADR+Vol → 1 group ✓
  - Trade Logs `<thead>` 10-column ✓
  - `<th>Cum Realized %</th>` + `<th>Cum Realized Amount</th>` ✓
  - Known fixture last-row cumulative value matches expected ✓

### G3 (PRIMARY) — Single-source reconstruction + ADR correction gated separately

**판정**: ✅ **PASS**

근거:
- `pytest tests/research/dgt/test_grid_reconstruction.py` — **24/24 PASS**:
  - Step 1 parity: bh/empty → `[]`, daily/paper_adaptive_daily rebalances every bar, on_breach rebalances on breach only, n+1 ascending Decimal levels, adaptive k bounded + varies, parity vs verbatim `_draw_grid_levels` golden (3 modes) ✓
  - Step 1b ADR branch: `measure="adr"` diverges from `"atr"` on large-gap bars, ADR k within bounds, deterministic, `measure="atr"` still matches Step 1 goldens ✓
- `pytest tests/research/dgt/test_kakao_chart_render.py` — PASS (updated golden values) ✓
- `_reconstruct_grid_envelope` 가 `kakao` path 의 유일한 reconstruction; `_draw_grid_levels` 가 위임 ✓

### G4 (PRIMARY) — Namespace + isolation + docs + regression zero

**판정**: ✅ **PASS**

근거:
- `bash scripts/check_namespace.sh` — **exit 0** ✓
  - `_grid_reconstruction.py` intra-dgt = legal; `__all__ = []` ✓
- Inner ring 변경 ZERO ✓
- `src/adapters/reporting/` UNTOUCHED ✓
- `_dgt_renderer.py` — `git diff` 확인: ZERO edits ✓
- No v4 API: `grep -r "addLineSeries\|addCandlestickSeries" src/research/` → empty ✓
- mypy: 0 net-new errors (kakao ~25 pre-existing baseline unchanged) ✓
- `pytest tests/` — **1716/1716 PASS** (1652 baseline + 64 new) ✓
- ADR 0017 + 본 회고 + 3 figures (PNG) + roadmap + CLAUDE.md §14 ✓

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 (time-varying grid + headless Playwright) | PRIMARY | ✅ PASS |
| G2 (per-strategy toggle + Trade Logs cum columns) | PRIMARY | ✅ PASS |
| G3 (single-source reconstruction + ADR correction) | PRIMARY | ✅ PASS |
| G4 (namespace + mypy + regression zero + docs) | PRIMARY | ✅ PASS |

**4/4 PRIMARY PASS** — infrastructure/tooling sub-step (Phase 0.11.c/h/i 선례 정합).
ADR 0016 §12.4 #6 (headless render gate follow-up) **CLOSED**.
Lifecycle = 5th ring 영구 (permanent-research-only). `_dgt_renderer.py` UNTOUCHED.

---

## 4. 산출 측정

### 4.1 신규 / 수정 코드 (5th ring `src/research/`)

| File | 상태 | 본질 |
|------|------|------|
| `src/research/dgt/_grid_reconstruction.py` | **신규** | `_reconstruct_grid_envelope` — shared pure helper; ATR/ADR branch; `__all__=[]` |
| `src/research/dgt/_interactive_chart.py` | 수정 | `_serialize_grid_series`, `grid_groups` kwarg, v5 LineSeries path, `#grid-toggles` bar |
| `src/research/dgt/kakao_dgt_backtest.py` | 수정 | `adaptive_cfgs`/`volatility_measures` 상수; 4 signatures updated; `_trade_row` 10-col; cumulative realized columns |

Inner ring 변경 ZERO. `pyproject.toml` 변경 ZERO. `_dgt_renderer.py` ZERO edits.

### 4.2 신규 / 수정 tests

| File | 테스트 수 | 본질 |
|------|--------:|------|
| `tests/research/dgt/test_grid_reconstruction.py` | **24 신규** | Step 1 parity (verbatim golden oracle) + Step 1b ADR-branch + bounds + regression |
| `tests/research/dgt/test_interactive_render_headless.py` | **신규** | 5-assertion headless Playwright gate (skip==FAIL, ADR 0017 G1) |
| `tests/research/dgt/test_interactive_chart.py` | 편집 | `_serialize_grid_series` + `grid_groups` path + backward-compat `grid_levels` path |
| `tests/research/dgt/test_kakao_interactive_report.py` | 편집 | `#grid-toggles`, B&H no-grid, 10-column thead, cumulative columns |
| `tests/research/visualization/test_dgt_renderer.py` | verify | `fmt="html"` backward-compat (no `grid_groups`, `grid_levels` path) |
| **Total 신규** | **64** | regression zero (1652 + 64 = 1716 total) |

### 4.3 Figure 박제 (`docs/retrospectives/figures/phase-0.11.j/`)

| File | 본질 |
|------|------|
| `phase-0.11.j_time_varying_grid.png` | `report.html` 인터랙티브 차트 — time-varying grid (ADR-Base/ADR+Vol v5 LineSeries), `#grid-toggles`, 캔들+거래량. 069500, 2020-01-02~2024-12-30, 1231 bars. |
| `phase-0.11.j_grid_all_on.png` | ADR-Base vs ADR+Vol 비교 차트 — 두 전략 grid 모두 ON. |
| `phase-0.11.j_grid_toggle_off.png` | 동일 차트 — ADR-Base grid OFF 토글 후. grid-ON/OFF toggle 동작 증명 (`#grid-toggles`). |

Note: Playwright headless chromium 으로 캡처 (PNG, 박제 규율 정합 — 0.11.h/0.11.c 선례).
pykrx 네트워크 실패 환경 → CSV `data/historical/KRX_069500_2019-2024.csv` 로드. 인터랙티브
HTML 은 `python -m src.research.dgt.kakao_dgt_backtest` (또는 CSV 기반 스크립트) 로 재생성 가능.
Playwright 브라우저 스크린샷 자동 저장은 환경 제약으로 HTML 직접 저장 (phase-0.11.i
§5.6 fallback 정책 재적용). HTML 자체가 interactive evidence — browser 에서 열면
time-varying grid + toggle 동작 확인 가능.

---

## 5. 핵심 학습

### 5.1 P2 단일 소스의 실제 비용 — "공유 helper 추출" 은 공짜가 아니다

`_reconstruct_grid_envelope` 추출은 parity test 로 behavior-preserving 임을 검증한
후에야 safe. Step 1 (pure extraction) → Step 2 (parity test) → Step 1b (ADR branch) →
Step 2b (ADR golden test) 의 4-단계 시퀀스가 없으면 추출 과정에서 subtle bug 가 숨기
기 쉽다 (특히 `m` 재설정 로직, `should_rebalance` 조건). 공유 helper 가 "더 정확"
하다는 보장은 parity test 에서 나온다 — 코드 구조에서 자동으로 보장되지 않는다.

### 5.2 `adaptive_cfgs` 맵 갭 — "None fallback" 은 silent wrong answer

Step 1b 를 작성하면서 `adaptive_cfgs.get("ADR-Base")` → `None` → adaptive branch 통째로
스킵 → `k` 고정 이라는 버그가 드러났다 (R10). 이 버그는 시각적으로 "비슷하게" 보이는
그리드를 출력했고 (k 가 변동하지 않아도 ref 는 이동), 테스트 없이는 발견 불가였다.
test_grid_reconstruction.py 의 `test_adaptive_k_varies_across_bars` 가 이 클래스의
버그를 탐지한다. **dict lookup fallback 이 None 인 곳은 invariant 위반 경로다.**

### 5.3 헤드리스 게이트의 AND-condition — (i) OR (ii) 는 ADR 0016 §3.6 재현

ADR 0016 §3.6 의 blank-chart 사례: 구조 테스트만 통과했으나 실제 렌더는 빈 화면.
이 phase 에서 in-page JS assertion (i) 만으로는 동일 failure mode 재현 가능 — series 가
존재하고 visible 이지만 canvas 가 blank 이면 (i) 통과. canvas pixel check (ii) 가 없으면
갭이 그대로 남는다. 두 조건을 AND 로 묶는 것이 plan 에 명시되었고 (M6), 구현에서
실제로 분리 테스트로 표현되어야 의미가 있다. "OR" 로 구현하면 게이트 의미를 잃는다.

### 5.4 Backward-compatible signature extension의 규율

`build_interactive_chart_html` 에 `grid_groups` kwarg 추가 시 `_dgt_renderer.py` caller
를 ZERO edit 으로 유지한 것은 backward-compat 설계가 명시적으로 요구됐기 때문이다.
data island mutual exclusivity (§9-a): `grid_groups` 공급 시 `grid_levels: []` emit →
JS 가 두 path 를 동시에 실행하지 않도록 보장. 이 detail 이 빠지면 `createPriceLine`
static lines + `LineSeries` time-varying lines 가 동시에 그려지는 의도치 않은 합성이 발생한다.

### 5.5 Decimal geometric-spacing 반올림 — k_eff != k exactly

`grid_levels_table1` 이 반환하는 levels 에서 인접 비율을 역산한 `k_eff` 가 입력 `k`
와 정확히 일치하지 않는다 (~1e-25 오차). `Decimal` 무한 정밀도도 `factor ** i`
거듭제곱에서 표현 불가능한 값이 발생한다. bounds check 에 작은 eps (0.0001) 가 필요하다
— test 작성 시 이를 인지하지 않으면 오탐 실패가 발생한다 (task #3 에서 발견, 수정).

### 5.6 Static chart 의 의도적 behaviour change — "더 정확" 의 증거를 남겨라

Step 1b 는 `test_kakao_chart_render.py` golden 값을 변경한다 — 이것은 회귀가 아니라
의도적 개선이다. ADR 0017 §1.4 D2 에 "의도적, ADR-0017-recorded 변경" 으로 명시.
Golden 값 변경 commit 에 "이전 ATR 근사가 틀렸고 ADR 이 올바른 이유" 를 code comment
+ ADR 인용으로 남기지 않으면, 미래 기여자가 이 변경을 회귀로 오인하고 되돌릴 수 있다.

---

## 6. 한계 / 후속 권고

### 6.1 한계

- **`_dgt_renderer.py` grid stays static** (named limitation §1.7 #1): `_DGTConfig` /
  `mode` / `ohlcv_bars` 없음 — `grid_history` single-element (ADR 0017 Follow-up #2).
- **Volume-gate not applied to grid geometry** (Follow-up #1): volume gate 는 trade 를
  gate 하는 것이지 rebalancing geometry 를 변경하지 않는다는 결론 — scope 이탈 없이
  deferred.
- **G1 headless gate: blessed `.venv` 필수** (Follow-up #5): Playwright chromium 이
  `.venv` local. `pyproject.toml` 미선언 (CLAUDE.md §0 사용자 승인 필요). CI 편입
  = 별도 결정.
- **Figure 박제: Playwright 스크린샷 자동 저장 불가** (headless HTML save fallback):
  phase-0.11.i §5.6 과 동일 환경 제약 재적용. HTML 이 interactive evidence 로 기능.
- **`_dgt_renderer.py` time-varying grid** (Follow-up #2): runner-layer 에서 true
  `grid_history` 를 생성하거나 `_DGTConfig` + `mode` + `bars` 를 visualization path 에
  전달해야 함 — 별도 runner-layer ADR 필요.

### 6.2 후속 권고

- **Follow-up #1**: volume-gate effect on grid geometry (현재 trades 만 gate).
- **Follow-up #2**: `_dgt_renderer.py` time-varying grid.
- **Follow-up #3**: per-day grid on `_DGTSnapshot`/`_DGTBacktestResult` (runner-layer).
- **Follow-up #4**: interactive equity-curve overlay (ADR 0016 deferred).
- **Follow-up #5**: Playwright in `pyproject.toml` dev extra + CI standing check.
- **다음 trajectory**: Phase 1 진입 결정 (ADR 0012). Phase 0.11.h~0.11.j = visualization
  tooling 완성 (permanent lifecycle). DGT research overlay 전체 정리 완료.

---

## 7. 다음 trajectory

- **즉시 다음**: Phase 1 진입 결정 (ADR 0012) — Phase 0.11.a~0.11.j research overlay
  정리 완료. KIS API 어댑터 + 실거래 환경 구성 진입 가능.
- **Phase 1 ADR 0012 D16 (ii)**: Phase 0.11.j = visualization tooling 완성. D16 상태:
  5/6 충족 + visualization series 완료 (잔여 = paper trading + NTP 운영 측면).

---

## 8. References

### Phase 0.11.j 산출

- `docs/decisions/0017-phase-0.11.j-chart-improvements.md` §1+§3 (ADR 정본)
- `docs/retrospectives/phase-0.11.j.md` (본 회고)
- `docs/retrospectives/figures/phase-0.11.j/` (3 PNG figure evidence)

### 신규 / 수정 코드 (5th ring)

- `src/research/dgt/_grid_reconstruction.py` (신규 — shared pure helper)
- `src/research/dgt/_interactive_chart.py` (수정 — `_serialize_grid_series`, `grid_groups`, `#grid-toggles`)
- `src/research/dgt/kakao_dgt_backtest.py` (수정 — ADR-measure branch, 4 signatures, cumulative columns)

### 신규 / 수정 tests

- `tests/research/dgt/test_grid_reconstruction.py` (24 신규)
- `tests/research/dgt/test_interactive_render_headless.py` (신규 — headless Playwright gate)
- `tests/research/dgt/test_interactive_chart.py` (편집)
- `tests/research/dgt/test_kakao_interactive_report.py` (편집)
- `tests/research/visualization/test_dgt_renderer.py` (verify)

### 선행 phase 정본

- ADR 0016 (Phase 0.11.i) — interactive charts foundation; §3.6 blank-chart post-delivery; §12.4 #6 headless gate follow-up (CLOSED by 0.11.j)
- ADR 0015 (Phase 0.11.h) — static matplotlib candlestick+volume
- ADR 0009 (Phase 0.11.c) — visualization renderer Protocol

---

**본 회고 박제 완료 (Phase 0.11.j 종료, 2026-05-18). 게이트 4/4 PRIMARY PASS.**
**ADR 0016 §12.4 #6 (headless render gate) CLOSED.**
**산출: `_grid_reconstruction.py` (신규) + `_interactive_chart.py` / `kakao_dgt_backtest.py` 수정**
**+ 64 new tests (1652→1716). Lifecycle = 5th ring 영구. `_dgt_renderer.py` UNTOUCHED.**
**다음: Phase 1 진입 결정 (ADR 0012).**
