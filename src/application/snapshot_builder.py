"""DailySnapshotBuilder — end-of-day portfolio valuation + snapshot save.

Per ADR §8.7, this is a separate workflow from `DailyOrchestrator.run_for_date`.
The CLI / scheduler calls them in sequence (orchestrator → builder), so a
broker reconciliation between decisions and the snapshot is the runner's
choice, not bundled into the orchestrator transaction.

Phase 0 single-currency (KRW). Phase 3+ multi-currency may extend.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.domain.models import PortfolioSnapshot, PositionValuation

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime

    from src.domain.models import Money
    from src.ports.broker import BrokerPort
    from src.ports.market_data import MarketDataPort
    from src.ports.unit_of_work import UnitOfWorkPort


class DailySnapshotBuilder:
    """Builds and persists one PortfolioSnapshot per call.

    Wired with the same Broker / MarketData ports as the orchestrator, plus
    the same uow_factory and clock. ``initial_capital`` is the system's
    starting capital (Phase 0: configured at boot from `config/`); each
    snapshot carries it forward verbatim (ADR §8.6).
    """

    def __init__(
        self,
        *,
        broker: BrokerPort,
        market_data: MarketDataPort,
        uow_factory: Callable[[], UnitOfWorkPort],
        clock: Callable[[], datetime],
        initial_capital: Money,
    ) -> None:
        self._broker = broker
        self._market_data = market_data
        self._uow_factory = uow_factory
        self._clock = clock
        self._initial_capital = initial_capital

    def build_and_save(self, snapshot_date: date) -> PortfolioSnapshot:
        """Compute valuations from the current market + position state and
        upsert the resulting PortfolioSnapshot for ``snapshot_date``.

        Returns the persisted snapshot for caller-side reporting.
        """
        as_of = self._clock()
        with self._uow_factory() as uow:
            stored_positions = uow.positions.list_all()
            balance = self._broker.get_balance()
            valuations: list[PositionValuation] = []
            for position in stored_positions:
                # Phase 0 / ADR §8.6 option A: position.quantity (including
                # any pending_partial_quantity) is the single source of truth
                # for valuation.
                if position.quantity <= 0:
                    continue
                price = self._market_data.get_price(position.asset, as_of)
                valuations.append(
                    PositionValuation.from_position(position, price.value)
                )
            snapshot = PortfolioSnapshot.build(
                snapshot_date=snapshot_date,
                snapshot_at=as_of,
                initial_capital=self._initial_capital,
                cash=balance.cash,
                valuations=valuations,
            )
            uow.snapshots.save(snapshot)
            uow.commit()
        return snapshot
