# Phase 0.11.b sub-step .4 — D11 AND-gate 정식 판정 + INFORMATIONAL 강등 + D10 archive 확정

> ADR 0008 §1.6 D11 AND-gate 정식 판정 + §1.10 시나리오 C graceful degradation. Markdown only (ADR 0008 D2).
>
> Asset: **069500** (KODEX 200, KR_ETF). Window: 2020-01-02 ~ 2024-12-30 (1231 bars). Grid_size=95, n_folds=5, elapsed=0.42s.

---

## 1. Sub-step .3 산출 인용 (sensitivity-heatmap.md)

- Commit hash: `76b2400` (sub-step .3 박제 정본).
- Best parameter set: **n=11, k=3%, m=1**
  - OOS Sharpe = **2.2701**
  - OOS CAGR = **4.154%**
  - OOS MDD = **-0.701%**
  - OOS Calmar = **20.6827**
  - DSR = **-1.3307**
  - trades (OOS aggregate) = **34**

---

## 2. D11 AND-gate 4 조건 정식 판정

| 조건 | 임계 | 합격 / 전체 | 비고 |
|---|---|---:|---|
| (a) 4-metric ±10% band | CAGR≥2.32% AND MDD≥-9.10% AND Sharpe≥0.473 AND Calmar≥0.280 | **58/95** | sub-step .3 박제 인용 |
| (b) DSR ≥ 1.0 | Bailey-López de Prado 2014 5% 유의 수준 | **0/95** ❌ | sub-step .3 박제 인용 (구조적 unattainable) |
| (c) OOS Sharpe ≥ 0.473 (informational slice) | baseline × 0.9 | **79/95** | sub-step .3 박제 인용 |
| (d) Perturbation ±10% worst OOS Sharpe > 0.3 | D11 (c) PRIMARY (renumber) | worst = **1.7541** → **PASS** | sub-step .4 영역 1 산출 |

### AND-gate 종합 = **FAIL**

- (b) DSR 0/95 PASS — **구조적 unattainable** (n_trials=95 multiple-testing penalty + 5 fold small sample). AND-gate 의 (b) 조건이 구조적으로 만족 불가 → AND-gate FAIL 확정.
- R1 (HIGH) 의 일봉 한계 (ADR 0007 §1.8 + ADR 0008 §1.5) 정량 박제.

---

## 3. INFORMATIONAL 강등 박제

- G2 CONDITIONAL PRIMARY (ADR 0008 §1.4) → **INFORMATIONAL FAIL** 강등.
- ADR 0008 §1.4 G2 + §1.10 시나리오 C graceful degradation path 정합.
- 사용자 결정 (2026-05-13 sub-step .3 종료): "0.11.b.4 진입 — D11 INFORMATIONAL 강등 + D10 archive 확정 시나리오 C 수락".

---

## 4. D10 archive 확정 박제

- ADR 0007 §1.7 D10 = archive (default) 결정 **supersede 없음** 박제.
- D11 AND-gate FAIL → ADR 0007 §1.7.2 promote 경로 trigger 미발동.
- ADR 0007 §3 회고 정본 유지. Strategy registry 미합류 (ADR 0007 R5 정합).
- Staleness tripwire (ADR 0007 §1.7.1): `tests/integration/test_namespace_isolation.py` FAIL 시점이 archive 의미 종료 시점.

---

## 5. PBO informational 산출 (영역 2)

- PBO (Probability of Backtest Overfitting) = **0.2766**
- Bailey-Borwein-López de Prado-Zhu 2017 simplified path (grid_runner aggregate 입력).
- 임계 (Bailey 2017): PBO < 0.5 → **no overfitting** (현 PBO = 0.2766).
- Informational (ADR 0008 §1.6 D8 (iv) OPTIONAL) — DSR / perturbation PRIMARY 가드레일 보조.

---

## 6. Phase 1 ADR 0012 D11 분봉 DGT 검토 정량 근거 박제

- **Best parameter set 정량 박제**:
  - n = **11**, k = **3%**, m = **1**
  - OOS Sharpe = 2.2701 / OOS CAGR = 4.154% / OOS MDD = -0.701% / OOS Calmar = 20.6827 / DSR = -1.3307
- **DSR / perturbation / PBO 수치 박제**:
  - Best DSR = **-1.3307** (Bailey 2014 임계 1.0 미달, n_trials=95 penalty)
  - Perturbation 27 points: worst = **1.7541** / mean = **2.0783** / passes_d11_c = **True**
  - PBO = **0.2766** (Bailey 2017 simplified)
- **일봉 한계 정당화**: sub-step .3 G2 FAIL → 분봉 DGT 재검토는 일봉의 intraday oscillation 정보 부재 (ADR 0007 §1.5 R1 일봉≠분봉) 정량 근거 제공. Phase 1 ADR 0012 D11 분봉 DGT 검토 진입 시 본 sub-step 산출이 정량 oracle.

---

## 7. Graceful degradation rationale

ADR 0008 §1.10 시나리오 C verbatim:

> **시나리오 C — D11 strict → G2 FAIL → Phase 1 진입 지연**:
> - 발생: D11 AND-gate 채택 후 일봉 한계 (0.11.a R1) 로 G2 FAIL → 0.11.b archive 확정 → 사용자 "왜 0.11.b 했냐?" 의문.
> - 원인: 일봉 환경에서 grid trading 의 본질적 한계 — intraday oscillation 정보 부재.
> - Mitigation: G2 FAIL graceful degradation — INFORMATIONAL 강등 + best parameter set + DSR / perturbation 수치 박제 → Phase 1 ADR 0012 분봉 DGT 검토 시 정량 근거 활용 (archive 가치 보존). 사용자 명시 "튜닝 결과가 좋으면 promote 재고" 의 *대칭 case* (튜닝 후에도 archive 라면 archive 사유의 정량 박제).

**사용자 결정 verbatim (2026-05-13 sub-step .3 종료 시점)**:

> "0.11.b.4 진입 — D11 INFORMATIONAL 강등 + D10 archive 확정 시나리오 C 수락 (ADR 0008 §1.10 시나리오 C graceful degradation path 정합)"

---

## 8. Perturbation 27-point 상세 (영역 1 산출)

| Rank | n | k (%) | m | IS Sharpe | OOS Sharpe | OOS CAGR (%) | OOS MDD (%) | OOS Calmar | DSR | trades |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12 | 2.70 | 1 | -0.0714 | 2.2943 | 3.991 | -0.696 | 20.8975 | -0.9247 | 40 |
| 2 | 12 | 3 | 1 | -0.1153 | 2.2779 | 3.978 | -0.652 | 20.5802 | -0.8206 | 34 |
| 3 | 11 | 2.70 | 1 | -0.0803 | 2.2766 | 4.110 | -0.744 | 20.9588 | -0.9564 | 40 |
| 4 | 11 | 3 | 1 | -0.1158 | 2.2701 | 4.154 | -0.701 | 20.6827 | -0.8478 | 34 |
| 5 | 10 | 2.70 | 1 | -0.0938 | 2.2634 | 4.459 | -0.792 | 21.0694 | -0.9389 | 40 |
| 6 | 10 | 3 | 1 | -0.1282 | 2.2477 | 4.433 | -0.746 | 20.6723 | -0.8456 | 34 |
| 7 | 12 | 3.30 | 1 | -0.1408 | 2.2112 | 2.753 | -0.605 | 19.6968 | -1.0718 | 30 |
| 8 | 11 | 3.30 | 1 | -0.1431 | 2.2100 | 2.886 | -0.650 | 19.9997 | -1.0934 | 30 |
| 9 | 12 | 2.70 | 0 | -0.0783 | 2.2040 | 3.188 | -0.694 | 18.8542 | -1.1025 | 34 |
| 10 | 12 | 3 | 0 | -0.0975 | 2.2031 | 3.208 | -0.646 | 18.8940 | -0.9971 | 28 |
| 11 | 11 | 3 | 0 | -0.1076 | 2.1933 | 3.418 | -0.696 | 18.9314 | -1.0044 | 28 |
| 12 | 10 | 3.30 | 1 | -0.1442 | 2.1912 | 3.119 | -0.694 | 19.8974 | -1.0860 | 30 |
| 13 | 11 | 2.70 | 0 | -0.0802 | 2.1832 | 3.312 | -0.741 | 18.8335 | -1.1230 | 34 |
| 14 | 10 | 2.70 | 0 | -0.0931 | 2.1727 | 3.656 | -0.793 | 18.8911 | -1.0943 | 34 |
| 15 | 10 | 3 | 0 | -0.1084 | 2.1704 | 3.665 | -0.742 | 18.9409 | -0.9986 | 28 |
| 16 | 12 | 3.30 | 0 | -0.0600 | 2.1198 | 2.338 | -0.601 | 18.1253 | -1.1970 | 26 |
| 17 | 11 | 3.30 | 0 | -0.0806 | 2.1084 | 2.506 | -0.650 | 18.0237 | -1.2008 | 26 |
| 18 | 10 | 3.30 | 0 | -0.0885 | 2.0949 | 2.712 | -0.693 | 18.0774 | -1.1928 | 26 |
| 19 | 12 | 3 | 2 | -0.2607 | 1.8888 | 4.044 | -0.752 | 19.6694 | -0.8677 | 45 |
| 20 | 11 | 3 | 2 | -0.2702 | 1.8870 | 4.119 | -0.805 | 20.0812 | -0.9169 | 45 |
| 21 | 10 | 3 | 2 | -0.2813 | 1.8650 | 4.360 | -0.859 | 20.0618 | -0.9237 | 45 |
| 22 | 12 | 2.70 | 2 | -0.2262 | 1.8455 | 4.266 | -0.771 | 19.3203 | -0.9196 | 53 |
| 23 | 11 | 2.70 | 2 | -0.2380 | 1.8254 | 4.297 | -0.824 | 19.4819 | -0.9721 | 53 |
| 24 | 10 | 2.70 | 2 | -0.2287 | 1.8140 | 4.636 | -0.881 | 19.4129 | -0.9606 | 53 |
| 25 | 11 | 3.30 | 2 | -0.3065 | 1.7711 | 2.704 | -0.817 | 19.0769 | -1.2220 | 43 |
| 26 | 12 | 3.30 | 2 | -0.3064 | 1.7698 | 2.640 | -0.760 | 18.7270 | -1.1843 | 43 |
| 27 | 10 | 3.30 | 2 | -0.3161 | 1.7541 | 2.896 | -0.872 | 19.0876 | -1.2240 | 43 |

Perturbation 27 points: worst OOS Sharpe = **1.7541** / mean = **2.0783** / D11 (c) threshold (>0.3) = **PASS**.

---

## 9. Reproducibility (D12)

- Deterministic ordering: grid + WFO + perturbation + PBO pipeline 은 seed-free (Decimal-only).
- 2 회 동일 실행 시 byte-identical 산출 (AC15 정신 계승, ADR 0008 D12).

