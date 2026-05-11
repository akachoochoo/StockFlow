# Phase 0.11.a — DGT 일봉 prototype vs Phase 0.7.3 baseline 비교 (AC9)

> ADR 0007 §1.4 G2 INFORMATIONAL + §1.10 AC9 산출물.
> 작성일: 2026-05-12 (sub-step 0.11.a.4).
> 비교 window: **2020-01-02 ~ 2024-12-30** (ADR 0003 §18 Phase 0.7.3 baseline-aligned, Critic Round 2 Minor #4 정정).
> 자산: KODEX 200 (069500). D3 default 단독 (Phase 0.7.3 baseline 의 069500 + 132030 EQUAL 과 자산 1차원 차이 — 본질적 분산 효과 비교 불가, informational 만).

---

## 1. 비교 표 (4지표 + 보조)

| 지표 | Phase 0.7.3 baseline (069500 + 132030 EQUAL, PriceDropStrategy)¹ | Phase 0.11.a DGT (069500 단독, n=7 k=5% m=3, 일봉)² | diff |
|---|---:|---:|---:|
| **CAGR %** | **+2.5779** | **+1.23** | -1.35 pp |
| **MDD %** | **-8.2737** | **-19.55** | -11.28 pp (악화) |
| **Sharpe** | **0.5255** | **0.17** | -0.35 |
| **Calmar** | **0.3116** | **0.063** | -0.25 |
| Total return % | +13.2280 | +6.17 | -7.06 pp |
| Trade count | 28 (cumulative sells) | 85 (BUY + SELL 합) | +57 |
| Final balance | — | 10,617,147 KRW (10M 초기) | — |
| Wallet (net of fees) | — | -49,764.79 KRW | — |

¹ 출처: `docs/retrospectives/phase-0.7.3-results.md:45-54` verbatim. ADR 0003 §18 박제.
² 출처: `tests/fixtures/golden/dgt_069500_2021_2025.json` (0.11.a.4 산출).

거래세율 footnote³:
- KR_ETF (069500) 거래세 = 0.18% sell-only (D8 default, KRX 공식, 2025 시점).
- 위탁수수료 = 0.015% 양방 (D8 default, ADR 0007 §1.3).
- D7 호가 단위 = KR_ETF tick=5원 단일 (ADR 0007 §2.1, `src/domain/tick_size.py:18-57` 정합).
- 출처 URL/문서 버전 박제 의무 = 0.11.a.5 회고 시 final 확정.

---

## 2. G2 informational 판정

| Gate | 기준 | 결과 |
|------|------|------|
| **G2 (DGT IRR vs Phase 0.7.3 baseline)** | CAGR ≥ baseline 2.58% AND MDD ≤ baseline -8.27% AND Sharpe ≥ 0.53 AND Calmar ≥ 0.31 | **FAIL** (4/4 지표 모두 baseline 미달) |

**판정**: G2 informational FAIL.

**D9 default 발동 (ADR 0007 §1.5 R1 mitigation)**: abandon (A'' fallback) — runner archive, KRX 마찰비용 모델 + 수식 박제 보존.

---

## 3. R1 (HIGH) 실증 — Architect Round 1 A2 antithesis 정확

ADR 0007 §1.5 R1 mitigation 정신:
> "primary success = 박제 (수식 + 마찰비용 + 네임스페이스). G2 informational only."

**Architect Round 1 A2 antithesis** ("일봉 DGT 는 not faithful + not integrable") 4지표 실증 confirmed:

1. **분봉 → 일봉 → arbitrage cycle 격감**. 논문 (BTC/ETH 1분봉 24/7) 의 n²/8 - n/4 임계 차익거래 수 (n=7: 49/8 - 7/4 ≈ 4.4) 는 일봉 1230 bar 환경에서 **달성 가능**하지만 실제 trade 85건 중 SELL 비중이 BUY 보다 낮음 (wallet net negative -49,764). 분봉 환경의 빠른 oscillation 부재.

2. **자산군 분산 효과 박탈**. Phase 0.7.3 의 H3 PASS (Sharpe 0.5255) 는 069500 (주식) + 132030 (골드) 분산이 본질 (ADR 0005 §9.6.2). DGT 단독 069500 = 분산 zero → Sharpe 0.17 (Phase 0.5 단일 종목 0.30 보다도 낮음). DGT 의 grid mechanism 이 분산 효과를 만들지 못함.

3. **MDD -19.55% < 5-year window 일봉 069500 단순 buy-and-hold 평가**. Phase 0.7.1 baseline (PriceDropStrategy, 069500 단독) MDD -7.95% 와 비교해도 DGT 의 grid SELL 효과가 MDD 완화 못함. **grid SELL 이 익절 효과 ≠ MDD 방어**.

**Phase 0.11.a 의 본질적 학습 (D10 archive 정당화)**:
- "DGT 는 분봉/24/7 환경에서만 의미. 일봉 환경 + 한국 시장 마찰비용 (거래세 0.18% sell + 수수료 0.015% 양방) 적용 시 Phase 0.7.3 baseline 대비 전 지표 열위."
- R1 (분봉/일봉 본질 차이) 박제 — Phase 1 ADR 0008 KIS API 분봉 검토 시 정량 근거.

---

## 4. 박제 primary success criterion (G1 + G3 + G4 PASS 확인)

ADR 0007 §1.4 success criterion 재정의 = "박제 (수식 + 마찰비용 + 네임스페이스) primary, G2 informational only". G1 + G3 + G4 PASS 시 sub-step 성공:

| Gate | 기준 | 결과 | Evidence |
|------|------|------|----------|
| **G1** PRIMARY | AC1~AC6 (수식 + KoreanMarketCostModel) | **PASS** | `tests/research/test_cost_model.py` 11 + `tests/research/test_formulas.py` 23 = 34 tests |
| **G2** INFORMATIONAL | AC7~AC9 (runner + 비교) | **FAIL** (anticipated, R1) | 본 §2 — Phase 0.7.3 4지표 미달. D9 default abandon 발동. |
| **G3** PRIMARY | AC10~AC12 (D4 + ADR header + 회고) | **부분 PASS** (회고 = 0.11.a.5 잔여) | AC10/AC11 통과. AC12 = 0.11.a.5 산출. |
| **G4** PRIMARY | AC13~AC15 (CI + Decimal + 재현성) | **PASS** | `scripts/check_namespace.sh` OK + `mypy --strict` OK + AC15 byte-identical pass |

**박제 primary 측면 sub-step 성공** — G2 FAIL 는 R1 mitigation 예상 결과.

---

## 5. R6 측정 (실행시간 / 메모리)

| 항목 | 측정 | Bound | 결과 |
|------|------|-------|------|
| 실행시간 (real) | **0.13s** | 60s | ✅ |
| 최대 RSS | **36.78 MB** | 1 GB | ✅ |
| Snapshot 수 | 1231 (5-year 일봉 bar 수) | — | — |

명령:
```bash
/usr/bin/time -l uv run python -m src.research.dgt.cli \
  --asset 069500 --start 2020-01-02 --end 2024-12-30 \
  --initial-capital 10000000 --grid-levels 7 --grid-spacing-pct 5 --levels-above 3 \
  --csv data/historical/KRX_069500_2019-2024.csv \
  --output tests/fixtures/golden/dgt_069500_2021_2025.json
```

R6 bound 통과 (60s/1GB margin 매우 큼).

---

## 6. 통합 권고 (D10 lifecycle, 0.11.a.5 회고 시 final 확정 후보)

본 §2 결과 + §3 R1 실증 + ADR 0007 §1.7 lifecycle:

- **(a) D10 = archive (default 권고)** — `src/research/dgt/` 코드 보존 (Phase 1+ 재검토 / 분봉 ADR 트리거 시 참조). cost model 의 한국 시장 마찰비용 모델 = Phase 1 ADR 0008 (가칭) 재사용 후보. staleness tripwire = `tests/integration/test_namespace_isolation.py` FAIL.
- (b) D10 = abandon — `src/research/dgt/` 삭제. 분봉 DGT 미래 검토 시 본 §3 R1 실증 인용. Phase 0.11.a placeholder 정신만 종결.
- (c) D10 = promote — **권고 안 함**. G2 4/4 FAIL 으로 strategy registry 합류 정당화 불가.

권고 = **(a) archive**. 0.11.a.5 회고 시 사용자 final 결정.

---

## 7. References

- arXiv:2506.11921v1 (Chen, Chen, Jang 2025) — DGT 논문.
- `docs/decisions/0007-phase-0.11.a-dgt-research-namespace.md` — ADR 0007 §1 (진입) + §2 (KRX 표 정정).
- `docs/retrospectives/phase-0.7.3-results.md:45-54` — Phase 0.7.3 baseline verbatim.
- `docs/decisions/0003-phase-0.7-decisions.md` §18 — Phase 0.7.3 baseline 박제.
- `docs/decisions/0005-phase-0.9-decisions.md` §9.6.2 — 자산군 분산 = H3 충분 조건 (R1 mitigation 정신).
- `tests/fixtures/golden/dgt_069500_2021_2025.json` — 본 비교의 DGT 측 출처 (0.11.a.4 산출).
