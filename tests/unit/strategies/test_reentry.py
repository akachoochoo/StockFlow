"""Unit tests for src.domain.strategies.reentry — D-2 / F + factory."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.adapters.mock.market_data import MockMarketData
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Position,
    SplitSlot,
)
from src.domain.strategies.reentry import (
    HybridTimeBasedReentry,
    MovingAverageReentry,
    create_reentry_strategy,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)


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


def _empty_position() -> Position:
    return Position.empty(_asset())


def _empty_slot(
    slot_number: int = 1,
    *,
    last_exit_price: Decimal | None = None,
    last_exit_date: date | None = None,
) -> SplitSlot:
    return SplitSlot.empty(
        slot_number=slot_number,
        last_exit_price=last_exit_price,
        last_exit_date=last_exit_date,
    )


def _bar(asset: Asset, d: date, close: str) -> OHLCV:
    """OHLCV with all OHLC == close for clean SMA fixtures."""
    c = Decimal(close)
    return OHLCV(
        asset=asset,
        trade_date=d,
        open=c,
        high=c,
        low=c,
        close=c,
        volume=Decimal("1000"),
    )


def _market_with_closes(asset: Asset, close_by_date: dict[date, str]) -> MockMarketData:
    bars = [_bar(asset, d, c) for d, c in sorted(close_by_date.items())]
    return MockMarketData(ohlcv_by_asset={asset: bars})


# ---------------------------------------------------------------------------
# Policy D-2 — MovingAverageReentry
# ---------------------------------------------------------------------------
class TestMovingAverageReentry:
    AS_OF = date(2026, 4, 30)
    DROP_PCT = Decimal("5")

    def _slot_with_exit(self) -> SplitSlot:
        return _empty_slot(
            last_exit_price=Decimal("33000"),
            last_exit_date=date(2026, 4, 1),
        )

    def _position_with_filled_slot(self) -> Position:
        # A position with split_level >= 1 — bypasses §4.7 first-buy.
        # Used as the fixture's "we have history" Position. Its precise
        # contents don't matter for MovingAverageReentry beyond
        # `position.split_level > 0` and `position.asset`.
        from src.domain.models import SplitEntry

        entry = SplitEntry(
            split_number=1,
            entry_date=date(2026, 1, 1),
            quantity=Decimal("10"),
            entry_price=Decimal("30000"),
            idempotency_key="seed-1",
        )
        slots = [SplitSlot.filled(entry=entry)]
        slots.extend(_empty_slot(slot_number=i) for i in range(2, 8))
        return Position(
            asset=_asset(),
            quantity=Decimal("10"),
            avg_price=Decimal("30000"),
            split_level=1,
            last_buy_at=UTC_NOW,
            slots=slots,
        )

    def test_first_buy_bypass_when_position_empty(self):
        # §4.7 (좁힌 정의): split_level == 0 → bypass with current_price.
        # No market data needed because bypass short-circuits.
        market = _market_with_closes(_asset(), {})
        policy = MovingAverageReentry(market_data=market, window=20)
        trigger = policy.get_trigger_price(
            slot=_empty_slot(),
            position=_empty_position(),
            current_price=Decimal("30000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.AS_OF,
        )
        assert trigger == Decimal("30000")

    def test_fresh_slot_in_non_empty_position_uses_ma_not_bypass(self):
        # §4.7 narrowed: subsequent splits' fresh slots do NOT bypass.
        # MA is computed instead — and if data sufficient, the MA-based
        # trigger is returned (slot history irrelevant for D-2).
        asset = _asset()
        closes = {
            self.AS_OF - timedelta(days=i + 1): "30000"
            for i in range(30)
        }
        market = _market_with_closes(asset, closes)
        policy = MovingAverageReentry(market_data=market, window=20)
        trigger = policy.get_trigger_price(
            slot=_empty_slot(slot_number=2),  # fresh, no exit history
            position=self._position_with_filled_slot(),  # split_level >= 1
            current_price=Decimal("28000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.AS_OF,
        )
        assert trigger == Decimal("28500")  # SMA(30000) * 0.95

    def test_ma_reentry_with_sufficient_data(self):
        # 20 bars all close=30000 → SMA=30000 → trigger=30000*0.95=28500
        asset = _asset()
        closes = {
            self.AS_OF - timedelta(days=i + 1): "30000"
            for i in range(30)  # plenty of history; window=20 will use last 20
        }
        market = _market_with_closes(asset, closes)
        policy = MovingAverageReentry(market_data=market, window=20)
        trigger = policy.get_trigger_price(
            slot=self._slot_with_exit(),
            position=self._position_with_filled_slot(),
            current_price=Decimal("28000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.AS_OF,
        )
        assert trigger == Decimal("28500")

    def test_ma_reentry_data_insufficient_returns_none(self):
        # Only 19 bars, window=20 → not enough → None
        asset = _asset()
        closes = {
            self.AS_OF - timedelta(days=i + 1): "30000"
            for i in range(19)
        }
        market = _market_with_closes(asset, closes)
        policy = MovingAverageReentry(market_data=market, window=20)
        trigger = policy.get_trigger_price(
            slot=self._slot_with_exit(),
            position=self._position_with_filled_slot(),
            current_price=Decimal("28000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.AS_OF,
        )
        assert trigger is None

    def test_ma_reentry_excludes_current_day(self):
        # 19 historical bars before as_of + 1 bar AT as_of (the current day).
        # If lookahead bug existed, len would be 20 and SMA would compute.
        # Correct behaviour: as_of bar excluded, len=19 < window → None.
        asset = _asset()
        closes = {
            self.AS_OF - timedelta(days=i + 1): "30000"
            for i in range(19)
        }
        # As-of bar (would be lookahead if included)
        closes[self.AS_OF] = "99999"
        market = _market_with_closes(asset, closes)
        policy = MovingAverageReentry(market_data=market, window=20)
        trigger = policy.get_trigger_price(
            slot=self._slot_with_exit(),
            position=self._position_with_filled_slot(),
            current_price=Decimal("28000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.AS_OF,
        )
        assert trigger is None  # as_of bar excluded → only 19 bars

    def test_ma_reentry_handles_holidays(self):
        # Sparse calendar (only 21 trading days within last 60 calendar days);
        # buffer=42 days so we have 30 candidate dates → only 21 bars.
        # Last 20 used for SMA. SMA computed correctly from those bars.
        asset = _asset()
        # Place bars on every other date (simulating heavy holiday blocks).
        closes = {
            self.AS_OF - timedelta(days=2 * i + 1): "30000"
            for i in range(21)  # 21 bars within calendar buffer
        }
        market = _market_with_closes(asset, closes)
        policy = MovingAverageReentry(market_data=market, window=20)
        trigger = policy.get_trigger_price(
            slot=self._slot_with_exit(),
            position=self._position_with_filled_slot(),
            current_price=Decimal("28000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.AS_OF,
        )
        assert trigger == Decimal("28500")  # SMA=30000, trigger=28500

    def test_buffer_calculation_for_various_windows(self):
        # window=20 → buffer=42, window=60 → buffer=106. We assert the
        # implementation fetches enough calendar days to cover trading
        # days for the configured window. We verify by feeding exactly
        # `window` bars within the buffer window and confirming SMA fires.
        for window, expected_buffer in [(20, 42), (60, 106)]:
            asset = _asset()
            # Place exactly `window` bars distributed over the buffer.
            closes = {
                self.AS_OF - timedelta(days=expected_buffer - i): "30000"
                for i in range(window)
            }
            market = _market_with_closes(asset, closes)
            policy = MovingAverageReentry(market_data=market, window=window)
            trigger = policy.get_trigger_price(
                slot=self._slot_with_exit(),
                position=self._position_with_filled_slot(),
                current_price=Decimal("28000"),
                drop_threshold_pct=self.DROP_PCT,
                as_of=self.AS_OF,
            )
            assert trigger == Decimal("28500"), (
                f"window={window} should fire with {window} bars in buffer"
            )

    def test_invalid_window_rejected(self):
        market = _market_with_closes(_asset(), {})
        with pytest.raises(ValueError, match=r"window"):
            MovingAverageReentry(market_data=market, window=0)
        with pytest.raises(ValueError, match=r"window"):
            MovingAverageReentry(market_data=market, window=501)

    def test_unsupported_ma_type_rejected(self):
        market = _market_with_closes(_asset(), {})
        with pytest.raises(ValueError, match=r"ma_type"):
            MovingAverageReentry(market_data=market, ma_type="ema")


# ---------------------------------------------------------------------------
# Policy F — HybridTimeBasedReentry
# ---------------------------------------------------------------------------
class TestHybridTimeBasedReentry:
    EXIT_DATE = date(2026, 4, 1)
    DROP_PCT = Decimal("5")

    def _slot_with_exit(self) -> SplitSlot:
        return _empty_slot(
            last_exit_price=Decimal("33000"),
            last_exit_date=self.EXIT_DATE,
        )

    def _position_with_filled_slot_avg(self, avg: str) -> Position:
        """A non-empty position so split_level >= 1 (avoids §4.7 bypass)."""
        from src.domain.models import SplitEntry

        entry = SplitEntry(
            split_number=1,
            entry_date=date(2026, 1, 1),
            quantity=Decimal("10"),
            entry_price=Decimal(avg),
            idempotency_key="seed-1",
        )
        slots = [SplitSlot.filled(entry=entry)]
        slots.extend(_empty_slot(slot_number=i) for i in range(2, 8))
        return Position(
            asset=_asset(),
            quantity=Decimal("10"),
            avg_price=Decimal(avg),
            split_level=1,
            last_buy_at=UTC_NOW,
            slots=slots,
        )

    def test_first_buy_bypass_when_position_empty(self):
        # §4.7 (좁힌 정의): split_level == 0 → bypass with current_price.
        policy = HybridTimeBasedReentry(cooldown_days=60)
        trigger = policy.get_trigger_price(
            slot=_empty_slot(),
            position=_empty_position(),
            current_price=Decimal("30000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=date(2026, 4, 30),
        )
        assert trigger == Decimal("30000")

    def test_with_exit_history_uses_last_exit_anchor(self):
        # 33000 * 0.95 = 31350 (regardless of days since exit per §4.3)
        policy = HybridTimeBasedReentry(cooldown_days=60)
        trigger = policy.get_trigger_price(
            slot=self._slot_with_exit(),
            position=self._position_with_filled_slot_avg("35000"),
            current_price=Decimal("30000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.EXIT_DATE + timedelta(days=200),  # well past cooldown
        )
        assert trigger == Decimal("31350")

    def test_hybrid_reentry_on_exit_day(self):
        # ADR §4.6 — same-day exit also uses last_exit anchor.
        policy = HybridTimeBasedReentry(cooldown_days=60)
        trigger = policy.get_trigger_price(
            slot=self._slot_with_exit(),
            position=self._position_with_filled_slot_avg("35000"),
            current_price=Decimal("30000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=self.EXIT_DATE,
        )
        assert trigger == Decimal("31350")

    def test_fresh_slot_in_non_empty_position_uses_avg_price(self):
        # ADR §4.3 + §4.7 5차: fresh EMPTY slot (no exit history) in a
        # position with at least one FILLED slot falls back to
        # position.avg_price as anchor (Phase 0 D behaviour).
        # avg=35000 → trigger = 35000 * 0.95 = 33250
        policy = HybridTimeBasedReentry(cooldown_days=60)
        trigger = policy.get_trigger_price(
            slot=_empty_slot(slot_number=2),  # no last_exit_*
            position=self._position_with_filled_slot_avg("35000"),
            current_price=Decimal("30000"),
            drop_threshold_pct=self.DROP_PCT,
            as_of=date(2026, 4, 30),
        )
        assert trigger == Decimal("33250")

    def test_negative_cooldown_days_rejected(self):
        with pytest.raises(ValueError, match=r"cooldown_days"):
            HybridTimeBasedReentry(cooldown_days=-1)

    def test_excessive_cooldown_days_rejected(self):
        with pytest.raises(ValueError, match=r"cooldown_days"):
            HybridTimeBasedReentry(cooldown_days=366)


# ---------------------------------------------------------------------------
# Factory — create_reentry_strategy
# ---------------------------------------------------------------------------
class TestCreateReentryStrategy:
    def test_moving_average_dispatch_with_defaults(self):
        market = _market_with_closes(_asset(), {})
        policy = create_reentry_strategy("moving_average", market_data=market)
        assert isinstance(policy, MovingAverageReentry)
        assert policy.window == 20
        assert policy.ma_type == "sma"

    def test_moving_average_dispatch_with_custom_window(self):
        market = _market_with_closes(_asset(), {})
        policy = create_reentry_strategy(
            "moving_average", market_data=market, window=60
        )
        assert isinstance(policy, MovingAverageReentry)
        assert policy.window == 60

    def test_moving_average_requires_market_data(self):
        with pytest.raises(ValueError, match=r"market_data"):
            create_reentry_strategy("moving_average")

    def test_moving_average_with_non_int_window_rejected(self):
        market = _market_with_closes(_asset(), {})
        with pytest.raises(ValueError, match=r"window"):
            create_reentry_strategy(
                "moving_average", market_data=market, window="20"
            )

    def test_hybrid_dispatch_with_default_cooldown(self):
        policy = create_reentry_strategy("hybrid")
        assert isinstance(policy, HybridTimeBasedReentry)
        assert policy.cooldown_days == 60

    def test_hybrid_dispatch_with_custom_cooldown(self):
        policy = create_reentry_strategy("hybrid", cooldown_days=30)
        assert isinstance(policy, HybridTimeBasedReentry)
        assert policy.cooldown_days == 30

    def test_hybrid_with_non_int_cooldown_rejected(self):
        with pytest.raises(ValueError, match=r"cooldown_days"):
            create_reentry_strategy("hybrid", cooldown_days="60")

    def test_unknown_name_rejected(self):
        with pytest.raises(ValueError, match=r"unknown reentry strategy"):
            create_reentry_strategy("aggressive_dca")
