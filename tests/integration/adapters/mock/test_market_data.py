"""Tests for src.adapters.mock.market_data.MockMarketData."""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from src.adapters.mock.market_data import MockMarketData
from src.domain.constants import KST
from src.domain.exceptions import MarketDataUnavailableError
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
)


def _asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


def _bar(asset: Asset, trade_date: date, close: str = "35000") -> OHLCV:
    return OHLCV(
        asset=asset,
        trade_date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1000000"),
    )


def _kst_close_utc(d: date) -> datetime:
    return datetime.combine(d, time(15, 30), tzinfo=KST).astimezone(UTC)


def _kst_morning_utc(d: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute), tzinfo=KST).astimezone(UTC)


# ---------------------------------------------------------------------------
# get_price
# ---------------------------------------------------------------------------
class TestGetPrice:
    def test_returns_close_of_most_recent_available_bar(self):
        a = _asset()
        bars = [
            _bar(a, date(2026, 4, 28), close="35000"),
            _bar(a, date(2026, 4, 29), close="35500"),
        ]
        md = MockMarketData(ohlcv_by_asset={a: bars})
        # After 4/29 close (16:00 KST = 07:00 UTC) → 4/29's close available
        as_of = _kst_morning_utc(date(2026, 4, 29), hour=16)
        price = md.get_price(a, as_of)
        assert price.value == Decimal("35500")
        assert price.timestamp == as_of

    def test_returns_yesterday_close_during_today_session(self):
        # During 4/30 session (09:00-15:30 KST), 4/30 bar not yet available.
        # Should return 4/29's close.
        a = _asset()
        bars = [
            _bar(a, date(2026, 4, 29), close="35500"),
            _bar(a, date(2026, 4, 30), close="36000"),
        ]
        md = MockMarketData(ohlcv_by_asset={a: bars})
        as_of = _kst_morning_utc(date(2026, 4, 30), hour=10)  # mid-session
        price = md.get_price(a, as_of)
        assert price.value == Decimal("35500")

    def test_no_bars_for_asset_raises(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={})
        with pytest.raises(MarketDataUnavailableError, match="no OHLCV"):
            md.get_price(a, _kst_morning_utc(date(2026, 4, 30)))

    def test_as_of_before_any_bar_raises(self):
        a = _asset()
        bars = [_bar(a, date(2026, 4, 29), close="35500")]
        md = MockMarketData(ohlcv_by_asset={a: bars})
        # Asking on 4/27 — first bar is 4/29 → unavailable
        as_of = _kst_morning_utc(date(2026, 4, 27))
        with pytest.raises(MarketDataUnavailableError):
            md.get_price(a, as_of)

    def test_construction_rejects_asset_mismatch(self):
        a = _asset(code="069500")
        b = _asset(code="105190")
        with pytest.raises(ValueError, match=r"OHLCV\.asset"):
            MockMarketData(ohlcv_by_asset={a: [_bar(b, date(2026, 4, 29))]})


# ---------------------------------------------------------------------------
# get_ohlcv
# ---------------------------------------------------------------------------
class TestGetOhlcv:
    def test_filters_by_date_range(self):
        a = _asset()
        bars = [
            _bar(a, date(2026, 4, 27)),
            _bar(a, date(2026, 4, 28)),
            _bar(a, date(2026, 4, 29)),
            _bar(a, date(2026, 4, 30)),
        ]
        md = MockMarketData(ohlcv_by_asset={a: bars})
        result = md.get_ohlcv(a, date(2026, 4, 28), date(2026, 4, 29))
        assert [b.trade_date for b in result] == [
            date(2026, 4, 28),
            date(2026, 4, 29),
        ]

    def test_inclusive_bounds(self):
        a = _asset()
        bars = [_bar(a, date(2026, 4, 29))]
        md = MockMarketData(ohlcv_by_asset={a: bars})
        result = md.get_ohlcv(a, date(2026, 4, 29), date(2026, 4, 29))
        assert len(result) == 1

    def test_empty_when_asset_missing(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={})
        assert md.get_ohlcv(a, date(2026, 4, 1), date(2026, 4, 30)) == []

    def test_start_after_end_rejected(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        with pytest.raises(ValueError, match="start"):
            md.get_ohlcv(a, date(2026, 4, 30), date(2026, 4, 1))

    def test_returns_sorted_by_date(self):
        a = _asset()
        bars = [
            _bar(a, date(2026, 4, 29)),
            _bar(a, date(2026, 4, 27)),
            _bar(a, date(2026, 4, 28)),
        ]
        md = MockMarketData(ohlcv_by_asset={a: bars})
        result = md.get_ohlcv(a, date(2026, 4, 1), date(2026, 4, 30))
        assert [b.trade_date for b in result] == [
            date(2026, 4, 27),
            date(2026, 4, 28),
            date(2026, 4, 29),
        ]


# ---------------------------------------------------------------------------
# is_market_open
# ---------------------------------------------------------------------------
class TestIsMarketOpen:
    def test_open_at_09_00_kst_weekday(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        # Thursday 2026-04-30 09:00 KST
        as_of = datetime(2026, 4, 30, 9, 0, tzinfo=KST).astimezone(UTC)
        assert md.is_market_open(a, as_of) is True

    def test_closed_at_08_59_kst_weekday(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 4, 30, 8, 59, tzinfo=KST).astimezone(UTC)
        assert md.is_market_open(a, as_of) is False

    def test_open_at_15_30_kst_weekday(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 4, 30, 15, 30, tzinfo=KST).astimezone(UTC)
        assert md.is_market_open(a, as_of) is True

    def test_closed_at_15_31_kst_weekday(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 4, 30, 15, 31, tzinfo=KST).astimezone(UTC)
        assert md.is_market_open(a, as_of) is False

    def test_closed_on_saturday(self):
        # 2026-05-02 is Saturday
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 5, 2, 10, 0, tzinfo=KST).astimezone(UTC)
        assert as_of.astimezone(KST).weekday() == 5
        assert md.is_market_open(a, as_of) is False

    def test_closed_on_sunday(self):
        # 2026-05-03 is Sunday
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 5, 3, 10, 0, tzinfo=KST).astimezone(UTC)
        assert md.is_market_open(a, as_of) is False

    def test_closed_on_explicit_holiday(self):
        a = _asset()
        md = MockMarketData(
            ohlcv_by_asset={a: []},
            explicit_holidays=frozenset({date(2026, 5, 5)}),  # Children's Day
        )
        # 2026-05-05 is a Tuesday, but a Korean holiday
        as_of = datetime(2026, 5, 5, 10, 0, tzinfo=KST).astimezone(UTC)
        assert md.is_market_open(a, as_of) is False


# ---------------------------------------------------------------------------
# next_market_close
# ---------------------------------------------------------------------------
class TestNextMarketClose:
    def test_returns_today_close_if_before_close_on_weekday(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 4, 30, 10, 0, tzinfo=KST).astimezone(UTC)
        result = md.next_market_close(a, as_of)
        assert result == _kst_close_utc(date(2026, 4, 30))

    def test_returns_today_close_at_exactly_close_time(self):
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = _kst_close_utc(date(2026, 4, 30))
        result = md.next_market_close(a, as_of)
        assert result == _kst_close_utc(date(2026, 4, 30))

    def test_returns_next_day_close_after_close_time(self):
        # Thursday 2026-04-30 16:00 KST → next close is Friday 5/1
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 4, 30, 16, 0, tzinfo=KST).astimezone(UTC)
        result = md.next_market_close(a, as_of)
        assert result == _kst_close_utc(date(2026, 5, 1))

    def test_skips_weekend(self):
        # Friday 2026-05-01 16:00 KST → next close is Monday 5/4
        a = _asset()
        md = MockMarketData(ohlcv_by_asset={a: []})
        as_of = datetime(2026, 5, 1, 16, 0, tzinfo=KST).astimezone(UTC)
        result = md.next_market_close(a, as_of)
        assert result == _kst_close_utc(date(2026, 5, 4))

    def test_skips_explicit_holiday(self):
        a = _asset()
        md = MockMarketData(
            ohlcv_by_asset={a: []},
            explicit_holidays=frozenset({date(2026, 5, 5)}),
        )
        # Monday 2026-05-04 16:00 KST → 5/5 is holiday → next close 5/6
        as_of = datetime(2026, 5, 4, 16, 0, tzinfo=KST).astimezone(UTC)
        result = md.next_market_close(a, as_of)
        assert result == _kst_close_utc(date(2026, 5, 6))

    def test_skips_today_when_today_is_holiday(self):
        a = _asset()
        md = MockMarketData(
            ohlcv_by_asset={a: []},
            explicit_holidays=frozenset({date(2026, 5, 5)}),
        )
        # Tuesday 2026-05-05 10:00 KST (it's a holiday)
        as_of = datetime(2026, 5, 5, 10, 0, tzinfo=KST).astimezone(UTC)
        result = md.next_market_close(a, as_of)
        assert result == _kst_close_utc(date(2026, 5, 6))
