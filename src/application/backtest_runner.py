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
from typing import TYPE_CHECKING, Any

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
from src.domain.strategies.profit_target import SellStrategyConfig
from src.use_cases.asset_context import AssetContext
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
        Position,
    )
    from src.domain.strategies.price_drop import SplitStrategyConfig
    from src.ports.signals import SignalPort
    from src.use_cases.asset_context import AssetPolicyOverride


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
    # Phase 0.5 step 0.5.23: broker's final Position state (positive
    # quantities only) so equivalence tests can compare slot-by-slot
    # byte-identical state (ADR §10.2). Empty list when no position
    # remains at the end of the run.
    final_positions: list[Position] = field(default_factory=list)
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
        final_positions: list[Position] | None = None,
        trading_days_per_year: int = _DEFAULT_TRADING_DAYS_PER_YEAR,
        risk_free_rate: Decimal = _DEFAULT_RISK_FREE_RATE,
    ) -> BacktestResult:
        """Factory that computes metrics once from the snapshot series.

        Per ADR §9.5: same metrics functions used by paper/live trading
        reports, so the calculation lives in `metrics.py` and not here.

        ``final_positions`` (Phase 0.5 §10.2) carries the broker's
        end-of-run Position objects so callers can compare slot-by-slot
        byte-identical state. Defaults to ``[]`` for callers that don't
        need slot-level inspection.
        """
        return cls(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            decisions=decisions,
            snapshots=snapshots,
            final_positions=list(final_positions) if final_positions else [],
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

    Phase 0.7.1: accepts ``assets: list[Asset]`` (non-empty). Trading dates
    are the intersection of all assets' bars so a missing-data day for any
    asset is skipped for all (ADR 0003 §9.3). Single-asset runs behave
    identically to the previous single-asset interface.

    Constructed with ``assets``, ``strategy_config``, ``initial_capital``, and
    the OHLCV map; ``run(start, end)`` produces a `BacktestResult`. The
    runner wires fresh adapters per call so each `run` is fully isolated
    (ADR §9.4).
    """

    def __init__(
        self,
        *,
        assets: list[Asset],
        strategy_config: SplitStrategyConfig,
        initial_capital: Money,
        ohlcv_by_asset: dict[Asset, list[OHLCV]],
        sell_strategy_config: SellStrategyConfig | None = None,
        reentry_strategy_name: str = "hybrid",
        reentry_parameters: dict[str, Any] | None = None,
        signal_factory: Callable[[], SignalPort] | None = None,
        decision_kst_time: time = time(9, 0),
        snapshot_kst_time: time = time(16, 0),
        trading_days_per_year: int = _DEFAULT_TRADING_DAYS_PER_YEAR,
        risk_free_rate: Decimal = _DEFAULT_RISK_FREE_RATE,
        per_asset_strategy_overrides: dict[str, SplitStrategyConfig] | None = None,
        buy_strategy_name: str = "price_drop",
        per_asset_overrides: dict[str, AssetPolicyOverride] | None = None,
    ) -> None:
        if not assets:
            raise ValueError("assets must be a non-empty list")
        self._assets = list(assets)
        self._strategy_config = strategy_config
        self._initial_capital = initial_capital
        self._ohlcv_by_asset = ohlcv_by_asset
        # ADR 0003 §16.13.9 박제 — Phase 0.7.2 자산별 strategy override.
        # None default → 단일 strategy_config 적용 (Phase 0.7.1 회귀
        # invariant). dict 시 키 = asset.fqn ("EXCHANGE:CODE"), 모든
        # assets fqn 정확히 일치 필요 (subset / extra 모두 거부).
        if per_asset_strategy_overrides is not None:
            expected_fqns = {a.fqn for a in self._assets}
            actual_fqns = set(per_asset_strategy_overrides.keys())
            if actual_fqns != expected_fqns:
                missing = expected_fqns - actual_fqns
                extra = actual_fqns - expected_fqns
                raise ValueError(
                    "per_asset_strategy_overrides keys must match assets fqns "
                    "exactly. "
                    f"missing={sorted(missing)} extra={sorted(extra)}"
                )
        self._per_asset_overrides = (
            dict(per_asset_strategy_overrides)
            if per_asset_strategy_overrides is not None
            else None
        )
        # Phase 1.1 Case A / Tier 2: per-asset buy+sell+reentry params
        # (code-keyed). Takes precedence over the legacy buy-only
        # per_asset_strategy_overrides (fqn-keyed). None → broadcast / legacy.
        self._per_asset_policy = (
            dict(per_asset_overrides) if per_asset_overrides is not None else None
        )
        self._sell_strategy_config = sell_strategy_config or SellStrategyConfig(
            profit_target_pct=Decimal("10.0"),
            max_sells_per_day=7,
        )
        self._reentry_strategy_name = reentry_strategy_name
        self._reentry_parameters = (
            dict(reentry_parameters)
            if reentry_parameters is not None
            else {"cooldown_days": 60}
        )
        self._signal_factory = signal_factory or (lambda: NullSignal())
        self._decision_kst_time = decision_kst_time
        self._snapshot_kst_time = snapshot_kst_time
        self._trading_days_per_year = trading_days_per_year
        self._risk_free_rate = risk_free_rate
        self._buy_strategy_name = buy_strategy_name

    def run(self, start: date, end: date) -> BacktestResult:
        if start > end:
            raise ValueError(f"start ({start}) > end ({end})")

        # Trading dates = intersection of each asset's bar dates within
        # [start, end]. A day missing from any asset is excluded entirely
        # (ADR 0003 §9.3 — "한 종목 누락일은 멀티 백테스트 skip").
        # Single-asset case: intersection of one set = that set (same as before).
        date_sets = [
            {b.trade_date for b in self._ohlcv_by_asset.get(asset, [])
             if start <= b.trade_date <= end}
            for asset in self._assets
        ]
        if date_sets:
            common_dates = date_sets[0]
            for ds in date_sets[1:]:
                common_dates = common_dates & ds
        else:
            common_dates = set()
        trading_dates = sorted(common_dates)

        # Wire one set of adapters reused across the whole run. The mutable
        # `clock_holder` lets us swap between decision-time and snapshot-time
        # without rebuilding the broker / orchestrator.
        clock_holder: list[datetime | None] = [None]

        def clock() -> datetime:
            value = clock_holder[0]
            assert value is not None, "BacktestRunner did not set the clock"
            return value

        # Lazy import to avoid circular dependency
        # (src.cli.__init__ → main → backtest_runner → composition).
        from src.cli.composition import (
            build_asset_contexts,
            create_buy_strategy,
            slot_model_for_buy_strategy,
        )

        broker = MockBroker(
            initial_balance=Balance(cash=self._initial_capital),
            clock=clock,
            slot_model=slot_model_for_buy_strategy(self._buy_strategy_name),
        )
        market_data = MockMarketData(ohlcv_by_asset=self._ohlcv_by_asset)
        signal = self._signal_factory()
        from src.domain.strategies.profit_target import ProfitTargetSell
        from src.domain.strategies.reentry import create_reentry_strategy

        # ADR 0004 §5.7: factory dispatch between PriceDropStrategy +
        # SupportLevelStrategy. Reentry policy is only required for
        # PriceDropStrategy (ADR §4.3 β-2).
        reentry = (
            create_reentry_strategy(
                self._reentry_strategy_name,
                market_data=market_data,
                **self._reentry_parameters,
            )
            if self._buy_strategy_name == "price_drop"
            else None
        )
        strategy = create_buy_strategy(
            self._buy_strategy_name, reentry=reentry
        )
        shared_uow = InMemoryUnitOfWork()

        # Build one AssetContext per asset. ADR 0003 §7.3 — policy uniformity
        # (buy_strategy / sell_strategy / reentry 동일). Phase 0.7.2 §16.13.9
        # — per_asset_strategy_overrides 적용 시 자산별 SplitStrategyConfig
        # (per_split_amount 만 자산별 다름) 가능. None 시 단일 fallback
        # (Phase 0.7.1 회귀 invariant).
        if self._per_asset_policy is not None:
            # Phase 1.1 Case A / Tier 2 — per-asset buy+sell+reentry params.
            asset_contexts = build_asset_contexts(
                assets=self._assets,
                buy_strategy_name=self._buy_strategy_name,
                reentry_strategy_name=self._reentry_strategy_name,
                market_data=market_data,
                buy_config=self._strategy_config,
                sell_config=self._sell_strategy_config,
                reentry_parameters=self._reentry_parameters,
                per_asset_overrides=self._per_asset_policy,
            )
        else:
            asset_contexts = [
                AssetContext(
                    asset=asset,
                    strategy=strategy,
                    config=(
                        self._per_asset_overrides[asset.fqn]
                        if self._per_asset_overrides is not None
                        else self._strategy_config
                    ),
                    sell_strategy=ProfitTargetSell(),
                    sell_config=self._sell_strategy_config,
                )
                for asset in self._assets
            ]
        orchestrator = DailyOrchestrator(
            broker=broker,
            market_data=market_data,
            signal=signal,
            asset_contexts=asset_contexts,
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
            decisions_today = orchestrator.run_for_date(d)
            decisions.extend(decisions_today)

            # Snapshot at KRX close window — T's close available
            clock_holder[0] = self._utc_for(d, self._snapshot_kst_time)
            snap = snapshot_builder.build_and_save(d)
            snapshots.append(snap)

        # Phase 0.5 §10.2: capture broker's end-of-run Position state so
        # the backtest↔paper equivalence regression can compare slots
        # byte-identical (slot_number / state / entry / last_exit_*).
        final_positions = broker.get_positions()

        return BacktestResult.from_run(
            start_date=start,
            end_date=end,
            initial_capital=self._initial_capital,
            decisions=decisions,
            snapshots=snapshots,
            final_positions=final_positions,
            trading_days_per_year=self._trading_days_per_year,
            risk_free_rate=self._risk_free_rate,
        )

    @staticmethod
    def _utc_for(d: date, t: time) -> datetime:
        """Combine a date with a KST time-of-day and convert to UTC."""
        return datetime.combine(d, t, tzinfo=KST).astimezone(UTC)
