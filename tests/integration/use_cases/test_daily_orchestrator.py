"""Integration tests for src.use_cases.daily_orchestrator.DailyOrchestrator.

Wires real Mock adapters in most paths; uses small fakes (defined in-file)
for controlled fault injection where MockBroker / MockMarketData can't easily
simulate the scenario.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.adapters.mock.market_data import MockMarketData
from src.adapters.mock.signals import NullSignal
from src.domain.constants import KST
from src.domain.exceptions import (
    BrokerConnectionError,
    BrokerOrderError,
    DataIntegrityError,
    IntegrityError,
    MarketDataUnavailableError,
)
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Balance,
    CircuitBreakerSignal,
    Currency,
    Decision,
    Exchange,
    Money,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
    SignalLevel,
    SignalSource,
    SplitEntry,
    SplitSlot,
)
from src.domain.strategies.price_drop import PriceDropStrategy, SplitStrategyConfig
from src.domain.strategies.reentry import HybridTimeBasedReentry
from src.use_cases.daily_orchestrator import DailyOrchestrator, SkipReason


def _strategy() -> PriceDropStrategy:
    """Phase 0.5 default for orchestrator tests — Hybrid policy preserves
    Phase 0 avg_price drop semantics for fresh slots (ADR §4.3)."""
    return PriceDropStrategy(reentry=HybridTimeBasedReentry(cooldown_days=60))


TODAY = date(2026, 4, 30)


def _utc_after_close(d: date) -> datetime:
    """UTC datetime corresponding to KST 16:00 on `d` (after KRX close)."""
    return datetime.combine(d, time(16, 0), tzinfo=KST).astimezone(UTC)


def _asset(code: str = "069500", lot_size: str = "1") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal(lot_size),
    )


def _bar(asset: Asset, d: date, close: str) -> OHLCV:
    return OHLCV(
        asset=asset,
        trade_date=d,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1000000"),
    )


def _config() -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal("7.0"),
        max_split_count=7,
        per_split_amount=Money(amount=Decimal("1000000"), currency=Currency.KRW),
    )


def _seeded_position(
    asset: Asset,
    *,
    quantity: str,
    avg_price: str,
    split_level: int,
    last_buy_at: datetime,
    max_split_count: int = 7,
) -> Position:
    """Build a Position with `split_level` FILLED slots + EMPTY rest."""
    qty = Decimal(quantity)
    avg = Decimal(avg_price)
    if split_level == 0:
        return Position.empty(asset, max_split_count=max_split_count)
    base = qty // Decimal(split_level)
    remainder = qty - base * Decimal(split_level - 1)
    entries = [
        SplitEntry(
            split_number=i,
            entry_date=last_buy_at.date(),
            quantity=base,
            entry_price=avg,
            idempotency_key=f"seed-{i}",
        )
        for i in range(1, split_level)
    ]
    entries.append(
        SplitEntry(
            split_number=split_level,
            entry_date=last_buy_at.date(),
            quantity=remainder,
            entry_price=avg,
            idempotency_key=f"seed-{split_level}",
        )
    )
    slots: list[SplitSlot] = [SplitSlot.filled(entry=e) for e in entries]
    slots.extend(
        SplitSlot.empty(slot_number=i)
        for i in range(split_level + 1, max_split_count + 1)
    )
    return Position(
        asset=asset,
        quantity=qty,
        avg_price=avg,
        split_level=split_level,
        last_buy_at=last_buy_at,
        slots=slots,
    )


def _signal(
    level: SignalLevel = SignalLevel.NORMAL,
    source: SignalSource = SignalSource.NULL,
    asset_class: AssetClass = AssetClass.KR_ETF,
    *,
    at: datetime | None = None,
) -> CircuitBreakerSignal:
    at = at or _utc_after_close(TODAY)
    return CircuitBreakerSignal(
        level=level,
        source=source,
        asset_class=asset_class,
        evaluated_at=at,
        triggered_by=[],
        reasoning={},
        valid_until=at + timedelta(days=1),
    )


# ---------------------------------------------------------------------------
# Fakes for fault injection
# ---------------------------------------------------------------------------
@dataclass
class _FakeSignal:
    """SignalPort that returns a fixed signal or raises a configured error."""

    signal: CircuitBreakerSignal | None = None
    raise_error: Exception | None = None

    def collect(self, asset_class: AssetClass, as_of: datetime) -> CircuitBreakerSignal:
        if self.raise_error is not None:
            raise self.raise_error
        assert self.signal is not None
        return self.signal


@dataclass
class _FakeMarketData:
    """MarketDataPort that delegates to inner or raises a configured error."""

    inner: MockMarketData
    raise_on_get_price: Exception | None = None

    def get_price(self, asset, as_of):
        if self.raise_on_get_price is not None:
            raise self.raise_on_get_price
        return self.inner.get_price(asset, as_of)

    def get_ohlcv(self, asset, start, end):
        return self.inner.get_ohlcv(asset, start, end)

    def is_market_open(self, asset, as_of):
        return self.inner.is_market_open(asset, as_of)

    def next_market_close(self, asset, as_of):
        return self.inner.next_market_close(asset, as_of)


class _FakeBroker:
    """BrokerPort that exposes hooks for raising errors at specific calls."""

    def __init__(
        self,
        *,
        balance: Balance,
        positions: list[Position] | None = None,
        place_error: Exception | None = None,
        get_status_error: Exception | None = None,
        get_status_result: OrderResult | None = None,
        place_result: OrderResult | None = None,
        balance_error: Exception | None = None,
    ):
        self._balance = balance
        self._positions = list(positions or [])
        self.place_error = place_error
        self.get_status_error = get_status_error
        self.get_status_result = get_status_result
        self.place_result = place_result
        self.balance_error = balance_error
        self.placed: list[OrderRequest] = []

    def get_balance(self):
        if self.balance_error is not None:
            raise self.balance_error
        return self._balance

    def get_positions(self):
        return list(self._positions)

    def place_order(self, request):
        self.placed.append(request)
        if self.place_error is not None:
            raise self.place_error
        assert self.place_result is not None
        return self.place_result

    def get_order_status(self, idempotency_key):
        if self.get_status_error is not None:
            raise self.get_status_error
        return self.get_status_result

    def cancel_order(self, broker_order_id):
        del broker_order_id
        return False


# ---------------------------------------------------------------------------
# Helpers for wiring an orchestrator with real Mock adapters
# ---------------------------------------------------------------------------
def _make_real_orchestrator(
    *,
    asset: Asset | None = None,
    bars: list[OHLCV] | None = None,
    initial_balance: Balance | None = None,
    rng_seed: int = 42,
    timeout_rate: float = 0.0,
    rejection_rate: float = 0.0,
    clock_at: datetime | None = None,
) -> tuple[DailyOrchestrator, MockBroker]:
    """Build a DailyOrchestrator wired to a real MockBroker.

    Phase 0.5 (ADR 0002 §3.2.1) blocks partial fills end-to-end, so this
    helper does not expose a partial-fill knob. Tests that previously
    relied on partial fills are obsolete.
    """
    asset = asset or _asset()
    bars = bars or [
        _bar(asset, date(2026, 4, 28), "35000"),
        _bar(asset, date(2026, 4, 29), "35000"),
    ]
    initial_balance = initial_balance or Balance(
        cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
    )
    clock_at = clock_at or _utc_after_close(TODAY)

    broker = MockBroker(
        initial_balance=initial_balance,
        clock=lambda: clock_at,
        rng=random.Random(rng_seed),
        simulate_timeout_rate=timeout_rate,
        simulate_rejection_rate=rejection_rate,
    )
    market_data = MockMarketData(ohlcv_by_asset={asset: bars})
    signal = NullSignal()
    strategy = _strategy()

    orchestrator = DailyOrchestrator(
        broker=broker,
        market_data=market_data,
        signal=signal,
        strategy=strategy,
        config=_config(),
        asset=asset,
        clock=lambda: clock_at,
        uow_factory=lambda: InMemoryUnitOfWork(),
    )
    return orchestrator, broker


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
class TestNormalBuyFlow:
    def test_first_split_filled(self):
        orch, broker = _make_real_orchestrator()
        decision = orch.run_for_date(TODAY)
        assert isinstance(decision, Decision)
        assert decision.action_kinds() == ["buy_split_1"]
        assert decision.buy_action is not None and decision.buy_action.order_id is not None
        assert decision.reasoning["order_status"] == OrderStatus.FILLED.value
        assert decision.reasoning["filled_quantity"] == "28"
        # Idempotency key reflected
        assert broker.all_orders()[0].idempotency_key == "KRX:069500:2026-04-30"

    def test_subsequent_split_after_drop(self):
        # Pre-place a position via broker to set up state
        asset = _asset()
        orch, broker = _make_real_orchestrator(
            asset=asset,
            bars=[
                _bar(asset, date(2026, 4, 28), "35000"),
                _bar(asset, date(2026, 4, 29), "32000"),  # 8.57% drop
            ],
        )
        # seed an initial position
        broker._positions[asset.fqn] = _seeded_position(
            asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
            last_buy_at=_utc_after_close(date(2026, 4, 28)),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action_kinds() == ["buy_split_2"]
        assert decision.buy_action is not None
        assert decision.buy_action.slot_number == 2


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
class TestCircuitBreaker:
    def _make_with_signal(self, level: SignalLevel) -> tuple[DailyOrchestrator, _FakeBroker]:
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = _FakeBroker(
            balance=Balance(cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)),
        )
        orch = DailyOrchestrator(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(level=level, at=clock_at)),
            strategy=_strategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
            uow_factory=lambda: InMemoryUnitOfWork(),
        )
        return orch, broker

    def test_halt_short_circuits_before_broker_calls(self):
        orch, broker = self._make_with_signal(SignalLevel.HALT)
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.CIRCUIT_BREAKER_HALT
        assert decision.buy_action is None and not decision.sell_actions
        assert broker.placed == []  # broker was never asked to place anything

    def test_emergency_short_circuits(self):
        orch, broker = self._make_with_signal(SignalLevel.EMERGENCY)
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.CIRCUIT_BREAKER_HALT
        assert broker.placed == []

    def test_caution_halves_quantity(self):
        # NORMAL with full price would buy 28 shares; CAUTION should buy 14.
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        balance = Balance(cash=Money(amount=Decimal("100000000"), currency=Currency.KRW))
        broker = MockBroker(
            initial_balance=balance,
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        orch = DailyOrchestrator(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(level=SignalLevel.CAUTION, at=clock_at)),
            strategy=_strategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
            uow_factory=lambda: InMemoryUnitOfWork(),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action_kinds() == ["buy_split_1"]
        # 28 / 2 = 14 (lot_size = 1)
        assert decision.reasoning["filled_quantity"] == "14"
        assert decision.reasoning["pre_adjust_quantity"] == "28"

    def test_caution_can_reduce_quantity_to_zero(self):
        # If pre-adjust quantity == lot_size, halving + floor = 0 → QUANTITY_TOO_SMALL
        asset = _asset(lot_size="20")
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        # spend 1,000,000 / 35,000 = 28.57 → floor to 20-multiple = 20
        # CAUTION halves to 10 → floor to 20-multiple = 0 → skip
        balance = Balance(cash=Money(amount=Decimal("100000000"), currency=Currency.KRW))
        orch = DailyOrchestrator(
            broker=MockBroker(initial_balance=balance, clock=lambda: clock_at),
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(level=SignalLevel.CAUTION, at=clock_at)),
            strategy=_strategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
            uow_factory=lambda: InMemoryUnitOfWork(),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.QUANTITY_TOO_SMALL
        assert decision.reasoning["pre_adjust_quantity"] == "20"
        assert decision.reasoning["adjusted_quantity"] == "0"


# ---------------------------------------------------------------------------
# Strategy-side skip mapping
# ---------------------------------------------------------------------------
class TestStrategySkipMapping:
    def test_max_split_reached_maps_to_strategy_no_buy(self):
        # Phase 0.5: all slots FILLED → STRATEGY_NO_BUY (no EMPTY slots
        # to evaluate).
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "20000")]
        orch, broker = _make_real_orchestrator(asset=asset, bars=bars)
        broker._positions[asset.fqn] = _seeded_position(
            asset,
            quantity="100",
            avg_price="30000",
            split_level=7,
            last_buy_at=_utc_after_close(date(2026, 4, 28)),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.STRATEGY_NO_BUY
        assert decision.reasoning.get("max_split_reached") == "True"

    def test_drop_insufficient_maps_to_strategy_no_buy(self):
        # Phase 0.5 with HybridTimeBasedReentry: fresh slot fallback
        # uses avg_price anchor → trigger = 35000 * 0.93 = 32550. Current
        # 33500 > 32550 → no fire → STRATEGY_NO_BUY.
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "33500")]
        orch, broker = _make_real_orchestrator(asset=asset, bars=bars)
        broker._positions[asset.fqn] = _seeded_position(
            asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
            last_buy_at=_utc_after_close(date(2026, 4, 28)),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.STRATEGY_NO_BUY

    def test_max_split_per_day_reached_emits_dedicated_skip_reason(self):
        # Phase 0.5: strategy emits SkipReason.MAX_SPLIT_PER_DAY_REACHED
        # directly (no orchestrator remap to STRATEGY_NO_BUY).
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "32000")]
        orch, broker = _make_real_orchestrator(asset=asset, bars=bars)
        broker._positions[asset.fqn] = _seeded_position(
            asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
            last_buy_at=_utc_after_close(TODAY),  # entry_date == TODAY
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.MAX_SPLIT_PER_DAY_REACHED
        assert decision.reasoning["today_buys"] == "1"
        assert decision.reasoning["max_split_per_day"] == "1"

    def test_quantity_below_lot_size_maps_to_quantity_too_small(self):
        asset = _asset(lot_size="100")
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        orch, _ = _make_real_orchestrator(asset=asset, bars=bars)
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.QUANTITY_TOO_SMALL

    def test_insufficient_balance_maps_directly(self):
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        small_balance = Balance(cash=Money(amount=Decimal("100"), currency=Currency.KRW))
        orch, _ = _make_real_orchestrator(
            asset=asset, bars=bars, initial_balance=small_balance,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.INSUFFICIENT_BALANCE


# ---------------------------------------------------------------------------
# External system errors
# ---------------------------------------------------------------------------
class TestExternalErrors:
    def _wired(self, **overrides):
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker_kwargs = overrides.pop("broker_kwargs", {})
        signal_obj = overrides.pop("signal", _FakeSignal(signal=_signal(at=clock_at)))
        market_data_obj = overrides.pop(
            "market_data", MockMarketData(ohlcv_by_asset={asset: bars})
        )
        broker = overrides.pop(
            "broker",
            _FakeBroker(
                balance=Balance(
                    cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
                ),
                place_result=OrderResult(
                    idempotency_key="KRX:069500:2026-04-30",
                    asset=asset,
                    broker_order_id="bid-1",
                    status=OrderStatus.FILLED,
                    filled_quantity=Decimal("28"),
                    filled_price=Decimal("35000"),
                    submitted_at=clock_at,
                    filled_at=clock_at,
                ),
                **broker_kwargs,
            ),
        )
        orch = DailyOrchestrator(
            broker=broker,
            market_data=market_data_obj,
            signal=signal_obj,
            strategy=_strategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
            uow_factory=lambda: InMemoryUnitOfWork(),
        )
        return orch, broker

    def test_signal_failure_skips(self):
        orch, _ = self._wired(
            signal=_FakeSignal(raise_error=MarketDataUnavailableError("signal down")),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.MARKET_DATA_UNAVAILABLE
        assert decision.reasoning["stage"] == "signal_collect"

    def test_market_data_unavailable_skips(self):
        asset = _asset()
        inner = MockMarketData(ohlcv_by_asset={asset: [_bar(asset, date(2026, 4, 29), "35000")]})
        fake_md = _FakeMarketData(
            inner=inner, raise_on_get_price=MarketDataUnavailableError("api down"),
        )
        orch, _ = self._wired(market_data=fake_md)
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.MARKET_DATA_UNAVAILABLE
        assert "signal_level" in decision.reasoning  # signal info preserved

    def test_data_integrity_skips(self):
        asset = _asset()
        inner = MockMarketData(ohlcv_by_asset={asset: [_bar(asset, date(2026, 4, 29), "35000")]})
        fake_md = _FakeMarketData(
            inner=inner, raise_on_get_price=DataIntegrityError("high<low"),
        )
        orch, _ = self._wired(market_data=fake_md)
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.DATA_INTEGRITY_ISSUE

    def test_broker_balance_failure_skips(self):
        orch, _ = self._wired(
            broker_kwargs={"balance_error": BrokerConnectionError("network down")},
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_TIMEOUT
        assert decision.reasoning["stage"] == "account_state"


# ---------------------------------------------------------------------------
# Order placement: timeout recovery + rejection
# ---------------------------------------------------------------------------
class TestOrderPlacement:
    def _wire(
        self,
        *,
        place_error: Exception | None = None,
        get_status_result: OrderResult | None = None,
        get_status_error: Exception | None = None,
        place_result: OrderResult | None = None,
    ) -> tuple[DailyOrchestrator, _FakeBroker]:
        asset = _asset()
        clock_at = _utc_after_close(TODAY)
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        broker = _FakeBroker(
            balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
            ),
            place_error=place_error,
            place_result=place_result
            or OrderResult(
                idempotency_key="KRX:069500:2026-04-30",
                asset=asset,
                broker_order_id="bid-1",
                status=OrderStatus.FILLED,
                filled_quantity=Decimal("28"),
                filled_price=Decimal("35000"),
                submitted_at=clock_at,
                filled_at=clock_at,
            ),
            get_status_result=get_status_result,
            get_status_error=get_status_error,
        )
        orch = DailyOrchestrator(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(at=clock_at)),
            strategy=_strategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
            uow_factory=lambda: InMemoryUnitOfWork(),
        )
        return orch, broker

    def test_timeout_recovery_finds_filled_order(self):
        clock_at = _utc_after_close(TODAY)
        orch, _ = self._wire(
            place_error=BrokerConnectionError("timeout"),
            get_status_result=OrderResult(
                idempotency_key="KRX:069500:2026-04-30",
                asset=_asset(),
                broker_order_id="bid-recovered",
                status=OrderStatus.FILLED,
                filled_quantity=Decimal("28"),
                filled_price=Decimal("35000"),
                submitted_at=clock_at,
                filled_at=clock_at,
            ),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action_kinds() == ["buy_split_1"]
        assert decision.buy_action is not None and decision.buy_action.order_id == "bid-recovered"

    def test_timeout_recovery_returns_none_skips(self):
        orch, _ = self._wire(
            place_error=BrokerConnectionError("timeout"),
            get_status_result=None,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_TIMEOUT

    def test_timeout_recovery_get_status_also_fails_skips(self):
        orch, _ = self._wire(
            place_error=BrokerConnectionError("timeout"),
            get_status_error=BrokerConnectionError("status query down"),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_TIMEOUT

    def test_broker_order_error_maps_to_rejected(self):
        orch, _ = self._wire(
            place_error=BrokerOrderError("validation failed"),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_REJECTED

    def test_rejected_order_status_skips(self):
        clock_at = _utc_after_close(TODAY)
        orch, _ = self._wire(
            place_result=OrderResult(
                idempotency_key="KRX:069500:2026-04-30",
                asset=_asset(),
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=clock_at,
                filled_at=None,
            ),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_REJECTED

    def test_unknown_order_status_skips_as_timeout(self):
        clock_at = _utc_after_close(TODAY)
        orch, _ = self._wire(
            place_result=OrderResult(
                idempotency_key="KRX:069500:2026-04-30",
                asset=_asset(),
                broker_order_id=None,
                status=OrderStatus.UNKNOWN,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=clock_at,
                filled_at=None,
            ),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_TIMEOUT

    # Phase 0.5 (ADR 0002 §3.2.1) blocks partial fills end-to-end so the
    # PARTIALLY_FILLED → "buy_split_X_partial" action label can no longer
    # be produced. Phase 1 will reintroduce partial-fill labelling alongside
    # the slot-aware partial-fill redesign.


# ---------------------------------------------------------------------------
# _adjust_quantity (direct unit test for full coverage of all signal levels)
# ---------------------------------------------------------------------------
class TestAdjustQuantity:
    def setup_method(self):
        orch, _ = _make_real_orchestrator()
        self.orch = orch

    def test_normal_passes_through(self):
        result = self.orch._adjust_quantity(            SignalLevel.NORMAL, Decimal("28"), Decimal("1")
        )
        assert result == Decimal("28")

    def test_caution_halves_and_floors(self):
        result = self.orch._adjust_quantity(            SignalLevel.CAUTION, Decimal("28"), Decimal("1")
        )
        assert result == Decimal("14")

    def test_caution_floors_to_lot_size(self):
        # 28 / 2 = 14, floor to 10-multiple = 10
        result = self.orch._adjust_quantity(            SignalLevel.CAUTION, Decimal("28"), Decimal("10")
        )
        assert result == Decimal("10")

    def test_halt_returns_zero(self):
        result = self.orch._adjust_quantity(            SignalLevel.HALT, Decimal("28"), Decimal("1")
        )
        assert result == Decimal(0)

    def test_emergency_returns_zero(self):
        result = self.orch._adjust_quantity(            SignalLevel.EMERGENCY, Decimal("28"), Decimal("1")
        )
        assert result == Decimal(0)


# ---------------------------------------------------------------------------
# IntegrityError propagation
# ---------------------------------------------------------------------------
class TestIntegrityErrorPropagation:
    def test_integrity_error_from_signal_propagates(self):
        asset = _asset()
        clock_at = _utc_after_close(TODAY)
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        signal = _FakeSignal(raise_error=IntegrityError("clock skew"))
        orch = DailyOrchestrator(
            broker=_FakeBroker(
                balance=Balance(cash=Money(amount=Decimal("100"), currency=Currency.KRW))
            ),
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=signal,
            strategy=_strategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
            uow_factory=lambda: InMemoryUnitOfWork(),
        )
        with pytest.raises(IntegrityError):
            orch.run_for_date(TODAY)


# ---------------------------------------------------------------------------
# (Phase 0 TestPendingPartial removed — Phase 0.5 / ADR 0002 §3.2.1 blocks
# partial fills end-to-end, so the partial-fill carry tests no longer apply.)
# ---------------------------------------------------------------------------
# Persistence via uow_factory (ADR §8.5)
# ---------------------------------------------------------------------------
class TestPersistence:
    """Verify run_for_date persists Decision + Order + Position via the UoW."""

    def _orch_with_shared_uow(
        self,
        *,
        broker,
        market_data,
        signal,
        clock_at,
    ):
        shared_uow = InMemoryUnitOfWork()
        orch = DailyOrchestrator(
            broker=broker,
            market_data=market_data,
            signal=signal,
            strategy=_strategy(),
            config=_config(),
            asset=_asset(),
            clock=lambda: clock_at,
            uow_factory=lambda: shared_uow,
        )
        return orch, shared_uow

    def test_buy_decision_persists_decision_order_and_position(self):
        # Real Mock broker with default rates: place_order returns FILLED.
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
            ),
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        orch, uow = self._orch_with_shared_uow(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=NullSignal(),
            clock_at=clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action_kinds() == ["buy_split_1"]

        # Decision saved
        saved_decisions = uow.decisions.list_by_date_range(TODAY, TODAY)
        assert len(saved_decisions) == 1
        assert saved_decisions[0].action_kinds() == ["buy_split_1"]

        # Order saved (FILLED)
        saved_order = uow.orders.get_by_idempotency_key(
            "KRX:069500:2026-04-30"
        )
        assert saved_order is not None
        assert saved_order.status is OrderStatus.FILLED

        # Position saved
        saved_position = uow.positions.get(asset.fqn)
        assert saved_position is not None
        assert saved_position.quantity > 0

    def test_skip_decision_saves_decision_only_no_order_no_position(self):
        # HALT signal short-circuits before broker; no Order, no Position.
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        broker = _FakeBroker(
            balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
            ),
        )
        orch, uow = self._orch_with_shared_uow(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(level=SignalLevel.HALT, at=clock_at)),
            clock_at=clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.is_skip()

        # Decision saved
        assert len(uow.decisions.list_by_date_range(TODAY, TODAY)) == 1
        # No Order, no Position
        assert uow.orders.get_by_idempotency_key("KRX:069500:2026-04-30") is None
        assert uow.positions.get(asset.fqn) is None

    def test_broker_timeout_with_no_recovery_skips_order_save(self):
        # BrokerConnectionError + recovery returns None → no Order persisted.
        asset = _asset()
        clock_at = _utc_after_close(TODAY)
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        broker = _FakeBroker(
            balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
            ),
            place_error=BrokerConnectionError("timeout"),
            get_status_result=None,  # recovery fails
        )
        orch, uow = self._orch_with_shared_uow(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(at=clock_at)),
            clock_at=clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_TIMEOUT
        # Decision saved, but no Order or Position
        assert len(uow.decisions.list_by_date_range(TODAY, TODAY)) == 1
        assert uow.orders.get_by_idempotency_key(
            "KRX:069500:2026-04-30"
        ) is None
        assert uow.positions.get(asset.fqn) is None

    def test_broker_order_error_skips_order_save(self):
        # BrokerOrderError → Order never accepted → no Order to save.
        asset = _asset()
        clock_at = _utc_after_close(TODAY)
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        broker = _FakeBroker(
            balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
            ),
            place_error=BrokerOrderError("validation"),
        )
        orch, uow = self._orch_with_shared_uow(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(at=clock_at)),
            clock_at=clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_REJECTED
        assert uow.orders.get_by_idempotency_key(
            "KRX:069500:2026-04-30"
        ) is None
        assert uow.positions.get(asset.fqn) is None

    def test_rejected_order_status_persists_order_record_for_audit(self):
        # Broker accepts the request but returns REJECTED status →
        # Order record is saved (audit trail). No Position update.
        asset = _asset()
        clock_at = _utc_after_close(TODAY)
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        broker = _FakeBroker(
            balance=Balance(
                cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
            ),
            place_result=OrderResult(
                idempotency_key="KRX:069500:2026-04-30",
                asset=asset,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=clock_at,
                filled_at=None,
            ),
        )
        orch, uow = self._orch_with_shared_uow(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=_FakeSignal(signal=_signal(at=clock_at)),
            clock_at=clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.skip_reason is SkipReason.BROKER_REJECTED
        # Order saved with REJECTED status — audit trail
        saved = uow.orders.get_by_idempotency_key("KRX:069500:2026-04-30")
        assert saved is not None
        assert saved.status is OrderStatus.REJECTED
        # No Position update on rejection
        assert uow.positions.get(asset.fqn) is None

    # Phase 0 partial-fill persistence test removed — Phase 0.5 (ADR 0002
    # §3.2.1) blocks partial fills end-to-end. Phase 1 will reintroduce
    # both the broker capability and the persistence test alongside the
    # slot-aware partial-fill redesign.
