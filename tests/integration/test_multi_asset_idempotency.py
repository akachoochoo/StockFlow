"""Multi-asset idempotency key uniqueness regression (ADR 0003 §10.3).

Verifies that same-day multi-asset runs (069500 + 214980) produce
idempotency keys that are globally unique across assets and that
DB UNIQUE constraint on orders.idempotency_key (TEXT PRIMARY KEY)
prevents duplicate insertion at the SQLite level.

Four scenarios:
    1. Both assets BUY slot 1 on the same day (first-entry).
    2. Both assets SELL slot 1 on the same day (profit target).
    3. Mixed: A BUY slot 1 + B SELL slot 1.
    4. DB UNIQUE constraint direct verification (integrity error on dup insert).
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.market_data import MockMarketData
from src.adapters.mock.signals import NullSignal
from src.cli.composition import kodex200, kodex_short_bond_plus
from src.domain.constants import KST
from src.domain.models import (
    OHLCV,
    Balance,
    Currency,
    Money,
    OrderSide,
    OrderStatus,
    Position,
    SplitEntry,
    SplitSlot,
)
from src.domain.strategies.price_drop import PriceDropStrategy, SplitStrategyConfig
from src.domain.strategies.profit_target import ProfitTargetSell, SellStrategyConfig
from src.domain.strategies.reentry import HybridTimeBasedReentry
from src.infrastructure.db import connect
from src.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork
from src.use_cases.asset_context import AssetContext
from src.use_cases.daily_orchestrator import DailyOrchestrator

if TYPE_CHECKING:
    from pathlib import Path

    from src.domain.models import Asset


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRADE_DATE = date(2026, 5, 3)
AS_OF_UTC: datetime = datetime.combine(
    TRADE_DATE, time(7, 0, 0), tzinfo=UTC  # KST 16:00 = UTC 07:00
)
INITIAL_CASH = Decimal("100_000_000")  # 100M KRW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utc(d: date) -> datetime:
    return datetime.combine(d, time(16, 0), tzinfo=KST).astimezone(UTC)


def _bar(asset: Asset, d: date, close: str) -> OHLCV:
    return OHLCV(
        asset=asset,
        trade_date=d,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1_000_000"),
    )


def _strategy() -> PriceDropStrategy:
    return PriceDropStrategy(reentry=HybridTimeBasedReentry(cooldown_days=60))


def _config(drop_threshold_pct: str = "5.0") -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal(drop_threshold_pct),
        max_split_count=7,
        per_split_amount=Money(amount=Decimal("5_000_000"), currency=Currency.KRW),
    )


def _sell_config(profit_target_pct: str = "10.0") -> SellStrategyConfig:
    return SellStrategyConfig(
        profit_target_pct=Decimal(profit_target_pct),
        max_sells_per_day=7,
    )


def _filled_position_slot1(
    asset: Asset,
    *,
    entry_price: str,
    quantity: str = "1",
) -> Position:
    """Build a Position with exactly slot 1 FILLED and slots 2-7 EMPTY."""
    entry = SplitEntry(
        split_number=1,
        entry_date=date(2026, 4, 1),
        quantity=Decimal(quantity),
        entry_price=Decimal(entry_price),
        idempotency_key="seed-1",
    )
    slots: list[SplitSlot] = [SplitSlot.filled(entry=entry)]
    slots.extend(SplitSlot.empty(slot_number=i) for i in range(2, 8))
    return Position(
        asset=asset,
        quantity=Decimal(quantity),
        avg_price=Decimal(entry_price),
        split_level=1,
        last_buy_at=_utc(date(2026, 4, 1)),
        slots=slots,
    )


def _uow_factory(conn: sqlite3.Connection):
    def factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(conn)
    return factory


def _orders_by_key(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Dump orders table as {idempotency_key: Row}."""
    rows = conn.execute("SELECT * FROM orders").fetchall()
    return {row["idempotency_key"]: row for row in rows}


def _decisions_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()
    assert row is not None
    return row[0]


# ---------------------------------------------------------------------------
# Scenario 1 — same-day BUY both assets (first-entry)
# ---------------------------------------------------------------------------
class TestScenario1SameDayBuyBothAssets:
    """Both 069500 and 214980 enter first-buy on the same date.

    ADR §10.3 박제: idempotency keys differ because asset.fqn prefix differs.
    DB UNIQUE constraint satisfied — commit succeeds.
    """

    @pytest.fixture
    def conn(self, tmp_path: Path) -> sqlite3.Connection:
        return connect(tmp_path / "test.db")

    def test_two_buy_decisions_unique_keys(self, conn: sqlite3.Connection) -> None:
        asset_a = kodex200()      # KRX:069500
        asset_b = kodex_short_bond_plus()  # KRX:214980

        # Both assets at a price that triggers first-entry:
        # position=None + HybridTimeBasedReentry → trigger = current_price → always fires.
        price_a = "35000"
        price_b = "100000"

        bars: dict = {
            asset_a: [
                _bar(asset_a, TRADE_DATE - __import__("datetime").timedelta(days=1), price_a),
                _bar(asset_a, TRADE_DATE, price_a),
            ],
            asset_b: [
                _bar(asset_b, TRADE_DATE - __import__("datetime").timedelta(days=1), price_b),
                _bar(asset_b, TRADE_DATE, price_b),
            ],
        }
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=INITIAL_CASH, currency=Currency.KRW)
            ),
            clock=lambda: AS_OF_UTC,
        )
        # No pre-seeded positions — both assets have empty state (first-entry).
        market_data = MockMarketData(ohlcv_by_asset=bars)

        ctx_a = AssetContext(
            asset=asset_a,
            strategy=_strategy(),
            config=_config(),
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        ctx_b = AssetContext(
            asset=asset_b,
            strategy=_strategy(),
            config=_config(),
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        orchestrator = DailyOrchestrator(
            broker=broker,
            market_data=market_data,
            signal=NullSignal(),
            asset_contexts=[ctx_a, ctx_b],
            clock=lambda: AS_OF_UTC,
            uow_factory=_uow_factory(conn),
        )

        decisions = orchestrator.run_for_date(TRADE_DATE)

        # Two decisions (one per asset).
        assert len(decisions) == 2

        # Both must be BUY (first-entry).
        for d in decisions:
            assert d.buy_action is not None, (
                f"Expected BUY for {d.asset.fqn}, got skip_reason={d.skip_reason}"
            )
            assert d.buy_action.slot_number == 1

        # Two orders in DB.
        orders = _orders_by_key(conn)
        assert len(orders) == 2, f"Expected 2 orders, got {len(orders)}: {list(orders)}"

        # Both BUY, both FILLED.
        for key, row in orders.items():
            assert row["side"] == OrderSide.BUY.value, f"Expected BUY for {key}"
            assert row["status"] == OrderStatus.FILLED.value, f"Expected FILLED for {key}"

        # Key format: {asset.fqn}:{date}:buy:1
        key_a = f"KRX:069500:{TRADE_DATE.isoformat()}:buy:1"
        key_b = f"KRX:214980:{TRADE_DATE.isoformat()}:buy:1"
        assert key_a in orders, f"Missing key {key_a!r}; found {list(orders)}"
        assert key_b in orders, f"Missing key {key_b!r}; found {list(orders)}"

        # Keys are distinct (asset.fqn prefix differs).
        assert key_a != key_b

        # DB UNIQUE constraint survived — both commits succeeded.
        assert _decisions_count(conn) == 2


# ---------------------------------------------------------------------------
# Scenario 2 — same-day SELL both assets (slot 1 profit target)
# ---------------------------------------------------------------------------
class TestScenario2SameDaySellBothAssets:
    """Both assets have slot 1 FILLED at +15% profit, sell on the same day.

    drop_threshold_pct=50% ensures no reentry BUY fires after the sell.
    ADR §10.3: SELL keys differ by asset.fqn.
    """

    @pytest.fixture
    def conn(self, tmp_path: Path) -> sqlite3.Connection:
        return connect(tmp_path / "test.db")

    def test_two_sell_decisions_unique_keys(self, conn: sqlite3.Connection) -> None:
        asset_a = kodex200()
        asset_b = kodex_short_bond_plus()

        # Entry prices: A=10000, B=100000.  Current prices +15% → profit >10% target.
        entry_a, price_a = "10000", "11500"
        entry_b, price_b = "100000", "115000"

        bars: dict = {
            asset_a: [
                _bar(asset_a, TRADE_DATE - __import__("datetime").timedelta(days=1), price_a),
                _bar(asset_a, TRADE_DATE, price_a),
            ],
            asset_b: [
                _bar(asset_b, TRADE_DATE - __import__("datetime").timedelta(days=1), price_b),
                _bar(asset_b, TRADE_DATE, price_b),
            ],
        }
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=INITIAL_CASH, currency=Currency.KRW)
            ),
            clock=lambda: AS_OF_UTC,
        )
        # Seed FILLED positions for both assets.
        broker.set_position(_filled_position_slot1(asset_a, entry_price=entry_a))
        broker.set_position(_filled_position_slot1(asset_b, entry_price=entry_b))

        market_data = MockMarketData(ohlcv_by_asset=bars)

        # drop_threshold_pct=50% — current price is only +15% above entry,
        # so reentry trigger = last_exit_price * (1 - 0.50) is far below,
        # but after sell the position is empty so fresh first-buy would fire.
        # Use a very conservative drop_threshold (50%) for BUY config so
        # current price won't be <= trigger for a NEW first-entry:
        # HybridTimeBasedReentry after sell: slot has last_exit_price set.
        # trigger = last_exit_price * (1 - 50/100) = 11500 * 0.5 = 5750 (A)
        # current_price=11500 > 5750 → no BUY. Same for B.
        conservative_config = _config(drop_threshold_pct="50.0")

        ctx_a = AssetContext(
            asset=asset_a,
            strategy=_strategy(),
            config=conservative_config,
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        ctx_b = AssetContext(
            asset=asset_b,
            strategy=_strategy(),
            config=conservative_config,
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        orchestrator = DailyOrchestrator(
            broker=broker,
            market_data=market_data,
            signal=NullSignal(),
            asset_contexts=[ctx_a, ctx_b],
            clock=lambda: AS_OF_UTC,
            uow_factory=_uow_factory(conn),
        )

        decisions = orchestrator.run_for_date(TRADE_DATE)

        assert len(decisions) == 2

        # Both decisions should have sell_actions (slot 1).
        for d in decisions:
            assert len(d.sell_actions) >= 1, (
                f"Expected at least 1 sell for {d.asset.fqn}, "
                f"got skip_reason={d.skip_reason}"
            )
            assert d.sell_actions[0].slot_number == 1

        # At least 2 SELL orders in DB.
        orders = _orders_by_key(conn)
        sell_orders = {k: v for k, v in orders.items() if v["side"] == OrderSide.SELL.value}
        assert len(sell_orders) >= 2, f"Expected >=2 SELL orders; got {list(sell_orders)}"

        # SELL key format: {asset.fqn}:{date}:sell:1
        key_a = f"KRX:069500:{TRADE_DATE.isoformat()}:sell:1"
        key_b = f"KRX:214980:{TRADE_DATE.isoformat()}:sell:1"
        assert key_a in orders, f"Missing {key_a!r}; found {list(orders)}"
        assert key_b in orders, f"Missing {key_b!r}; found {list(orders)}"

        # Keys are distinct.
        assert key_a != key_b

        # Decisions persisted.
        assert _decisions_count(conn) == 2


# ---------------------------------------------------------------------------
# Scenario 3 — mixed: A BUY slot 1 + B SELL slot 1
# ---------------------------------------------------------------------------
class TestScenario3MixedBuyAndSell:
    """A (069500) has no position → first-entry BUY.
    B (214980) has slot 1 FILLED at +15% → SELL slot 1.

    Keys: buy key and sell key both contain slot_number=1 but differ by
    asset.fqn AND side — no UNIQUE collision.
    """

    @pytest.fixture
    def conn(self, tmp_path: Path) -> sqlite3.Connection:
        return connect(tmp_path / "test.db")

    def test_mixed_buy_and_sell_unique_keys(self, conn: sqlite3.Connection) -> None:
        asset_a = kodex200()
        asset_b = kodex_short_bond_plus()

        price_a = "35000"
        entry_b, price_b = "100000", "115000"

        import datetime as _dt
        bars: dict = {
            asset_a: [
                _bar(asset_a, TRADE_DATE - _dt.timedelta(days=1), price_a),
                _bar(asset_a, TRADE_DATE, price_a),
            ],
            asset_b: [
                _bar(asset_b, TRADE_DATE - _dt.timedelta(days=1), price_b),
                _bar(asset_b, TRADE_DATE, price_b),
            ],
        }
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=INITIAL_CASH, currency=Currency.KRW)
            ),
            clock=lambda: AS_OF_UTC,
        )
        # A: no position (first-entry BUY).
        # B: slot 1 FILLED at entry_b, current +15% → triggers sell.
        broker.set_position(_filled_position_slot1(asset_b, entry_price=entry_b))

        market_data = MockMarketData(ohlcv_by_asset=bars)

        # B: after sell, conservative config prevents re-buy
        # (same logic as scenario 2 — 50% threshold, exit_price * 0.5 << current).
        conservative_config = _config(drop_threshold_pct="50.0")

        ctx_a = AssetContext(
            asset=asset_a,
            strategy=_strategy(),
            config=_config(),            # normal config for A (first-entry fires)
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        ctx_b = AssetContext(
            asset=asset_b,
            strategy=_strategy(),
            config=conservative_config,  # conservative BUY config for B
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        orchestrator = DailyOrchestrator(
            broker=broker,
            market_data=market_data,
            signal=NullSignal(),
            asset_contexts=[ctx_a, ctx_b],
            clock=lambda: AS_OF_UTC,
            uow_factory=_uow_factory(conn),
        )

        decisions = orchestrator.run_for_date(TRADE_DATE)

        assert len(decisions) == 2

        decision_a = next(d for d in decisions if d.asset == asset_a)
        decision_b = next(d for d in decisions if d.asset == asset_b)

        # A: BUY slot 1.
        assert decision_a.buy_action is not None, (
            f"Expected BUY for A, got skip_reason={decision_a.skip_reason}"
        )
        assert decision_a.buy_action.slot_number == 1

        # B: at least one SELL slot 1.
        assert len(decision_b.sell_actions) >= 1, (
            f"Expected SELL for B, got skip_reason={decision_b.skip_reason}"
        )
        assert decision_b.sell_actions[0].slot_number == 1

        # Orders in DB.
        orders = _orders_by_key(conn)

        buy_key_a = f"KRX:069500:{TRADE_DATE.isoformat()}:buy:1"
        sell_key_b = f"KRX:214980:{TRADE_DATE.isoformat()}:sell:1"

        assert buy_key_a in orders, f"Missing {buy_key_a!r}; found {list(orders)}"
        assert sell_key_b in orders, f"Missing {sell_key_b!r}; found {list(orders)}"

        # Same slot_number (1) but different asset + side → distinct keys.
        assert buy_key_a != sell_key_b

        # Both orders have correct side.
        assert orders[buy_key_a]["side"] == OrderSide.BUY.value
        assert orders[sell_key_b]["side"] == OrderSide.SELL.value

        # Decisions persisted.
        assert _decisions_count(conn) == 2


# ---------------------------------------------------------------------------
# Scenario 4 — DB UNIQUE constraint direct verification
# ---------------------------------------------------------------------------
class TestScenario4DbUniqueConstraint:
    """After scenario-1 commits two BUY orders, attempting to INSERT one of
    those same idempotency_keys again must raise sqlite3.IntegrityError.

    This proves the DB-level guard is alive independent of the orchestrator.
    """

    @pytest.fixture
    def conn(self, tmp_path: Path) -> sqlite3.Connection:
        return connect(tmp_path / "test.db")

    def test_duplicate_idempotency_key_raises_integrity_error(
        self, conn: sqlite3.Connection,
    ) -> None:
        asset_a = kodex200()
        asset_b = kodex_short_bond_plus()

        price_a = "35000"
        price_b = "100000"

        import datetime as _dt
        bars: dict = {
            asset_a: [
                _bar(asset_a, TRADE_DATE - _dt.timedelta(days=1), price_a),
                _bar(asset_a, TRADE_DATE, price_a),
            ],
            asset_b: [
                _bar(asset_b, TRADE_DATE - _dt.timedelta(days=1), price_b),
                _bar(asset_b, TRADE_DATE, price_b),
            ],
        }
        broker = MockBroker(
            initial_balance=Balance(
                cash=Money(amount=INITIAL_CASH, currency=Currency.KRW)
            ),
            clock=lambda: AS_OF_UTC,
        )
        market_data = MockMarketData(ohlcv_by_asset=bars)

        ctx_a = AssetContext(
            asset=asset_a,
            strategy=_strategy(),
            config=_config(),
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        ctx_b = AssetContext(
            asset=asset_b,
            strategy=_strategy(),
            config=_config(),
            sell_strategy=ProfitTargetSell(),
            sell_config=_sell_config(),
        )
        orchestrator = DailyOrchestrator(
            broker=broker,
            market_data=market_data,
            signal=NullSignal(),
            asset_contexts=[ctx_a, ctx_b],
            clock=lambda: AS_OF_UTC,
            uow_factory=_uow_factory(conn),
        )
        decisions = orchestrator.run_for_date(TRADE_DATE)

        # Precondition: both assets bought (scenario-1 conditions).
        assert all(d.buy_action is not None for d in decisions), (
            f"Precondition failed: expected both to BUY. "
            f"skip_reasons={[d.skip_reason for d in decisions]}"
        )

        # Grab one existing key from the DB.
        orders = _orders_by_key(conn)
        assert len(orders) == 2
        existing_key = next(iter(orders))  # pick any one

        # Attempt a direct INSERT with the same idempotency_key (PRIMARY KEY).
        # SQLite must reject this with IntegrityError.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO orders (
                    idempotency_key, asset_fqn, asset_json, side,
                    order_type, quantity, target_price, status,
                    broker_order_id, filled_quantity, filled_price,
                    submitted_at, filled_at
                ) VALUES (?, 'KRX:069500', '{}', 'buy', 'limit',
                          '1', '35000', 'FILLED', NULL,
                          '1', '35000', '2026-05-03T07:00:00+00:00', NULL)
                """,
                (existing_key,),
            )
            conn.commit()
