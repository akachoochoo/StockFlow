"""Market data port — price and trading session info.

Phase 0 supports daily-bar OHLCV only. Intraday/minute bars and order book
arrive in later Phases (see docs/roadmap.md).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date, datetime

    from src.domain.models import OHLCV, Asset, Price


class MarketDataPort(Protocol):
    """Market data lookups.

    All time-dependent methods take an explicit `as_of` parameter (UTC) for
    time injection (CLAUDE.md §3.2). Implementations MUST NOT call
    datetime.now() internally — the caller (orchestrator / backtest runner)
    decides what 'now' means. This is what makes the same domain code reusable
    for both backtests and live trading.

    Errors are raised via:
    - MarketDataUnavailableError: data missing or API failure
    - DataIntegrityError: returned data fails sanity checks (CLAUDE.md §5.1)
    """

    def get_price(self, asset: Asset, as_of: datetime) -> Price:
        """Return the latest known price at or before `as_of` (UTC)."""
        ...

    def get_ohlcv(self, asset: Asset, start: date, end: date) -> list[OHLCV]:
        """Return daily OHLCV bars in [start, end] inclusive, sorted ascending.

        Empty list if no trading days fall in the range.
        """
        ...

    def is_market_open(self, asset: Asset, as_of: datetime) -> bool:
        """Whether the asset's market is open at `as_of` (UTC)."""
        ...

    def next_market_close(self, asset: Asset, as_of: datetime) -> datetime:
        """Return the next market close time at or after `as_of` (UTC)."""
        ...
