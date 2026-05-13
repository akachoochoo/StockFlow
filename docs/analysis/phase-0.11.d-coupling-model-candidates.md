# Phase 0.11.d.3 — 자산-전략 결합 모델 후보 박제 (D3 + D4 + D7)

> **Phase**: 0.11.d sub-step .3 (ADR 0010 §1.8 정합)
> **본질**: 자산-전략 결합 모델 4 후보 (D3) + sell strategy 차별화 3 후보 (D4) + Backtest 호환성 16-cell 매트릭스 (D7) — *trade-off 정량 박제 only*.
> **Lifecycle**: deferred reference (ADR 0010 §1.7 — 후속 결정 라운드의 정본 입력).
> **Scope invariant** (ADR 0010 §1.6 #2): **본 보고서는 후보 박제 only — 채택 zero / 결정 zero / 코드 변경 zero**. 후속 결정 라운드 (가칭 Phase 0.11.f / Phase 1 ADR 0012) 가 본 보고서 + ADR 0008 D11 결과 + ADR 0009 산출 + 사용자 confirmation 을 입력으로 채택 결정.
> **선행**: `docs/analysis/phase-0.11.d-current-structure-diagnosis.md` (sub-step .2, commit `cdb6e4d`) — 5 layer 진단 surface + 8 증거.
> **박제 commit hash**: `cdb6e4d` (Phase 0.11.d.2). 후속 phase 진입 시 §10 staleness tripwire 의무.

---

## 1. Executive Summary

| 후보 식별 | 단순 라벨 | 본질 | 코드 변경량 | 채택 여부 |
|----------|---------|------|------------|----------|
| **D3 (i)** | Mapping | `Mapping[AssetId, StrategyConfig]` — `per_asset_strategy_overrides` 일반화 | **최소** | 후보 (채택 X) |
| **D3 (ii)** | AssetContext | `composition.py` 단일 strategy 공유 제약 해제 + AssetContext 활용 | **중간** | 후보 (채택 X) |
| **D3 (iii)** | Registry | Strategy Registry + asset-keyed lookup (신규 dispatch) | **큼** | 후보 (채택 X) |
| **D3 (iv)** | Portfolio | Portfolio-level strategy composition (BacktestRunner.from_run 재설계) | **최대** | 후보 (채택 X) |
| **D4 (a)** | buy-only | Buy 만 차별화, sell 공유 — `ProfitTargetSell` 단일 유지 | 변경 zero | 후보 (채택 X) |
| **D4 (b)** | buy+sell | Buy + sell 자산별 차별화 — `OrderRequest`/`OrderResult` 시그니처 변경 | MEDIUM | 후보 (채택 X) |
| **D4 (c)** | sell stack | Sell strategy stack (ProfitTarget + StopLoss + TrailingStop) | HIGH | 후보 (채택 X, §13.3 경계) |

**거리 정보 압축** (Architect 권고 패턴):
- *기존 구현 활용* 경로: D3 (i) Mapping + D3 (ii) AssetContext — `per_asset_strategy_overrides` (`backtest_runner.py:187`) + `AssetContext` (`asset_context.py:37-57`) 기존재 활용.
- *신규 인프라 도입* 경로: D3 (iii) Registry + D3 (iv) Portfolio — Phase 0.10 의 StrategyRenderer Registry 와 본질 다름 (stateless read-only vs stateful position 변경).

**D7 16-cell 매트릭스 압축** (영향 분포):
- zero impact: 16 cells 중 **11 cells**.
- minor impact: **3 cells** (Registry × TradeView + AssetContext × StrategyRenderer + Portfolio × risk_metrics).
- major impact: **5 cells** (Registry × StrategyRenderer + Portfolio × {TradeView, DrawdownEpisode, StrategyRenderer}).

---

## 2. D3 — 자산-전략 결합 모델 4 후보

### 2.1 후보 (i) — `Mapping[AssetId, StrategyConfig]`

**본질**: `BacktestRunner.per_asset_strategy_overrides` (`backtest_runner.py:187`) 기존 인자 일반화. 자산별 `SplitStrategyConfig` 차별화만 지원 — 전략 type 자체는 단일 `buy_strategy_name`.

**변경 surface** (sub-step .2 진단 §4 정합):
- `BacktestRunner.__init__` 시그니처 — `per_asset_strategy_overrides` 인자 활용 (기존재, 변경 zero).
- `src/cli/composition.py:230-243` — 자산별 config dict 주입 (단일 strategy_config 1 지점 변경).
- `src/infrastructure/yaml_strategy_config_loader.py:157-201` — `_check_policy_uniformity` 의 `buy_parameters` 필드 완화 (정책 동일성 6 필드 중 1 필드 제외).

**5-dimension trade-off**:
- **단순성**: ✅ 최단 — 기존 데이터 구조 활용.
- **현 가정 정합**: ✅ `per_asset_strategy_overrides` 도입 ADR 0003 §16.13.9 정합.
- **Cascading risk**: 낮음 — config 차원만 변경, 도메인 strategy class 불변.
- **OCP**: 부분 — strategy type 변경 시 새 후보 필요.
- **현 코드 변경량**: 최소.

**한계**:
- 자산별 *전략 type* (PriceDrop vs SupportLevel) 차별화 불가 — `buy_strategy_name` 단일 가정 유지.
- 본 후보는 사용자 spec ("자산별로 전략과 파라미터") 의 *파라미터 차원만* 해결.

### 2.2 후보 (ii) — `AssetContext` 기반 strategy 주입

**본질**: 기존 `AssetContext` (`asset_context.py:37-57`) 의 `strategy: PriceDropStrategy | SupportLevelStrategy` union type 활용. `composition.py` 단일 instance 공유 제약 해제 — 자산별 다른 strategy instance/type 주입.

**변경 surface**:
- `src/cli/composition.py:230-243` — `buy_strategy` 단일 인스턴스 → 자산별 dict 변환 + `AssetContext` 구축 시 자산별 strategy 주입.
- `src/infrastructure/yaml_strategy_config_loader.py:157-201` — `_check_policy_uniformity` 의 `buy_strategy` + `buy_parameters` 필드 완화.
- `src/use_cases/asset_context.py` — 변경 zero (이미 구조적 수용).
- `src/application/backtest_runner.py` — 변경 minor (현 단일 `buy_strategy_name` 가정 해제, AssetContext 활용 경로 추가).

**5-dimension trade-off**:
- **단순성**: 중 — 기존 데이터 구조 + 주입 패턴 변경.
- **현 가정 정합**: ✅ AssetContext 기존재 (Architect critical finding, sub-step .2 §3 증거 7).
- **Cascading risk**: 중 — composition.py 변경 + yaml 로더 완화 + CLAUDE.md §16.1 항목 #2 정정 필요.
- **OCP**: ✅ — 새 strategy type 추가 시 AssetContext.strategy union 확장만 필요.
- **현 코드 변경량**: 중간.

**한계 / 정정 트리거**:
- CLAUDE.md §16.1 항목 #2 "AssetContext 의식 (코드 추가 금지)" 정정 필요 — sub-step .2 §3 증거 7 정합.
- ADR 0009 `_align_results_for_overlay` (`_align.py`) 의 strategy_id 분기 처리 가능 여부 검증 필요 (D7 (ii) 영향 § 4.1).

### 2.3 후보 (iii) — Strategy Registry + asset-keyed lookup

**본질**: Phase 0.10 의 `StrategyRendererRegistry` (`renderer_registry.py`) 패턴 차용 — strategy_id → Strategy instance mapping + asset.fqn → strategy_id mapping. 신규 dispatch layer 도입.

**변경 surface**:
- 신규 파일: `src/application/strategy_registry.py` (또는 `src/adapters/`) — `StrategyRegistry` class + asset-keyed lookup.
- `src/cli/composition.py:230-243` — Registry 초기화 + AssetContext 생성 시 Registry lookup.
- `src/infrastructure/yaml_strategy_config_loader.py:157-201` — `_check_policy_uniformity` 의 `buy_strategy` + `buy_parameters` 필드 완화.
- yaml 스키마 갱신 — asset-keyed strategy_id field.

**5-dimension trade-off**:
- **단순성**: 중 — 신규 abstraction layer.
- **현 가정 정합**: ❌ `StrategyRendererRegistry` 와 본질 다름 (renderer = stateless read-only marker dispatch / strategy = stateful position 변경). Phase 0.10 패턴 차용 가능하나 *의미* 충돌 risk.
- **Cascading risk**: 중 — Registry 도입 + `StrategyRenderer` Protocol 영향 (D7 major).
- **OCP**: ✅ — 새 strategy type 추가 = Registry 등록만 필요.
- **현 코드 변경량**: 큼.

**한계**:
- ADR 0006 §4 `StrategyRenderer` Protocol 시그니처 변경 필요 (D7 §4.1 major) — 본 phase의 §13.3 "친절한 추가 금지" 정신과 양립 여부 후속 라운드 결정.

### 2.4 후보 (iv) — Portfolio-level strategy composition

**본질**: Portfolio = 자산-전략 쌍 list + 자본 배분 정책 + cash management — `BacktestRunner` 의 단일 strategy 가정을 본질부터 재설계. Phase 0.7.2 의 `AllocationPolicy` (ADR 0003 §16) 와 결합.

**변경 surface**:
- `src/application/backtest_runner.py:67-97` — `BacktestResult` 시그니처 변경 (portfolio-level vs asset-level metric 분리).
- `src/application/backtest_runner.py:172-231` — `BacktestRunner.__init__` 재설계 (strategy_config 단일 → portfolio-level composition).
- `src/use_cases/asset_context.py` — AssetContext + Portfolio aggregate 신규.
- 신규 portfolio composition abstraction — Strategy Pattern + Composite Pattern.
- ADR 0003 §17 capital allocation 정책 결합.

**5-dimension trade-off**:
- **단순성**: 낮음 — Portfolio + Strategy 추상화 동시 재설계.
- **현 가정 정합**: ❌ — `BacktestRunner.from_run` 재설계 cascading (Phase 0.10 reporting layer 전체 영향).
- **Cascading risk**: 높음 — `BacktestRunner` → reporting (TradeView / DrawdownEpisode / risk_metrics) → `StrategyRenderer` Protocol 전체 영향 (D7 major × 3).
- **OCP**: ✅ — Portfolio composition 추가만으로 확장.
- **현 코드 변경량**: 최대.

**한계**:
- 사용자 spec ("자산별로 전략과 파라미터 다양하게") 의 *최소 충분 조건 초과* — Portfolio composition 은 Phase 1+ scope (ADR 0012 §1.10 시나리오 평가 필요).
- Phase 0.7.3 baseline 회귀 측정 비용 매우 높음 (BacktestResult 시그니처 변경 시).

### 2.5 5-dimension trade-off 압축 표 (D3 ADR §1.3 원본 정합)

| 후보 | 단순성 | 현 가정 정합 | Cascading risk | OCP | 현 코드 변경량 | 채택? |
| --- | --- | --- | --- | --- | --- | --- |
| (i) Mapping | ✅ 최단 | ✅ `per_asset_strategy_overrides` 일반화 | 낮음 (config 차원만) | 부분 | **최소** | 후보 (채택 X) |
| (ii) AssetContext | 중 | ✅ AssetContext 기존재 | 중 (composition.py 변경) | ✅ | **중간** | 후보 (채택 X) |
| (iii) Registry | 중 | ❌ renderer dispatch 와 본질 다름 | 중 (registry 도입) | ✅ | **큼** | 후보 (채택 X) |
| (iv) Portfolio composition | 낮음 | ❌ capital allocation 결합 cascading | 높음 (BacktestRunner.from_run 까지 영향) | ✅ | **최대** | 후보 (채택 X) |

### 2.6 거리 정보 박제 (Architect 권고)

**기존 구현 활용 경로** ((i) + (ii)):
- D3 (i) Mapping = `per_asset_strategy_overrides` (`backtest_runner.py:187`) 일반화 — *최소 거리*.
- D3 (ii) AssetContext = `AssetContext` (`asset_context.py:37-57`) composition 제약 해제 — *기존 구조 정합*.
- 두 경로 모두 *Architect 권고 패턴* — Phase 0.11.d 진단 산출 핵심.

**신규 인프라 도입 경로** ((iii) + (iv)):
- D3 (iii) Registry = 신규 dispatch layer + asset-keyed lookup.
- D3 (iv) Portfolio = Portfolio + Strategy 추상화 재설계.
- 두 경로 모두 *cascading risk 높음* — 후속 라운드 정량 평가 (특히 ADR 0009 visualization 영향, D7 매트릭스 참조).

---

## 3. D4 — Sell Strategy 차별화 3 후보

### 3.1 후보 (a) — Buy 만 차별화, sell 공유

**본질**: 자산별 buy strategy 만 차별화 + sell strategy 는 `ProfitTargetSell` 단일 공유. CLAUDE.md §16.1 항목 #4 invariant 보존.

**5-dimension cascading**:
| 차원 | 영향 |
|------|------|
| `OrderRequest` | 변경 zero |
| `OrderResult` | 변경 zero |
| partial fill | 변경 zero |
| reconciliation | 변경 zero |
| invariant 해제 비용 | **LOW** (CLAUDE.md §16.1 항목 #4 보존) |

**한계**:
- 손절 (StopLoss) 도입 불가 — Phase 1 ADR 0012 §2 손절 정책과 양립 여부 후속 라운드 결정.

### 3.2 후보 (b) — Buy + sell 자산별 차별화

**본질**: 자산별 buy + sell strategy 모두 차별화. `AssetContext.sell_strategy: SellStrategyPort` (`asset_context.py:55`) 기존 union type 활용.

**5-dimension cascading**:
| 차원 | 영향 |
|------|------|
| `OrderRequest` | 시그니처 변경 — asset-specific sell strategy 식별 필드 추가 |
| `OrderResult` | 시그니그 변경 — sell strategy id 박제 (어느 strategy 가 매도 trigger 했는지 기록) |
| partial fill | partial fill 처리 시 asset 별 sell strategy lookup 필요 |
| reconciliation | reconciliation 시 sell strategy id 비교 필요 |
| invariant 해제 비용 | **MEDIUM** — CLAUDE.md §16.1 항목 #4 해제 + Phase 1 ADR 0012 §2 손절 정책과 동시 결정 필요 |

**구조적 가능성**: `AssetContext.sell_strategy: SellStrategyPort` 이미 union type 수용 — *구조적 비용 낮음*. 차단 지점 = `composition.py:239` `ProfitTargetSell()` 하드코딩 + `_check_policy_uniformity` 의 `sell_strategy`/`sell_parameters` 필드 비교.

**한계**:
- CLAUDE.md §16.1 항목 #4 invariant 해제 = *정책적 비용 높음* (구조와 무관). 사용자 명시 confirmation 필요.

### 3.3 후보 (c) — Sell strategy stack (ProfitTarget + StopLoss + TrailingStop)

**본질**: 자산별 sell strategy 가 단일 instance 가 아닌 *stack* (조합) — 동시에 여러 sell rule 평가 + 우선순위 dispatch.

**5-dimension cascading**:
| 차원 | 영향 |
|------|------|
| `OrderRequest` | 시그니처 변경 — sell stack 식별 |
| `OrderResult` | 시그니처 변경 — 어느 stack rule 발화 박제 |
| partial fill | partial fill 시 stack 순서 보존 |
| reconciliation | reconciliation 시 stack state 비교 (rule 발화 순서 일치) |
| invariant 해제 비용 | **HIGH** — CLAUDE.md §16.1 항목 #4 해제 + §13.3 "친절한 추가 금지" 경계, 사용자 spec 외 |

**경계 (§13.3)**:
- 사용자 spec verbatim ("자산별로 전략과 파라미터 다양하게") 에 *stack* 명시 없음.
- *후보 박제 자체* 가 §13.3 경계 — ADR 0010 §1.3 D4 (c) 박제 시 "후보 박제 only" invariant 강조 정합.

**보존**:
- 후속 라운드 (Phase 1 ADR 0012 §2 or 별도 ADR) 가 사용자 명시 spec 추가 시 본 후보 정량 평가 가능. 본 phase 는 trade-off 박제만.

### 3.4 구조적 비용 vs 정책적 비용 괴리 (Architect tension 1)

ADR 0010 §1.3 D4 본문 박제 정합:

- **구조적 비용**: `AssetContext.sell_strategy` 가 이미 `SellStrategyPort` type → (b) 의 구조적 비용은 낮음. 차단 지점 2 곳 (`composition.py:239` 하드코딩 + `_check_policy_uniformity` 필드 비교) 만 완화하면 구조 활용 가능.
- **정책적 비용**: CLAUDE.md §16.1 항목 #4 invariant 해제 = *구조와 무관하게 높음*. 사용자 spec confirmation + Phase 1 ADR 0012 §2 손절 정책과 동시 결정 필요.

→ 구조 가능성 (낮음) ≠ 정책 가능성 (높음) — 후속 라운드 결정 시 양차원 분리 평가 의무.

---

## 4. D7 — Backtest 호환성 16-cell 매트릭스

### 4.1 4 후보 (D3) × 4 reporting 객체 매트릭스

Phase 0.10.bb 박제 reporting layer 4 객체 (TradeView / DrawdownEpisode / StrategyRenderer Protocol / risk_metrics) × D3 4 후보 = 16 cells. 영향 등급: zero / minor / major / blocker.

| 후보 \ 객체 | `TradeView` | `DrawdownEpisode` | `StrategyRenderer` Protocol | `risk_metrics` |
| --- | --- | --- | --- | --- |
| (i) Mapping | zero | zero | zero | zero |
| (ii) AssetContext | zero | zero | minor (annotation enrichment 패턴 확장 가능) | zero |
| (iii) Registry | minor (strategy_id 표시 변경) | zero | **major** (Protocol 시그니처 변경 — strategy_id 추가) | zero |
| (iv) Portfolio composition | **major** (TradeView 의 portfolio-level metric 재정의) | **major** (drawdown 의 portfolio-level vs asset-level 구분) | major | minor |

### 4.2 영향 등급 분포

- **zero impact (11 cells)**: (i) 전 columns + (ii) 의 3 cells + (iii) DrawdownEpisode + risk_metrics + (iv) 의 zero columns 없음.
- **minor impact (3 cells)**:
  - (ii) × StrategyRenderer — `TradeView.annotations` enrichment 패턴 (ADR 0006 §16.3 `_enrich_with_slot_number`) 확장 — 자산별 strategy_id annotation inject 가능.
  - (iii) × TradeView — strategy_id 표시 변경 (현 단일 `TradeView.strategy_id` 가 자산별 다양화).
  - (iv) × risk_metrics — Phase 0.10.bb `risk_metrics` (Sharpe / Calmar) 의 portfolio-level vs asset-level 구분.
- **major impact (5 cells)**:
  - (iii) × StrategyRenderer — Protocol 시그니처 변경 (strategy_id 추가) — ADR 0006 §4.2 frozen invariant 위반 risk.
  - (iv) × TradeView — portfolio-level metric 재정의.
  - (iv) × DrawdownEpisode — drawdown 의 portfolio-level vs asset-level 구분.
  - (iv) × StrategyRenderer — Protocol 시그니처 + 산출 시점 변경.
- **blocker (0 cells)**: 모든 후보가 *기술적으로 가능* — blocker level cascading 없음.

### 4.3 ADR 0009 comparison mode 와의 연결성

ADR 0009 §1.3 D6 `_align_results_for_overlay` (`_align.py`, sub-step 0.11.c.4 산출 commit `3af0415`) 의 strategy_id 분기:

- **(ii) AssetContext 채택 시**: `_align_results_for_overlay` 가 자산별 strategy_id 수집 후 overlay 시 strategy_id 분기 처리 필요. 변경량 minor — `_align_*_for_overlay` 함수의 strategy_id 인자가 단일 → 자산별 dict 변환.
- **(iii) Registry 채택 시**: `_align_results_for_overlay` 가 Registry lookup 호출 + strategy_id 일관성 검증 필요. 변경량 minor — Registry 통합 dependency injection.
- **(iv) Portfolio composition 채택 시**: `_align_results_for_overlay` 의 D6 공통 축 (time + pnl_cumulative + drawdown) 정의 자체 재고 — portfolio-level pnl vs asset-level pnl 구분. 변경량 major — `_OverlayPayload` 시그니처 변경 가능.

→ 본 phase 의 D3 후보 채택 (후속 라운드 영역) 시 ADR 0009 산출 갱신 의무 — sub-step 0.11.c.4 산출 (`_align.py`, `_comparison.py`, `cli.py`) 영향 분석 필수.

### 4.4 ADR 0006 reporting layer 영향 압축

(iv) Portfolio composition 외 모든 후보 = ADR 0006 reporting layer 변경 minor 이하. **(iii) Registry 만 `StrategyRenderer` Protocol 시그니처 변경 major** — ADR 0006 §4.2 frozen invariant 위반 risk → 후속 라운드 채택 시 ADR 0006 보존 path (Protocol 신규 추가 + 기존 Protocol frozen 유지) 의무.

---

## 5. D6 — Portfolio-level Cash Management 영향 (Trade-off Only)

ADR 0010 §1.3 D6 본문 박제 정합 (결정 없음, trade-off only):

**자산별 전략 차별화 시 cash flow 비대칭**:
- DGT (빈번 매매) vs B&H (1회 매수 + 보유) — 자산별 cash withdrawal/deposit 패턴 비대칭.
- Portfolio-level cash pool 공유 시: 한 자산의 매수 자금 부족 → 다른 자산 cash 차입.
- 자산별 격리 시: 각 자산에 독립 cash budget — Phase 0.7.2 `AllocationPolicy` (EQUAL / VOL / INV_VOL) 정책 적용 가능.

**두 path trade-off**:
| 차원 | Portfolio cash pool 공유 | 자산별 cash 격리 |
|------|--------------------------|------------------|
| Cash efficiency | 높음 | 중 |
| Asset isolation | 낮음 | 높음 (Phase 1 ADR 0012 §1.6 Operating Contract 정합) |
| ADR 0003 §16 정합 | ❌ | ✅ |
| Reconciliation 복잡도 | 높음 (자산 간 cross-transfer 추적) | 낮음 |

**본 phase 결정 없음** — 후속 라운드 영역. 추정 결정 라운드:
- D3 (i) Mapping 채택 시 → 자산별 cash 격리 default (config 차원만 차별화).
- D3 (ii) AssetContext 채택 시 → 양 path 모두 가능 (composition.py 정책 결정 필요).
- D3 (iv) Portfolio composition 채택 시 → Portfolio-level cash pool 공유 default + 자산별 cash 격리는 명시 옵션.

---

## 6. ADR 0008 D11 Trigger 결과별 D3 후보 식별 영향

ADR 0010 §1.3 D11 (iii) 정본 인용 — Phase 0.11.b DGT 분봉 검토 결과가 본 phase 의 D3 후보 식별에 미치는 영향:

### 6.1 ADR 0008 D11 trigger = positive (DGT promote)

**시나리오**: Phase 1 ADR 0012 D11 분봉 DGT 검토 결과 promote 권고 → DGT 가 특정 자산에 합류.

**D3 후보 식별 영향**:
- **D3 (ii) AssetContext positive 영향**: `AssetContext.strategy: PriceDropStrategy | SupportLevelStrategy | _DGTStrategy` union 확장 — 자산별 전략 차별화 *실제 trigger* 강화.
- **D3 (i) Mapping 부분 positive**: DGT 가 `SplitStrategyConfig` 와 다른 config schema → Mapping 후보의 *config type 통일 가정* 깨짐 (cascading risk 증가).
- **D3 (iii) Registry positive**: 새 strategy type 추가 = Registry 등록만 필요 — OCP 정합.
- **D3 (iv) Portfolio positive**: DGT (grid 기반 stateful) + PriceDrop (split 기반 stateful) 조합 = Portfolio composition 의 필요성 증가.

### 6.2 ADR 0008 D11 trigger = neutral (DGT informational only — 현 상태 2026-05-13)

**시나리오**: Phase 0.11.b 결과 = D10 archive 확정, DGT registry 미합류 (정본 ADR 0008 §3 박제).

**D3 후보 식별 영향**:
- **모든 후보에 영향 zero** — D3 후보 식별은 PriceDropStrategy + SupportLevelStrategy 2 strategy 가정 하에 진행.
- *현 상태* (2026-05-13): 본 phase 진단은 neutral path 기반. 후속 라운드 (Phase 0.11.f / Phase 1) 진입 시 D11 결과 재확인 의무.

### 6.3 ADR 0008 D11 trigger = negative (DGT archive 확정 — 강한 negative)

**시나리오**: DGT 정량 근거 분봉 환경에서도 부정적 → 완전 archive.

**D3 후보 식별 영향**:
- **D3 후보 식별 단순화**: 단일 PriceDropStrategy/SupportLevel 가정 유지 — D3 (i) Mapping 후보의 정당성 강화.
- **D3 (ii) AssetContext 정당성 약화**: 전략 type 차별화 trigger 부재 — config 차별화만으로 충분.

---

## 7. 후보 채택 안 함 Invariant (§1.6 #2 재강조)

본 보고서 = **trade-off 박제 only**. 채택 결정은 본 phase 가 아닌 후속 결정 라운드 영역.

**측정 가능 형태**:
- 본 보고서에 *default* 라벨 부재 (모든 후보 = "후보" 라벨만).
- §2.5 trade-off 표 + §3 sell strategy 표 + §4 16-cell 매트릭스 = trade-off 분석만, 채택 권고 없음.
- 후속 라운드 trigger = ADR 0010 §1.3 D11 4 조건 모두 충족 시.

**후속 라운드 입력 (정본)**:
1. 본 보고서 (sub-step 0.11.d.3 commit hash — ADR 0010 §3 회고에 박제 예정).
2. sub-step 0.11.d.2 진단 보고서 (`current-structure-diagnosis.md`, commit `cdb6e4d`).
3. ADR 0008 D11 trigger 결과 (현 = neutral, 2026-05-13).
4. ADR 0009 visualization comparison mode 산출 (commit `3af0415`).
5. 사용자 명시 confirmation (ADR 0010 §3 회고 영역).

---

## 8. ADR 0010 D 결정 cross-reference

| D 식별 | 본 보고서 절 | 본질 |
|--------|------------|------|
| D3 | §2 | 자산-전략 결합 모델 4 후보 |
| D4 | §3 | Sell strategy 차별화 3 후보 |
| D6 | §5 | Portfolio cash management trade-off |
| D7 | §4 | 16-cell 매트릭스 |
| D8 | §7 + sub-step .4 영역 | 회귀 invariant (후속 phase 박제 대상) |
| D11 | §6 | 후속 phase trigger 조건 — DGT 결과별 영향 |

---

## 9. Staleness Tripwire

본 보고서는 deferred reference — 후속 phase 진입 시 stale 검증 의무.

**검증 명령** (후속 phase ralplan 시 실행):
```bash
# 본 boundary commit 이후 5 surface 파일 변경 zero 확인
git diff cdb6e4d..HEAD -- \
    src/application/backtest_runner.py \
    src/use_cases/asset_context.py \
    src/cli/composition.py \
    src/infrastructure/yaml_strategy_config_loader.py
# empty 이면 본 보고서 §2 / §3 정합 유지. non-empty 이면 후보별 변경 surface 재검증 의무.

# ADR 0006 StrategyRenderer Protocol 변경 zero 확인 (D7 매트릭스 영향)
git diff cdb6e4d..HEAD -- src/ports/strategy_renderer.py
# empty 이면 D7 (iii) major impact 정합 유지.

# ADR 0009 _align_results_for_overlay 변경 zero 확인 (§4.3 영향)
git diff cdb6e4d..HEAD -- src/research/visualization/_align.py
# empty 이면 §4.3 ADR 0009 연결성 정합 유지.
```

---

## 10. References

### ADR 정본 인용
- ADR 0010 §1.3 D3 — 자산-전략 결합 모델 4 후보 정본.
- ADR 0010 §1.3 D4 — Sell strategy 차별화 3 후보 + cascading 정본.
- ADR 0010 §1.3 D6 — Portfolio cash management 정본 (결정 없음).
- ADR 0010 §1.3 D7 — 16-cell 매트릭스 정본.
- ADR 0010 §1.3 D11 — 후속 phase trigger 조건 정본.
- ADR 0010 §1.6 #2 — "후보 박제 only" invariant 정본.
- ADR 0003 §16 — AllocationPolicy (cash management trade-off 영향).
- ADR 0003 §16.13.9 — `per_asset_strategy_overrides` 도입.
- ADR 0003 §7.3 — 정책 동일성 강제 원본.
- ADR 0004 §5.4 — `AssetContext.strategy` union type.
- ADR 0006 §4.2 — `StrategyRenderer` Protocol frozen invariant.
- ADR 0006 §16.3 — `_enrich_with_slot_number` annotation enrichment 패턴.
- ADR 0008 §3 — DGT D11 trigger 결과 (현 = neutral, 2026-05-13).
- ADR 0009 §1.3 D6 — `_align_results_for_overlay` 공통 축 매핑.

### 선행 산출
- `docs/analysis/phase-0.11.d-current-structure-diagnosis.md` (sub-step 0.11.d.2, commit `cdb6e4d`) — 5 layer 진단 surface + 8 증거.

### 후속 sub-step
- **0.11.d.4**: ADR 0010 §2 — Supersede verbatim template (D5 — ADR 0003:2983-2993 + ADR 0004:1588-1601 인용) + 회귀 invariant 박제 (D8) + D11 트리거 정량화.
- **0.11.d.5**: 회고 + ADR §3 + CLAUDE.md §16.1 항목 #2 정정 권고 박제 (옵션 Z).

### CLAUDE.md 인용
- §13.3 — "친절한 추가 금지" (D4 (c) sell stack 경계).
- §14 — "Phase 1 진입 전 작성 금지 통합 목록" / "종목별 다른 정책".
- §16.1 항목 #2 — AssetContext (코드 현실 괴리, 옵션 Z 정정 권고 대상).
- §16.1 항목 #4 — sell strategy 단일 가정 (D4 invariant 해제 영향).

---

**본 후보 박제 보고서 박제 완료 (Phase 0.11.d sub-step 0.11.d.3, 2026-05-13). 코드 변경 zero — D3 4 후보 + D4 3 후보 + D7 16-cell 매트릭스 + D6 cash management trade-off + D11 trigger 결과별 D3 영향 정량 박제 only. 채택 결정 zero — §1.6 #2 invariant 보존. 후속 결정 라운드 입력 정본 5 점 (본 보고서 + sub-step .2 진단 + ADR 0008 D11 + ADR 0009 산출 + 사용자 confirmation).**
