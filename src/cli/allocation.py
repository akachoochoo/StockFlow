"""Phase 0.7.2 자본 배분 산식 — ADR 0003 §16.13 박제.

CLI layer 의 순수 함수 모듈. 도메인 / port 의존 zero (CLAUDE.md §1.1
정신 정합). Phase 0.8 IndicatorPort 도입 시 통합 검토 가능.

책임:
- ``_calculate_volatility`` — daily log returns 표준편차 (raw, no
  annualization). sigma 산출 위치 결정 §16.5.1 옵션 (c) Composition 직접.
- ``compute_per_asset_budgets`` — ``AllocationPolicy`` 별 per_split_amount
  산정. EQUAL 시 yaml 그대로 (Phase 0.7.1 회귀 invariant). INV_VOL /
  VOL 시 자동 산정.
"""
from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

from src.domain.models import AllocationPolicy


def _calculate_volatility(closes: list[Decimal]) -> Decimal:
    """daily log returns 의 표준편차 (population, raw — no annualization).

    ADR §16.13.5 default — annualization 없음. 여러 자산 weight 산정 시
    √N 이 양쪽에 동일 곱이라 무차별. population (1/n) stddev 사용 —
    sample (1/(n-1)) 와의 차이도 weight 산정 시 무차별.

    Args:
        closes: lookback 윈도우 (e.g. 246 거래일) 의 종가 series.
            len(closes) >= 2 필수 (n-1 log returns 산출).

    Returns:
        표준편차 (Decimal, 항상 >= 0).

    Raises:
        ValueError: closes 길이 < 2 또는 non-positive close 포함.
    """
    if len(closes) < 2:
        raise ValueError(
            f"Need >= 2 closes for volatility, got {len(closes)}"
        )
    if any(c <= 0 for c in closes):
        raise ValueError("All closes must be positive (log undefined)")

    log_returns = [(curr / prev).ln() for prev, curr in pairwise(closes)]
    n = Decimal(len(log_returns))
    mean = sum(log_returns, Decimal(0)) / n
    sq_diff_sum = sum((r - mean) ** 2 for r in log_returns)
    variance = sq_diff_sum / n
    return variance.sqrt()


def compute_per_asset_budgets(
    policy: AllocationPolicy,
    total_capital: Decimal,
    asset_volatilities: dict[str, Decimal],
    yaml_per_split_amounts: dict[str, int],
    max_split_counts: dict[str, int],
) -> dict[str, int]:
    """정책별 per_split_amount (KRW int) 산정.

    ADR §16.13.2 / §16.13.5 박제:

    - **EQUAL** (default) — yaml 의 ``per_split_amount`` 그대로 반환.
      Phase 0.7.1 회귀 invariant 보존 — breaking change zero.
    - **INV_VOL** — ``weight_i = (1/sigma_i) / sum_j(1/sigma_j)``; ``per_asset_budget_i
      = total * weight_i``; ``per_split_amount_i = per_asset_budget_i //
      max_split_count_i``.
    - **VOL** — ``weight_i = sigma_i / sum_j sigma_j``; (이하 동일).

    Args:
        policy: 채택된 ``AllocationPolicy``.
        total_capital: 총 자본 (KRW Decimal). CLI ``--capital`` 인자.
        asset_volatilities: 자산 코드 → sigma 매핑. EQUAL 시 무시 (빈 dict 가능).
        yaml_per_split_amounts: 자산 코드 → yaml 박제 per_split_amount.
        max_split_counts: 자산 코드 → yaml 박제 max_split_count.

    Returns:
        자산 코드 → per_split_amount (KRW int).

    Raises:
        ValueError: sigma <= 0 (INV_VOL 시 0 division), 또는 자산 set
            미스매치 (volatilities / yaml_per_split_amounts /
            max_split_counts dict keys 가 다른 경우 — INV_VOL/VOL 만
            검증).
    """
    if policy is AllocationPolicy.EQUAL:
        return dict(yaml_per_split_amounts)

    # INV_VOL / VOL: 자산 set 일치 검증.
    yaml_codes = set(yaml_per_split_amounts.keys())
    vol_codes = set(asset_volatilities.keys())
    split_codes = set(max_split_counts.keys())
    if not (yaml_codes == vol_codes == split_codes):
        raise ValueError(
            f"Asset code sets must match: yaml={yaml_codes} "
            f"volatilities={vol_codes} max_splits={split_codes}"
        )
    if any(sigma <= 0 for sigma in asset_volatilities.values()):
        raise ValueError(
            "All volatilities must be positive (weight undefined)"
        )

    if policy is AllocationPolicy.INV_VOL:
        weights = {
            code: Decimal(1) / sigma for code, sigma in asset_volatilities.items()
        }
    elif policy is AllocationPolicy.VOL:
        weights = dict(asset_volatilities)
    else:
        raise ValueError(f"Unknown allocation policy: {policy}")

    total_weight = sum(weights.values(), Decimal(0))
    per_asset_budgets = {
        code: int(total_capital * w / total_weight)
        for code, w in weights.items()
    }
    return {
        code: per_asset_budgets[code] // max_split_counts[code]
        for code in per_asset_budgets
    }
