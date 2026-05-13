# Phase 0.11.d.2 — 현재 구조 진단 보고서: 자산별 전략 차별화 capability

> **Phase**: 0.11.d sub-step .2 (ADR 0010 §1.8 정합)
> **본질**: 멀티 자산 운용 시 자산별로 전략/파라미터를 다양하게 가져갈 수 있는 구조 정밀 진단 — 5 layer 변경 surface + 8 증거 + 객체 시그니처 dump.
> **Lifecycle**: deferred reference (ADR 0010 §1.7 — archive/abandon/promote 아님, 후속 결정 라운드의 정본 입력).
> **Scope invariant** (ADR 0010 §1.6): **본 보고서는 진단 only — 코드 변경 zero / 후보 채택 zero / 결정 zero**. 후보 박제 + 결정은 sub-step .3 (`coupling-model-candidates.md`) + 후속 라운드 영역.
> **박제 commit hash**: `38da6bf` (Phase 0.11.c.5, 2026-05-13). 이후 commit 발생 시 §7 staleness tripwire 갱신 의무 (ADR 0010 §1.3 D10).

---

## 1. Executive Summary

| 질문 | 답 |
|------|----|
| 자산별 *파라미터* 차별화 가능? | **부분적으로 가능** — `BacktestRunner.per_asset_strategy_overrides` 기존재 (application layer). 단, yaml 로더는 정책 동일성 강제 (`_check_policy_uniformity`) — 즉 *실 사용 경로 (CLI + yaml)* 에서는 차단됨. |
| 자산별 *전략 type* (PriceDrop vs SupportLevel vs DGT 등) 차별화 가능? | **불가** — `composition.py:230-243` 가 모든 자산에 단일 strategy 인스턴스 공유 주입. `AssetContext.strategy` 필드는 자산별 다른 instance 를 받을 수 있는 구조이지만 *주입 지점* 이 단일 instance 를 broadcast. |
| 자산별 *sell strategy* 차별화 가능? | **불가** (구조적 + 정책적 양면) — `composition.py:239` 가 `ProfitTargetSell()` 하드코딩 + `yaml_strategy_config_loader.py:188-193` 가 `sell_strategy` / `sell_parameters` 필드 동일성 강제. **정책적**: CLAUDE.md §16.1 항목 #4 invariant. |
| 자산별 *전략 + 파라미터 + sell* 통합 차별화 가능? | **현 구조에서 불가** — 단, 변경 surface = 3 지점 (composition + yaml validator + `_check_policy_uniformity` 완화). |

**핵심 발견**: 자산별 차별화 capability 는 *application + use_cases layer 에 부분 구현* (Architect critical finding, ADR 0010 §1.2 증거 6+7) 되어 있으나 *cli + infrastructure layer 가 정책 동일성을 강제* 하여 활용 차단. 즉 "구조는 준비됨, 게이트가 닫힘".

---

## 2. 진단 Surface — 5 Layer (D2 정합)

ADR 0010 §1.3 D2 정합 — 4 layer (domain / use_cases / application / cli) + **infra layer** 추가 (Round 1 ITERATE Architect 권고, `yaml_strategy_config_loader.py` 정책 동일성 강제 지점 포함).

| Layer | 경로 | 자산별 차별화 관련 surface |
|-------|------|----------------------------|
| domain | `src/domain/` | strategies (PriceDrop / SupportLevel) — 자산 무관 stateless. 변경 surface = zero (본 진단 범위). |
| use_cases | `src/use_cases/asset_context.py` | `AssetContext` frozen dataclass — 이미 자산별 strategy + config + sell 번들링 (증거 7). |
| application | `src/application/backtest_runner.py` | `BacktestRunner.__init__` — `per_asset_strategy_overrides` 인자 기존재 (증거 6). |
| cli | `src/cli/composition.py` | `asset_contexts` 구축 — 모든 자산에 단일 strategy 인스턴스 공유 (증거 8a, 차단 지점 1). |
| infrastructure | `src/infrastructure/yaml_strategy_config_loader.py` | `_check_policy_uniformity` Pydantic validator — yaml load 시점 정책 동일성 강제 (증거 8b, 차단 지점 2). |

**5 layer 정합 — Phase 0.11.a §1.6 5-ring namespace 패턴과 별도** (5-ring은 production rings vs research overlay; 본 진단은 application/cli/infrastructure가 모두 production ring).

---

## 3. 8 증거 박제 (ADR 0010 §1.2 정본 인용)

### 증거 1 — CLAUDE.md §14 "작성 금지" 통합 목록

> "종목별 다른 정책 (자산별 다른 정책) — Phase 1+ (ADR 0003 §19.4 / ADR 0004 §7.4.2 보류)"

→ "보류" 의 의미: 구조 도입은 보류되었으나, *후보 식별 + 진단* 은 Phase 1+ 가 아니라 본 phase (0.11.d) 에서 가능 (Round 1 ITERATE Patch 1+11 정합).

### 증거 2 — CLAUDE.md §16.1 항목 #4 단일 sell strategy 가정 invariant

> "sell strategy 단일 가정 — `ProfitTargetSell` 단일 sell strategy 가정 유지. 손절 (StopLoss) 은 Phase 1 ADR 에서 sell strategy 추가 형태로 도입."

→ ADR 0010 §1.3 D4 의 (b) buy + sell 차별화 / (c) sell strategy stack 채택 시 본 invariant 해제 필요 (R3 cascading risk).

### 증거 3 — `docs/multi-asset-trading-system-design.md` §2.2 + §3.1

설계 의도: 자산별 파라미터 분리 (KR 7%/7분할, US 8-10%/5-7분할, BTC 15-20%/5분할) + "AI 차단기가 한 자산 진입을 정지해도 다른 자산은 독립 운영".

→ 설계 의도는 *파라미터 자산별 차별화* 인데, *전략 객체 자산별 차별화* 는 미명시. 현 코드는 파라미터 자체도 yaml 로더가 차단 (증거 8b).

### 증거 4 — Phase 0.7~0.9 회고 패턴

Phase 0.7.3 baseline (069500 + 132030 EQUAL): *동일 전략 (PriceDropStrategy) 을 두 자산에 적용 + weight (allocation) 만 다름*. ADR 0005 §9.6.2 "자산군 분산 = H3 충분 조건" 은 자산-weight 분산을 입증했을 뿐, 자산-전략 분산은 미검증.

→ Baseline 자체가 single-strategy 가정 하의 산출 (D8 R6 정합 — 회귀 invariant 의 자기참조).

### 증거 5 — Phase 0.11.a §8.1 한계

> "DGT 단독 069500 vs Phase 0.7.3 069500+132030 의 자산 1차원 차이 — 분산 효과의 분리 측정 불가."

→ 비교 단위가 *자산 = 전략* 짝짓기. 자산-전략 분산 측정의 구조적 단서 (Round 1 ITERATE Patch 3 정합).

### 증거 6 — `BacktestRunner.per_asset_strategy_overrides` 기존재 (Architect critical finding)

`src/application/backtest_runner.py:186` 에 `per_asset_strategy_overrides: dict[str, SplitStrategyConfig] | None = None` 인자 기존재. ADR 0003 §16.13.9 박제 — Phase 0.7.2 자산별 strategy override.

검증 명령:
```bash
grep -n "per_asset_strategy_overrides" src/application/backtest_runner.py
```

→ 파라미터 차별화 경로가 *application layer 에 기존 구현* — 즉 ADR 0010 §1.3 D3 후보 (i) Mapping[AssetId, StrategyConfig] 는 *기존 구현 일반화* 수준 (Architect 권고 "거리 정보" 정합).

### 증거 7 — `AssetContext` 기존 구현 (CLAUDE.md §16.1 항목 #2 괴리 핵심)

`src/use_cases/asset_context.py:37-57` 의 `AssetContext` frozen dataclass 가 이미 자산별 `strategy` + `config` + `sell_strategy` + `sell_config` 번들링.

```python
class AssetContext:
    asset: Asset
    strategy: PriceDropStrategy | SupportLevelStrategy
    config: SplitStrategyConfig
    sell_strategy: SellStrategyPort
    sell_config: SellStrategyConfig
```

CLAUDE.md §16.1 항목 #2 박제: "AssetContext 기반 데이터 흐름 (코드 추가 금지)" — 그러나 실제 코드에는 `AssetContext` dataclass + `DailyOrchestrator` / `composition.py` 사용처 *이미 구현*.

→ **CLAUDE.md §16.1 항목 #2 와 코드 현실 괴리 박제 의무** (옵션 Z = §3 회고에 정정 권고만, 정정 commit 안 함 — ADR 0010 §1.10 시나리오 C mitigation).

### 증거 8 — 정책 동일성 강제 지점 (자산-전략 type 차별화 차단)

**8a. `src/cli/composition.py:230-243` — 단일 strategy 인스턴스 공유 주입**:

```python
buy_strategy = create_buy_strategy(buy_strategy_name, reentry=reentry)
asset_contexts = [
    AssetContext(
        asset=asset,
        strategy=buy_strategy,          # 모든 asset 에 동일 인스턴스
        config=strategy_config,          # 단일 config
        sell_strategy=ProfitTargetSell(), # 하드코딩
        sell_config=effective_sell_config,
    )
    for asset in assets
]
```

→ 모든 자산에 단일 `buy_strategy` 인스턴스 + 단일 `strategy_config` + 하드코딩 `ProfitTargetSell()` 주입. AssetContext 의 자산별 차별화 capability *주입 시점 차단*.

**8b. `src/infrastructure/yaml_strategy_config_loader.py:157-201` — `_check_policy_uniformity` Pydantic validator**:

```python
@model_validator(mode="after")
def _check_policy_uniformity(self) -> _RootSchema:
    """ADR 0003 §7.3 — 정책 동일성 강제."""
    ...
    policy_fields = (
        "buy_strategy", "buy_parameters",
        "sell_strategy", "sell_parameters",
        "reentry_strategy", "reentry_parameters",
    )
    for code, entry in enabled_items[1:]:
        entry_dump = entry.model_dump()
        for field_name in policy_fields:
            if entry_dump[field_name] != ref_dump[field_name]:
                raise ValueError(...)
```

→ yaml load 시점에 자산별 `buy_strategy` / `buy_parameters` / `sell_strategy` / `sell_parameters` / `reentry_strategy` / `reentry_parameters` 동일성 강제. 6 필드 모두 일치해야 통과 — 즉 yaml entry-level 자산별 차별화 완전 차단.

→ 차단 지점 = 2 곳 (cli composition + infra yaml validator). 변경 시 cascading surface 정량 (sub-step .3 영역).

---

## 4. 변경 Surface 표 — 자산별 차별화 활성화 시 영향

본 표는 *현재 구조 진단* — 후보 채택 X (ADR 0010 §1.6 #2). 변경 영향 surface 정량만.

| 변경 surface | 위치 | 변경 내용 (가설) | Cascading 영향 |
|--------------|------|------------------|----------------|
| **차단 해제 1** | `src/cli/composition.py:230-243` | 단일 `buy_strategy` 인스턴스 → 자산별 dict 주입 | `AssetContext.strategy` 가 이미 union type 수용 → cascading 낮음 |
| **차단 해제 2** | `src/infrastructure/yaml_strategy_config_loader.py:157-201` | `_check_policy_uniformity` 완화 (policy_fields 축소 or skip) | yaml 스키마 정합성 — 자산별 다른 strategy_id 수용 가능한 형태로 schema 갱신 필요 |
| **차단 해제 3 (조건부)** | `src/cli/composition.py:239` | `ProfitTargetSell()` 하드코딩 해제 (sell_strategy 자산별 차별화 시) | CLAUDE.md §16.1 항목 #4 invariant 해제 — Phase 1 ADR 0012 §2 손절 정책과 동시 결정 필요 |
| **활용 surface 1** | `src/application/backtest_runner.py:186` | `per_asset_strategy_overrides` 기존재 — 일반화만 필요 | ADR 0003 §16.13.9 정합, 회귀 invariant 측정 가능 (`overrides=None` → baseline) |
| **활용 surface 2** | `src/use_cases/asset_context.py:37-57` | `AssetContext` 기존재 — 코드 변경 zero, 주입만 변경 | CLAUDE.md §16.1 항목 #2 정정 권고 (옵션 Z) |
| **보존 surface** | `src/domain/strategies/` | domain layer 전체 보존 | Stateless strategy invariant 정합 |
| **회귀 invariant 측정** | `BacktestRunner(per_asset_strategy_overrides=None)` | single-strategy 동작 baseline 보존 (D8) | Phase 0.7.3 baseline (069500+132030 EQUAL+PriceDropStrategy) 정확 재현 의무 |

**핵심**: 차단 해제 2 지점 + 활용 surface 2 지점 = **총 변경 surface 4개 + 보존 1개 + invariant 측정 1개**. 후보 채택 시 cascading 영향 분석은 sub-step .3 영역 (D3 4 후보 × D7 16-cell 매트릭스).

---

## 5. 객체 시그니처 Dump (D1 (c) 정합 — 5 파일 × 절대 line range × commit hash)

**박제 시점 commit hash**: `38da6bf` (Phase 0.11.c.5, 2026-05-13).

### 5.1 `src/application/backtest_runner.py:67-97` — `BacktestResult` frozen dataclass

```python
@dataclass(frozen=True)
class BacktestResult:
    """Aggregate result of one backtest run."""
    start_date: date
    end_date: date
    initial_capital: Money
    decisions: list[Decision] = field(default_factory=list)
    snapshots: list[PortfolioSnapshot] = field(default_factory=list)
    final_positions: list[Position] = field(default_factory=list)
    n_trading_days: int = 0
    cagr_pct: Decimal = Decimal(0)
    max_drawdown_pct: Decimal = Decimal(0)
    sharpe_ratio: Decimal = Decimal(0)
    calmar_ratio: Decimal = Decimal(0)
```

→ 자산별 metric 분리 *현 시그니처에 없음*. 자산별 차별화 채택 시 portfolio-level vs asset-level metric 구분 필요 (D7 16-cell (iv) Portfolio composition 후보 영향).

### 5.2 `src/application/backtest_runner.py:172-231` — `BacktestRunner.__init__` 시그니처

```python
def __init__(
    self,
    *,
    assets: list[Asset],
    strategy_config: SplitStrategyConfig,
    initial_capital: Money,
    ohlcv_by_asset: dict[Asset, list[OHLCV]],
    sell_strategy_config: SellStrategyConfig | None = None,
    reentry_strategy_name: str = "hybrid",
    reentry_parameters: dict[str, Any] | None = None,
    signal_factory: Callable[[], SignalPort] | None = None,
    decision_kst_time: time = time(9, 0),
    snapshot_kst_time: time = time(16, 0),
    trading_days_per_year: int = _DEFAULT_TRADING_DAYS_PER_YEAR,
    risk_free_rate: Decimal = _DEFAULT_RISK_FREE_RATE,
    per_asset_strategy_overrides: dict[str, SplitStrategyConfig] | None = None,
    buy_strategy_name: str = "price_drop",
) -> None:
    ...
    if per_asset_strategy_overrides is not None:
        expected_fqns = {a.fqn for a in self._assets}
        actual_fqns = set(per_asset_strategy_overrides.keys())
        if actual_fqns != expected_fqns:
            raise ValueError(...)
```

→ `per_asset_strategy_overrides` 인자 기존재 (line 186). 단, 타입이 `dict[str, SplitStrategyConfig]` — 즉 *config 차별화만 지원, strategy type 차별화는 미지원*. 또한 `buy_strategy_name: str` 가 단일 — 모든 자산에 같은 strategy type 가정.

### 5.3 `src/use_cases/asset_context.py:37-57` — `AssetContext` frozen dataclass

```python
class AssetContext:
    """Per-asset dependency bundle for DailyOrchestrator.

    Phase 0.8 (ADR 0004 §5.4): strategy is a union of
    PriceDropStrategy / SupportLevelStrategy. yaml policy uniformity
    (ADR 0003 §7.3) ensures all AssetContexts in a single run share the
    same strategy *type* (only the asset differs).
    """
    asset: Asset
    strategy: PriceDropStrategy | SupportLevelStrategy
    config: SplitStrategyConfig
    sell_strategy: SellStrategyPort
    sell_config: SellStrategyConfig
```

→ 자산별 strategy + config + sell_strategy + sell_config 번들. 구조적으로 자산별 차별화 가능 — 단, 주입 시점 (composition.py) 이 단일 인스턴스 broadcast. **CLAUDE.md §16.1 항목 #2 괴리 박제 (증거 7)** — 본 dataclass + DailyOrchestrator/composition.py 사용처는 *이미 구현* 인데 §16.1 항목 #2 는 "코드 추가 금지" 의식으로 박제 → 정정 권고 필요.

### 5.4 `src/cli/composition.py:230-243` — Strategy 인스턴스 공유 주입

```python
buy_strategy = create_buy_strategy(buy_strategy_name, reentry=reentry)

# Build one AssetContext per asset; all share the same strategy instance
# and configs (ADR 0003 §7.3 — policy uniformity checked by loader).
asset_contexts = [
    AssetContext(
        asset=asset,
        strategy=buy_strategy,          # ← 단일 인스턴스 broadcast
        config=strategy_config,          # ← 단일 config broadcast
        sell_strategy=ProfitTargetSell(),# ← 하드코딩
        sell_config=effective_sell_config,
    )
    for asset in assets
]
```

→ **차단 지점 1** (자산-전략 차별화). 주석 자체가 "all share the same strategy instance and configs" 명시 — ADR 0003 §7.3 정책 동일성 명시적 강제.

### 5.5 `src/infrastructure/yaml_strategy_config_loader.py:157-201` — `_check_policy_uniformity`

```python
@model_validator(mode="after")
def _check_policy_uniformity(self) -> _RootSchema:
    """Phase 0.7.1 strict: all enabled assets must share the same policy.
    ADR 0003 §7.3 — 정책 동일성 강제.
    """
    enabled_items = [(code, entry) for code, entry in self.assets.items() if entry.enabled]
    if len(enabled_items) <= 1:
        return self
    ref_code, ref_entry = enabled_items[0]
    ref_dump = ref_entry.model_dump()
    policy_fields = (
        "buy_strategy", "buy_parameters",
        "sell_strategy", "sell_parameters",
        "reentry_strategy", "reentry_parameters",
    )
    for code, entry in enabled_items[1:]:
        entry_dump = entry.model_dump()
        for field_name in policy_fields:
            if entry_dump[field_name] != ref_dump[field_name]:
                raise ValueError(...)
    return self
```

→ **차단 지점 2** (yaml load 시점 정책 동일성). 6 필드 (buy_strategy / buy_parameters / sell_strategy / sell_parameters / reentry_strategy / reentry_parameters) 동일성 강제. 자산별 차별화 시 본 validator 완화 (or 제거) 필요 — sub-step .3 영역 (D3 후보별 변경 surface).

---

## 6. 잠정 결론 — 현재 구조 capability

### 6.1 구조적 capability (이미 존재)

1. **`per_asset_strategy_overrides`** (`backtest_runner.py:187`) — application layer 에 자산별 `SplitStrategyConfig` 차별화 경로 기존재.
2. **`AssetContext`** (`asset_context.py:37-57`) — use_cases layer 에 자산별 strategy + config + sell 번들링 기존재.
3. **`DailyOrchestrator`** — `asset_contexts: list[AssetContext]` 순회 — 자산별 차별화 처리 가능 구조.

### 6.2 차단 지점 (활성화 필요)

1. **`composition.py:230-243`** — 단일 strategy 인스턴스 공유 주입 (모든 자산에 동일 instance broadcast).
2. **`yaml_strategy_config_loader.py:157-201`** — `_check_policy_uniformity` validator (6 policy field 동일성 강제).
3. **`ProfitTargetSell()` 하드코딩** (`composition.py:239`) — sell strategy 차별화 차단 (CLAUDE.md §16.1 항목 #4 invariant 동시 영향).

### 6.3 정책적 capability gap

1. **CLAUDE.md §14**: "종목별 다른 정책 — Phase 1+ 보류".
2. **CLAUDE.md §16.1 항목 #4**: 단일 sell strategy 가정.
3. **CLAUDE.md §16.1 항목 #2**: AssetContext "코드 추가 금지" — **코드 현실 괴리** (옵션 Z 정정 권고 대상).

### 6.4 결론 (사용자 질문에 대한 답)

> "현재 구조가 멀티 자산 운용시 자산별로 전략과 전략의 세부 파라미터를 다양하게 가져갈수 있는 구조야?"

**답**: *부분적으로 가능 — 구조는 준비되어 있으나 정책 게이트로 차단됨*.

- 자산별 *파라미터* (`SplitStrategyConfig`) 차별화 = `per_asset_strategy_overrides` 활용 가능 (단, yaml 로더 `_check_policy_uniformity` 완화 필요).
- 자산별 *전략 type* (PriceDrop vs SupportLevel) 차별화 = `AssetContext` 구조는 수용 가능하나 `composition.py` 단일 instance 주입 + yaml 로더 `buy_strategy` 동일성 강제로 *활용 차단*.
- 자산별 *sell strategy* 차별화 = `AssetContext.sell_strategy: SellStrategyPort` 구조는 수용 가능하나 `composition.py` 하드코딩 + CLAUDE.md §16.1 항목 #4 invariant 정책 차단.

**변경 surface**: 2 지점 차단 해제 + 1 지점 활용 (총 3) — sub-step .3 의 D3/D4/D7 매트릭스 입력.

---

## 7. Staleness Tripwire (ADR 0010 §1.3 D10)

본 보고서는 deferred reference — 후속 phase 진입 시 stale 검증 의무.

**검증 명령** (후속 phase ralplan 시 실행):
```bash
# 본 진단 commit ~ HEAD 사이 5 surface 파일 변경 zero 확인
git diff 38da6bf..HEAD -- \
    src/application/backtest_runner.py \
    src/use_cases/asset_context.py \
    src/cli/composition.py \
    src/infrastructure/yaml_strategy_config_loader.py
# empty 이면 본 보고서 정합 유지. non-empty 이면 §5 line range + §6 결론 재검증 의무.
```

**변경 surface 갱신 조건**:
- `BacktestRunner.__init__` 시그니처 변경 → §5.2 갱신.
- `AssetContext` 필드 추가/변경 → §5.3 + 증거 7 갱신.
- `composition.py` strategy 주입 변경 → §5.4 + 차단 지점 1 갱신.
- `_check_policy_uniformity` validator 완화/제거 → §5.5 + 차단 지점 2 갱신.

---

## 8. References

### ADR 정본 인용
- ADR 0010 §1.2 — 8 증거 박제 원본 (본 보고서 §3 정합).
- ADR 0010 §1.3 D1 — 시그니처 dump 형식 (commit hash + 절대 line range).
- ADR 0010 §1.3 D2 — 5 layer 진단 범위.
- ADR 0010 §1.3 D10 — staleness tripwire 정의.
- ADR 0010 §1.6 — Independence Declaration (본 phase 정체성 invariant).
- ADR 0003 §7.3 — 정책 동일성 강제 원본 (`composition.py:233` + `yaml_strategy_config_loader.py:157` 주석 인용).
- ADR 0003 §16.13.9 — `per_asset_strategy_overrides` 도입 박제.
- ADR 0004 §5.4 — `AssetContext.strategy` union type 박제.

### 소스 정본 인용 (commit `38da6bf`)
- `src/application/backtest_runner.py:67-97` — BacktestResult.
- `src/application/backtest_runner.py:172-231` — BacktestRunner.__init__.
- `src/use_cases/asset_context.py:37-57` — AssetContext.
- `src/cli/composition.py:230-243` — strategy 공유 주입.
- `src/infrastructure/yaml_strategy_config_loader.py:157-201` — _check_policy_uniformity.

### CLAUDE.md 인용
- §14 — "Phase 1 진입 전 작성 금지 통합 목록" / "종목별 다른 정책" 항목.
- §16.1 항목 #2 — "AssetContext 기반 데이터 흐름" (코드 현실 괴리 박제 대상).
- §16.1 항목 #4 — "sell strategy 단일 가정" invariant.

### 다음 sub-step
- **0.11.d.3**: `docs/analysis/phase-0.11.d-coupling-model-candidates.md` — D3 4 후보 trade-off 표 + D4 3 후보 cascading 영향 surface + D7 16-cell 매트릭스.
- **0.11.d.4**: ADR 0010 §2 — Supersede verbatim template (D5) + 회귀 invariant (D8) + D11 트리거 정량화.
- **0.11.d.5**: 회고 + ADR §3 + CLAUDE.md §16.1 항목 #2 정정 권고 박제 (옵션 Z).

---

**본 진단 보고서 박제 완료 (Phase 0.11.d sub-step 0.11.d.2, 2026-05-13). 코드 변경 zero — `docs/analysis/` 신규 디렉토리 첫 박제 + ADR 0010 §1.3 D9 정합. 후보 채택 X — 후속 sub-step .3 영역. CLAUDE.md §16.1 항목 #2 정정 권고 = sub-step .5 회고 영역 (옵션 Z).**
