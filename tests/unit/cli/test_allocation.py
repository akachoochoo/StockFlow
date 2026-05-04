"""Unit tests for src.cli.allocation — ADR 0003 §16.13 산식 검증.

순수 함수 모듈 — 도메인 / port 의존 zero. 단위 테스트 단순.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.cli.allocation import (
    _calculate_volatility,
    compute_per_asset_budgets,
)
from src.domain.models import AllocationPolicy


# ---------------------------------------------------------------------------
# _calculate_volatility
# ---------------------------------------------------------------------------
class TestCalculateVolatility:
    def test_two_closes_zero_change_returns_zero(self):
        # log(1) = 0, mean = 0, sigma = 0
        assert _calculate_volatility([Decimal(100), Decimal(100)]) == 0

    def test_constant_closes_returns_zero(self):
        # 모든 returns = 0 → sigma = 0
        closes = [Decimal(100)] * 5
        assert _calculate_volatility(closes) == 0

    def test_increasing_steady_returns_low_volatility(self):
        # 일정 비율 증가 — log returns 동일 → sigma = 0
        closes = [Decimal(100) * Decimal("1.01") ** i for i in range(5)]
        result = _calculate_volatility(closes)
        # 부동 / Decimal 정밀도 한계로 정확히 0 은 아니지만 매우 작음
        assert result < Decimal("1e-20")

    def test_oscillating_closes_higher_volatility(self):
        # 진동: 100 → 110 → 100 → 110 → 100 (로그 returns 부호 교대)
        closes = [
            Decimal(100), Decimal(110), Decimal(100), Decimal(110),
            Decimal(100),
        ]
        sigma = _calculate_volatility(closes)
        # 진동 sigma > 단조 sigma — sanity check
        steady = _calculate_volatility(
            [Decimal(100) * Decimal("1.05") ** i for i in range(5)]
        )
        assert sigma > steady

    def test_too_few_closes_raises(self):
        with pytest.raises(ValueError, match=">= 2 closes"):
            _calculate_volatility([Decimal(100)])
        with pytest.raises(ValueError, match=">= 2 closes"):
            _calculate_volatility([])

    def test_non_positive_close_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _calculate_volatility([Decimal(100), Decimal(0)])
        with pytest.raises(ValueError, match="positive"):
            _calculate_volatility([Decimal(-1), Decimal(100)])

    def test_returns_non_negative(self):
        # sigma 는 항상 >= 0 (수학적 정의).
        closes = [Decimal(100), Decimal(95), Decimal(105), Decimal(98)]
        assert _calculate_volatility(closes) >= 0


# ---------------------------------------------------------------------------
# compute_per_asset_budgets
# ---------------------------------------------------------------------------
class TestComputePerAssetBudgetsEqual:
    """EQUAL 정책 — yaml per_split_amount 그대로 (Phase 0.7.1 회귀)."""

    def test_returns_yaml_values_as_is(self):
        result = compute_per_asset_budgets(
            policy=AllocationPolicy.EQUAL,
            total_capital=Decimal(100_000_000),
            asset_volatilities={},  # ignored
            yaml_per_split_amounts={"069500": 5_000_000, "214980": 5_000_000},
            max_split_counts={"069500": 7, "214980": 7},
        )
        assert result == {"069500": 5_000_000, "214980": 5_000_000}

    def test_returns_copy_not_alias(self):
        # 원본 변경 시 결과 영향 없는지 (mutation 방어)
        yaml = {"069500": 5_000_000}
        result = compute_per_asset_budgets(
            policy=AllocationPolicy.EQUAL,
            total_capital=Decimal(100_000_000),
            asset_volatilities={},
            yaml_per_split_amounts=yaml,
            max_split_counts={"069500": 7},
        )
        yaml["069500"] = 999
        assert result["069500"] == 5_000_000

    def test_ignores_volatilities(self):
        # EQUAL 시 sigma 무시 — 빈 dict 도 OK.
        result = compute_per_asset_budgets(
            policy=AllocationPolicy.EQUAL,
            total_capital=Decimal(100_000_000),
            asset_volatilities={},
            yaml_per_split_amounts={"X": 1234},
            max_split_counts={"X": 5},
        )
        assert result == {"X": 1234}


class TestComputePerAssetBudgetsInvVol:
    """INV_VOL 정책 — 변동성 낮은 자산 비중 ↑."""

    def test_low_vol_asset_gets_higher_budget(self):
        # 069500 sigma=0.02 (high), 214980 sigma=0.005 (low — 채권 ETF 모사)
        # weight 069500 = (1/0.02) / (1/0.02 + 1/0.005) = 50/250 = 0.2
        # weight 214980 = (1/0.005) / 250 = 200/250 = 0.8
        # budget 069500 = 100M * 0.2 = 20M / 7 = 2_857_142
        # budget 214980 = 100M * 0.8 = 80M / 7 = 11_428_571
        result = compute_per_asset_budgets(
            policy=AllocationPolicy.INV_VOL,
            total_capital=Decimal(100_000_000),
            asset_volatilities={
                "069500": Decimal("0.02"),
                "214980": Decimal("0.005"),
            },
            yaml_per_split_amounts={"069500": 5_000_000, "214980": 5_000_000},
            max_split_counts={"069500": 7, "214980": 7},
        )
        # 채권 ETF (낮은 sigma) 비중 ↑
        assert result["214980"] > result["069500"]
        # 정확값: 80M // 7 = 11_428_571, 20M // 7 = 2_857_142
        assert result["069500"] == 2_857_142
        assert result["214980"] == 11_428_571

    def test_equal_vol_yields_equal_budgets(self):
        result = compute_per_asset_budgets(
            policy=AllocationPolicy.INV_VOL,
            total_capital=Decimal(100_000_000),
            asset_volatilities={
                "A": Decimal("0.01"), "B": Decimal("0.01"),
            },
            yaml_per_split_amounts={"A": 5_000_000, "B": 5_000_000},
            max_split_counts={"A": 7, "B": 7},
        )
        assert result["A"] == result["B"]
        # 50M each // 7 = 7_142_857
        assert result["A"] == 7_142_857


class TestComputePerAssetBudgetsVol:
    """VOL 정책 — 변동성 높은 자산 비중 ↑ (§6.1 후보 #2 직접 처방)."""

    def test_high_vol_asset_gets_higher_budget(self):
        # 069500 sigma=0.02 (high), 214980 sigma=0.005 (low)
        # weight 069500 = 0.02 / 0.025 = 0.8
        # weight 214980 = 0.005 / 0.025 = 0.2
        # budget 069500 = 80M / 7 = 11_428_571
        # budget 214980 = 20M / 7 = 2_857_142
        result = compute_per_asset_budgets(
            policy=AllocationPolicy.VOL,
            total_capital=Decimal(100_000_000),
            asset_volatilities={
                "069500": Decimal("0.02"),
                "214980": Decimal("0.005"),
            },
            yaml_per_split_amounts={"069500": 5_000_000, "214980": 5_000_000},
            max_split_counts={"069500": 7, "214980": 7},
        )
        # 주식 ETF (높은 sigma) 비중 ↑
        assert result["069500"] > result["214980"]
        assert result["069500"] == 11_428_571
        assert result["214980"] == 2_857_142

    def test_inv_vol_and_vol_are_inverses(self):
        # 두 정책의 weights 가 자산 매핑상 정확히 swap.
        vols = {"A": Decimal("0.02"), "B": Decimal("0.005")}
        yaml = {"A": 5_000_000, "B": 5_000_000}
        max_split = {"A": 7, "B": 7}

        inv = compute_per_asset_budgets(
            AllocationPolicy.INV_VOL, Decimal(100_000_000),
            vols, yaml, max_split,
        )
        vol = compute_per_asset_budgets(
            AllocationPolicy.VOL, Decimal(100_000_000),
            vols, yaml, max_split,
        )
        # INV_VOL 의 A 비중 = VOL 의 B 비중 (swap)
        assert inv["A"] == vol["B"]
        assert inv["B"] == vol["A"]


class TestComputePerAssetBudgetsValidation:
    def test_zero_volatility_inv_vol_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_per_asset_budgets(
                AllocationPolicy.INV_VOL,
                Decimal(100_000_000),
                {"A": Decimal(0)},
                {"A": 5_000_000},
                {"A": 7},
            )

    def test_negative_volatility_raises(self):
        with pytest.raises(ValueError, match="positive"):
            compute_per_asset_budgets(
                AllocationPolicy.VOL,
                Decimal(100_000_000),
                {"A": Decimal(-1)},
                {"A": 5_000_000},
                {"A": 7},
            )

    def test_mismatched_codes_raises(self):
        with pytest.raises(ValueError, match="Asset code sets"):
            compute_per_asset_budgets(
                AllocationPolicy.INV_VOL,
                Decimal(100_000_000),
                {"A": Decimal("0.01")},
                {"A": 5_000_000, "B": 5_000_000},  # B 누락 in vols
                {"A": 7, "B": 7},
            )

    def test_equal_skips_vol_validation(self):
        # EQUAL 시 sigma / max_split 검증 스킵 — yaml 만 있으면 OK.
        result = compute_per_asset_budgets(
            AllocationPolicy.EQUAL,
            Decimal(100_000_000),
            {"A": Decimal(0)},  # 0 sigma 도 EQUAL 시 무시
            {"A": 5_000_000},
            {},  # max_split 빈 dict 도 EQUAL 시 무시
        )
        assert result == {"A": 5_000_000}


class TestComputePerAssetBudgetsBudgetIntegrity:
    """배분 결과의 budget integrity (총합 보존, floor 효과)."""

    def test_sum_of_budgets_does_not_exceed_total(self):
        # int floor 로 인해 sum(per_asset_budget) <= total_capital.
        # per_split_amount 도 budget // max_split (floor) → 더 작아짐.
        result = compute_per_asset_budgets(
            AllocationPolicy.INV_VOL,
            Decimal(100_000_000),
            {"A": Decimal("0.01"), "B": Decimal("0.02"), "C": Decimal("0.005")},
            {"A": 0, "B": 0, "C": 0},
            {"A": 7, "B": 7, "C": 7},
        )
        # per_split * max_split <= per_asset_budget; 합 <= total
        total_estimated = sum(v * 7 for v in result.values())
        assert total_estimated <= 100_000_000
