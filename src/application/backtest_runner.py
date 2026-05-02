"""BacktestRunner — replay historical bars day-by-day.

Per ADR §9 (Step 8) the runner uses two clocks per trading day:

- ``decision_at`` — KRX morning (default 09:00 KST). At this moment the
  current day's close is NOT yet available, so MockMarketData returns the
  previous trading day's close. The orchestrator therefore makes a
  look-ahead-free decision using T-1 data.
- ``snapshot_at`` — KRX afternoon (default 16:00 KST). The current day's
  close IS available, so the snapshot reflects today's market value.

Phase 0 simplification: backtest is single-asset, single-process,
single-thread. Wiring uses MockBroker + MockMarketData + NullSignal +
InMemoryUnitOfWork for fully deterministic in-memory replay. Each
``run()`` call wires a fresh adapter set so independent runs cannot leak
state into each other (ADR §9.4).

Performance metrics (CAGR / MDD / Sharpe / Calmar) live in
``src.application.metrics`` as pure functions over snapshots. The runner
calls them once via ``BacktestResult.from_run`` so the same calculations
work unchanged for paper / live trading reports (ADR §9.5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.adapters.mock.market_data import MockMarketData
from src.adapters.mock.signals import NullSignal
from src.application.metrics import (
    cagr,
    calmar_ratio,
    max_drawdown,
    sharpe_ratio,
)
from src.application.snapshot_builder import DailySnapshotBuilder
from src.domain.constants import KST
from src.domain.models import Balance
from src.domain.strategies.price_drop import PriceDropStrategy
from src.use_cases.daily_orchestrator import DailyOrchestrator

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from src.domain.models import (
        OHLCV,
        Asset,
        Decision,
        Money,
        PortfolioSnapshot,
    )
    from src.domain.strategies.price_drop import SplitStrategyConfig
    from src.ports.signals import SignalPort


_DEFAULT_TRADING_DAYS_PER_YEAR = 252
_DEFAULT_RISK_FREE_RATE = Decimal(0)


@dataclass(frozen=True)
class BacktestResult:
    """Aggregate result of one backtest run.

    `decisions` and `snapshots` carry the per-day records. The four metric
    fields (`cagr_pct`, `max_drawdown_pct`, `sharpe_ratio`, `calmar_ratio`)
    are computed via ``BacktestResult.from_run`` from `snapshots`. Convenience
    @property accessors derive final-value / total-return from the last
    snapshot, falling back to initial state when no trading days were
    processed.

    All percent fields are in PERCENT units (e.g. 10 = 10%) to match
    PortfolioSnapshot.total_return_pct.
    """

    start_date: date
    end_date: date
    initial_capital: Money
    decisions: list[Decision] = field(default_factory=list)
    snapshots: list[PortfolioSnapshot] = field(default_factory=list)
    n_trading_days: int = 0
    cagr_pct: Decimal = Decimal(0)
    max_drawdown_pct: Decimal = Decimal(0)
    sharpe_ratio: Decimal = Decimal(0)
    calmar_ratio: Decimal = Decimal(0)

    @property
    def final_snapshot(self) -> PortfolioSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def final_value(self) -> Money:
        snap = self.final_snapshot
        return snap.total_value if snap is not None else self.initial_capital

    @property
    def total_return_pct(self) -> Decimal:
        snap = self.final_snapshot
        return snap.total_return_pct if snap is not None else Decimal(0)

    @classmethod
    def from_run(
        cls,
        *,
        start_date: date,
        end_date: date,
        initial_capital: Money,
        decisions: list[Decision],
        snapshots: list[PortfolioSnapshot],
        trading_days_per_year: int = _DEFAULT_TRADING_DAYS_PER_YEAR,
        risk_free_rate: Decimal = _DEFAULT_RISK_FREE_RATE,
    ) -> BacktestResult:
        """Factory that computes metrics once from the snapshot series.

        Per ADR §9.5: same metrics functions used by paper/live trading
        reports, so the calculation lives in `metrics.py` and not here.
        """
        return cls(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            decisions=decisions,
            snapshots=snapshots,
            n_trading_days=len(snapshots),
            cagr_pct=cagr(
                snapshots, trading_days_per_year=trading_days_per_year
            ),
            max_drawdown_pct=max_drawdown(snapshots),
            sharpe_ratio=sharpe_ratio(
                snapshots,
                risk_free_rate=risk_free_rate,
                trading_days_per_year=trading_days_per_year,
            ),
            calmar_ratio=calmar_ratio(
                snapshots, trading_days_per_year=trading_days_per_year
            ),
        )


class BacktestRunner:
    """Replay historical OHLCV across [start, end] dates.

    Constructed with the `asset`, `strategy_config`, `initial_capital`, and
    the OHLCV map; ``run(start, end)`` produces a `BacktestResult`. The
    runner wires fresh adapters per call so each `run` is fully isolated
    (ADR §9.4).
    """

    def __init__(
        self,
        *,
        asset: Asset,
        strategy_config: SplitStrategyConfig,
        initial_capital: Money,
        ohlcv_by_asset: dict[Asset, list[OHLCV]],
        signal_factory: Callable[[], SignalPort] | None = None,
        decision_kst_time: time = time(9, 0),
        snapshot_kst_time: time = time(16, 0),
        trading_days_per_year: int = _DEFAULT_TRADING_DAYS_PER_YEAR,
        risk_free_rate: Decimal = _DEFAULT_RISK_FREE_RATE,
    ) -> None:
        self._asset = asset
        self._strategy_config = strategy_config
        self._initial_capital = initial_capital
        self._ohlcv_by_asset = ohlcv_by_asset
        self._signal_factory = signal_factory or (lambda: NullSignal())
        self._decision_kst_time = decision_kst_time
        self._snapshot_kst_time = snapshot_kst_time
        self._trading_days_per_year = trading_days_per_year
        self._risk_free_rate = risk_free_rate

    def run(self, start: date, end: date) -> BacktestResult:
        if start > end:
            raise ValueError(f"start ({start}) > end ({end})")

        # Iterate only over days that have an OHLCV bar — those are the
        # trading days. Non-trading days (weekends/holidays) have no bar.
        bars = self._ohlcv_by_asset.get(self._asset, [])
        trading_dates = sorted(
            b.trade_date for b in bars if start <= b.trade_date <= end
        )

        # Wire one set of adapters reused across the whole run. The mutable
        # `clock_holder` lets us swap between decision-time and snapshot-time
        # without rebuilding the broker / orchestrator.
        clock_holder: list[datetime | None] = [None]

        def clock() -> datetime:
            value = clock_holder[0]
            assert value is not None, "BacktestRunner did not set the clock"
            return value

        broker = MockBroker(
            initial_balance=Balance(cash=self._initial_capital),
            clock=clock,
        )
        market_data = MockMarketData(ohlcv_by_asset=self._ohlcv_by_asset)
        signal = self._signal_factory()
        # Phase 0.5 step 0.5.10: hardcode HybridTimeBasedReentry until
        # YAML config (step 0.5.20) wires policy choice through.
        from src.domain.strategies.reentry import HybridTimeBasedReentry

        strategy = PriceDropStrategy(
            reentry=HybridTimeBasedReentry(cooldown_days=60),
        )
        shared_uow = InMemoryUnitOfWork()

        orchestrator = DailyOrchestrator(
            broker=broker,
            market_data=market_data,
            signal=signal,
            strategy=strategy,
            config=self._strategy_config,
            asset=self._asset,
            clock=clock,
            uow_factory=lambda: shared_uow,
        )
        snapshot_builder = DailySnapshotBuilder(
            broker=broker,
            market_data=market_data,
            uow_factory=lambda: shared_uow,
            clock=clock,
            initial_capital=self._initial_capital,
        )

        decisions: list[Decision] = []
        snapshots: list[PortfolioSnapshot] = []
        for d in trading_dates:
            # Decision at KRX open — T's close not yet available
            clock_holder[0] = self._utc_for(d, self._decision_kst_time)
            decision = orchestrator.run_for_date(d)
            decisions.append(decision)

            # Snapshot at KRX close window — T's close available
            clock_holder[0] = self._utc_for(d, self._snapshot_kst_time)
            snap = snapshot_builder.build_and_save(d)
            snapshots.append(snap)

        return BacktestResult.from_run(
            start_date=start,
            end_date=end,
            initial_capital=self._initial_capital,
            decisions=decisions,
            snapshots=snapshots,
            trading_days_per_year=self._trading_days_per_year,
            risk_free_rate=self._risk_free_rate,
        )

    @staticmethod
    def _utc_for(d: date, t: time) -> datetime:
        """Combine a date with a KST time-of-day and convert to UTC."""
        return datetime.combine(d, t, tzinfo=KST).astimezone(UTC)
