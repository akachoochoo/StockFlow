# Phase 0.11.i — Interactive DGT Charts (lightweight-charts) 회고

> Phase 0.11.i narrative 회고. 작성일: 2026-05-17.
> 정본: ADR 0016 §1 + §3 (본 commit 동시) / figure evidence:
> `docs/retrospectives/figures/phase-0.11.i/`.

---

## 1. 위상 + 종료

Phase 0.11.i 진입 (2026-05-17, ADR 0016 §1 박제) → 종료
(2026-05-17, ADR 0016 §3 박제, 본 회고).

기간: 1일 (2026-05-17, single-session multi-agent team).

선행: Phase 0.11.h 종료 (2026-05-17, ADR 0015 §3, 게이트 4/4 PRIMARY PASS) — DGT
백테스트 리포트 static matplotlib candlestick+volume 박제 직후. 사용자가 throwaway
Plotly demo (`reports/interactive-demo/dgt_069500_interactive.html`, ~5 MB) 를 평가 →
**interactive, lightweight-charts** 채택 결정.

종료 사유: DGT 백테스트 리포트의 모든 chart surface 를 **interactive lightweight-charts**
로 전환 완료. ADR 0006 §14.4 Option C rejection + ADR 0009 D4(b) 역전. Phase 0.11.h
static matplotlib renderer 는 archival-only path 로 강등 (sunset trigger 정의).

---

## 2. Sub-step 진행

| Sub-step | 본질 | 산출 |
|----------|------|------|
| 0.11.i.1 | Vendor lightweight-charts JS asset (`src/research/dgt/assets/`) + PROVENANCE.txt | vendored `lightweight-charts.standalone.production.js` (~50 KB v5.x) + `PROVENANCE.txt` |
| 0.11.i.2 | `_interactive_chart.py` HTML builder module + tests-first | `_interactive_chart.py` (`_serialize_ohlcv/volume/markers/grid_levels`, `_safe_json_embed`, `build_interactive_chart_html`) + `test_interactive_chart.py` |
| 0.11.i.3 | Wire interactive charts into `report.html` (`kakao_dgt_backtest.py`) | `_render_html_report` 기존 base64-PNG `<img>` → interactive `<div>` 전환 + `--static-charts` rollback flag + `test_kakao_interactive_report.py` |
| 0.11.i.4 | `fmt` kwarg on `_dgt_renderer.py` + Protocol (Option iii) | `_visualization_renderer.py` Protocol + `_dgt_renderer.py` `fmt` dispatch + extended `test_dgt_renderer.py` |
| 0.11.i.5 | Plotly demo + temp-install cleanup | `reports/interactive-demo/` deleted; `plotly==6.7.0` + `narwhals==2.21.2` uninstalled; `pyproject.toml` plotly-free 확인 |
| 0.11.i.6 | Test suite + namespace + verification gate (G4) | 1650/1650 PASS (1575 + 75 new); `check_namespace.sh` exit 0; mypy regression-zero |
| 0.11.i.7 | Figure 박제 (static + interactive evidence) | `phase-0.11.i_static_comparison_069500.png` (905 KB) + `phase-0.11.i_interactive_report_069500.html` (613 KB) |
| 0.11.i.8 | ADR 0016 + 회고 + roadmap + CLAUDE.md §14 | 본 회고 + ADR 0016 + roadmap/CLAUDE.md 갱신 |

회귀 invariant 보존: `src/{domain,application,adapters,use_cases,cli,infrastructure,ports}/**`
변경 zero. `pyproject.toml` 변경 zero (vendored JS = non-pip asset).
기존 1575 tests 영향 zero. Inner ring diff = 0.

---

## 3. 게이트 판정

ADR 0016 §1.4 G1~G4 success criterion:

### G1 (PRIMARY) — `report.html` interactive + zero network references

**판정**: ✅ **PASS** — 단 phase-close 판정은 **구조 검증 한정**이었고, post-delivery
에 렌더 결함 2건을 발견·수정 후 재검증했다 (§3.6 / ADR 0016 §3.6).

근거 (구조 검증, phase-close):
- `pytest tests/research/dgt/test_kakao_interactive_report.py` — **14/14 PASS**.
- `report.html` zero `data:image/png;base64` main-chart `<img>` ✓
- `<script type="application/json">` data island parseable, correct counts ✓
- zero `http(s)://` `<script src>` (2 https matches = Apache License comments in vendored
  JS, not network fetches) ✓
- `--static-charts` flag → PNG-based HTML (matplotlib rollback path works) ✓

근거 (렌더 검증, post-delivery 2026-05-17 — §3.6):
- Playwright headless chromium 실제 로드: page error 0, 캔버스 픽셀에 캔들·거래량·
  마커 렌더 확인, `.chart-interactive` 요소 스크린샷 정상 ✓
- 인터랙티브 figure 결함 수정 후 재생성.

**주의**: phase-close 시 본 게이트는 구조 단언만으로 PASS 처리되어 실제 렌더링은
검증되지 않았고, 렌더 결함 2건이 통과되었다. §3.6 에 박제.

### G2 (PRIMARY) — `fmt` kwarg + static contract preserved

**판정**: ✅ **PASS**.

근거:
- `pytest tests/research/visualization/test_dgt_renderer.py` — **12/12 PASS** (Phase
  0.11.i 신규 tests 포함).
- `render_full_period(bars, trades, artifacts)` (no `fmt`) → PNG bytes (`\x89PNG`) ✓
- `render_full_period(bars, trades, artifacts, fmt="html")` → HTML str with
  `LightweightCharts`/`createChart` + data island ✓
- `artifacts=None` graceful-degrade ✓
- `isinstance(_DGTVisualizationRenderer(), _VisualizationRenderer)` True ✓
- `cli.py:400` caller regression: bare call (no `fmt`) still works ✓

### G3 (PRIMARY) — ADR 0016 + 회고 + figure parade + roadmap/CLAUDE.md

**판정**: ✅ **PASS**.

근거:
- `docs/decisions/0016-phase-0.11.i-interactive-charts.md` 존재 ✓
  - §1.2 reversal 범위 명시 (ADR 0006 §14.4 + ADR 0009 D4(b)) ✓
  - D1~D9 + G1~G4 + R1~R11 박제 ✓
  - §12.3.1 keyword 검색 결과 문서화 (3건 처리) ✓
  - sunset trigger (D9) + minimum browser baseline (ES2020) 정의 ✓
- `docs/retrospectives/phase-0.11.i.md` 존재 (본 파일) ✓
- `docs/retrospectives/figures/phase-0.11.i/`:
  - `phase-0.11.i_static_comparison_069500.png` — 905 KB (static matplotlib 박제 path
    proof: ADR-Base vs ADR+Vol vs B&H-100%, 069500, 2020-01-02~2024-12-30, 1231 bars) ✓
  - `phase-0.11.i_interactive_report_069500.html` — 613 KB (interactive evidence) ✓
- `docs/roadmap.md` Phase 0.11.i row 추가 ✓
- `CLAUDE.md §14` 현 상태 + 인덱스 갱신 ✓

### G4 (PRIMARY) — Namespace CI + intra-research isolation + mypy + regression zero

**판정**: ✅ **PASS**.

근거:
- `bash scripts/check_namespace.sh` — **exit 0** ✓
  - 7-ring inner-ring isolation ✓
  - `dgt/ → non-dgt research` FORBIDDEN 보존 (`_interactive_chart.py` 가 `dgt/` 내
    에 있으므로 intra-dgt import = legal) ✓
  - `visualization/ → dgt/` ALLOWED (forward direction 보존) ✓
- `__all__ = []` 보존: `_interactive_chart.py`, `_visualization_renderer.py`,
  `_dgt_renderer.py` 전부 ✓
- Inner ring 변경 zero ✓
- mypy: `_dgt_renderer.py:280` 1 new error (worker-1 해소). Pre-existing 24-error
  baseline (kakao) unchanged ✓
- `pytest tests/` — **1650/1650 PASS** ✓
  신규 75 tests:
  - `tests/research/dgt/test_interactive_chart.py` (new)
  - `tests/research/dgt/test_kakao_interactive_report.py` (new)
  - `tests/research/visualization/test_dgt_renderer.py` (extended)
- `pip3 show plotly` → **not found** ✓

### 종합

| Gate | 종류 | 결과 |
|------|------|------|
| G1 (`report.html` interactive + zero network refs) | PRIMARY | ✅ PASS — post-delivery 정정 (§3.6) |
| G2 (`fmt` kwarg + static contract preserved) | PRIMARY | ✅ PASS |
| G3 (ADR 0016 + 회고 + figures + roadmap/CLAUDE.md) | PRIMARY | ✅ PASS |
| G4 (namespace + mypy + regression zero + plotly removed) | PRIMARY | ✅ PASS |

**4/4 PRIMARY PASS** — infrastructure phase 이므로 전 게이트 PASS (Phase 0.11.c/h
선례 정합). **단 G1 은 phase-close 시 구조 검증만으로 PASS 처리되어 렌더 결함 2건이
통과되었고, post-delivery 에 발견·수정·재검증되었다 — §3.6 참조.** ADR 0016 lifecycle
= permanent (interactive) + archival-with-sunset (static).

### §3.6 Post-delivery 결함 정정 (2026-05-17)

Phase 0.11.i 종료 직후 사용자 브라우저 확인에서 인터랙티브 차트가 **빈 화면**으로
보고되었다. headless Playwright 로 근본 원인을 추적, 결함 2건을 발견·수정했다.

- **결함 1 — lightweight-charts v4 API / v5 lib 불일치** (`_interactive_chart.py`):
  vendored JS v5.2.0 인데 init 스크립트가 v4 API (`addCandlestickSeries`,
  `addHistogramSeries`, `setMarkers`) 호출 → 로드 즉시 `TypeError` → 미렌더. 수정:
  v5 API (`addSeries(LightweightCharts.CandlestickSeries, …)`, `createSeriesMarkers`).
- **결함 2 — full-page HTML 을 `<div>` raw 삽입** (`kakao_dgt_backtest.py`
  `_render_html_report`): `build_interactive_chart_html` 의 완전한 HTML 문서를
  `<iframe>` 아닌 raw `<div>` 에 삽입 → CSS `.chart-interactive > *{height:100%}` 가
  삽입된 `<h1>` 을 600px 로 부풀려 차트를 가시 영역 밖으로 밀어냄. 수정: `<iframe
  srcdoc>` 삽입.
- **근본 원인 — 검증 갭**: G1 검증이 구조 단언(HTML 에 심볼·데이터 존재) 한정으로
  JS 실행/렌더를 검증하지 않았다. 계획의 "Step 6 스크린샷 렌더 검증"이 headless
  환경에서 미실행 → HTML 직접 저장 fallback → 두 결함 통과. Architect R1 리뷰가
  정확히 경고한 갭 ("`createChart` grep ≠ 실제 렌더; 빈 차트 통과 가능").
- **재검증**: Playwright headless 로 page error 0 + 캔버스 렌더 픽셀 확인; 전체
  1650 tests PASS, `check_namespace.sh` exit 0. → §5.7 학습 박제.

---

## 4. 산출 측정

### 4.1 신규 / 수정 코드 (5th ring `src/research/`)

| File | 상태 | 본질 |
|------|------|------|
| `src/research/dgt/assets/lightweight-charts.standalone.production.js` | 신규 (vendored) | TradingView lightweight-charts v5.x, ~50 KB, offline self-contained |
| `src/research/dgt/assets/PROVENANCE.txt` | 신규 | version + upstream URL + SHA-256 + minimum browser baseline (ES2020) |
| `src/research/dgt/_interactive_chart.py` | 신규 | HTML builder: `_serialize_*` + `_safe_json_embed` + `build_interactive_chart_html` |
| `src/research/dgt/kakao_dgt_backtest.py` | 수정 | `_render_html_report` interactive 전환 + `--static-charts` rollback flag |
| `src/research/visualization/_visualization_renderer.py` | 수정 | Protocol `render_full_period` `fmt` kwarg + `@overload` |
| `src/research/visualization/_dgt_renderer.py` | 수정 | `fmt` dispatch (png → matplotlib / html → lightweight-charts) |
| `scripts/gen_phase_0_11_i_figures.py` | 신규 (helper) | Figure 박제용 pykrx-bypass 스크립트 (CSV 로드) |

Inner ring 변경 zero. `pyproject.toml` 변경 zero.

### 4.2 신규 tests

| File | 테스트 수 | 본질 |
|------|--------:|------|
| `tests/research/dgt/test_interactive_chart.py` | 신규 | `_serialize_ohlcv/volume/markers`, `_safe_json_embed` XSS, `build_interactive_chart_html` 구조, Decimal round-trip, offline self-containment |
| `tests/research/dgt/test_kakao_interactive_report.py` | 14 신규 | `report.html` zero base64, data island parse, zero network refs, rollback flag, report.html structure |
| `tests/research/visualization/test_dgt_renderer.py` | 확장 | `fmt="png"` regression, `fmt="html"` HTML str, graceful-degrade, structural typing |
| **Total 신규** | **75** | regression zero (1575 + 75 = 1650 total) |

### 4.3 Figure 박제 (`docs/retrospectives/figures/phase-0.11.i/`)

| File | Size | 본질 |
|------|----:|------|
| `phase-0.11.i_static_comparison_069500.png` | 905 KB | static matplotlib 박제 path proof (ADR-Base vs ADR+Vol vs B&H-100%, 069500 2020~2024, 1231 bars) |
| `phase-0.11.i_interactive_report_069500.html` | 613 KB | interactive lightweight-charts report (browser screenshot 불가 환경 → HTML 직접 저장, plan §6 fallback) |

Note: browser screenshot 자동화 (Selenium/Playwright) 는 DD3 에 의해 out-of-scope.
Render-correctness 는 headless env 이므로 interactive HTML 직접 저장으로 대체 —
plan §6 "if you cannot capture a browser screenshot ... save the interactive report.html
itself into the figures dir and note that" 적용.

---

## 5. 핵심 학습

### 5.1 Vendored JS = zero blast radius dependency (P2/DD1)

pyproject.toml 에 추가하는 pip 의존성 vs. vendored JS 파일의 근본적 차이:
pip dep 는 Python trading 프로세스 실행 시 import/exec — cron / order flow / domain
에 영향. Vendored JS 는 browser 가 `report.html` 열 때만 실행 — Python 프로세스와
완전 격리. 이 distinction 이 CLAUDE.md §0 "새 외부 의존성" 의 blast radius 분석에서
결정적 justification 이 됨.

### 5.2 Option B (vendored) vs. Option C (CDN) — offline 재현성이 결정 요인

CDN 의 "zero repo asset" 이점은 illusory: view-time network fetch 는 figure 박제
재현성에 구조적 hole 을 만든다. 50 KB vendored file + SHA-256 provenance 가 CDN pin
보다 재현성 측면에서 압도적으로 우위. Option B 가 P5 (offline) 를 uniquely satisfy.

### 5.3 Protocol Option (iii) `fmt` kwarg = least-invasive extension pattern

ADR 0009 `:188` "Protocol 변경 zero" 를 완전히 지키려면 새 sibling method 를 추가해야
하지만 (ii), 이것은 `@runtime_checkable` structural typing 에서 모든 implementor 에
새 method body 강제 — ADR 0009 `:188` 의 intent (no forced migration) 을 오히려 더
크게 위반. Defaulted kwarg (iii) 가 letter 는 좁게 위반하면서 spirit 은 더 잘 보존하는
역설적 pattern — 인터페이스 extension 에서 recurring insight.

### 5.4 Intra-research cross-import rule이 C1 relocation을 강제

`_interactive_chart.py` 를 `visualization/` 에 두면 `kakao_dgt_backtest.py` (dgt 내)
가 `dgt → visualization` reverse import 를 발생시켜 `check_namespace.sh:58-68` 위반.
`dgt/` 에 두면 `kakao_dgt_backtest.py` = intra-dgt (legal), `_dgt_renderer.py`
(`visualization/`) = forward direction (legal). 위치 결정이 namespace rule 에 의해
mechanical 하게 결정되는 명확한 사례.

### 5.5 `_safe_json_embed` = 작지만 load-bearing hardening

`json.dumps(obj).replace("</", "<\\/")` 한 줄이 `</script>` breakout XSS vector 를
차단. data island 패턴 (`<script type="application/json">`) 은 대용량 OHLCV JSON 을
JS 코드 문자열 interpolation 없이 분리 → testability 와 safety 동시 확보.

### 5.6 Figure 박제 — headless env fallback은 계획에 명시해야

pykrx 네트워크 실패 + browser 자동화 불가 = 두 가지 env 제약이 figure 박제 계획에
영향. plan §6 의 "if you cannot capture a browser screenshot ... save the interactive
report.html itself" fallback 이 있었기 때문에 막힘 없이 진행. Future phase 에서도
figure 박제 plan 에 env 제약 fallback 을 명시적으로 포함할 것.

### 5.7 구조 검증 ≠ 렌더 검증 — G1 이 빈 차트를 통과시킨 이유 (§3.6)

본 phase 의 가장 큰 학습. G1 의 자동 검증은 "HTML 이 `createChart`·data island·
올바른 카운트를 포함하는가" 라는 **구조 단언** 한정이었다 — JS 를 실행하지도,
브라우저에 렌더하지도 않는다. 그 결과 렌더 결함 2건 (v5 API 불일치, iframe 임베딩
누락) 이 14/14 + 12/12 "PASS" 를 통과하고도 실제 차트는 빈 화면이었다. 계획의
"Step 6 스크린샷 렌더 검증" 이 유일한 실렌더 게이트였으나 headless 환경에서
미실행되어 §5.6 의 HTML-직접-저장 fallback 으로 대체되었고 — **그 fallback 이
구조 검증의 갭을 메우지 못한다는 점이 간과되었다** (§5.6 의 fallback 은 "박제
산출물 확보" 는 해결하지만 "렌더 정확성 검증" 은 해결하지 않는다).

Architect 가 R1 리뷰에서 이 갭을 정확히 예측했다: *"G1 은 `createChart` 문자열만
grep 한다 — 실제 렌더가 아니다; JS init 에 오타가 있어 load 시 throw 하면 빈 차트가
그대로 통과한다."* 이 경고가 plan 의 "구조 테스트 only, render = 1회 스크린샷"
타협으로 흡수되었고, 스크린샷이 실행 안 되자 갭이 그대로 노출됐다.

교훈: **JS/렌더 산출물은 구조 테스트로 검증 완료라 부를 수 없다.** headless 렌더
스모크 (page error 0 + 캔버스 픽셀 non-empty 확인) 가 최소 게이트여야 한다.
post-delivery 정정에 사용한 Playwright 가 그 도구 — 검증 파이프라인 편입 여부는
ADR 0016 §12.4 #6 follow-up.

---

## 6. 한계 / 후속 권고

### 6.1 한계

- **G1 렌더 검증 갭 (post-delivery 노출)**: phase-close 시 구조 검증만으로 PASS
  처리 → 렌더 결함 2건 통과. post-delivery 에 Playwright headless 로 발견·수정·
  재검증 (§3.6 / §5.7). 검증 파이프라인에 headless 렌더 스모크가 없다는 구조적
  한계가 남아 있음 — ADR 0016 §12.4 #6.
- **마커 과밀**: `_build_interactive_comparison_html` 이 3개 전략 거래를 합산
  (069500 기준 ~698 마커) 하여 full-period 뷰에서 차트를 거의 덮는다. 인터랙티브
  zoom 이 부분 완화하나 (확대 시 마커 분산) full 뷰 가독성은 낮음. 개선 = 별도
  follow-up (ADR 0016 §12.4 #7).
- **Rollback flag 임시 존재**: `--static-charts` / `_STATIC_CHARTS=1` 는 검증 윈도우
  한정 feature. interactive path 안정 확인 후 제거 필요 (ADR 0016 follow-up).
- **Static 박제 path sunset 기준 미충족**: Phase 0.11.c~0.11.i retrospective figure 가
  아직 모두 interactive screenshot 으로 대체되지 않음 → matplotlib path 계속 유지.
  sunset trigger = D9 조건 충족 시 별도 ADR.

### 6.2 후속 권고

- **헤드리스 렌더 스모크 도입 검토**: 구조 테스트만으로 JS 렌더 산출물 검증 불가
  (§5.7). Playwright (본 phase post-delivery 정정에 사용, 검증용으로 venv 유지) 기반
  page-error-0 + 캔버스 픽셀 non-empty 스모크 체크를 검증 파이프라인에 편입할지 결정.
- **마커 과밀 개선**: 전략별 마커 토글 / 마커 thinning / per-strategy pane 분리 등
  (ADR 0016 §12.4 #7).
- **Rollback flag 제거**: interactive path 안정 확인 후 `--static-charts` 제거.
- **lightweight-charts 버전 업그레이드**: v5.x pin → 미래 deliberate sub-step.
- **B&H / 7split renderer interactive 화**: DGT-only 인 본 phase 의 scope 에서 제외.
  별도 future phase.

---

## 7. 다음 trajectory

- **즉시 다음**: Phase 1 진입 결정 (ADR 0012) — Phase 0.11.a~0.11.i research overlay
  정리 완료. KIS API 어댑터 + 실거래 환경 구성 진입 가능.
- **DGT research**: interactive chart 를 활용한 DGT 전략 시각적 검증 phase (별도 ADR).
- **Phase 1 ADR 0012 D16 (ii)**: Phase 0.11.i = visualization tooling 완료 (permanent).
  Phase 1 진입 게이트에 반영.

---

## 8. References

### Phase 0.11.i 산출

- `docs/decisions/0016-phase-0.11.i-interactive-charts.md` §1+§3 (ADR 정본)
- `docs/retrospectives/phase-0.11.i.md` (본 회고)
- `docs/retrospectives/figures/phase-0.11.i/` (2 figure evidence)

### 신규 / 수정 코드 (5th ring)

- `src/research/dgt/assets/lightweight-charts.standalone.production.js` (vendored)
- `src/research/dgt/assets/PROVENANCE.txt` (provenance)
- `src/research/dgt/_interactive_chart.py` (신규)
- `src/research/dgt/kakao_dgt_backtest.py` (수정: interactive + rollback flag)
- `src/research/visualization/_visualization_renderer.py` (수정: `fmt` kwarg)
- `src/research/visualization/_dgt_renderer.py` (수정: `fmt` dispatch)

### 신규 tests

- `tests/research/dgt/test_interactive_chart.py` (신규)
- `tests/research/dgt/test_kakao_interactive_report.py` (신규, 14 tests)
- `tests/research/visualization/test_dgt_renderer.py` (확장)

### 선행 phase 정본

- ADR 0015 (Phase 0.11.h) — static candlestick+volume (직전 phase)
- ADR 0009 (Phase 0.11.c) — visualization renderers + D4(b) + §1.10 시나리오 C
- ADR 0006 (Phase 0.10) — §14.4 Option C rejection + `:807`/`:1286` deferred lists

---

**본 회고 박제 완료 (Phase 0.11.i 종료, 2026-05-17). 게이트 4/4 PRIMARY PASS —
단 G1 은 post-delivery 렌더 결함 2건 발견·수정 후 재검증 (§3.6 / §5.7).
infrastructure phase 본질 정합 (Phase 0.11.c/h 선례). 산출: vendored JS (~50 KB) +
`_interactive_chart.py` (HTML builder) + `kakao_dgt_backtest.py` / `_dgt_renderer.py`
수정 + 75 new tests (1575→1650). ADR 0006 §14.4 + ADR 0009 D4(b) 역전 박제.
Lifecycle = permanent (interactive) + archival-with-sunset (static). 다음: Phase 1 진입
결정 (ADR 0012).**
