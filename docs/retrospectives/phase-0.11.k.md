# Phase 0.11.k — DGT On-Breach 전략 + Entry Controls 회고

> 작성일: 2026-05-21. 성격: **사용자 주도 인터랙티브 리뷰 → 반복 개선 세션**
> (사전 ADR/게이트 없이 진행). 정본 ADR 미작성 — 본 회고가 1차 박제.
> 산출물: `src/research/dgt/` opt-in 플래그 + `--strategy-set breach` + 멀티에셋 수정.
> 성능 figure 는 `reports/` (gitignore) — 본 회고 표가 박제값.

---

## 1. 발단

사용자가 `reports/kakao-dgt/report.html` (당시 daily 재중심 ADR 구성) 을 보고 두 가지를
관찰: **① 그리드 상/하단을 절대 터치하지 않음, ② 산 가격보다 낮은 가격에 자주 팔아
손실이 커짐.** 리뷰 요청.

근본 원인 진단 (코드 + 트레이드 로그 대조):
- **daily 재중심**(`rebalance_mode="daily"`) 이 매 봉 그리드를 종가 중심으로 재생성 →
  가격이 항상 그리드 중앙에 핀 → 가장자리 도달 불가 (관찰 ①, 설계상 필연).
- 재중심으로 매도 레벨이 과거 매수가 아래로 표류 + `holdings/(n+1)` lot-blind 슬라이스
  매도 + profit guard 부재 → 평단 이하 매도 (관찰 ②). 트레이드 로그상 2020 COVID
  구간 누적 실현 -421K 까지 하락 후 회복 못함.

→ "그리드를 액티브하게 재중심하는 것이 그리드 트레이딩의 핵심 불변식(매도는 매수 위)을
깨뜨린다" 결론. 사용자가 옵션 A(진짜 grid 복원) 선택.

---

## 2. 반복 개선 체인 (단일종목 069500, 2020-2024, 1천만, n=11)

| # | 시도 | 결과 (대표값) | 학습 |
|---|------|--------------|------|
| 1 | **pure static** (`_DGTPrototypeRunner`, 재중심 zero) | 2% +6.11% / 3% +7.22% / 5% +6.67%, MDD -18~21% | 재중심 안 하니 손실 매도 사라짐(라운드트립 집계 +). 단 가장자리 이탈 후 휴면 |
| 2 | **on_breach** (돌파 시에만 재중심) | 2% -13.38% / 3% -4.17% / 5% +2.20% | **재중심은 daily든 on_breach든 손실 매도 재유발.** 좁을수록 잦은 돌파 → 더 나쁨 |
| 3 | **on_breach + profit_guard** (평단 이하 매도 차단) | 2% +2.16% / 3% +11.62% / **5% +19.31%** | 누적실현 음수행 0. PnL 급반등. **단 MDD 상승**(안 팔고 보유 → 미실현↑) |
| 4 | **+ ADR 적응 k** (6전략 병행: 고정 vs ADR) | ADR 전부 ~flat (-0.85~+0.37%), 고정 5% +19.31% 압승 | 069500 ADR≈2% → k_max 캡(2/3/5%) 거의 안 걸림 → ADR 3종 수렴. **고정 넓은 k 우위** |
| 5 | **+ D+B entry controls** (정액배분 + 60% 캡) | 5% +9.56%, MDD **-19.96%** | MDD 전 전략 ~8%p 개선. **단 V자 폭락(COVID)을 못 사서 5% 상단 손해** |
| 6 | **D+B 캡 75%** (완화) | 5% **+15.68%**, MDD -22.90%, Sharpe 0.288 | 상단 대부분 회복 + MDD 여전히 B&H 우위. 절충점 |
| — | B&H-100% (벤치마크) | +21.10%, MDD -34.58%, Sharpe 0.292 | — |

핵심: 단일 069500(V자 회복)에서 캡은 5%의 상단을 깎음 → **5% 단독이면 캡 없이 D만**이
risk-adjusted 최선 (Calmar 캡없음 0.149 > 75% 0.132 > 60% 0.095).

---

## 3. 멀티에셋 (분산 대형주 10종, 자본 2.5억, 종목당 2,500만)

종목: 005930·000660·005380·005490·035420·055550·051910·015760·097950·068270.

### 3.1 5년 (2020-2024) — D+B 75% 캡

| 전략 | PnL | MDD | Sharpe | Calmar |
|---|---|---|---|---|
| **On-Breach-5% (고정)** | **+15.19%** | **-24.08%** | **0.292** | **0.122** |
| On-Breach-ADR-5% | +9.03% | -27.36% | 0.203 | 0.065 |
| B&H-10% | +15.90% | -36.71% | 0.247 | 0.084 |

**🎯 이번 리뷰 전체에서 처음으로 DGT 가 B&H 를 위험조정으로 이긴 구성.** On-Breach-5%+D+B:
수익 동급(+15.19% vs +15.90%) + Sharpe·Calmar 모두 상회 + MDD 12.6%p 우위.

**단일종목과 정반대 — 멀티에선 D+B 가 도움**: 분산 바스켓엔 V자 회복 안 한 종목
(NAVER·LG화학·셀트리온) 이 섞여, 그 종목에 초반 올인 안 한 게(=캡) 이득. On-Breach-5%
+8.34%(캡 전) → +15.19%(D+B). → **캡/정액배분은 분산 포트폴리오에서 더 효과적.**
ADR 변형도 멀티에선 종목별 변동성 차이로 캡이 다르게 걸려 갈림 (단일에선 동일했음).

### 3.2 최근 1년 (2025-05-21 ~ 2026-05-21) — 강세장

| 전략 | PnL | MDD | Sharpe | Calmar |
|---|---|---|---|---|
| On-Breach-ADR-5% | +38.42% | -12.39% | 1.92 | 3.22 |
| On-Breach-5% (고정) | +36.71% | -13.21% | 1.82 | 2.89 |
| **B&H-10%** | **+185.88%** | -23.01% | **3.03** | **8.51** |

**강세장에서 DGT 의 구조적 한계가 극단적으로 노출.** 바스켓 B&H +186% (SK하이닉스 AI 붐
등). DGT 는 +30~38% (절대수익·낮은 MDD 는 양호) 이나 **B&H 의 1/5**, 위험조정으로도 완패
(Sharpe 1.9 vs 3.0). 그리드가 상승분을 조기 매도 → 추세장에서 buy&hold 를 절대 못 따라감.

---

## 4. 종합 결론 (정직한 메타)

**국면이 전부를 결정한다.** 동일 전략·종목인데:
- **횡보/폭락 포함 5년 + 분산** → On-Breach-5%+D+B 가 B&H 를 위험조정으로 이김.
- **강세장 1년** → B&H 가 모든 지표로 압승.

→ DGT 는 **MDD 방어 + 횡보장 수확** 도구이지, 추세장 수익 도구가 아님. 이번 세션의 모든
개선(가드/적응k/entry control)은 **완화책**이며 "추세장에서 B&H 에 진다"는 구조적 결론
(ADR 0014 G2 FAIL, ADR 0007 D10 archive 와 정합)을 메커니즘 수준에서 재확인. 자산군 분산이
DGT 를 가장 살리는 조건이라는 점도 재확인 (ADR 0005 §9.6.2 학습 정합).

DGT lifecycle 변동 없음 — **5th ring research-only 영구 격리 유지, registry 미합류.**

---

## 5. 코드 변경 (inner ring 변경 zero)

`_DGTDynamicRunner` 에 4개 opt-in 플래그 추가 (모두 기본 off → 회귀 zero):

| 플래그 | 의미 |
|--------|------|
| `profit_guard` | 실행가 ≤ 가중평균 매수원가면 매도 스킵 ("매도는 매수 레벨 위에서만"). `state.avg_cost` 추적 (`state.py`) |
| `adaptive` + `volatility_measure` | 그리드 (재)생성 시점마다 ADR/ATR 로 k 재계산 (`_compute_adr`/`_compute_atr` 재사용, clamp[k_min,k_max]) |
| `flat_allocation` | 매수액 = `initial_capital/(n+1)` 정액 (front-loaded `cash/(n+1)` 대체) |
| `max_invested_pct` | 비용기반 노출(holdings×avg_cost)이 캡 도달 시 매수 스킵 — 폭락 깊어져도 추가 매수 불가 |

`kakao_dgt_backtest.py`:
- `--strategy-set {adr,breach}` CLI 플래그. `breach` = on_breach + guard + flat-alloc + 75% 캡,
  6전략 sweep (고정 2/3/5% + ADR 2/3/5%, multiplier 1.0, k∈[0.5%, cap]).
- 멀티에셋 인터랙티브 차트: per-stock 차트가 merged 대신 **실제 종목별 결과**(`strategy_per_stock`)
  사용하도록 배선 + 메인 비교 차트는 멀티 시 정적 폴백 (포트폴리오엔 단일 캔들 시계열 없음).
- `_cumulative_realized_by_date()` 신규 — 멀티에셋 트레이드 로그 누적실현을 종목별 평단 합산으로.
- `_build_asset` — KRX ticker-name 조회 실패(로그인 게이트) 시 code 폴백.
- `_grid_reconstruction.py` — `on_breach` 모드에 ADR 적응 분기 추가 (차트=러너 일치).

---

## 6. 처리한 버그

1. **중복 `_run_static`** — 옵션 A 구현 중 실수로 함수 2개 생성 → 제거.
2. **멀티에셋 인터랙티브 크래시** — merged 결과(`close_price=0`)로 그리드 재구성 시
   `reference_price must be > 0`. Phase 0.11.i 이후 잠복.
3. **멀티에셋 누적실현 혼합 평단** — merged 트레이드에 단일종목 평단 회계 적용 →
   한국전력(2만)·LG화학(30만) 혼합 → 가짜 음수 1471행. 종목별 합산으로 수정 → 0행.
4. **pykrx ticker-name 로그인 게이트** — 외부 이슈, 폴백으로 우회.

---

## 7. 테스트 / 검증

- 신규 테스트: `TestDGTDynamicRunnerProfitGuard` (3) + `TestDGTDynamicRunnerAdaptiveK` (4)
  + `TestDGTDynamicRunnerEntryControls` (3) + `TestCumulativeRealizedByDate` (2).
- **`pytest tests/research/dgt/` 364 PASS** (세션 시작 시점 대비 +13).
- `bash scripts/check_namespace.sh` exit 0 (5th ring 격리 유지).
- `src/{domain,application,adapters,use_cases,cli,infrastructure,ports}/**` + `pyproject.toml`
  변경 zero.

---

## 8. 미결 / follow-up

- **정본 ADR 미작성** — 본 세션은 게이트 없는 탐색. 정식 박제 원하면 ADR(0018) +
  roadmap + CLAUDE.md §14 갱신 필요.
- 5년 멀티 리포트(`reports/kakao-dgt/`, `kakao-dgt-multi/`)는 cum-realized 수정 전 생성분 —
  필요 시 재생성.
- ADR 적응 k: multiplier 스윕(현재 1.0 고정)·k_min 조정은 미탐색.
- entry control: 추세 매수 게이트(옵션 C, slope gate)·시간 단계적 해제(옵션 A)는 미적용.
- Phase 1 권고 (재확인): DGT = MDD 방어 전용, 정적 배분 + 자산군 분산. 추세장 수익은 B&H.
