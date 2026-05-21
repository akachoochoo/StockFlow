"""KISMarketData — MarketDataPort over the KIS quotations API (Stage 2.3).

Implements the full MarketDataPort read surface:
- ``get_price``        : live current price (현재가) — ``inquire-price``.
- ``get_ohlcv``        : daily adjusted OHLCV bars — ``inquire-daily-itemchartprice``
                          (date-window pagination; KIS returns ≤100 bars/call).
- ``is_market_open``   : KRX session model (mirrors MockMarketData).
- ``next_market_close``: next KRX close (mirrors MockMarketData).

Time injection (CLAUDE.md §3.2): every time-dependent method takes ``as_of``
(UTC) — this adapter NEVER calls ``datetime.now()``. ``get_price`` returns a
**live** current quote (the KIS endpoint has no historical lookup), so the
returned ``Price.timestamp`` is the caller-supplied ``as_of`` and ``as_of`` is
expected to be ≈ now in live trading. Past-date replay uses pykrx / MockMarketData
instead (ADR 0012 D1 c — KIS 정본 for live, pykrx fallback).

Real-money invariants: Decimal 전용 (model coercion str→Decimal), no-retry
(delegated to ``KISClient``), no secret 로깅 (ADR 0012 R10). External data is
validated at this boundary (CLAUDE.md §5.1) — model ``ValidationError`` (e.g.
price ≤ 0, high < low) is wrapped into ``MarketDataUnavailableError`` /
``DataIntegrityError`` so the domain only ever sees valid models.

출처: ADR 0020 §2.2 (inquire-price FHKST01010100 / inquire-daily-itemchartprice
FHKST03010100 + 필드) / CLAUDE.md §3.2 (as_of 주입) / §5.1 (경계 검증).
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.adapters.kis.models import KISDailyPriceResponse, KISPriceResponse
from src.domain.constants import KST
from src.domain.exceptions import DataIntegrityError, MarketDataUnavailableError
from src.domain.models import OHLCV, Price

if TYPE_CHECKING:
    from datetime import date

    from src.adapters.kis._client import KISClient
    from src.domain.models import Asset

# inquire-price (현재가) — TR_ID identical for 실/모의 (FH...).
_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
_PRICE_TR_ID = "FHKST01010100"

# inquire-daily-itemchartprice (일봉 OHLCV) — TR_ID identical for 실/모의.
_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
_DAILY_TR_ID = "FHKST03010100"

# KIS returns at most ~100 daily bars per call (ADR 0020 §2.2). The runaway
# guard caps the number of pagination windows (100 bars x 200 ~= 20,000 trading
# days ≈ 80y — far beyond any realistic backtest range).
_MAX_OHLCV_PAGES = 200

# KRX regular trading session (mirrors MockMarketData; KST is a fixed offset).
_KRX_OPEN = time(9, 0)
_KRX_CLOSE = time(15, 30)


class KISMarketData:
    """MarketDataPort implementation backed by the KIS quotations API."""

    def __init__(
        self,
        *,
        client: KISClient,
        explicit_holidays: frozenset[date] = frozenset(),
        max_daily_change_pct: Decimal = Decimal("30"),
    ) -> None:
        self._client = client
        self._explicit_holidays = explicit_holidays
        self._max_daily_change_pct = max_daily_change_pct

    # ------------------------------------------------------------------
    # MarketDataPort — price
    # ------------------------------------------------------------------
    def get_price(self, asset: Asset, as_of: datetime) -> Price:
        """Return the **live** current price (현재가) for ``asset``.

        The KIS ``inquire-price`` endpoint reports the latest quote only (no
        historical lookup), so ``as_of`` is expected to be ≈ now in live
        trading and is used verbatim as the returned ``Price.timestamp``.
        Past-date replay must use pykrx / MockMarketData instead.

        ``stck_prpr`` ≤ 0 (Price model requires value > 0) → wrapped into
        ``MarketDataUnavailableError`` (CLAUDE.md §5.1 — boundary validation).

        Price-outlier guard (CLAUDE.md §5.2): the day-over-day move vs the
        previous close (``stck_sdpr``) is computed here and, if its absolute
        value exceeds ``max_daily_change_pct`` (default ±30%), a
        ``DataIntegrityError`` is raised. KRX caps regular trading at ±30%, so
        an *over*-±30% move cannot arise from normal trading — it signals a
        stock split / merger / data error. The conservative response is to
        reject the quote so the suspicious price is used NOWHERE and the asset
        stays halted until a human confirms (telegram alert wiring = Stage 3).
        The change is computed deterministically from
        ``stck_prpr`` vs ``stck_sdpr`` (the KIS-provided ``prdy_ctrt`` is
        reference-only — its live reliability is verified in Stage 4).

        **Consequence**: ``get_price`` feeds BOTH the buy decision and the EOD
        snapshot, so an outlier rejection affects both paths at once. This is
        intentional and conservative — a suspect price must not enter any
        downstream computation. ``stck_sdpr`` ≤ 0 (previous close absent / 0)
        → the change is undefined, so the outlier check is skipped to avoid a
        division by zero; ``stck_prpr`` itself is still > 0-validated by the
        Price model.
        """
        body = self._client.request(
            "GET",
            _PRICE_PATH,
            tr_id=_PRICE_TR_ID,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": asset.code,
            },
        )
        try:
            parsed = KISPriceResponse.model_validate(body)
        except ValidationError as exc:
            raise MarketDataUnavailableError(
                f"KIS inquire-price response invalid for {asset.fqn} "
                f"({len(exc.errors())} field error(s))"
            ) from exc

        prpr = parsed.output.stck_prpr
        prev_close = parsed.output.stck_sdpr
        # Outlier guard: skip when prev close is absent/0 (change undefined →
        # avoid division by zero). stck_prpr itself is value>0-checked below.
        if prev_close > 0:
            change_pct = abs((prpr - prev_close) / prev_close * 100)
            if change_pct > self._max_daily_change_pct:
                raise DataIntegrityError(
                    f"KIS inquire-price day-over-day change for {asset.fqn} "
                    f"({change_pct}%) exceeds {self._max_daily_change_pct}% "
                    f"threshold (CLAUDE.md §5.2: split/merger/data-error "
                    f"suspected — quote rejected, asset halted)"
                )

        try:
            return Price(
                asset=asset,
                value=prpr,
                timestamp=as_of,
            )
        except ValidationError as exc:
            # e.g. stck_prpr <= 0. The price model is the integrity gate.
            raise MarketDataUnavailableError(
                f"KIS inquire-price returned an invalid price for {asset.fqn} "
                f"({len(exc.errors())} field error(s))"
            ) from exc

    # ------------------------------------------------------------------
    # MarketDataPort — daily OHLCV (date-window paginated)
    # ------------------------------------------------------------------
    def get_ohlcv(self, asset: Asset, start: date, end: date) -> list[OHLCV]:
        """Return adjusted daily OHLCV bars in ``[start, end]``, sorted ascending.

        KIS ``inquire-daily-itemchartprice`` returns at most ~100 bars per call
        (descending by date). To cover ranges wider than one page we paginate by
        **date window**: each call requests ``[start, window_end]``; after a
        page we move ``window_end`` to the day before the earliest bar returned
        and repeat until the earliest returned bar reaches ``start`` (or a page
        comes back empty). Results are merged, de-duplicated by ``trade_date``,
        and sorted ascending.

        ``start > end`` → ``ValueError`` (caller bug). Empty range → ``[]``.
        Any OHLCV integrity violation (high < low, etc.) surfaces as
        ``DataIntegrityError`` (CLAUDE.md §5.1).
        """
        if start > end:
            raise ValueError(f"start ({start}) > end ({end})")

        merged: dict[date, OHLCV] = {}
        window_end = end
        for _ in range(_MAX_OHLCV_PAGES):
            if window_end < start:
                break
            page = self._fetch_ohlcv_page(asset, start, window_end)
            if not page:
                break
            for bar in page:
                if start <= bar.trade_date <= end:
                    merged[bar.trade_date] = bar
            earliest = min(bar.trade_date for bar in page)
            if earliest <= start:
                break
            window_end = earliest - timedelta(days=1)

        return [merged[d] for d in sorted(merged)]

    def _fetch_ohlcv_page(
        self, asset: Asset, start: date, end: date
    ) -> list[OHLCV]:
        """Fetch a single ≤100-bar OHLCV page for ``[start, end]``."""
        body = self._client.request(
            "GET",
            _DAILY_PATH,
            tr_id=_DAILY_TR_ID,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": asset.code,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",  # 수정주가
            },
        )
        try:
            parsed = KISDailyPriceResponse.model_validate(body)
        except ValidationError as exc:
            raise MarketDataUnavailableError(
                f"KIS inquire-daily-itemchartprice response invalid for "
                f"{asset.fqn} ({len(exc.errors())} field error(s))"
            ) from exc

        bars: list[OHLCV] = []
        for item in parsed.output2:
            # KIS pads non-trading entries with all-zero rows; skip them so the
            # OHLCV model's value>0 invariant is not tripped by filler.
            if item.stck_clpr == 0:
                continue
            try:
                bars.append(
                    OHLCV(
                        asset=asset,
                        trade_date=_parse_kis_date(item.stck_bsop_date),
                        open=item.stck_oprc,
                        high=item.stck_hgpr,
                        low=item.stck_lwpr,
                        close=item.stck_clpr,
                        volume=item.acml_vol,
                    )
                )
            except ValidationError as exc:
                # high < low / out-of-range OHLC → external data integrity issue.
                raise DataIntegrityError(
                    f"KIS daily bar failed integrity check for {asset.fqn} "
                    f"on {item.stck_bsop_date} ({len(exc.errors())} error(s))"
                ) from exc
        return bars

    # ------------------------------------------------------------------
    # MarketDataPort — session (mirrors MockMarketData)
    # ------------------------------------------------------------------
    def is_market_open(self, asset: Asset, as_of: datetime) -> bool:
        """Whether KRX is open at ``as_of`` (UTC).

        Mirrors MockMarketData: 09:00-15:30 KST, weekday, minus
        ``explicit_holidays``. The KIS chk-holiday endpoint is NOT used here —
        holiday awareness is injected via ``explicit_holidays`` for now (Stage 3/4
        may wire the KIS holiday API). Phase 1 = single KRX session.
        """
        del asset  # Phase 1: all assets share the KRX session.
        local_dt = as_of.astimezone(KST)
        if local_dt.weekday() >= 5:
            return False
        if local_dt.date() in self._explicit_holidays:
            return False
        return _KRX_OPEN <= local_dt.time() <= _KRX_CLOSE

    def next_market_close(self, asset: Asset, as_of: datetime) -> datetime:
        """Return the next KRX close at or after ``as_of`` (UTC).

        Mirrors MockMarketData. The KIS chk-holiday endpoint is NOT used —
        ``explicit_holidays`` drives non-trading days (Stage 3/4 follow-up).
        """
        del asset  # Phase 1: all assets share the KRX session.
        local_dt = as_of.astimezone(KST)
        local_date = local_dt.date()
        # Today's close still ahead?
        if (
            local_dt.weekday() < 5
            and local_date not in self._explicit_holidays
            and local_dt.time() <= _KRX_CLOSE
        ):
            return _bar_close_utc(local_date)
        # Otherwise advance to the next trading day.
        candidate = local_date + timedelta(days=1)
        while candidate.weekday() >= 5 or candidate in self._explicit_holidays:
            candidate += timedelta(days=1)
        return _bar_close_utc(candidate)


def _parse_kis_date(wire: str) -> date:
    """Parse a KIS ``stck_bsop_date`` wire string ("YYYYMMDD") to a date."""
    return datetime.strptime(wire, "%Y%m%d").replace(tzinfo=UTC).date()


def _bar_close_utc(trade_date: date) -> datetime:
    """KRX 15:30 KST close for ``trade_date``, expressed in UTC."""
    local_close = datetime.combine(trade_date, _KRX_CLOSE, tzinfo=KST)
    return local_close.astimezone(UTC)


__all__ = ["KISMarketData"]
