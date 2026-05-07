"""Unit tests for src.application.reporting.episode (Phase 0.10 — ADR 0006 §5).

Pure function tests for ``detect_drawdown_episodes`` — strategy-agnostic
equity curve drawdown 추출. 합성 curve 사용, 도메인 의존성 zero.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.application.reporting.episode import (
    DrawdownEpisode,
    detect_drawdown_episodes,
)


def _curve(*values: int | str, start: date = date(2024, 1, 1)) -> list[
    tuple[date, Decimal]
]:
    """Convenience — sequential daily equity curve from int/str values."""
    return [
        (start + timedelta(days=i), Decimal(str(v)))
        for i, v in enumerate(values)
    ]


class TestEdgeCases:
    def test_empty_curve_returns_empty(self):
        assert detect_drawdown_episodes([]) == []

    def test_single_point_returns_empty(self):
        assert detect_drawdown_episodes(_curve(100)) == []

    def test_threshold_zero_rejected(self):
        with pytest.raises(ValueError, match="must be negative"):
            detect_drawdown_episodes(_curve(100, 90), threshold_pct=Decimal("0"))

    def test_threshold_positive_rejected(self):
        with pytest.raises(ValueError, match="must be negative"):
            detect_drawdown_episodes(
                _curve(100, 90), threshold_pct=Decimal("5")
            )

    def test_all_increasing_no_episode(self):
        assert detect_drawdown_episodes(_curve(100, 105, 110, 120)) == []

    def test_all_flat_no_episode(self):
        assert detect_drawdown_episodes(_curve(100, 100, 100, 100)) == []


class TestSimpleEpisode:
    def test_simple_recovered_episode(self):
        # 100 → 90 (-10%) → 100 (recovery)
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 100), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.peak_date == date(2024, 1, 1)
        assert ep.peak_value == Decimal("100")
        assert ep.trough_date == date(2024, 1, 2)
        assert ep.trough_value == Decimal("90")
        assert ep.recovery_date == date(2024, 1, 3)
        assert ep.recovered is True
        assert ep.drawdown_pct == Decimal("-10")
        assert ep.duration_days == 2  # peak_date 2024-01-01 → recovery_date 2024-01-03

    def test_simple_unrecovered_episode(self):
        # 100 → 90 → 85 (no recovery)
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 85), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.peak_value == Decimal("100")
        assert ep.trough_value == Decimal("85")
        assert ep.recovery_date is None
        assert ep.recovered is False
        assert ep.drawdown_pct == Decimal("-15")
        assert ep.duration_days == 2  # peak_date → series end (2024-01-03)


class TestThresholdBoundary:
    def test_drawdown_below_threshold_skipped(self):
        # 100 → 96 (-4%, below 5% threshold) → 100 (recovery)
        episodes = detect_drawdown_episodes(
            _curve(100, 96, 100), threshold_pct=Decimal("-5")
        )
        assert episodes == []

    def test_drawdown_at_threshold_included(self):
        # 100 → 95 (-5%, 정확히 threshold) → 100
        episodes = detect_drawdown_episodes(
            _curve(100, 95, 100), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 1
        assert episodes[0].drawdown_pct == Decimal("-5")

    def test_drawdown_just_above_threshold_included(self):
        # 100 → 94 (-6%) → 100
        episodes = detect_drawdown_episodes(
            _curve(100, 94, 100), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 1


class TestMultipleEpisodes:
    def test_two_separate_episodes(self):
        # Episode 1: 100 → 90 (-10%) → 100
        # Episode 2: 110 → 99 (-10%) → 110
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 100, 110, 99, 110), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 2
        assert episodes[0].peak_value == Decimal("100")
        assert episodes[0].recovered is True
        assert episodes[1].peak_value == Decimal("110")
        assert episodes[1].recovered is True

    def test_episode_continues_through_partial_recovery(self):
        # 100 → 90 (-10%, episode start) → 95 (-5%, partial) → 80 (trough) → 100 (recovery)
        # Episode count = 1 (single episode, trough updated)
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 95, 80, 100), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.peak_value == Decimal("100")
        assert ep.trough_value == Decimal("80")
        assert ep.trough_date == date(2024, 1, 4)
        assert ep.recovered is True

    def test_recovered_then_unrecovered_final(self):
        # Episode 1: 100 → 90 → 100 (recovered)
        # Episode 2: 110 → 90 (-18%) — no recovery
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 100, 110, 90), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 2
        assert episodes[0].recovered is True
        assert episodes[1].recovered is False
        assert episodes[1].peak_value == Decimal("110")


class TestPeakUpdate:
    def test_new_high_updates_peak_after_recovery(self):
        # 100 → 90 → 100 (recovery to original peak) → 110 (new high)
        # Then 110 → 99 → episode from new peak 110
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 100, 110, 99, 110), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 2
        assert episodes[1].peak_value == Decimal("110")

    def test_recovery_above_peak_creates_higher_peak(self):
        # 100 → 90 → 105 (recovery + new high) — recovery at first hit of >= peak
        # Day 3 value 105 >= peak 100 → recovery_date = day 3, peak then 105
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 105), threshold_pct=Decimal("-5")
        )
        assert len(episodes) == 1
        assert episodes[0].recovered is True
        assert episodes[0].recovery_date == date(2024, 1, 3)


class TestDrawdownPctCalculation:
    def test_drawdown_pct_negative(self):
        # 200 → 150 = -25%
        episodes = detect_drawdown_episodes(
            _curve(200, 150, 200), threshold_pct=Decimal("-5")
        )
        assert episodes[0].drawdown_pct == Decimal("-25")

    def test_drawdown_pct_decimal_precision(self):
        # 100 → 87.5 = -12.5%
        episodes = detect_drawdown_episodes(
            [(date(2024, 1, 1), Decimal("100")),
             (date(2024, 1, 2), Decimal("87.5")),
             (date(2024, 1, 3), Decimal("100"))],
            threshold_pct=Decimal("-5"),
        )
        assert episodes[0].drawdown_pct == Decimal("-12.5")


class TestAssetCodeScope:
    def test_asset_code_default_none(self):
        episodes = detect_drawdown_episodes(_curve(100, 90, 100))
        assert episodes[0].asset_code is None

    def test_asset_code_passed_through(self):
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 100), asset_code="005930"
        )
        assert episodes[0].asset_code == "005930"


class TestRealisticScenarios:
    def test_phase_0_9_2_unrecovered_pattern(self):
        # Phase 0.9.2 풍 시나리오: peak 후 -22% → -37% (큰 폭 unrecovered)
        episodes = detect_drawdown_episodes(
            _curve(100, 90, 80, 78, 65, 63, 70),
            threshold_pct=Decimal("-5"),
        )
        # Single unrecovered episode (never hits >= 100)
        assert len(episodes) == 1
        assert episodes[0].recovered is False
        assert episodes[0].trough_value == Decimal("63")

    def test_default_threshold_minus_5(self):
        # default threshold = -5% verified
        episodes_default = detect_drawdown_episodes(_curve(100, 95, 100))
        episodes_explicit = detect_drawdown_episodes(
            _curve(100, 95, 100), threshold_pct=Decimal("-5")
        )
        assert episodes_default == episodes_explicit


class TestReturnType:
    def test_returns_list_of_dataclass(self):
        episodes = detect_drawdown_episodes(_curve(100, 90, 100))
        assert all(isinstance(ep, DrawdownEpisode) for ep in episodes)

    def test_dataclass_is_frozen(self):
        episodes = detect_drawdown_episodes(_curve(100, 90, 100))
        try:
            episodes[0].peak_value = Decimal("999")  # type: ignore[misc]
        except (AttributeError, Exception):
            return
        raise AssertionError("DrawdownEpisode should be frozen")
