"""Unit tests for src.adapters.kis.market_data — KISMarketData (Stage 2.3).

Uses a fake ``KISClient`` — **zero real network**. ``as_of`` is always injected
(datetime.now() 미사용 검증).

Coverage:
- get_price: stck_prpr → Price.value (Decimal), timestamp=as_of.
- get_ohlcv: single-page mapping + ascending sort.
- get_ohlcv: 100-bar pagination (2 windows → merged, de-duplicated, sorted).
- get_ohlcv: start > end → ValueError.
- get_ohlcv: empty range → [].
- get_ohlcv: OHLCV integrity violation (high < low) → DataIntegrityError.
- is_market_open: 장중 / 장외 / 주말 / explicit_holiday.
- next_market_close: 당일 마감 전 / 당일 마감 후 / 주말 다음 영업일.
- datetime.now() 미사용 확인 (as_of 주입만).
- kis_marketdata_port_signature: 4 메서드 전부 존재.
- kis_decimal_only: Price.value + OHLCV 필드 Decimal 전용.

Function names carry ``kis_market_data_`` (Stage gate selector).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.adapters.kis._client import KISApiError
from src.adapters.kis.config import KISConfig, TradingMode
from src.adapters.kis.market_data import KISMarketData
from src.domain.constants import KST
from src.domain.exceptions import DataIntegrityError, MarketDataUnavailableError
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="삼성전자",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2000, 1, 4),
    )


# Fixed UTC instants (KST = UTC+9).
# 2026-05-22 10:00 KST = 2026-05-22 01:00 UTC → 장중
_DURING_SESSION = datetime(2026, 5, 22, 1, 0, 0, tzinfo=UTC)
# 2026-05-22 07:00 UTC = 2026-05-22 16:00 KST → 장 마감 후
_AFTER_SESSION = datetime(2026, 5, 22, 7, 0, 0, tzinfo=UTC)
# 2026-05-23 is Saturday UTC+9
_SATURDAY_KST = datetime(2026, 5, 22, 21, 0, 0, tzinfo=UTC)  # 2026-05-23 06:00 KST (Sat)
# 2026-05-25 is Monday
_MONDAY_BEFORE_OPEN = datetime(2026, 5, 24, 22, 0, 0, tzinfo=UTC)  # 2026-05-25 07:00 KST


# ---------------------------------------------------------------------------
# Fake KISClient
# ---------------------------------------------------------------------------
class _FakeKISClient:
    """Returns queued bodies for successive request() calls."""

    def __init__(self, bodies: list[dict[str, object]]) -> None:
        self._bodies = list(bodies)
        self._config = KISConfig(
            mode=TradingMode.PAPER,
            base_url="https://openapivts.koreainvestment.com:29443",
            appkey="PKabcdefghijklmnop",
            appsecret="SECRETsecret==",
            cano="50012345",
            acnt_prdt_cd="01",
        )
        self.calls: list[dict[str, object]] = []

    @property
    def config(self) -> KISConfig:
        return self._config

    def request(
        self,
        method: str,
        path: str,
        *,
        tr_id: str,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        tr_cont: str = "",
    ) -> dict[str, object]:
        self.calls.append({"method": method, "path": path, "tr_id": tr_id, "params": params})
        if not self._bodies:
            raise KISApiError("no more canned bodies")
        return self._bodies.pop(0)


# ---------------------------------------------------------------------------
# Wire body builders (all numeric fields as strings — KIS 전부 string)
# ---------------------------------------------------------------------------
_ENVELOPE = {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리"}


def _price_body(stck_prpr: str = "75000") -> dict[str, object]:
    return {
        **_ENVELOPE,
        "output": {
            "stck_prpr": stck_prpr,
            "stck_oprc": "74000",
            "stck_hgpr": "76000",
            "stck_lwpr": "73500",
            "acml_vol": "8500000",
            "stck_sdpr": "74500",
            "prdy_vrss": "500",
            "prdy_ctrt": "0.67",
        },
    }


def _daily_body(items: list[dict[str, str]]) -> dict[str, object]:
    return {
        **_ENVELOPE,
        "output1": {},
        "output2": items,
    }


def _daily_item(
    date_str: str,
    *,
    oprc: str = "74000",
    hgpr: str = "76000",
    lwpr: str = "73000",
    clpr: str = "75000",
    vol: str = "8500000",
) -> dict[str, str]:
    """Build a KIS daily bar wire dict.

    Defaults: open=74000, high=76000, low=73000, close=75000 — all within
    [low, high], satisfying the OHLCV model invariant (low <= open/close <= high).
    """
    return {
        "stck_bsop_date": date_str,
        "stck_oprc": oprc,
        "stck_hgpr": hgpr,
        "stck_lwpr": lwpr,
        "stck_clpr": clpr,
        "acml_vol": vol,
    }


# ---------------------------------------------------------------------------
# get_price
# ---------------------------------------------------------------------------
class TestKisMarketDataGetPrice:
    def test_kis_market_data_get_price_maps_stck_prpr_to_value(self) -> None:
        client = _FakeKISClient([_price_body("75000")])
        md = KISMarketData(client=client)
        price = md.get_price(_asset(), _DURING_SESSION)
        assert price.value == Decimal("75000")

    def test_kis_market_data_get_price_timestamp_equals_as_of(self) -> None:
        """as_of 주입: Price.timestamp must equal the injected as_of (not now)."""
        client = _FakeKISClient([_price_body("75000")])
        md = KISMarketData(client=client)
        price = md.get_price(_asset(), _DURING_SESSION)
        assert price.timestamp == _DURING_SESSION

    def test_kis_market_data_get_price_asset_matches(self) -> None:
        asset = _asset("005930")
        client = _FakeKISClient([_price_body("80000")])
        md = KISMarketData(client=client)
        price = md.get_price(asset, _DURING_SESSION)
        assert price.asset == asset

    def test_kis_market_data_get_price_uses_fhkst_tr_id(self) -> None:
        client = _FakeKISClient([_price_body()])
        md = KISMarketData(client=client)
        md.get_price(_asset(), _DURING_SESSION)
        assert client.calls[0]["tr_id"] == "FHKST01010100"

    def test_kis_market_data_get_price_invalid_zero_price_raises_unavailable(self) -> None:
        """stck_prpr = 0 → Price model rejects (value > 0) → MarketDataUnavailableError."""
        client = _FakeKISClient([_price_body("0")])
        md = KISMarketData(client=client)
        with pytest.raises(MarketDataUnavailableError):
            md.get_price(_asset(), _DURING_SESSION)


# ---------------------------------------------------------------------------
# get_price — Decimal invariant
# ---------------------------------------------------------------------------
class TestKisMarketDataDecimalOnly:
    def test_kis_decimal_only_price_value_is_decimal(self) -> None:
        """CLAUDE.md §2: Price.value must be Decimal, never float."""
        client = _FakeKISClient([_price_body("75000")])
        md = KISMarketData(client=client)
        price = md.get_price(_asset(), _DURING_SESSION)
        assert isinstance(price.value, Decimal)
        assert not isinstance(price.value, float)

    def test_kis_decimal_only_ohlcv_fields_are_decimal(self) -> None:
        items = [_daily_item("20260522")]
        client = _FakeKISClient([_daily_body(items)])
        md = KISMarketData(client=client)
        bars = md.get_ohlcv(_asset(), date(2026, 5, 22), date(2026, 5, 22))
        assert len(bars) == 1
        bar = bars[0]
        for field_val in (bar.open, bar.high, bar.low, bar.close, bar.volume):
            assert isinstance(field_val, Decimal)
            assert not isinstance(field_val, float)


# ---------------------------------------------------------------------------
# get_ohlcv — single page
# ---------------------------------------------------------------------------
class TestKisMarketDataGetOhlcvSinglePage:
    def test_kis_market_data_ohlcv_single_page_mapping(self) -> None:
        items = [
            _daily_item("20260522", oprc="74000", hgpr="76000", lwpr="73500", clpr="75000", vol="8500000"),
        ]
        client = _FakeKISClient([_daily_body(items)])
        md = KISMarketData(client=client)
        bars = md.get_ohlcv(_asset(), date(2026, 5, 22), date(2026, 5, 22))
        assert len(bars) == 1
        bar = bars[0]
        assert bar.trade_date == date(2026, 5, 22)
        assert bar.open == Decimal("74000")
        assert bar.high == Decimal("76000")
        assert bar.low == Decimal("73500")
        assert bar.close == Decimal("75000")
        assert bar.volume == Decimal("8500000")

    def test_kis_market_data_ohlcv_ascending_sort(self) -> None:
        """KIS returns descending; we must return ascending."""
        # Each close must be within [low=73000, high=76000] (default range).
        items = [
            _daily_item("20260522", clpr="75000"),
            _daily_item("20260521", clpr="74000"),
            _daily_item("20260520", clpr="73500"),
        ]
        client = _FakeKISClient([_daily_body(items)])
        md = KISMarketData(client=client)
        bars = md.get_ohlcv(_asset(), date(2026, 5, 20), date(2026, 5, 22))
        dates = [b.trade_date for b in bars]
        assert dates == sorted(dates)

    def test_kis_market_data_ohlcv_empty_range_returns_empty_list(self) -> None:
        # Return a body with no output2 items (within valid date range but no bars).
        client = _FakeKISClient([_daily_body([])])
        md = KISMarketData(client=client)
        bars = md.get_ohlcv(_asset(), date(2026, 5, 20), date(2026, 5, 22))
        assert bars == []

    def test_kis_market_data_ohlcv_start_greater_than_end_raises_value_error(self) -> None:
        client = _FakeKISClient([])
        md = KISMarketData(client=client)
        with pytest.raises(ValueError, match="start"):
            md.get_ohlcv(_asset(), date(2026, 5, 22), date(2026, 5, 20))

    def test_kis_market_data_ohlcv_uses_fhkst_tr_id(self) -> None:
        client = _FakeKISClient([_daily_body([])])
        md = KISMarketData(client=client)
        md.get_ohlcv(_asset(), date(2026, 5, 20), date(2026, 5, 22))
        assert client.calls[0]["tr_id"] == "FHKST03010100"

    def test_kis_market_data_ohlcv_skips_zero_close_filler_rows(self) -> None:
        """KIS pads with all-zero rows on non-trading days; skip them."""
        items = [
            _daily_item("20260522", clpr="75000"),
            # All-zero filler row (non-trading day): clpr=0 triggers the skip guard.
            # Use matching zeros for all OHLC so the row is consistently filtered
            # before reaching the OHLCV model's invariant checks.
            {
                "stck_bsop_date": "20260521",
                "stck_oprc": "0",
                "stck_hgpr": "0",
                "stck_lwpr": "0",
                "stck_clpr": "0",
                "acml_vol": "0",
            },
        ]
        client = _FakeKISClient([_daily_body(items)])
        md = KISMarketData(client=client)
        # Range = [2026-05-22, 2026-05-22]: filler row is outside range anyway,
        # and earliest valid bar (2026-05-22) == start → single HTTP call.
        bars = md.get_ohlcv(_asset(), date(2026, 5, 22), date(2026, 5, 22))
        assert len(bars) == 1
        assert bars[0].trade_date == date(2026, 5, 22)


# ---------------------------------------------------------------------------
# get_ohlcv — pagination (100-bar window)
# ---------------------------------------------------------------------------
class TestKisMarketDataGetOhlcvPagination:
    def test_kis_market_data_ohlcv_pagination_two_windows_merged(self) -> None:
        """Simulate a range wider than one page.

        Window 1: end=2026-05-22, returns bars 2026-05-12 .. 2026-05-22 (11 bars).
          Earliest = 2026-05-12 > start=2026-05-01 → continue.
          Next window_end = 2026-05-11.
        Window 2: end=2026-05-11, returns bars 2026-05-01 .. 2026-05-11 (11 bars).
          Earliest = 2026-05-01 <= start → stop.
        Total merged = 22 bars, sorted ascending.
        """
        # Build window 1: 11 bars descending (2026-05-22 .. 2026-05-12).
        # clpr must be within [low=73000, high=76000] default range.
        page1_items = [
            _daily_item(f"202605{d:02d}", clpr="74500")
            for d in range(22, 11, -1)  # 22,21,...,12
        ]
        # Build window 2: 11 bars descending (2026-05-11 .. 2026-05-01).
        page2_items = [
            _daily_item(f"202605{d:02d}", clpr="74500")
            for d in range(11, 0, -1)  # 11,10,...,1
        ]

        client = _FakeKISClient([_daily_body(page1_items), _daily_body(page2_items)])
        md = KISMarketData(client=client)
        bars = md.get_ohlcv(_asset(), date(2026, 5, 1), date(2026, 5, 22))

        assert len(bars) == 22
        # Two HTTP calls were made (two windows)
        assert len(client.calls) == 2
        # Ascending order
        dates = [b.trade_date for b in bars]
        assert dates == sorted(dates)
        # First and last
        assert bars[0].trade_date == date(2026, 5, 1)
        assert bars[-1].trade_date == date(2026, 5, 22)

    def test_kis_market_data_ohlcv_pagination_deduplicates_overlapping_bars(self) -> None:
        """If both windows return the same date, it should appear only once."""
        page1 = [_daily_item("20260522", clpr="75000"), _daily_item("20260521", clpr="74000")]
        page2 = [_daily_item("20260521", clpr="74000")]  # duplicate
        client = _FakeKISClient([_daily_body(page1), _daily_body(page2)])
        md = KISMarketData(client=client)
        bars = md.get_ohlcv(_asset(), date(2026, 5, 21), date(2026, 5, 22))
        dates = [b.trade_date for b in bars]
        assert len(dates) == len(set(dates)), "duplicate trade_dates found"

    def test_kis_market_data_ohlcv_single_page_when_earliest_reaches_start(self) -> None:
        """When earliest bar == start, stop after 1 call."""
        items = [
            _daily_item("20260522", clpr="75000"),
            _daily_item("20260521", clpr="74000"),
            _daily_item("20260520", clpr="73500"),
        ]
        client = _FakeKISClient([_daily_body(items)])
        md = KISMarketData(client=client)
        bars = md.get_ohlcv(_asset(), date(2026, 5, 20), date(2026, 5, 22))
        assert len(client.calls) == 1
        assert len(bars) == 3


# ---------------------------------------------------------------------------
# get_ohlcv — integrity violation
# ---------------------------------------------------------------------------
class TestKisMarketDataOhlcvIntegrity:
    def test_kis_market_data_ohlcv_high_lt_low_raises_data_integrity_error(self) -> None:
        """high < low violates OHLCV model invariant → DataIntegrityError."""
        bad_item = _daily_item("20260522", oprc="74000", hgpr="73000", lwpr="75000", clpr="74000")
        client = _FakeKISClient([_daily_body([bad_item])])
        md = KISMarketData(client=client)
        with pytest.raises(DataIntegrityError):
            md.get_ohlcv(_asset(), date(2026, 5, 22), date(2026, 5, 22))


# ---------------------------------------------------------------------------
# is_market_open
# ---------------------------------------------------------------------------
class TestKisMarketDataIsMarketOpen:
    def test_kis_market_data_is_market_open_during_session(self) -> None:
        """2026-05-22 10:00 KST (01:00 UTC) is a Friday → open."""
        md = KISMarketData(client=_FakeKISClient([]))
        assert md.is_market_open(_asset(), _DURING_SESSION) is True

    def test_kis_market_data_is_market_open_after_session(self) -> None:
        """2026-05-22 16:00 KST (07:00 UTC) → closed."""
        md = KISMarketData(client=_FakeKISClient([]))
        assert md.is_market_open(_asset(), _AFTER_SESSION) is False

    def test_kis_market_data_is_market_open_saturday(self) -> None:
        """Weekend → closed."""
        # 2026-05-23 06:00 KST = 2026-05-22 21:00 UTC (Saturday in KST)
        sat = datetime(2026, 5, 22, 21, 0, 0, tzinfo=UTC)
        local = sat.astimezone(KST)
        assert local.weekday() == 5  # Saturday
        md = KISMarketData(client=_FakeKISClient([]))
        assert md.is_market_open(_asset(), sat) is False

    def test_kis_market_data_is_market_open_explicit_holiday(self) -> None:
        """An explicit_holiday weekday → closed."""
        # _DURING_SESSION is 2026-05-22 10:00 KST (Friday, normally open)
        holiday_date = _DURING_SESSION.astimezone(KST).date()
        md = KISMarketData(
            client=_FakeKISClient([]),
            explicit_holidays=frozenset([holiday_date]),
        )
        assert md.is_market_open(_asset(), _DURING_SESSION) is False

    def test_kis_market_data_is_market_open_at_open_boundary(self) -> None:
        """09:00:00 KST exactly → open."""
        open_utc = datetime(2026, 5, 22, 0, 0, 0, tzinfo=UTC)  # 09:00 KST
        md = KISMarketData(client=_FakeKISClient([]))
        assert md.is_market_open(_asset(), open_utc) is True

    def test_kis_market_data_is_market_open_at_close_boundary(self) -> None:
        """15:30:00 KST exactly → open (inclusive close)."""
        close_utc = datetime(2026, 5, 22, 6, 30, 0, tzinfo=UTC)  # 15:30 KST
        md = KISMarketData(client=_FakeKISClient([]))
        assert md.is_market_open(_asset(), close_utc) is True


# ---------------------------------------------------------------------------
# next_market_close
# ---------------------------------------------------------------------------
class TestKisMarketDataNextMarketClose:
    def test_kis_market_data_next_market_close_same_day_during_session(self) -> None:
        """During session → today's 15:30 KST."""
        md = KISMarketData(client=_FakeKISClient([]))
        close = md.next_market_close(_asset(), _DURING_SESSION)
        local = close.astimezone(KST)
        assert local.date() == _DURING_SESSION.astimezone(KST).date()
        assert local.hour == 15
        assert local.minute == 30

    def test_kis_market_data_next_market_close_after_session_advances_to_next_day(
        self,
    ) -> None:
        """After 15:30 KST on a Friday (2026-05-22) → Monday 2026-05-25."""
        # _AFTER_SESSION = 2026-05-22 16:00 KST
        md = KISMarketData(client=_FakeKISClient([]))
        close = md.next_market_close(_asset(), _AFTER_SESSION)
        local = close.astimezone(KST)
        assert local.date() == date(2026, 5, 25)  # Monday
        assert local.hour == 15
        assert local.minute == 30

    def test_kis_market_data_next_market_close_saturday_skips_to_monday(self) -> None:
        """Saturday KST → next close = Monday 15:30 KST."""
        sat = datetime(2026, 5, 22, 21, 0, 0, tzinfo=UTC)  # 2026-05-23 06:00 KST (Sat)
        md = KISMarketData(client=_FakeKISClient([]))
        close = md.next_market_close(_asset(), sat)
        local = close.astimezone(KST)
        assert local.date() == date(2026, 5, 25)  # Monday

    def test_kis_market_data_next_market_close_holiday_skips_to_next_trading_day(
        self,
    ) -> None:
        """A Monday that is a holiday → next close = Tuesday."""
        monday_during = datetime(2026, 5, 25, 1, 0, 0, tzinfo=UTC)  # 2026-05-25 10:00 KST
        holiday = monday_during.astimezone(KST).date()  # 2026-05-25
        md = KISMarketData(
            client=_FakeKISClient([]),
            explicit_holidays=frozenset([holiday]),
        )
        close = md.next_market_close(_asset(), monday_during)
        local = close.astimezone(KST)
        assert local.date() == date(2026, 5, 26)  # Tuesday

    def test_kis_market_data_next_market_close_is_utc(self) -> None:
        """Returned datetime must be UTC-aware."""
        md = KISMarketData(client=_FakeKISClient([]))
        close = md.next_market_close(_asset(), _DURING_SESSION)
        assert close.tzinfo is not None
        assert close.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# Port-signature gate
# ---------------------------------------------------------------------------
class TestKisMarketDataPortSignature:
    def test_kis_marketdata_port_signature_all_four_methods_exist(self) -> None:
        """All four MarketDataPort methods must be present."""
        for method_name in ("get_price", "get_ohlcv", "is_market_open", "next_market_close"):
            assert hasattr(KISMarketData, method_name), f"missing: {method_name}"
            assert callable(getattr(KISMarketData, method_name))

    def test_kis_marketdata_port_signature_no_datetime_now_in_source(self) -> None:
        """As-of injection contract: datetime.now() must not be called in market_data.py.

        Checks only non-comment, non-docstring lines — the docstring is allowed
        to mention the string as documentation (CLAUDE.md §3.2).
        """
        import ast
        import inspect

        import src.adapters.kis.market_data as md_module

        source = inspect.getsource(md_module)
        tree = ast.parse(source)
        # Walk all Call nodes; flag any `datetime.now()` actual call.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # datetime.now() → Attribute call on Name "datetime"
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "now"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "datetime"
                ):
                    pytest.fail(
                        f"market_data.py calls datetime.now() at line {node.lineno} — "
                        "use as_of injection (CLAUDE.md §3.2)"
                    )
