"""MockMarketData — fixture-based market data for backtest / paper trading.

OHLCV data is supplied at construction via ``ohlcv_by_asset``.
get_price returns the close of the most recent bar whose KRX session close
has already passed at ``as_of`` — this prevents look-ahead bias automatically
(design doc §4.2).
get_ohlcv filters bars by trade_date range.
is_market_open / next_market_close use a simple KRX session model:
09:00-15:30 KST, weekdays, minus the asset-agnostic ``explicit_holidays`` set.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

from src.domain.constants import KST
from src.domain.exceptions import MarketDataUnavailableError
from src.domain.models import Price

if TYPE_CHECKING:
    from datetime import date

    from src.domain.models import OHLCV, Asset


# KRX regular trading session (no DST adjustment needed; KST is a fixed offset)
_KRX_OPEN = time(9, 0)
_KRX_CLOSE = time(15, 30)


class MockMarketData:
    """Fixture-based MarketDataPort implementation for Phase 0."""

    def __init__(
        self,
        *,
        ohlcv_by_asset: dict[Asset, list[OHLCV]],
        explicit_holidays: frozenset[date] = frozenset(),
    ) -> None:
        self._bars: dict[Asset, list[OHLCV]] = {}
        for asset, bars in ohlcv_by_asset.items():
            for bar in bars:
                if bar.asset != asset:
                    raise ValueError(
                        f"OHLCV.asset ({bar.asset.fqn}) != map key ({asset.fqn})"
                    )
            self._bars[asset] = sorted(bars, key=lambda b: b.trade_date)
        self._explicit_holidays = explicit_holidays

    def get_price(self, asset: Asset, as_of: datetime) -> Price:
        bars = self._bars.get(asset)
        if not bars:
            raise MarketDataUnavailableError(f"no OHLCV data for {asset.fqn}")
        chosen: OHLCV | None = None
        for bar in bars:
            bar_close_utc = self._bar_close_utc(bar.trade_date)
            if bar_close_utc <= as_of:
                chosen = bar
            else:
                break  # bars are sorted; later bars are not yet available
        if chosen is None:
            raise MarketDataUnavailableError(
                f"no OHLCV data for {asset.fqn} available at {as_of.isoformat()}"
            )
        return Price(asset=asset, value=chosen.close, timestamp=as_of)

    def get_ohlcv(self, asset: Asset, start: date, end: date) -> list[OHLCV]:
        if start > end:
            raise ValueError(f"start ({start}) > end ({end})")
        bars = self._bars.get(asset, [])
        return [b for b in bars if start <= b.trade_date <= end]

    def is_market_open(self, asset: Asset, as_of: datetime) -> bool:
        del asset  # Phase 0: all assets share KRX session
        local_dt = as_of.astimezone(KST)
        if local_dt.weekday() >= 5:
            return False
        if local_dt.date() in self._explicit_holidays:
            return False
        return _KRX_OPEN <= local_dt.time() <= _KRX_CLOSE

    def next_market_close(self, asset: Asset, as_of: datetime) -> datetime:
        del asset  # Phase 0: all assets share KRX session
        local_dt = as_of.astimezone(KST)
        local_date = local_dt.date()
        # Today's close still ahead?
        if (
            local_dt.weekday() < 5
            and local_date not in self._explicit_holidays
            and local_dt.time() <= _KRX_CLOSE
        ):
            return self._bar_close_utc(local_date)
        # Otherwise advance to the next trading day
        candidate = local_date + timedelta(days=1)
        while candidate.weekday() >= 5 or candidate in self._explicit_holidays:
            candidate += timedelta(days=1)
        return self._bar_close_utc(candidate)

    @staticmethod
    def _bar_close_utc(trade_date: date) -> datetime:
        local_close = datetime.combine(trade_date, _KRX_CLOSE, tzinfo=KST)
        return local_close.astimezone(UTC)
