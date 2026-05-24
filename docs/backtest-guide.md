# 백테스트 가이드 — 두 전략 패러다임 (분할매수 vs DGT)

> 처음 쓰는 사람을 위한 길잡이. 이 시스템에는 **성격이 다른 두 전략**이 있고,
> 각각 **별도 config 파일 + 별도 명령**을 씁니다. 섞이지 않습니다.
> (왜 분리했는지는 맨 아래 "왜 두 개로 나눴나" 참조 — ADR 0022 §11.)

## 한눈에 — 어느 명령이 어느 파일과 짝인가

| | **분할매수 (PriceDrop / SupportLevel)** | **DGT (그리드 트레이딩)** |
|---|---|---|
| 무엇 | 하락 시 분할 매수 + 목표가 익절 + 재진입 | 그리드 레벨 통과 시 자동 매수/매도 (횡보 수확·MDD 방어) |
| 매수·매도 | 매수/매도/재진입 = **3개 전략 조합** | **1개 엔진**이 매수+매도 모두 (재중심 내장) |
| config 파일 | `config/strategies-*.yaml` | `config/grid-*.yaml` |
| 만드는 명령 | `manage_strategies.py add` / `wizard`(split) / `set` | `manage_strategies.py wizard`(dgt) / `grid-wizard` |
| 파라미터 | drop_threshold / max_split / profit_target / cooldown … | grid_count / k_min·k_max / measure(adr) / volume_gate … |
| 백테스트 | `trading backtest --config` | `trading grid-backtest --config` (또는 `backtest` 가 자동 감지) |

**가장 쉬운 시작**: `manage_strategies.py wizard <파일>` 을 실행하면 **맨 처음
"split=분할매수 / dgt=그리드"를 물어보고** 알맞은 config 파일을 만들어 줍니다.
어느 명령·파일을 쓸지 외울 필요 없이 wizard 하나로 양쪽 다 됩니다. (`grid-wizard`
는 DGT 로 바로 가는 단축 명령일 뿐입니다.)

**핵심**: DGT는 `buy_strategy` 선택지가 **아닙니다**. `add`의 매수 전략 목록에
DGT가 없는 건 정상입니다 — DGT는 별도 `grid-*.yaml` + `grid-backtest`로 갑니다.

**단일 진입점**: `trading backtest --config <파일>` 은 파일 종류를 자동 감지해
분할매수면 그대로, **DGT면 그리드 백테스트로 자동 라우팅**합니다 (wizard 와 동형).
즉 백테스트는 `backtest` 하나만 기억하면 됩니다. `grid-backtest` 는 명시적 DGT
진입으로 그대로 쓸 수 있습니다. (단 자동 라우팅은 backtest 한정 — paper/live 는
실거래 안전상 grid config 를 거부하고 안내합니다.)

---

## 가장 쉽게: 데이터+백테스트 한 번에 (파이프라인)

config만 있으면 **데이터 자동 다운로드 → 백테스트**를 한 명령으로:

```bash
uv run python scripts/run_backtest.py --config config/my.yaml \
  --start 2025-12-02 --end 2026-05-20 --capital 10000000
```
- config의 종목들을 읽어 **없는 기간 데이터만 pykrx로 받고**(있으면 스킵),
- `trading backtest --config ...`로 위임 → 분할매수/DGT 자동 라우팅.

> 네트워크(pykrx)는 이 `scripts/` 파이프라인에만 있습니다. 본 `trading` CLI는
> 오프라인 재생 전용(네트워크 없음)이라, 데이터 준비는 의도적으로 분리돼 있습니다.

아래는 단계를 직접 밟는 방법입니다(데이터를 따로 받아두고 여러 번 돌릴 때).

## 공통 전제: 종목은 `config/assets.yaml`에 등록돼야 함

두 패러다임 모두 종목코드가 `config/assets.yaml`(레지스트리)에 있어야 동작합니다.
- 새 종목 등록 = `manage_strategies.py add` (메타데이터 pykrx 자동 조회 + assets.yaml 기록).
- `grid-wizard`는 **이미 등록된** 종목 중에서 고릅니다 (등록은 `add`가 담당).

Phase 0 박제 9종(069500/214980/132030/005930/005380/055550/097950/015760/298040)은
이미 등록돼 있어 바로 쓸 수 있습니다.

---

## A. 분할매수 백테스트

```bash
# 1) (선택) 종목 추가 — pykrx 자동 조회 + 일괄 확인
uv run python scripts/manage_strategies.py add config/strategies-X.yaml --code 005930

# 1') 또는 백지에서 대화식 생성 (전략·파라미터 안내)
uv run python scripts/manage_strategies.py wizard config/strategies-X.yaml

# 2) 데이터 받기
uv run python scripts/download_kr_assets.py --code 069500 --start 2019-01-02 --end 2024-12-30

# 3) 백테스트
trading backtest --config config/strategies-X.yaml \
  --csv 069500=data/historical/KRX_069500_2019-2024.csv \
  --start 2019-01-02 --end 2024-12-30 --capital 10000000
```

> 단일 종목·빠른 실행은 `--config` 없이 플래그로도 됩니다:
> `trading backtest --csv path.csv --drop-pct 5.0 --per-split-amount 500000 ...`

**Cold start**: `add`에 넘긴 strategies 파일이 없거나 비어 있으면, 첫 종목의 전략
정책을 대화식으로 입력받아 파일을 새로 만듭니다 (둘째 종목부터는 기존 정책 상속).

---

## B. DGT 백테스트

```bash
# 1) DGT config 대화식 생성 (GridConfig 범위·기본값 안내)
#    wizard 에서 'dgt' 를 골라도 되고, grid-wizard 로 바로 가도 됩니다.
uv run python scripts/manage_strategies.py wizard config/grid-X.yaml   # → dgt 선택
#   (또는) uv run python scripts/manage_strategies.py grid-wizard config/grid-X.yaml

# 2) 데이터 받기 (위와 동일)
uv run python scripts/download_kr_assets.py --code 069500 --start 2019-01-02 --end 2024-12-30

# 3) DGT 백테스트 (멀티에셋 — 종목별 균등 자본 분할)
trading grid-backtest --config config/grid-X.yaml \
  --csv 069500=data/historical/KRX_069500_2019-2024.csv \
  --csv 132030=data/historical/KRX_132030_2019-2024.csv \
  --start 2019-01-02 --end 2024-12-30 --capital 100000000
```

> 단일 종목은 `--config` 없이도 됩니다:
> `trading grid-backtest --code 069500 --csv path.csv --measure adr --volume-gate ...`
> (기본값이 최적 구성: measure=adr, volume_gate=on, k=[0.5%,5%], n=11)

DGT의 역할 = **MDD 방어·횡보 수확**입니다. 강세장에서는 Buy&Hold에 못 미치는 게
설계상 trade-off입니다 (출력에 B&H 대비 수익/MDD가 함께 나옵니다).

---

## 왜 두 개로 나눴나 (ADR 0022 §11)

- DGT는 **매수와 매도가 한 메커니즘**입니다 (그리드 레벨을 아래로 통과 → 매수,
  위로 통과 → 매도, 매일 재중심). 분할매수처럼 매수/매도/재진입으로 쪼개지지 않습니다.
- 그래서 strategies.yaml의 `buy_strategy` 칸에 끼우면 매도 주체가 충돌합니다.
  DGT를 **별도 config + 별도 use_case(GridRunner)**로 둔 이유입니다 (D6/D9).
- 부수 효과로 **live 안전**: grid config는 backtest/paper 명령만 받고, 실거래(live)
  경로는 grid config를 애초에 받지 않습니다 (실거래 진입은 별도 승인 게이트 G5).

정본: [`docs/decisions/0022-phase-1.x-dgt-live-promotion.md`](./decisions/0022-phase-1.x-dgt-live-promotion.md),
개발 규칙: [`CLAUDE.md`](../CLAUDE.md).
