"""Phase 0.11.a — DGT 논문 (Chen, Chen, Jang 2025, arXiv:2506.11921) 수식 박제.

ADR 0007 §1.0 reference. 박제 primary success criterion 의 핵심 — LLM 회귀 시
부호/인덱싱 실수가 코드 + test 양쪽에 박힌 수식으로 잡힘 (사용자 ADR draft §2 정신).

수식 (paper 기호 → 코드 식별자):
- n      = grid_count (레벨 수 = n+1)
- k      = grid_size (등비 간격, 예: Decimal("0.05"))
- m      = levels_above (current price 위 grid 수)
- P      = reference_price (흑색 레벨)
- M      = total_capital

CLAUDE.md §2.1 — Decimal-only. 외부 import zero (stdlib + Decimal).
"""
from __future__ import annotations

from decimal import Decimal


def linear_up_profit_eq1(n: int, total_capital: Decimal) -> Decimal:
    """Eq.(1) — 선형 상승 시 P_u (profit upper).

    Paper test: n=4, M=100 → 75 (USDT, KRW equivalent ratio invariant).
    Formula: P_u = M * (n - 1) / n.
    """
    if n <= 0:
        raise ValueError(f"n must be > 0, got {n}")
    if total_capital <= 0:
        raise ValueError(f"total_capital must be > 0, got {total_capital}")
    return total_capital * (Decimal(n) - Decimal(1)) / Decimal(n)


def linear_down_loss_eq2(n: int, total_capital: Decimal) -> Decimal:
    """Eq.(2) — 선형 하락 시 L_l (loss lower).

    Paper test: n=4, M=100 → 125.
    Formula: L_l = M * (n + 1) / n.
    """
    if n <= 0:
        raise ValueError(f"n must be > 0, got {n}")
    if total_capital <= 0:
        raise ValueError(f"total_capital must be > 0, got {total_capital}")
    return total_capital * (Decimal(n) + Decimal(1)) / Decimal(n)


def expected_no_arb_eq3(n: int, total_capital: Decimal) -> Decimal:
    """Eq.(3) — arbitrage 미고려 시 E(G).

    Paper: E(G) = (P_u - L_l) / 2 — arbitrage 없을 때 평균 수익 < 0.
    For n=4, M=100: (75 - 125)/2 = -25 (negative invariant).
    """
    return (
        linear_up_profit_eq1(n, total_capital)
        - linear_down_loss_eq2(n, total_capital)
    ) / Decimal(2)


def critical_arb_count_eq5(n: int) -> Decimal:
    """Eq.(5) — 임계 차익거래 수 = n²/8 − n/4.

    Paper: number of arbitrage cycles needed to break even.
    For n=4: 16/8 - 4/4 = 1. For n=8: 64/8 - 8/4 = 6.
    """
    if n <= 0:
        raise ValueError(f"n must be > 0, got {n}")
    return Decimal(n) ** 2 / Decimal(8) - Decimal(n) / Decimal(4)


def grid_levels_table1(
    n: int,
    reference_price: Decimal,
    k: Decimal,
    levels_above: int,
) -> list[Decimal]:
    """Table 1 — 그리드 레벨 생성 (geometric spacing).

    Returns n+1 grid level prices, sorted ascending.

    Args:
        n: grid_count (levels = n+1).
        reference_price: P (흑색 레벨).
        k: grid_size ratio (예: Decimal("0.05") = 5%).
        levels_above: m (number of levels above reference, 0 ≤ m ≤ n).

    Geometric spacing: level_i = reference_price * (1 + k)^i for
    i in range(-(n - m), m + 1).

    Raises:
        ValueError: n <= 0, m outside [0, n], reference_price <= 0, or k <= 0.
    """
    if n <= 0:
        raise ValueError(f"n must be > 0, got {n}")
    if not (0 <= levels_above <= n):
        raise ValueError(f"levels_above must be in [0, {n}], got {levels_above}")
    if reference_price <= 0:
        raise ValueError(f"reference_price must be > 0, got {reference_price}")
    if k <= 0:
        raise ValueError(f"k must be > 0, got {k}")

    levels_below = n - levels_above
    factor = Decimal(1) + k
    return [
        reference_price * (factor ** i)
        for i in range(-levels_below, levels_above + 1)
    ]
