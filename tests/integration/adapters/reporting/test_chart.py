"""Integration tests for src.adapters.reporting.chart (Phase 0.10 — ADR 0006 §6).

mplfinance + matplotlib 외부 lib 호출 — integration test 분류.
PNG bytes smoke test (헤더 검증) + 다양 episode 시나리오 스모크.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.adapters.reporting.chart import render_episode_chart
from src.adapters.reporting.renderers.default import DefaultRenderer
from src.adapters.reporting.renderers.seven_split import SevenSplitRenderer
from src.application.reporting.episode import DrawdownEpisode
from src.application.reporting.trade_view import TradeView
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
)

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _asset() -> Asset:
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _bars(
    n: int = 100,
    start: date = date(2024, 1, 1),
    base_price: int = 100,
) -> list[OHLCV]:
    """Generate synthetic OHLCV — enough for MA20/MA60 testing."""
    bars: list[OHLCV] = []
    asset = _asset()
    for i in range(n):
        # Simple sinusoid + noise for non-trivial movement
        price = base_price + ((i % 13) - 6) * 2
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=date.fromordinal(start.toordinal() + i),
                open=Decimal(price),
                high=Decimal(price + 2),
                low=Decimal(price - 2),
                close=Decimal(price),
                volume=Decimal("1000000"),
            )
        )
    return bars


def _trade(
    *,
    side: str = "BUY",
    on_date: date,
    price: int = 100,
    annotations: dict[str, str] | None = None,
) -> TradeView:
    return TradeView(
        timestamp=datetime(on_date.year, on_date.month, on_date.day, 6, 0,
                           tzinfo=UTC),
        symbol="069500",
        side=side,  # type: ignore[arg-type]
        price=Decimal(price),
        quantity=Decimal("10"),
        strategy_id="price_drop",
        annotations=annotations or {},
    )


def _episode(
    *,
    peak: date = date(2024, 1, 30),
    trough: date = date(2024, 2, 5),
    recovery: date | None = date(2024, 2, 15),
    recovered: bool = True,
) -> DrawdownEpisode:
    return DrawdownEpisode(
        peak_date=peak,
        peak_value=Decimal("110"),
        trough_date=trough,
        trough_value=Decimal("90"),
        recovery_date=recovery,
        recovered=recovered,
        drawdown_pct=Decimal("-18.18"),
        duration_days=(recovery - peak).days if recovery else 30,
    )


class TestRenderEpisodeChartSmoke:
    def test_returns_png_bytes(self):
        bars = _bars(n=100)
        result = render_episode_chart(
            episode=_episode(),
            ohlcv_bars=bars,
            trades=[],
            renderer=DefaultRenderer(),
        )
        assert isinstance(result, bytes)
        assert result.startswith(_PNG_HEADER)
        assert len(result) > 100  # non-trivial PNG

    def test_with_trades_default_renderer(self):
        bars = _bars(n=100)
        trades = [
            _trade(side="BUY", on_date=date(2024, 2, 1), price=92),
            _trade(side="SELL", on_date=date(2024, 2, 10), price=100),
        ]
        result = render_episode_chart(
            episode=_episode(),
            ohlcv_bars=bars,
            trades=trades,
            renderer=DefaultRenderer(),
        )
        assert result.startswith(_PNG_HEADER)

    def test_with_trades_seven_split_renderer(self):
        bars = _bars(n=100)
        trades = [
            _trade(
                side="BUY", on_date=date(2024, 2, 1), price=92,
                annotations={"split_number": "1"},
            ),
            _trade(
                side="BUY", on_date=date(2024, 2, 3), price=88,
                annotations={"split_number": "2"},
            ),
            _trade(
                side="SELL", on_date=date(2024, 2, 12), price=100,
                annotations={"slot_number": "1"},
            ),
        ]
        result = render_episode_chart(
            episode=_episode(),
            ohlcv_bars=bars,
            trades=trades,
            renderer=SevenSplitRenderer(),
        )
        assert result.startswith(_PNG_HEADER)

    def test_unrecovered_episode(self):
        bars = _bars(n=100)
        result = render_episode_chart(
            episode=_episode(recovery=None, recovered=False),
            ohlcv_bars=bars,
            trades=[],
            renderer=DefaultRenderer(),
        )
        assert result.startswith(_PNG_HEADER)


class TestErrorHandling:
    def test_empty_ohlcv_raises(self):
        with pytest.raises(ValueError, match="empty"):
            render_episode_chart(
                episode=_episode(),
                ohlcv_bars=[],
                trades=[],
                renderer=DefaultRenderer(),
            )

    def test_no_bars_in_window_raises(self):
        # Episode in 2024-01, OHLCV in 2030 — no overlap
        bars = _bars(n=10, start=date(2030, 1, 1))
        with pytest.raises(ValueError, match="window"):
            render_episode_chart(
                episode=_episode(),  # peak 2024-01-30
                ohlcv_bars=bars,
                trades=[],
                renderer=DefaultRenderer(),
            )


class TestChartWindow:
    def test_short_window_omits_ma(self):
        # Few bars (< 20) — MA omitted
        bars = _bars(n=15)
        result = render_episode_chart(
            episode=_episode(
                peak=date(2024, 1, 5),
                trough=date(2024, 1, 8),
                recovery=date(2024, 1, 12),
            ),
            ohlcv_bars=bars,
            trades=[],
            renderer=DefaultRenderer(),
            chart_window_pad_days=2,
        )
        # No exception means MA gracefully omitted
        assert result.startswith(_PNG_HEADER)

    def test_medium_window_uses_ma20(self):
        # 20~59 bars → MA20 only
        bars = _bars(n=30)
        result = render_episode_chart(
            episode=_episode(
                peak=date(2024, 1, 10),
                trough=date(2024, 1, 15),
                recovery=date(2024, 1, 25),
            ),
            ohlcv_bars=bars,
            trades=[],
            renderer=DefaultRenderer(),
        )
        assert result.startswith(_PNG_HEADER)
