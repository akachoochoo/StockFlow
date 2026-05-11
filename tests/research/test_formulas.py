"""Phase 0.11.a — DGT formulas 단위 테스트.

사용자 ADR draft §1.1 / §2 verbatim: "Eq. (1)~(5) + Table 1 — 깨지면 LLM
수정안 거부". 박제 primary success criterion 핵심.

Decimal tolerance < Decimal("0.0001") (ADR 0007 §1.10 oracle 공통).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.research.dgt.formulas import (
    critical_arb_count_eq5,
    expected_no_arb_eq3,
    grid_levels_table1,
    linear_down_loss_eq2,
    linear_up_profit_eq1,
)


_TOL = Decimal("0.0001")


class TestEq1LinearUpProfit:
    def test_paper_n4_m100_returns_75(self) -> None:
        result = linear_up_profit_eq1(n=4, total_capital=Decimal("100"))
        assert abs(result - Decimal("75")) < _TOL

    def test_paper_n8_m1000(self) -> None:
        # M * (n-1)/n = 1000 * 7/8 = 875
        result = linear_up_profit_eq1(n=8, total_capital=Decimal("1000"))
        assert abs(result - Decimal("875")) < _TOL

    def test_invalid_n(self) -> None:
        with pytest.raises(ValueError, match="n must be > 0"):
            linear_up_profit_eq1(n=0, total_capital=Decimal("100"))

    def test_invalid_capital(self) -> None:
        with pytest.raises(ValueError, match="total_capital"):
            linear_up_profit_eq1(n=4, total_capital=Decimal("0"))


class TestEq2LinearDownLoss:
    def test_paper_n4_m100_returns_125(self) -> None:
        result = linear_down_loss_eq2(n=4, total_capital=Decimal("100"))
        assert abs(result - Decimal("125")) < _TOL

    def test_paper_n8_m1000(self) -> None:
        # M * (n+1)/n = 1000 * 9/8 = 1125
        result = linear_down_loss_eq2(n=8, total_capital=Decimal("1000"))
        assert abs(result - Decimal("1125")) < _TOL

    def test_invalid_n(self) -> None:
        with pytest.raises(ValueError, match="n must be > 0"):
            linear_down_loss_eq2(n=-1, total_capital=Decimal("100"))

    def test_invalid_capital(self) -> None:
        with pytest.raises(ValueError, match="total_capital"):
            linear_down_loss_eq2(n=4, total_capital=Decimal("-1"))


class TestEq3NoArbExpectation:
    def test_paper_n4_m100_negative_25(self) -> None:
        # (P_u - L_l)/2 = (75 - 125)/2 = -25
        result = expected_no_arb_eq3(n=4, total_capital=Decimal("100"))
        assert abs(result - Decimal("-25")) < _TOL

    @pytest.mark.parametrize("n", [4, 8, 16])
    def test_always_negative_invariant(self, n: int) -> None:
        result = expected_no_arb_eq3(n=n, total_capital=Decimal("100"))
        assert result < Decimal("0"), f"E(G) < 0 invariant violated for n={n}"


class TestEq5CriticalArbCount:
    @pytest.mark.parametrize(
        "n,expected",
        [
            (4, Decimal("1")),    # 16/8 - 4/4 = 2 - 1 = 1
            (8, Decimal("6")),    # 64/8 - 8/4 = 8 - 2 = 6
            (16, Decimal("28")),  # 256/8 - 16/4 = 32 - 4 = 28
        ],
    )
    def test_paper_formula(self, n: int, expected: Decimal) -> None:
        result = critical_arb_count_eq5(n=n)
        assert abs(result - expected) < _TOL

    def test_invalid_n(self) -> None:
        with pytest.raises(ValueError, match="n must be > 0"):
            critical_arb_count_eq5(n=0)


class TestTable1GridLevels:
    def test_n4_k_5pct_m2_reference_100(self) -> None:
        # n=4, m=2, k=0.05, P=100 → 5 levels at i ∈ {-2,-1,0,1,2}
        levels = grid_levels_table1(
            n=4,
            reference_price=Decimal("100"),
            k=Decimal("0.05"),
            levels_above=2,
        )
        assert len(levels) == 5
        # Reference 100 위치 = index 2 (levels_above=2 means 2 levels above, so
        # i=-2 → ~90.70, i=-1 → ~95.24, i=0 → 100, i=+1 → 105, i=+2 → 110.25)
        assert abs(levels[2] - Decimal("100")) < _TOL
        # Ascending ordering invariant
        for i in range(len(levels) - 1):
            assert levels[i] < levels[i + 1], f"Not ascending at index {i}"

    def test_extreme_levels_above_zero(self) -> None:
        # All levels below reference
        levels = grid_levels_table1(
            n=4,
            reference_price=Decimal("100"),
            k=Decimal("0.05"),
            levels_above=0,
        )
        assert len(levels) == 5
        # Reference == top level (i=0)
        assert abs(levels[-1] - Decimal("100")) < _TOL

    def test_extreme_levels_above_equals_n(self) -> None:
        # All levels above reference
        levels = grid_levels_table1(
            n=4,
            reference_price=Decimal("100"),
            k=Decimal("0.05"),
            levels_above=4,
        )
        assert len(levels) == 5
        # Reference == bottom level (i=0)
        assert abs(levels[0] - Decimal("100")) < _TOL

    def test_invalid_levels_above(self) -> None:
        with pytest.raises(ValueError, match="levels_above"):
            grid_levels_table1(
                n=4,
                reference_price=Decimal("100"),
                k=Decimal("0.05"),
                levels_above=5,  # > n
            )

    def test_invalid_reference_price(self) -> None:
        with pytest.raises(ValueError, match="reference_price"):
            grid_levels_table1(
                n=4,
                reference_price=Decimal("0"),
                k=Decimal("0.05"),
                levels_above=2,
            )

    def test_invalid_k(self) -> None:
        with pytest.raises(ValueError, match="k must be > 0"):
            grid_levels_table1(
                n=4,
                reference_price=Decimal("100"),
                k=Decimal("0"),
                levels_above=2,
            )

    def test_invalid_n(self) -> None:
        with pytest.raises(ValueError, match="n must be > 0"):
            grid_levels_table1(
                n=0,
                reference_price=Decimal("100"),
                k=Decimal("0.05"),
                levels_above=0,
            )
