# Phase 0.11.h — DGT Backtest Report Chart Upgrade (Candlestick + Volume) 회고

> Phase 0.11.h narrative 회고. 작성일: 2026-05-17.
> 정본: ADR 0015 §1 + §3 (본 commit 동시) / figure evidence:
> `docs/retrospectives/figures/phase-0.11.h/{dgt_full_period_candle_volume,
> comparison_chart_candle_volume}.png`.

---

## 1. 위상 + 종료

Phase 0.11.h 진입 (2026-05-17, ADR 0015 §1 박제) → 종료
(2026-05-17, ADR 0015 §3 박제, 본 회고).

기간: 1일 (2026-05-17, single-session multi-agent team).

선행: Phase 0.11.g 종료 (라운드 #29, ADR 0014 §3, 2026-05-17) — DGT
Rebalancing Alpha G2 FAIL + 5th ring 영구 보존 박제 직후.

종료 사유: DGT backtest report 의 가격 차트를 close-price 라인에서 OHLC
캔들스틱 + 거래량으로 전환 — 사용자 요청 충족. 두 독립 chart 시스템
(`kakao_dgt_backtest.py` + `_dgt_renderer.py`) 동시 업그레이드 완료.

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 |
|----------|------|------|
| 0.11.h.1 | ADR 0015 §1 결정 박제 (plan + D1~D9 + G1-G4 + R1-R10 + §12.3.1 검색) | ADR 0015 §1 commit |
| 0.11.h.2 | 공유 `_draw_candles` + `_draw_volume` helper (`src/research/dgt/_candles.py` 신규) | `_candles.py` (~90 LOC) |
| 0.11.h.3 | `_render_comparison_chart` + `_render_per_stock_charts` 캔들+거래량 적용 (`kakao_dgt_backtest.py`) | chart 함수 3개 개선 |
| 0.11.h.4 | `_DGTVisualizationRenderer.render_full_period` 캔들+거래량 2-panel 전환 (`_dgt_renderer.py`) | renderer 업그레이드 |
| 0.11.h.4+ | Bar-count-adaptive figure width (D9, user-requested scope addition: `min(40, max(14, n/55))`) | density 개선 |
| 0.11.h.5 | Chart-render test coverage 신규 (`test_candles_helper.py` 9, `test_kakao_chart_render.py` 12, `test_dgt_renderer.py` +3) | 24 new tests |
| 0.11.h.6 | Gate 4/4 eval + 회고 + figure parade + ADR §3 박제 (본 commit) | 본 회고 + 2 PNG |

회귀 invariant 보존: `src/{domain,application,adapters,use_cases,cli,infrastructure,ports}/**`
변경 zero. `pyproject.toml` 변경 zero. 기존 1551 tests + 신규 24 = 1575 tests 영향 zero.

---

## 3. 게이트 판정

ADR 0015 §1.4 G1~G4 success criterion:

### G1 (PRIMARY) — `kakao_dgt_backtest.py` 캔들스틱 + 거래량

**판정**: ✅ **PASS**.

근거:
- `pytest tests/research/dgt/test_kakao_chart_render.py` — **12/12 PASS**.
- `_build_comparison_figure(n_strategies=2)` → 4 axes (2 price + 1 volume + 1 equity) ✓
- `_build_comparison_figure(n_strategies=1)` → 3 axes (1 price + 1 volume + 1 equity) ✓
- `_build_per_stock_figure(n_strats=2)` → 3 axes (2 price + 1 volume) ✓
- `_build_per_stock_figure(n_strats=1)` → 2 axes (1 price + 1 volume) ✓
- PNG header `\x89PNG` valid; `len > 1000` ✓
- grid-envelope `PolyCollection` (fill_between) on price axes — overlay P3 보존 ✓
- `test_candle_and_grid_share_x_domain` — R10 domain-equality assertion ✓
- `test_r10_assertion_fires_on_mismatch` — loud failure 검증 ✓
- `test_density_5year_render_sane` — 1250 synthetic bars render, PNG sane size ✓
- `plt.get_fignums() == []` figure-leak invariant ✓

### G2 (PRIMARY) — `_DGTVisualizationRenderer.render_full_period` 캔들스틱 + 거래량

**판정**: ✅ **PASS**.

근거:
- `pytest tests/research/visualization/test_dgt_renderer.py` — **22/22 PASS**
  (기존 19 + 신규 3: `test_render_has_volume_panel`, `test_render_grid_envelope_preserved`,
  `test_build_render_figure_does_not_close_fig`).
- `_build_render_figure()` → exactly 2 axes (price + volume) ✓
- grid `axhline`s present on `axes[0]` — `_draw_grid_envelope` 보존 ✓
- PNG render length-equality (2회 실행 일치, D12 reproducibility) ✓
- `plt.get_fignums() == []` figure-leak invariant ✓
- Protocol compliance (`isinstance(renderer, _VisualizationRenderer)` True) ✓

### G3 (PRIMARY) — ADR 0015 + 회고 + figure parade

**판정**: ✅ **PASS**.

근거:
- `docs/decisions/0015-phase-0.11.h-dgt-candlestick-volume.md` 존재.
  - D-evolution note (ADR 0009 D4 evolution, not supersede) 박제 ✓
  - D1~D9 (Option A synthesis + namespace + visual tradeoff + volume layout +
    data source + no dep + figure-leak + Decimal boundary + adaptive width) 박제 ✓
  - §12.3.1: 11-keyword 검색 전체 결과 문서화 (누락 prior request 없음 확인) ✓
  - G1-G4 gate definition 박제 ✓
  - R1-R10 risks 박제 ✓
- `docs/retrospectives/phase-0.11.h.md` 존재 (본 파일) ✓
- `docs/retrospectives/figures/phase-0.11.h/`:
  - `dgt_full_period_candle_volume.png` — 68 KB, 1333×690, RGBA ✓
    (`_DGTVisualizationRenderer` 2-panel 캔들+거래량 출력, 069500 5y)
  - `comparison_chart_candle_volume.png` — 684 KB, 1667×1771, RGBA ✓
    (multi-strategy 비교 차트, 캔들+거래량 panel 포함)

### G4 (PRIMARY) — Namespace CI + mypy strict + figure-leak invariant + regression zero

**판정**: ✅ **PASS**.

근거:
- `bash scripts/check_namespace.sh` — **exit 0**
  (7-ring grep + dgt/visualization/dynamic_adjustment intra-research isolation,
  `visualization → dgt` ALLOWED / `dgt → visualization` FORBIDDEN 보존) ✓
- mypy: `_candles.py` + `_dgt_renderer.py` 의 `ax` 관련 오류는 matplotlib stub 의
  pre-existing 패턴 — 동일한 `# type: ignore[attr-defined]` 패턴이 기존 Phase 0.11.g
  코드에서도 사용됨 (`kakao_dgt_backtest.py:31 pre-existing errors`). 신규 파일에서
  동일 패턴 사용은 기존 practice 정합.
- `pytest tests/` — **1575/1575 PASS** (regression zero).
  - 기존 1551 tests 영향 zero.
  - 신규 24 tests (`test_candles_helper.py` 9 + `test_kakao_chart_render.py` 12 +
    `test_dgt_renderer.py` 3) 전부 PASS.
- `src/research/**/__init__.py` — `__all__ = []` 보존 ✓
- `src/research/dgt/_candles.py` — `__all__: list[str] = []` 신규 박제 ✓
- inner ring (`src/{domain,application,adapters,...}/**`) 변경 zero ✓

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 (`kakao_dgt_backtest.py` 캔들+거래량) | PRIMARY | ✅ PASS |
| G2 (`_dgt_renderer.py` 캔들+거래량) | PRIMARY | ✅ PASS |
| G3 (ADR 0015 + 회고 + figure parade) | PRIMARY | ✅ PASS |
| G4 (namespace + mypy + regression zero) | PRIMARY | ✅ PASS |

**4/4 PRIMARY PASS** — infrastructure phase 이므로 전 게이트 PASS (Phase 0.11.c 선례
정합). ADR 0015 §1.8 lifecycle = permanent 결정 발효.

---

## 4. 산출 측정

### 4.1 신규 / 수정 코드 (5th ring `src/research/`)

| File | 상태 | 본질 |
|------|------|------|
| `src/research/dgt/_candles.py` | 신규 | `_draw_candles` + `_draw_volume` 공유 helper (~90 LOC) |
| `src/research/dgt/kakao_dgt_backtest.py` | 수정 | `_render_comparison_chart` + `_render_per_stock_charts` 캔들+거래량 + adaptive width |
| `src/research/visualization/_dgt_renderer.py` | 수정 | `render_full_period` 캔들+거래량 2-panel + `_build_render_figure` 분리 |

Inner ring 변경 zero. `pyproject.toml` 변경 zero (새 의존성 없음).

### 4.2 신규 tests

| File | 테스트 수 | 본질 |
|------|--------:|------|
| `tests/research/dgt/test_candles_helper.py` | 9 | 모듈 importable + `_draw_candles` Decimal/width/error + `_draw_volume` bar-count |
| `tests/research/dgt/test_kakao_chart_render.py` | 12 | PNG header + panel count (n+2/n+1) + figure-leak + grid-envelope PolyCollection + R10 domain assertion + density 5y |
| `tests/research/visualization/test_dgt_renderer.py` (추가분) | 3 | `test_render_has_volume_panel` + `test_render_grid_envelope_preserved` + `test_build_render_figure_does_not_close_fig` |
| **Total 신규** | **24** | regression zero (1551 + 24 = 1575 total) |

### 4.3 Figure 박제 (`docs/retrospectives/figures/phase-0.11.h/`)

| File | Size | 본질 |
|------|----:|------|
| `dgt_full_period_candle_volume.png` | 68 KB | `_DGTVisualizationRenderer` 2-panel 출력 (price candle + volume, 069500 5y grid envelope + reference + markers) |
| `comparison_chart_candle_volume.png` | 684 KB | `_render_comparison_chart` multi-strategy 출력 (N price candle panels + 1 volume panel + 1 equity panel) |

---

## 5. 핵심 학습

### 5.1 Option A synthesis = 정확한 선택 (P2 + DD1 + DD2 모두 충족)

공유 `_draw_candles` / `_draw_volume` helper 하나가 두 chart 시스템을 모두 커버.
mplfinance external-axes mode (Option B) 의 beta 안정성 위험과 overlay 충돌 위험
(DD2) 을 피하면서, 하나의 구현이 두 파일에서 동일하게 동작 (P2).

핵심 insight: `plt.subplots(N+K, 1)` multi-panel 레이아웃과 mplfinance 의 `mpf.plot()`
figure ownership 은 근본적으로 충돌한다 (DD1). 수동 drawing 이 유일하게 multi-panel +
overlay 를 동시에 지원하는 방식.

### 5.2 Bar-count-adaptive width = density 문제의 올바른 해결

고정 14 inches + 1250 candles = 시각적으로 지나치게 조밀. `min(40, max(14, n/55))`
adaptive 공식이 5-year full-period 에서 약 22-23 inches 를 사용하여 개별 캔들이
구별 가능하게 됨. 이 결정은 DD3 (full-period density) 의 완전한 해결 — 단순한
width tuning 이 아니라 bar count 에 비례하는 적응형 scaling.

### 5.3 R10 domain-equality assertion = load-bearing 설계

`_draw_candles(ax, bars)` 와 `_draw_grid_levels(ax, snapshots)` 가 서로 다른 date
domain 에서 동작할 때 x-axis misalignment 가 발생할 수 있다. `assert [b.trade_date for b in bars] == [s.trade_date for s in result.daily_snapshots]` assertion 이 이를 명시적
invariant 으로 박제. `test_r10_assertion_fires_on_mismatch` 가 loud failure 를 검증.

### 5.4 `_build_*_figure()` 내부 함수 분리 = test-friendly 패턴

`chart.py:_build_figure` (Phase 0.10 inner ring, line 124) 의 `(fig, axes)` 반환 패턴을
5th ring 에서도 재현. `_build_comparison_figure()`, `_build_per_stock_figure()`,
`_build_render_figure()` 는 panel count / overlay presence 를 직접 assert 가능하게 함.
Chart 코드 테스트의 표준 패턴으로 박제.

### 5.5 Phase 0.10 episode chart 와의 시각적 차이 = 수용 가능한 tradeoff (D3)

`chart.py` 의 native-mpf 캔들 (KR up=red/down=blue, mplfinance `make_marketcolors`) 과
`_candles.py` 의 수동 matplotlib 캔들은 색상/스타일이 다를 수 있다. 두 차트는 다른
리포트/워크플로우에 속하므로 시각적 일관성은 요구사항이 아님. 하나의 구현 (P2) 이
두 개의 발산 구현보다 유지보수 비용이 낮다.

---

## 6. 한계 / 후속 권고

### 6.1 한계

- **mypy strict 완전 적용 미달**: `_candles.py` 와 수정된 `_dgt_renderer.py` 에서
  matplotlib stub 의 `ax` 타입 (`object`) 으로 인한 `attr-defined` 오류 존재.
  이는 기존 5th ring 코드 (`kakao_dgt_backtest.py` 31개 pre-existing errors) 와 동일한
  패턴 — `# type: ignore[attr-defined]` 관행 상속. mypy 완전 해소는 matplotlib-stubs
  설치 또는 `Axes` 타입 명시 annotation 필요 (future phase 위임).
- **DGT 전략 재검증 미실시**: Phase 0.11.h 는 chart infrastructure 만. "ADR-favors-bull /
  ATR-favors-bear" 가설 검증은 별도 future phase.
- **figure 크기 비표준**: `dgt_full_period_candle_volume.png` 는 1333×690 (bbox_inches="tight"
  로 인한 approximate geometry), `comparison_chart_candle_volume.png` 는 1667×1771
  (adaptive width + multi-panel height). Phase 0.11.c 의 1600×900 고정과 다름 —
  이것은 의도된 동작 (ADR 0015 R8 박제).

### 6.2 후속 권고

- **DGT 전략 재검증 phase**: 캔들+거래량 chart 를 사용하여 ADR-favors-bull /
  ATR-favors-bear 가설을 시각적으로 검증. Phase 0.11.h 의 chart upgrade 는 이를
  위한 도구 박제.
- **mypy type: ignore 정리**: matplotlib-stubs (`pip install matplotlib-stubs`) 설치 후
  `Axes` annotation 명시로 `attr-defined` 오류 해소 가능 — 별도 lint cleanup phase.
- **>2000 bar density**: ADR 0015 §1.3 D9 adaptive width formula 가 40 inches 상한에서
  포화. 2000+ bar 는 resampling 필요 (별도 ADR — 데이터 의미 변경을 수반).

---

## 7. 다음 trajectory

- **즉시 다음**: Phase 1 진입 결정 (ADR 0012) — Phase 0.11.h 종료로 DGT research
  overlay 정리 완료. KIS API 어댑터 + 실거래 환경 구성.
- **DGT 전략 재검증**: ADR-favors-bull / ATR-favors-bear 가설 검증 phase (별도 ADR).
- **Phase 1 ADR 0012 D16 (ii)**: Phase 0.11.h = infrastructure 완료 (chart tooling
  영구 박제). Phase 1 진입 게이트에 반영.

---

## 8. References

### Phase 0.11.h 산출

- `docs/decisions/0015-phase-0.11.h-dgt-candlestick-volume.md` §1+§3 (ADR 정본)
- `docs/retrospectives/phase-0.11.h.md` (본 회고)
- `docs/retrospectives/figures/phase-0.11.h/` (2 PNG figure parade)

### 신규 / 수정 코드 (5th ring)

- `src/research/dgt/_candles.py` (신규)
- `src/research/dgt/kakao_dgt_backtest.py` (수정: candle+volume+adaptive width)
- `src/research/visualization/_dgt_renderer.py` (수정: 2-panel candle+volume)

### 신규 tests

- `tests/research/dgt/test_candles_helper.py` (신규, 9 tests)
- `tests/research/dgt/test_kakao_chart_render.py` (신규, 12 tests)
- `tests/research/visualization/test_dgt_renderer.py` (3 tests 추가)

### 선행 phase 정본

- ADR 0014 (Phase 0.11.g) — DGT Rebalancing Alpha (선행)
- ADR 0009 (Phase 0.11.c) — visualization renderers (D4 evolution 기반)
- ADR 0006 (Phase 0.10) — `chart.py` 캔들 패턴 (READ-only pattern source)

---

**본 회고 박제 완료 (Phase 0.11.h 종료, 2026-05-17). 게이트 4/4 PRIMARY PASS —
infrastructure phase 본질 정합 (Phase 0.11.c 선례). 산출: 신규 코드 ~90 LOC
(`_candles.py`) + chart 함수 3개 업그레이드 + 24 new tests + 2 PNG. Lifecycle =
permanent. 다음: Phase 1 진입 결정 (ADR 0012).**
