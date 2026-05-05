"""Unit tests for src.domain.indicators.recent_high."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.indicators.recent_high import find_recent_high


class TestFindRecentHigh:
    def test_returns_max_of_window(self) -> None:
        closes = [Decimal(c) for c in ("100", "110", "120", "115", "105")]
        assert find_recent_high(closes, 5) == Decimal("120")

    def test_uses_trailing_window_when_more_data(self) -> None:
        # 7 closes, window 3 → max of last 3 = max(50, 60, 55) = 60
        closes = [Decimal(c) for c in ("10", "200", "30", "40", "50", "60", "55")]
        assert find_recent_high(closes, 3) == Decimal("60")

    def test_window_1_returns_last_close(self) -> None:
        closes = [Decimal("100"), Decimal("88")]
        assert find_recent_high(closes, 1) == Decimal("88")

    def test_insufficient_data_returns_none(self) -> None:
        closes = [Decimal("100"), Decimal("110")]
        assert find_recent_high(closes, 60) is None

    def test_empty_closes_returns_none(self) -> None:
        assert find_recent_high([], 60) is None

    def test_exact_window_size_match(self) -> None:
        closes = [Decimal(c) for c in ("10", "30", "20")]
        assert find_recent_high(closes, 3) == Decimal("30")

    def test_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 1"):
            find_recent_high([Decimal("1")], 0)

    def test_negative_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 1"):
            find_recent_high([Decimal("1")], -1)

    def test_all_equal_returns_value(self) -> None:
        closes = [Decimal("100")] * 10
        assert find_recent_high(closes, 10) == Decimal("100")

    def test_decreasing_series_max_is_first_in_window(self) -> None:
        # 60-day max — slot 5 simplification (ADR §2.2.1)
        closes = [Decimal(100 - i) for i in range(60)]
        # last 60: 100, 99, ..., 41 → max = 100
        assert find_recent_high(closes, 60) == Decimal("100")

    def test_max_outside_window_excluded(self) -> None:
        # spike at index 0, window 5 → max excludes the spike
        closes = [Decimal("9999")] + [Decimal(i) for i in (10, 20, 30, 40, 50)]
        assert find_recent_high(closes, 5) == Decimal("50")

    def test_phase_0_8_1_recent_high_60_pattern(self) -> None:
        # 60 closes, oscillating, max within window
        closes = [Decimal(c) for c in ("30000",) * 30 + ("31500",) + ("30000",) * 29]
        assert find_recent_high(closes, 60) == Decimal("31500")
