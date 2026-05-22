"""Confirmation test — PARTIALLY_FILLED buy does NOT advance split_level.

This is a *regression guard*, not new behaviour. CLAUDE.md §4.4 + ADR 0002 §3
require that a partial fill is never counted as a completed split. The
orchestrator already enforces this (daily_orchestrator.py:462 — a
``BuyActionRecord`` with ``split_level_after = prior + 1`` is built ONLY when
``order_result.status is OrderStatus.FILLED``; PARTIALLY_FILLED falls through
to the non-FILLED branch and produces a skip Decision with no buy action and
no position save). Phase 1.1 Stage 6 pins that invariant.

The orchestrator is wired with a fake BrokerPort that returns PARTIALLY_FILLED
for the first buy. The assertion is: no buy action, skip_reason set, and no
updated Position persisted (so split_level stays at its prior value).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.adapters.mock.market_data import MockMarketData
from src.domain.constants import KST
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Balance,
    CircuitBreakerSignal,
    Currency,
    Exchange,
    Market,
    Money,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
    SignalLevel,
    SignalSource,
)
from src.domain.strategies.price_drop import PriceDropStrategy, SplitStrategyConfig
from src.domain.strategies.profit_target import ProfitTargetSell, SellStrategyConfig
from src.domain.strategies.reentry import HybridTimeBasedReentry
from src.use_cases.asset_context import AssetContext
from src.use_cases.daily_orchestrator import DailyOrchestrator, SkipReason

TODAY = date(2026, 4, 30)


def _utc_after_close(d: date) -> datetime:
    return datetime.combine(d, time(16, 0), tzinfo=KST).astimezone(UTC)


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


class _PartialFillBroker:
    """BrokerPort returning PARTIALLY_FILLED for any placed BUY order."""

    def __init__(self, *, balance: Balance, clock_at: datetime) -> None:
        self._balance = balance
        self._clock_at = clock_at
        self.placed: list[OrderRequest] = []
        self.saved_positions: list[Position] = []

    def get_balance(self) -> Balance:
        return self._balance

    def get_positions(self) -> list[Position]:
        return []

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.placed.append(request)
        # Fill strictly less than requested → PARTIALLY_FILLED (must be > 0 and
        # < quantity per OrderResult/Order invariants).
        partial_qty = request.quantity - Decimal(1)
        assert partial_qty > 0
        return OrderResult(
            idempotency_key=request.idempotency_key,
            asset=request.asset,
            broker_order_id="broker-partial-1",
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=partial_qty,
            filled_price=request.target_price,
            submitted_at=self._clock_at,
            filled_at=self._clock_at,
        )

    def get_order_status(self, idempotency_key: str) -> OrderResult | None:
        del idempotency_key
        return None

    def cancel_order(self, broker_order_id: str) -> bool:
        del broker_order_id
        return False


def _signal(clock_at: datetime) -> CircuitBreakerSignal:
    return CircuitBreakerSignal(
        level=SignalLevel.NORMAL,
        source=SignalSource.NULL,
        asset_class=AssetClass.KR_ETF,
        evaluated_at=clock_at,
        triggered_by=[],
        reasoning={},
        valid_until=clock_at + timedelta(days=1),
    )


class _FixedSignal:
    def __init__(self, signal: CircuitBreakerSignal) -> None:
        self._signal = signal

    def collect(self, asset_class: AssetClass, as_of: datetime) -> CircuitBreakerSignal:
        del asset_class, as_of
        return self._signal


def _config() -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal("7.0"),
        max_split_count=7,
        per_split_amount=Money(amount=Decimal("1000000"), currency=Currency.KRW),
    )


def test_partial_fill_blocks_split_level():
    """A PARTIALLY_FILLED first buy must NOT advance split_level (CLAUDE.md §4.4)."""
    asset = _asset()
    bars = [_bar(asset, date(2026, 4, 29), "35000")]
    clock_at = _utc_after_close(TODAY)
    balance = Balance(cash=Money(amount=Decimal("100000000"), currency=Currency.KRW))
    broker = _PartialFillBroker(balance=balance, clock_at=clock_at)

    saved: list[Position] = []

    class _RecordingUoW(InMemoryUnitOfWork):
        def __init__(self) -> None:
            super().__init__()
            _orig_save = self.positions.save

            def _spy(position: Position) -> None:
                saved.append(position)
                _orig_save(position)

            self.positions.save = _spy  # type: ignore[method-assign]

    orch = DailyOrchestrator(
        broker=broker,
        market_data=MockMarketData(ohlcv_by_asset={asset: bars}),
        signal=_FixedSignal(_signal(clock_at)),
        asset_contexts=[
            AssetContext(
                asset=asset,
                strategy=PriceDropStrategy(
                    reentry=HybridTimeBasedReentry(cooldown_days=60)
                ),
                config=_config(),
                sell_strategy=ProfitTargetSell(),
                sell_config=SellStrategyConfig(
                    profit_target_pct=Decimal("10.0"), max_sells_per_day=7
                ),
            )
        ],
        clock=lambda: clock_at,
        uow_factory=_RecordingUoW,
    )

    decisions = orch.run_for_date(TODAY)
    decision = decisions[0]

    # The broker WAS asked to place a BUY (so we really exercised the path).
    assert len(broker.placed) == 1
    # PARTIALLY_FILLED → no completed split: no buy action, decision is a skip.
    assert decision.buy_action is None
    assert decision.is_skip()
    assert decision.skip_reason is SkipReason.BROKER_TIMEOUT
    assert decision.reasoning["order_status"] == OrderStatus.PARTIALLY_FILLED.value
    # No Position with an advanced split_level was persisted (split stays at 0).
    assert all(p.split_level == 0 for p in saved)
