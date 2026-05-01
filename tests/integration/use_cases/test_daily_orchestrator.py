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
)
from src.domain.strategies.price_drop import PriceDropStrategy, SplitStrategyConfig
from src.use_cases.daily_orchestrator import DailyOrchestrator, SkipReason

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
) -> Position:
    """Build a Position with auto-generated entries summing to `quantity`."""
    qty = Decimal(quantity)
    avg = Decimal(avg_price)
    if split_level == 0:
        entries: list[SplitEntry] = []
    else:
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
    return Position(
        asset=asset,
        quantity=qty,
        avg_price=avg,
        split_level=split_level,
        last_buy_at=last_buy_at,
        entries=entries,
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
    partial_fill_rate: float = 0.0,
    clock_at: datetime | None = None,
) -> tuple[DailyOrchestrator, MockBroker]:
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
        simulate_partial_fill_rate=partial_fill_rate,
    )
    market_data = MockMarketData(ohlcv_by_asset={asset: bars})
    signal = NullSignal()
    strategy = PriceDropStrategy()

    orchestrator = DailyOrchestrator(
        broker=broker,
        market_data=market_data,
        signal=signal,
        strategy=strategy,
        config=_config(),
        asset=asset,
        clock=lambda: clock_at,
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
        assert decision.action == "buy_split_1"
        assert decision.resulting_order_id is not None
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
        assert decision.action == "buy_split_2"
        assert decision.reasoning["next_split_level"] == "2"


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
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
        )
        return orch, broker

    def test_halt_short_circuits_before_broker_calls(self):
        orch, broker = self._make_with_signal(SignalLevel.HALT)
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.CIRCUIT_BREAKER_HALT.value}"
        assert decision.resulting_order_id is None
        assert broker.placed == []  # broker was never asked to place anything

    def test_emergency_short_circuits(self):
        orch, broker = self._make_with_signal(SignalLevel.EMERGENCY)
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.CIRCUIT_BREAKER_HALT.value}"
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
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == "buy_split_1"
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
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.QUANTITY_TOO_SMALL.value}"
        assert decision.reasoning["pre_adjust_quantity"] == "20"
        assert decision.reasoning["adjusted_quantity"] == "0"


# ---------------------------------------------------------------------------
# Strategy-side skip mapping
# ---------------------------------------------------------------------------
class TestStrategySkipMapping:
    def test_max_split_reached_maps_to_strategy_no_buy(self):
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
        assert decision.action == f"skip:{SkipReason.STRATEGY_NO_BUY.value}"
        assert decision.reasoning["strategy_reason"] == "skip:max_split_reached"

    def test_drop_insufficient_maps_to_strategy_no_buy(self):
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "33500")]  # only 4.28% drop
        orch, broker = _make_real_orchestrator(asset=asset, bars=bars)
        broker._positions[asset.fqn] = _seeded_position(
            asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
            last_buy_at=_utc_after_close(date(2026, 4, 28)),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.STRATEGY_NO_BUY.value}"
        assert decision.reasoning["strategy_reason"] == "skip:drop_insufficient"

    def test_quantity_below_lot_size_maps_to_quantity_too_small(self):
        asset = _asset(lot_size="100")  # huge lot
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        orch, _ = _make_real_orchestrator(asset=asset, bars=bars)
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.QUANTITY_TOO_SMALL.value}"
        assert decision.reasoning["strategy_reason"] == "skip:quantity_below_lot_size"

    def test_insufficient_balance_maps_directly(self):
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        small_balance = Balance(cash=Money(amount=Decimal("100"), currency=Currency.KRW))
        orch, _ = _make_real_orchestrator(
            asset=asset, bars=bars, initial_balance=small_balance,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.INSUFFICIENT_BALANCE.value}"
        assert decision.reasoning["strategy_reason"] == "skip:insufficient_balance"


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
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
        )
        return orch, broker

    def test_signal_failure_skips(self):
        orch, _ = self._wired(
            signal=_FakeSignal(raise_error=MarketDataUnavailableError("signal down")),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.MARKET_DATA_UNAVAILABLE.value}"
        assert decision.reasoning["stage"] == "signal_collect"

    def test_market_data_unavailable_skips(self):
        asset = _asset()
        inner = MockMarketData(ohlcv_by_asset={asset: [_bar(asset, date(2026, 4, 29), "35000")]})
        fake_md = _FakeMarketData(
            inner=inner, raise_on_get_price=MarketDataUnavailableError("api down"),
        )
        orch, _ = self._wired(market_data=fake_md)
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.MARKET_DATA_UNAVAILABLE.value}"
        assert "signal_level" in decision.reasoning  # signal info preserved

    def test_data_integrity_skips(self):
        asset = _asset()
        inner = MockMarketData(ohlcv_by_asset={asset: [_bar(asset, date(2026, 4, 29), "35000")]})
        fake_md = _FakeMarketData(
            inner=inner, raise_on_get_price=DataIntegrityError("high<low"),
        )
        orch, _ = self._wired(market_data=fake_md)
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.DATA_INTEGRITY_ISSUE.value}"

    def test_broker_balance_failure_skips(self):
        orch, _ = self._wired(
            broker_kwargs={"balance_error": BrokerConnectionError("network down")},
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.BROKER_TIMEOUT.value}"
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
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
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
        assert decision.action == "buy_split_1"
        assert decision.resulting_order_id == "bid-recovered"

    def test_timeout_recovery_returns_none_skips(self):
        orch, _ = self._wire(
            place_error=BrokerConnectionError("timeout"),
            get_status_result=None,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.BROKER_TIMEOUT.value}"

    def test_timeout_recovery_get_status_also_fails_skips(self):
        orch, _ = self._wire(
            place_error=BrokerConnectionError("timeout"),
            get_status_error=BrokerConnectionError("status query down"),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.BROKER_TIMEOUT.value}"

    def test_broker_order_error_maps_to_rejected(self):
        orch, _ = self._wire(
            place_error=BrokerOrderError("validation failed"),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == f"skip:{SkipReason.BROKER_REJECTED.value}"

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
        assert decision.action == f"skip:{SkipReason.BROKER_REJECTED.value}"

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
        assert decision.action == f"skip:{SkipReason.BROKER_TIMEOUT.value}"

    def test_partial_fill_action_label(self):
        clock_at = _utc_after_close(TODAY)
        orch, _ = self._wire(
            place_result=OrderResult(
                idempotency_key="KRX:069500:2026-04-30",
                asset=_asset(),
                broker_order_id="bid-partial",
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity=Decimal("14"),
                filled_price=Decimal("35000"),
                submitted_at=clock_at,
                filled_at=clock_at,
            ),
        )
        decision = orch.run_for_date(TODAY)
        assert decision.action == "buy_split_1_partial"
        assert decision.reasoning["filled_quantity"] == "14"


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
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
        )
        with pytest.raises(IntegrityError):
            orch.run_for_date(TODAY)


# ---------------------------------------------------------------------------
# Pending partial fill (ADR §7.9)
# ---------------------------------------------------------------------------
class TestPendingPartial:
    def test_partial_fill_does_not_become_split_entry_next_day(self):
        # Day T: partial fill produces a partial-only Position
        # (entries=[], pending_partial_quantity > 0).
        # Day T+1: orchestrator runs again; entries must remain empty
        # because partials are never retroactively promoted (CLAUDE.md §4.4).
        asset = _asset()
        bars_t = [_bar(asset, date(2026, 4, 29), "35000")]
        balance = Balance(
            cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
        )
        clock_t = _utc_after_close(TODAY)
        broker = MockBroker(
            initial_balance=balance,
            clock=lambda: clock_t,
            rng=random.Random(42),
            simulate_partial_fill_rate=1.0,  # force partial
        )
        orch = DailyOrchestrator(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars_t}),
            signal=NullSignal(),
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_t,
        )
        decision_t = orch.run_for_date(TODAY)
        # Partial fill action and warning surfaced
        assert decision_t.action.endswith("_partial")
        position_after_t = broker.get_positions()[0]
        assert position_after_t.entries == []
        assert position_after_t.has_pending_partial() is True

        # Day T+1: turn off partial-fill rate; price drops further (no buy
        # because drop check uses avg_price, but even if buy fires, partial
        # entries from T MUST NOT appear).
        next_day = date(2026, 5, 1)
        bars_tplus1 = [
            *bars_t,
            _bar(asset, next_day, "35100"),  # tiny up-move; no buy expected
        ]
        clock_tplus1 = _utc_after_close(next_day)
        broker._partial_fill_rate = 0.0
        # Re-wire orchestrator with the same broker (state persists) and
        # the new clock + extended market data.
        orch2 = DailyOrchestrator(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars_tplus1}),
            signal=NullSignal(),
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_tplus1,
        )
        orch2.run_for_date(next_day)
        position_after_tplus1 = broker.get_positions()[0]
        # Entries STILL empty — partial from T was never promoted
        assert position_after_tplus1.entries == []
        assert position_after_tplus1.has_pending_partial() is True

    def test_decision_logs_pending_partial_warning(self):
        # Seed a Position with pending_partial > 0 (entries summing < quantity)
        # and verify the orchestrator's Decision.reasoning carries the warning.
        asset = _asset()
        bars = [_bar(asset, date(2026, 4, 29), "35000")]
        clock_at = _utc_after_close(TODAY)
        balance = Balance(
            cash=Money(amount=Decimal("100000000"), currency=Currency.KRW)
        )
        broker = MockBroker(
            initial_balance=balance,
            clock=lambda: clock_at,
            rng=random.Random(42),
        )
        # Seed a partial-only position (entries empty; quantity > 0):
        seed = Position(
            asset=asset,
            quantity=Decimal("5"),
            avg_price=Decimal("35000"),
            split_level=0,
            last_buy_at=_utc_after_close(date(2026, 4, 28)),
            entries=[],
        )
        broker._positions[asset.fqn] = seed
        # Need to also pre-debit cash to keep balance consistent
        # (5 shares @ 35000 = 175,000 cost). Skipping for test simplicity —
        # balance still ample for next attempted order.
        orch = DailyOrchestrator(
            broker=broker,
            market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
            signal=NullSignal(),
            strategy=PriceDropStrategy(),
            config=_config(),
            asset=asset,
            clock=lambda: clock_at,
        )
        decision = orch.run_for_date(TODAY)
        assert decision.reasoning.get("pending_partial_warning") == "True"
        assert decision.reasoning.get("pending_partial_quantity") == "5"
