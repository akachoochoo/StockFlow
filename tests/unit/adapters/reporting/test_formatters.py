"""Unit tests for src.adapters.reporting.formatters (Phase 0.10.h)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timezone
from decimal import Decimal

import pytest

from src.adapters.reporting.formatters import (
    format_date,
    format_datetime_kst,
    format_money,
    format_pct,
    format_price,
    format_quantity,
)


class TestFormatMoney:
    def test_krw_integer(self):
        assert format_money(Decimal("102506200")) == "₩102,506,200"

    def test_krw_thousand_separator(self):
        assert format_money(Decimal("1000")) == "₩1,000"

    def test_krw_zero(self):
        assert format_money(Decimal("0")) == "₩0"

    def test_krw_negative(self):
        assert format_money(Decimal("-5000")) == "-₩5,000"

    def test_krw_rounds_half_up(self):
        # KRW = integer; .5 rounds up
        assert format_money(Decimal("100.5")) == "₩101"
        assert format_money(Decimal("-100.5")) == "-₩101"

    def test_krw_truncates_long_decimal(self):
        # 26-digit Decimal should not appear in output
        assert format_money(Decimal("1234.56789012345678901234")) == "₩1,235"

    def test_usd_two_decimals(self):
        assert format_money(Decimal("1234.5"), "USD") == "USD 1,234.50"

    def test_usd_negative(self):
        assert format_money(Decimal("-12.345"), "USD") == "-USD 12.35"


class TestFormatPct:
    def test_default_two_places_signed(self):
        assert format_pct(Decimal("11.11111111111111111")) == "+11.11%"

    def test_negative_signed(self):
        assert format_pct(Decimal("-37.6516")) == "-37.65%"

    def test_zero_signed(self):
        # +0.00% (signed=True default)
        assert format_pct(Decimal("0")) == "+0.00%"

    def test_unsigned(self):
        assert format_pct(Decimal("11.111"), signed=False) == "11.11%"

    def test_zero_places(self):
        assert format_pct(Decimal("11.6"), places=0) == "+12%"

    def test_four_places(self):
        assert format_pct(Decimal("-37.6516"), places=4) == "-37.6516%"

    def test_truncates_long_decimal(self):
        long = Decimal("11.11111111111111111111111111")
        assert format_pct(long) == "+11.11%"

    def test_rounds_half_up(self):
        assert format_pct(Decimal("11.115")) == "+11.12%"


class TestFormatPrice:
    def test_krw_integer(self):
        assert format_price(Decimal("37900")) == "₩37,900"

    def test_krw_rounds_long_decimal(self):
        assert format_price(Decimal("37947.64529058116232")) == "₩37,948"

    def test_usd_two_decimals(self):
        assert format_price(Decimal("123.456"), "USD") == "USD 123.46"


class TestFormatQuantity:
    def test_integer(self):
        assert format_quantity(Decimal("131")) == "131"

    def test_integer_thousand_separator(self):
        assert format_quantity(Decimal("12345")) == "12,345"

    def test_fractional(self):
        assert format_quantity(Decimal("1.5")) == "1.50"

    def test_fractional_truncates(self):
        assert format_quantity(Decimal("1.234567")) == "1.23"

    def test_zero(self):
        assert format_quantity(Decimal("0")) == "0"


class TestFormatDate:
    def test_iso(self):
        assert format_date(date(2020, 2, 12)) == "2020-02-12"


class TestFormatDatetimeKst:
    def test_utc_midnight_shows_date_only(self):
        # UTC midnight = "그 날짜" (일봉) — no time, no tz
        dt = datetime(2020, 2, 12, 0, 0, 0, tzinfo=UTC)
        # 2020-02-12 = 수요일 (Wed)
        assert format_datetime_kst(dt) == "2020-02-12 (수)"

    def test_naive_treated_as_utc(self):
        dt = datetime(2020, 2, 12, 0, 0, 0)  # naive
        assert format_datetime_kst(dt) == "2020-02-12 (수)"

    def test_intraday_converts_to_kst(self):
        # 2020-02-12T00:30:00 UTC = 09:30 KST same day
        dt = datetime(2020, 2, 12, 0, 30, 0, tzinfo=UTC)
        assert format_datetime_kst(dt) == "2020-02-12 09:30 KST (수)"

    def test_intraday_crossing_date_boundary(self):
        # 2020-02-12T16:00:00 UTC = 01:00 KST 2020-02-13 (목)
        dt = datetime(2020, 2, 12, 16, 0, 0, tzinfo=UTC)
        assert format_datetime_kst(dt) == "2020-02-13 01:00 KST (목)"

    def test_thursday_korean_weekday(self):
        # 2020-02-13 = 목요일
        dt = datetime(2020, 2, 13, 0, 0, 0, tzinfo=UTC)
        assert format_datetime_kst(dt) == "2020-02-13 (목)"

    def test_non_utc_tz_normalized(self):
        # +09:00 09:00 = UTC midnight = "그 날짜"
        kst_tz = timezone(__import__("datetime").timedelta(hours=9))
        dt = datetime(2020, 2, 12, 9, 0, 0, tzinfo=kst_tz)
        assert format_datetime_kst(dt) == "2020-02-12 (수)"


class TestEdgeCases:
    def test_format_money_very_large(self):
        assert format_money(Decimal("1000000000000")) == "₩1,000,000,000,000"

    def test_format_pct_negative_places_raises(self):
        # negative places — caller responsibility; Python format spec rejects.
        with pytest.raises(ValueError):
            format_pct(Decimal("1"), places=-1)
