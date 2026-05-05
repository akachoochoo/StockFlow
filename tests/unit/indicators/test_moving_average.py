"""Unit tests for src.domain.indicators.moving_average."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.indicators.moving_average import calculate_sma


class TestCalculateSma:
    def test_window_5_exact_average(self) -> None:
        closes = [Decimal(c) for c in ("100", "110", "120", "130", "140")]
        assert calculate_sma(closes, 5) == Decimal("120")

    def test_uses_trailing_window_when_more_data(self) -> None:
        # 7 closes, window 3 → average of last 3 = (50+60+70)/3 = 60
        closes = [Decimal(c) for c in ("10", "20", "30", "40", "50", "60", "70")]
        assert calculate_sma(closes, 3) == Decimal("60")

    def test_window_1_returns_last_close(self) -> None:
        closes = [Decimal("100"), Decimal("123")]
        assert calculate_sma(closes, 1) == Decimal("123")

    def test_insufficient_data_returns_none(self) -> None:
        closes = [Decimal("100"), Decimal("110")]
        assert calculate_sma(closes, 5) is None

    def test_empty_closes_returns_none(self) -> None:
        assert calculate_sma([], 5) is None

    def test_decimal_precision_preserved(self) -> None:
        # 1/3 -> repeating decimal, Decimal context (prec=28) preserves
        closes = [Decimal("1"), Decimal("1"), Decimal("1")]
        result = calculate_sma(closes, 3)
        assert result == Decimal("1")

    def test_decimal_division_no_float_drift(self) -> None:
        # 0.1 + 0.2 + 0.3 = 0.6, /3 = 0.2 — float would drift
        closes = [Decimal("0.1"), Decimal("0.2"), Decimal("0.3")]
        assert calculate_sma(closes, 3) == Decimal("0.2")

    def test_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 1"):
            calculate_sma([Decimal("1")], 0)

    def test_negative_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 1"):
            calculate_sma([Decimal("1")], -1)

    def test_exact_window_size_match(self) -> None:
        # len == window → uses all closes
        closes = [Decimal(c) for c in ("10", "20", "30")]
        assert calculate_sma(closes, 3) == Decimal("20")

    def test_phase_0_8_1_ma5_real_values(self) -> None:
        # KODEX 200 sample: 5 closes around 31000
        closes = [Decimal(c) for c in ("30900", "31000", "31100", "31050", "30950")]
        # mean = 155000/5 = 31000
        assert calculate_sma(closes, 5) == Decimal("31000")

    def test_phase_0_8_1_ma20_window(self) -> None:
        # 25 closes, window 20 — uses last 20 (5..24), mean = (5+24)/2 = 14.5
        closes = [Decimal(i) for i in range(25)]
        # last 20 closes: 5, 6, ..., 24 → sum = (5+24)*20/2 = 290
        # 290 / 20 = 14.5
        assert calculate_sma(closes, 20) == Decimal("14.5")
