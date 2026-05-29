"""Composition root for paper trading (ADR §10.7).

Wires the Mock adapter set + ``SqliteUnitOfWork`` into a runnable paper
trading flow. Cash is restored from the most-recent ``PortfolioSnapshot``
(ADR §10.3); positions from the ``positions`` table. The Phase 0 sanity
check (ADR §10.4) runs before wiring so a snapshot-vs-positions divergence
halts before any new decision.

The functions here BUILD components — they do not RUN them. The CLI
caller drives the two-step ``orchestrator.run_for_date`` →
``snapshot_builder.build_and_save`` flow with the right clock at each step.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.market_data import MockMarketData
from src.adapters.mock.signals import NullSignal
from src.application.snapshot_builder import DailySnapshotBuilder
from src.domain.constants import KST
from src.domain.exceptions import IntegrityError
from src.domain.models import Balance, SplitSlot, SupportSlot
from src.domain.strategies.price_drop import PriceDropStrategy
from src.domain.strategies.profit_target import (
    ProfitTargetSell,
    SellStrategyConfig,
)
from src.domain.strategies.reentry import create_reentry_strategy
from src.domain.strategies.support_level import SupportLevelStrategy
from src.infrastructure.db import connect
from src.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork
from src.infrastructure.yaml_asset_loader import load_asset_registry
from src.use_cases.asset_context import AssetContext
from src.use_cases.daily_orchestrator import DailyOrchestrator

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import date, time

    from src.adapters.db_position_broker_view import DbPositionBrokerView
    from src.adapters.kis._http import HttpClient
    from src.adapters.kis.broker import KISBroker
    from src.adapters.kis.config import KISConfig
    from src.adapters.kis.market_data import KISMarketData
    from src.domain.models import OHLCV, Asset, Money
    from src.domain.strategies.price_drop import SplitStrategyConfig
    from src.ports.market_data import MarketDataPort
    from src.ports.notifications import NotifierPort
    from src.ports.reentry_strategy import ReentryPriceStrategyPort
    from src.ports.unit_of_work import UnitOfWorkPort
    from src.use_cases.asset_context import AssetPolicyOverride
    from src.use_cases.pending_settler import PendingSettler
    from src.use_cases.reconciliation import Reconciler


def create_buy_strategy(
    name: str,
    *,
    reentry: ReentryPriceStrategyPort | None = None,
) -> PriceDropStrategy | SupportLevelStrategy:
    """Composition factory for buy strategies (ADR 0004 §5.2).

    yaml ``buy_strategy`` field dispatches here:
        - ``price_drop`` → ``PriceDropStrategy(reentry=...)`` (Phase 0~0.7)
        - ``support_level`` → ``SupportLevelStrategy()`` (Phase 0.8+)

    SupportLevelStrategy doesn't take a reentry policy (ADR §4.3 β-2 —
    each slot's trigger is its own indicator condition). ``reentry``
    parameter is required for ``price_drop`` and ignored for
    ``support_level``.
    """
    if name == "price_drop":
        if reentry is None:
            raise ValueError(
                "buy_strategy 'price_drop' requires reentry policy"
            )
        return PriceDropStrategy(reentry=reentry)
    if name == "support_level":
        return SupportLevelStrategy()
    raise ValueError(
        f"unknown buy_strategy {name!r}; "
        "expected 'price_drop' or 'support_level'"
    )


def slot_model_for_buy_strategy(
    name: str,
) -> type[SplitSlot] | type[SupportSlot]:
    """Slot model dispatch for ``MockBroker`` (ADR 0004 §5.6).

    Phase 0.8 (B-1, ADR §1.3): a Position's slot model is determined by
    the buy strategy. yaml ``buy_strategy`` field selects the slot type.
    """
    if name == "price_drop":
        return SplitSlot
    if name == "support_level":
        return SupportSlot
    raise ValueError(
        f"unknown buy_strategy {name!r}; "
        "expected 'price_drop' or 'support_level'"
    )


def build_asset_contexts(
    *,
    assets: list[Asset],
    buy_strategy_name: str,
    reentry_strategy_name: str,
    market_data: MarketDataPort,
    buy_config: SplitStrategyConfig,
    sell_config: SellStrategyConfig,
    reentry_parameters: dict[str, Any],
    per_asset_overrides: dict[str, AssetPolicyOverride] | None = None,
) -> list[AssetContext]:
    """Build one AssetContext per asset (Phase 1.1 per-asset params, Case A).

    ``per_asset_overrides`` (keyed by ``asset.code``) supplies per-asset
    buy/sell/reentry **parameters** when set; the strategy *types*
    (``buy_strategy_name`` / ``reentry_strategy_name`` / profit_target) stay
    uniform. When None, every asset uses the shared default configs (the
    Phase 0.7.1 broadcast — strategies are stateless, so per-asset instances
    are byte-identical in behaviour). Reentry/buy strategy instances are built
    per asset so each can carry its own reentry parameters.
    """
    if per_asset_overrides is not None:
        expected = {a.code for a in assets}
        if set(per_asset_overrides) != expected:
            raise ValueError(
                "per_asset_overrides keys must match asset codes exactly: "
                f"expected {sorted(expected)}, got {sorted(per_asset_overrides)}"
            )

    contexts: list[AssetContext] = []
    for asset in assets:
        override = (
            per_asset_overrides.get(asset.code)
            if per_asset_overrides is not None
            else None
        )
        eff_buy = override.buy_config if override is not None else buy_config
        eff_sell = override.sell_config if override is not None else sell_config
        eff_reentry_params = (
            override.reentry_parameters
            if override is not None
            else reentry_parameters
        )
        reentry = (
            create_reentry_strategy(
                reentry_strategy_name,
                market_data=market_data,
                **eff_reentry_params,
            )
            if buy_strategy_name == "price_drop"
            else None
        )
        contexts.append(
            AssetContext(
                asset=asset,
                strategy=create_buy_strategy(buy_strategy_name, reentry=reentry),
                config=eff_buy,
                sell_strategy=ProfitTargetSell(),
                sell_config=eff_sell,
            )
        )
    return contexts


@dataclass
class PaperComponents:
    """Wired paper-trading component graph.

    Caller drives the day with:
        components.set_clock(decision_at)
        decisions = components.orchestrator.run_for_date(today)
        components.set_clock(snapshot_at)
        snap = components.snapshot_builder.build_and_save(today)
        ...
        components.close()
    """

    orchestrator: DailyOrchestrator
    snapshot_builder: DailySnapshotBuilder
    set_clock: Callable[[datetime], None]
    close: Callable[[], None]


def utc_for(d: date, t: time) -> datetime:
    """KST date+time → UTC datetime helper (matches BacktestRunner._utc_for)."""
    return datetime.combine(d, t, tzinfo=KST).astimezone(UTC)


@dataclass(frozen=True)
class KISReadComponents:
    """Wired KIS read-only component graph (Phase 1.1 Stage 2.3).

    Holds the read-subset broker (``get_balance`` / ``get_holdings``) +
    market-data adapter, plus the resolved ``config`` (for printing
    mode / host / masked appkey — never the secret). There is no write
    surface here: ``KISBroker`` physically lacks ``place_order`` /
    ``cancel_order`` (ADR 0012 Option C read-before-write).
    """

    broker: KISBroker
    market_data: KISMarketData
    config: KISConfig


def build_kis_read_components(
    environ: Mapping[str, str] | None = None,
    *,
    http: HttpClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> KISReadComponents:
    """Wire the KIS read-only adapter graph from the environment.

    Composition root for the ``trading kis-check`` smoke command (Phase 1.1
    Stage 2.3). Reads credentials via ``KISConfig.from_env(environ)`` —
    missing / blank required vars raise ``ConfigurationError`` (propagated;
    no silent fallback, CLAUDE.md §6.3).

    DI per CLAUDE.md §1.2: ``http`` / ``clock`` are injectable so tests stay
    network-free (inject a fake ``HttpClient`` + a fixed UTC clock). In
    production both default to the real ``RequestsHttpClient`` + a UTC wall
    clock (CLAUDE.md §3.1 — UTC, no naïve ``datetime.now()``).

    Returns a :class:`KISReadComponents` (broker + market_data + config).
    The graph is **read-only**: ``KISBroker`` exposes only ``get_balance`` /
    ``get_holdings``; no order surface exists (ADR 0012 Option C).
    """
    # Local imports keep the adapter dependency out of the module-import path
    # for the paper-trading callers (which never touch KIS).
    from src.adapters.kis._client import KISClient
    from src.adapters.kis._http import RequestsHttpClient
    from src.adapters.kis.auth import KISAuth
    from src.adapters.kis.broker import KISBroker
    from src.adapters.kis.config import KISConfig
    from src.adapters.kis.market_data import KISMarketData

    config = KISConfig.from_env(environ)
    http_client: HttpClient = http if http is not None else RequestsHttpClient()
    utc_clock: Callable[[], datetime] = (
        clock if clock is not None else (lambda: datetime.now(UTC))
    )

    auth = KISAuth(config=config, http=http_client, clock=utc_clock)
    client = KISClient(
        config=config, http=http_client, auth=auth, clock=utc_clock
    )
    broker = KISBroker(client=client)
    market_data = KISMarketData(client=client)

    return KISReadComponents(
        broker=broker, market_data=market_data, config=config
    )


def build_kis_market_data(
    environ: Mapping[str, str] | None = None,
    *,
    http: HttpClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> KISMarketData:
    """Wire a read-only ``KISMarketData`` adapter from the environment.

    Composition root for the ``trading dry-run`` command (Phase 1.1 — paper
    -on-live): live KIS market data (``get_price`` / ``get_ohlcv`` read) feeds
    a MockBroker fill simulator (no real order, no real account). Mirrors
    :func:`build_kis_read_components` but wires the **market-data half only** —
    no ``KISBroker``, so balance / holdings (실계좌) are never queried.

    Reads credentials via ``KISConfig.from_env(environ)`` — missing / blank
    required vars raise ``ConfigurationError`` (propagated; no silent fallback,
    CLAUDE.md §6.3). DI per CLAUDE.md §1.2: ``http`` / ``clock`` are injectable
    so tests stay network-free (inject a fake ``HttpClient`` + a fixed UTC
    clock). In production both default to the real ``RequestsHttpClient`` + a
    UTC wall clock (CLAUDE.md §3.1).
    """
    # Local imports keep the adapter dependency out of the module-import path
    # for the paper-trading callers (which never touch KIS).
    from src.adapters.kis._client import KISClient
    from src.adapters.kis._http import RequestsHttpClient
    from src.adapters.kis.auth import KISAuth
    from src.adapters.kis.config import KISConfig
    from src.adapters.kis.market_data import KISMarketData

    config = KISConfig.from_env(environ)
    http_client: HttpClient = http if http is not None else RequestsHttpClient()
    utc_clock: Callable[[], datetime] = (
        clock if clock is not None else (lambda: datetime.now(UTC))
    )

    auth = KISAuth(config=config, http=http_client, clock=utc_clock)
    client = KISClient(
        config=config, http=http_client, auth=auth, clock=utc_clock
    )
    return KISMarketData(client=client)


def _default_halt(reason: str) -> None:
    """Default halt callback — write the persistent halt sentinel (CLAUDE.md §11.2).

    The :class:`~src.use_cases.reconciliation.Reconciler` takes
    ``halt: Callable[[str], None]`` so the use_case never imports cli (ring
    정합 — the wiring lives here in composition). ``safety.write_halt`` returns
    the sentinel ``Path``; we discard it so the signature matches
    ``Callable[[str], None]`` (mypy clean). ``safety`` is a cli-ring module, so
    importing it here (composition is also cli ring) is allowed.
    """
    from src.cli import safety

    safety.write_halt(reason)


def build_reconciler(
    db_path: Path | str,
    environ: Mapping[str, str] | None = None,
    *,
    http: HttpClient | None = None,
    clock: Callable[[], datetime] | None = None,
    notifier: NotifierPort | None = None,
    halt: Callable[[str], None] | None = None,
) -> tuple[Reconciler, Callable[[], None], KISConfig]:
    """Wire the reconciliation use case (Phase 1.1 Stage 4).

    Composition root for the ``trading reconcile`` command (CLAUDE.md §11.2 /
    ADR 0012 D14): DB positions vs **live** KIS holdings 대조. Wires:

    - the KIS **read-only** broker (``get_holdings`` — ``inquire-balance`` read;
      ``market_data`` half is built but ignored — reconciliation only reads
      holdings, never quotes). No write surface exists (Option C, ADR 0012).
    - a SQLite ``uow_factory`` over ``connect(db_path)`` (positions.list_all()).
    - the halt callback — defaults to :func:`_default_halt`
      (``safety.write_halt``) so a mismatch records a **persistent** halt
      sentinel; injectable so tests can spy without touching the real sentinel.
    - the notifier — defaults to ``build_notifier(environ)`` (Telegram + Console
      when configured, else Console-only) for the CRITICAL mismatch alert.
    - the clock — defaults to a UTC wall clock (CLAUDE.md §3.1).

    Reads credentials via ``KISConfig.from_env(environ)`` (inside
    ``build_kis_read_components``) — missing / blank required vars raise
    ``ConfigurationError`` (propagated; no silent fallback, CLAUDE.md §6.3). DI
    per CLAUDE.md §1.2: ``http`` / ``clock`` / ``notifier`` / ``halt`` are all
    injectable so tests stay network-free + sentinel-free.

    Returns ``(reconciler, close, config)``: the wired :class:`Reconciler`, a
    ``close`` callable that closes the SQLite connection (caller must invoke in
    a ``finally``), and the resolved :class:`KISConfig` (so the command can
    print mode / host — never the secret).

    The graph is **read-only**: ``KISBroker`` exposes only ``get_balance`` /
    ``get_holdings`` (no order surface), and the ``Reconciler`` itself never
    calls ``save`` / ``place_order`` (자동 수정 zero — CLAUDE.md §11.2).
    """
    # Local imports keep the adapter / telegram dependency off the module-import
    # path for the paper-trading callers (mirrors build_kis_read_components).
    from src.adapters.telegram.notifier import build_notifier
    from src.use_cases.reconciliation import Reconciler

    kis = build_kis_read_components(environ, http=http, clock=clock)

    conn = connect(db_path)

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(conn)

    clk: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
    halt_cb: Callable[[str], None] = halt or _default_halt
    notif: NotifierPort = notifier or build_notifier(environ)

    reconciler = Reconciler(
        uow_factory=uow_factory,
        # KISBroker (read subset, Option C) satisfies HoldingsReaderPort — the
        # narrow surface the Reconciler depends on (get_holdings only).
        # Interface Segregation removes the full-BrokerPort coupling the
        # Reconciler never used, so no suppression pragma is required here.
        broker=kis.broker,
        notifier=notif,
        halt=halt_cb,
        clock=clk,
    )
    return reconciler, conn.close, kis.config


@dataclass
class LiveComponents:
    """Wired live-trading component graph (Phase 1.1 Stage 8-4).

    The runner (Stage 8-5) drives the day with:
        settle = components.settler.settle(today)          # PENDING→FILLED
        recon  = components.reconciler.reconcile()         # in-process matched
        assert_armed_for_live(recon=recon, ...)            # arming gate (8-3)
        decisions = components.orchestrator.run_for_date(today)
        ...
        components.close()

    ``broker`` is the write-enabled KIS broker (also the reconciler's holdings
    source + the settler's status source). The orchestrator's ``self._broker``
    is a :class:`~src.adapters.db_position_broker_view.DbPositionBrokerView`
    (DB positions + KIS balance + KIS write delegation) — the KIS broker never
    attaches to the orchestrator directly (collaborator substitution, ADR 0012
    Stage 8 Option B). **No CLI wires this yet** — 실주문 zero until Stage 8-5
    behind the arming gate + D16.
    """

    orchestrator: DailyOrchestrator
    settler: PendingSettler
    reconciler: Reconciler
    broker: KISBroker
    position_source: DbPositionBrokerView
    market_data: KISMarketData
    notifier: NotifierPort
    config: KISConfig
    uow_factory: Callable[[], UnitOfWorkPort]
    clock: Callable[[], datetime]
    close: Callable[[], None]


def build_live_components(
    *,
    assets: list[Asset],
    db_path: Path | str,
    strategy_config: SplitStrategyConfig,
    environ: Mapping[str, str] | None = None,
    sell_strategy_config: SellStrategyConfig | None = None,
    reentry_strategy_name: str = "hybrid",
    reentry_parameters: dict[str, Any] | None = None,
    buy_strategy_name: str = "price_drop",
    explicit_holidays: frozenset[date] = frozenset(),
    http: HttpClient | None = None,
    clock: Callable[[], datetime] | None = None,
    notifier: NotifierPort | None = None,
    halt: Callable[[str], None] | None = None,
    max_pending_age_business_days: int = 1,
    per_asset_overrides: dict[str, AssetPolicyOverride] | None = None,
) -> LiveComponents:
    """Wire the live-trading component graph (Phase 1.1 Stage 8-4).

    Composition root for the future ``trading live`` command (Stage 8-5). Wires:

    - a **write-enabled** ``KISBroker`` — ``order_store`` injected
      (``SqliteKISOrderStore`` over the shared connection) so ``place_order`` /
      ``get_order_status`` / ``cancel_order`` work (idempotency dedup + org_no
      해석). A read-only construction would ``RuntimeError`` on any write — money
      cannot move through it (Option C boundary, ADR 0012).
    - ``KISMarketData`` (live ``get_price`` / ``get_ohlcv``).
    - ``PendingSettler`` (Stage 8-2) over the KIS broker's ``get_order_status``.
    - ``DbPositionBrokerView`` (Stage 8-1.5) as the orchestrator's
      ``self._broker``: split-slot positions restored from the DB + cash from
      KIS + write delegation to the KIS broker (resolves the 8-1.5 write stubs).
    - ``Reconciler`` (Stage 3.3) over the KIS broker's ``get_holdings``.
    - ``DailyOrchestrator`` + ``NullSignal`` + ``ProfitTargetSell``; the live
      sell threshold defaults to **+15%** (ADR 0012 D7).

    DI per CLAUDE.md §1.2: ``http`` / ``clock`` / ``notifier`` / ``halt`` are
    injectable so tests stay network-free + sentinel-free (mirrors
    :func:`build_reconciler`). Reads credentials via ``KISConfig.from_env`` —
    missing required vars raise ``ConfigurationError`` (no silent fallback).

    Returns a :class:`LiveComponents`. **Building the graph places no orders** —
    only the runner's ``orchestrator.run_for_date`` (behind the Stage 8-3 arming
    gate) does, and no CLI invokes that yet (실주문 zero).
    """
    if not assets:
        raise ValueError("assets must be a non-empty list")

    # Local imports keep the adapter / telegram dependency off the module-import
    # path for the paper-trading callers (mirrors build_kis_read_components).
    from src.adapters.db_position_broker_view import DbPositionBrokerView
    from src.adapters.kis._client import KISClient
    from src.adapters.kis._http import RequestsHttpClient
    from src.adapters.kis.auth import KISAuth
    from src.adapters.kis.broker import KISBroker
    from src.adapters.kis.config import KISConfig
    from src.adapters.kis.market_data import KISMarketData
    from src.adapters.kis.order_store import SqliteKISOrderStore
    from src.adapters.telegram.notifier import build_notifier
    from src.infrastructure.repositories.sqlite_order_repo import SqliteOrderRepo
    from src.infrastructure.repositories.sqlite_position_repo import (
        SqlitePositionRepo,
    )
    from src.use_cases.pending_settler import PendingSettler
    from src.use_cases.reconciliation import Reconciler

    config = KISConfig.from_env(environ)
    http_client: HttpClient = http if http is not None else RequestsHttpClient()
    utc_clock: Callable[[], datetime] = (
        clock if clock is not None else (lambda: datetime.now(UTC))
    )

    auth = KISAuth(config=config, http=http_client, clock=utc_clock)
    client = KISClient(
        config=config, http=http_client, auth=auth, clock=utc_clock
    )

    conn = connect(db_path)

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(conn)

    # Write-enabled KIS broker: order_store over the SHARED connection so dedup
    # (find_by_idempotency_key) + cancel routing (find_by_broker_order_id) read
    # committed orders.
    order_store = SqliteKISOrderStore(orders=SqliteOrderRepo(conn))
    kis_broker = KISBroker(
        client=client, order_store=order_store, clock=utc_clock
    )
    market_data = KISMarketData(
        client=client, explicit_holidays=explicit_holidays
    )

    # Orchestrator's self._broker: DB positions + KIS balance + KIS write
    # delegation (DbPositionBrokerView — the KIS broker never attaches directly).
    broker_view = DbPositionBrokerView(
        positions=SqlitePositionRepo(conn),
        balance_source=kis_broker,
        order_broker=kis_broker,
    )

    slot_model = slot_model_for_buy_strategy(buy_strategy_name)
    settler = PendingSettler(
        uow_factory=uow_factory,
        broker=kis_broker,
        slot_model=slot_model,
        max_pending_age_business_days=max_pending_age_business_days,
    )

    notif: NotifierPort = notifier or build_notifier(environ)
    halt_cb: Callable[[str], None] = halt or _default_halt
    reconciler = Reconciler(
        uow_factory=uow_factory,
        broker=kis_broker,  # get_holdings (read) — HoldingsReaderPort
        notifier=notif,
        halt=halt_cb,
        clock=utc_clock,
    )

    # Live sell threshold default = +15% (ADR 0012 D7); Phase 0 paper uses +10%.
    effective_sell_config = sell_strategy_config or SellStrategyConfig(
        profit_target_pct=Decimal("15.0"),
        max_sells_per_day=7,
    )
    effective_reentry_params = (
        dict(reentry_parameters)
        if reentry_parameters is not None
        else {"cooldown_days": 60}
    )
    # Per-asset params (Case A) or uniform broadcast (per_asset_overrides=None).
    # Strategy TYPES stay uniform either way (single slot_model).
    asset_contexts = build_asset_contexts(
        assets=assets,
        buy_strategy_name=buy_strategy_name,
        reentry_strategy_name=reentry_strategy_name,
        market_data=market_data,
        buy_config=strategy_config,
        sell_config=effective_sell_config,
        reentry_parameters=effective_reentry_params,
        per_asset_overrides=per_asset_overrides,
    )
    orchestrator = DailyOrchestrator(
        broker=broker_view,
        market_data=market_data,
        signal=NullSignal(),
        asset_contexts=asset_contexts,
        clock=utc_clock,
        uow_factory=uow_factory,
    )

    return LiveComponents(
        orchestrator=orchestrator,
        settler=settler,
        reconciler=reconciler,
        broker=kis_broker,
        position_source=broker_view,
        market_data=market_data,
        notifier=notif,
        config=config,
        uow_factory=uow_factory,
        clock=utc_clock,
        close=conn.close,
    )


# ===========================================================================
# DGT grid live (ADR 0022 §13 D30.2)
# ===========================================================================


@dataclass
class GridLiveComponents:
    """Wired DGT grid live component graph (ADR 0022 §13 D30.2).

    `trading grid-live` 가 사용 — settle → reconcile → arm → decide
    (run_grid_live_pipeline). orchestrator 는 GridDryRunOrchestrator 이지만
    broker 는 write-enabled KISBroker (실주문). holdings_provider 는
    grid_decisions 재생 (D25 make_grid_holdings_provider). market_data 는
    KISMarketData (실시세, read-only).
    """

    orchestrator: object  # GridDryRunOrchestrator (forward ref 회피)
    settler: object  # PendingSettler
    reconciler: object  # Reconciler
    broker: object  # KISBroker (write)
    market_data: object  # KISMarketData
    notifier: NotifierPort
    config: object  # KISConfig
    uow_factory: Callable[[], UnitOfWorkPort]
    clock: Callable[[], datetime]
    close: Callable[[], None]


def build_grid_live_components(
    *,
    db_path: Path | str,
    environ: Mapping[str, str] | None = None,
    http: HttpClient | None = None,
    clock: Callable[[], datetime] | None = None,
    notifier: NotifierPort | None = None,
    halt: Callable[[str], None] | None = None,
    max_pending_age_business_days: int = 1,
) -> GridLiveComponents:
    """Wire the DGT grid live component graph (ADR 0022 §13 D30.2).

    Composition root for ``trading grid-live``. Wires:

    - **write-enabled** ``KISBroker`` (order_store 공유 connection) — D17 6세그
      grid idempotency key 호환 (D24 변경 zero).
    - ``KISMarketData`` (read) — get_ohlcv lookback 로 bars 로드.
    - ``PendingSettler`` (grid 분기 D21 자동 활용) over KIS broker.
    - ``Reconciler`` (grid 인식 D26 자동 활용) over KIS broker (get_holdings
      read-only).
    - ``GridDryRunOrchestrator`` (D23) with KISBroker + live
      ``make_grid_holdings_provider`` (D25 — grid_decisions 재생).

    DI per CLAUDE.md §1.2: ``http`` / ``clock`` / ``notifier`` / ``halt`` 주입
    가능 — 테스트 network-free + sentinel-free.

    실주문은 ``orchestrator.step_today`` 호출 시에만 — runner 의 arming gate
    (D32) 이후. 본 함수는 그래프만 wire (실주문 zero).
    """
    from src.adapters.kis._client import KISClient
    from src.adapters.kis._http import RequestsHttpClient
    from src.adapters.kis.auth import KISAuth
    from src.adapters.kis.broker import KISBroker
    from src.adapters.kis.config import KISConfig
    from src.adapters.kis.market_data import KISMarketData
    from src.adapters.kis.order_store import SqliteKISOrderStore
    from src.adapters.telegram.notifier import build_notifier
    from src.infrastructure.repositories.sqlite_order_repo import SqliteOrderRepo
    from src.use_cases.grid_dry_run import (
        GridDryRunOrchestrator,
        make_grid_holdings_provider,
    )
    from src.use_cases.pending_settler import PendingSettler
    from src.use_cases.reconciliation import Reconciler

    config = KISConfig.from_env(environ)
    http_client: HttpClient = http if http is not None else RequestsHttpClient()
    utc_clock: Callable[[], datetime] = (
        clock if clock is not None else (lambda: datetime.now(UTC))
    )

    auth = KISAuth(config=config, http=http_client, clock=utc_clock)
    client = KISClient(
        config=config, http=http_client, auth=auth, clock=utc_clock
    )

    conn = connect(db_path)

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(conn)

    order_store = SqliteKISOrderStore(orders=SqliteOrderRepo(conn))
    kis_broker = KISBroker(
        client=client, order_store=order_store, clock=utc_clock
    )
    market_data = KISMarketData(client=client)

    notif: NotifierPort = notifier or build_notifier(environ)
    halt_cb: Callable[[str], None] = halt or _default_halt

    settler = PendingSettler(
        uow_factory=uow_factory,
        broker=kis_broker,
        max_pending_age_business_days=max_pending_age_business_days,
    )
    reconciler = Reconciler(
        uow_factory=uow_factory,
        broker=kis_broker,
        notifier=notif,
        halt=halt_cb,
        clock=utc_clock,
    )

    # GridDryRunOrchestrator with live holdings_provider — broker 의존을
    # grid_decisions 재생 (D25) 으로 대체. timestamp_for_bar = KST 종가 시각.
    def _ts_for_bar(b):  # noqa: ANN001
        d = b.trade_date
        return datetime(d.year, d.month, d.day, 6, 30, tzinfo=UTC)

    orchestrator = GridDryRunOrchestrator(
        broker=kis_broker,
        uow_factory=uow_factory,
        timestamp_for_bar=_ts_for_bar,
        holdings_provider=make_grid_holdings_provider(uow_factory),
    )

    return GridLiveComponents(
        orchestrator=orchestrator,
        settler=settler,
        reconciler=reconciler,
        broker=kis_broker,
        market_data=market_data,
        notifier=notif,
        config=config,
        uow_factory=uow_factory,
        clock=utc_clock,
        close=conn.close,
    )


def check_snapshot_position_sync(
    uow_factory: Callable[[], SqliteUnitOfWork],
) -> None:
    """Phase 0 sanity check (ADR §10.4).

    Verifies the most-recent snapshot's valuation set matches the
    positions table by ``asset.fqn``. First-ever run (no snapshot)
    short-circuits to OK. Mismatch raises ``IntegrityError`` — system
    halts; manual reconciliation required (no auto-fix per CLAUDE.md
    §11.2).
    """
    with uow_factory() as uow:
        last_snap = uow.snapshots.get_last()
        positions = uow.positions.list_all()
    if last_snap is None:
        return
    snap_assets = {v.asset.fqn for v in last_snap.valuations}
    pos_assets = {p.asset.fqn for p in positions if p.quantity > 0}
    if snap_assets != pos_assets:
        raise IntegrityError(
            f"Snapshot/position mismatch: snapshot has {snap_assets}, "
            f"positions table has {pos_assets}. Refusing to start; "
            f"manual reconciliation required."
        )


def build_paper_components(
    *,
    assets: list[Asset],
    bars_by_asset: dict[Asset, list[OHLCV]],
    db_path: Path | str,
    initial_capital: Money,
    strategy_config: SplitStrategyConfig,
    initial_clock: datetime,
    sell_strategy_config: SellStrategyConfig | None = None,
    reentry_strategy_name: str = "hybrid",
    reentry_parameters: dict[str, Any] | None = None,
    buy_strategy_name: str = "price_drop",
    market_data: MarketDataPort | None = None,
    per_asset_overrides: dict[str, AssetPolicyOverride] | None = None,
) -> PaperComponents:
    """Build a paper-trading orchestrator + snapshot builder.

    Phase 0.7.1 — accepts ``assets: list[Asset]`` (non-empty) and
    ``bars_by_asset`` dict. All assets share the same strategy_config /
    sell_strategy_config / reentry policy (ADR 0003 §7.3 uniformity).
    ``run_for_date`` returns one Decision per asset in declaration order.

    - Opens / bootstraps the SQLite DB at ``db_path``.
    - Runs the snapshot/position sanity check.
    - Restores cash from the latest snapshot (or ``initial_capital`` if
      no snapshot exists yet) and positions from the positions table.
    - Wires MockBroker + MockMarketData + NullSignal + PriceDropStrategy
      with a mutable clock so the caller can swap decision-time vs
      snapshot-time without rebuilding the graph.

    Phase 1.1 (paper-on-live) — ``market_data`` is optional. When ``None``
    (default, backward-compatible) a ``MockMarketData(bars_by_asset)`` is
    built as before (회귀 zero). When a ``MarketDataPort`` is injected (e.g.
    a live ``KISMarketData``) it is used verbatim and ``bars_by_asset`` is
    ignored (an empty dict is fine). The broker stays a MockBroker either
    way — live data + simulated fills, no real order / no real account.
    """
    if not assets:
        raise ValueError("assets must be a non-empty list")

    conn = connect(db_path)

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(conn)

    check_snapshot_position_sync(uow_factory)

    with uow_factory() as uow:
        last_snap = uow.snapshots.get_last()
        cash_money = last_snap.cash if last_snap is not None else initial_capital
        stored_positions = uow.positions.list_all()

    clock_holder: list[datetime] = [initial_clock]

    def set_clock(dt: datetime) -> None:
        clock_holder[0] = dt

    def clock() -> datetime:
        return clock_holder[0]

    broker = MockBroker(
        initial_balance=Balance(cash=cash_money),
        clock=clock,
        slot_model=slot_model_for_buy_strategy(buy_strategy_name),
    )
    for position in stored_positions:
        broker.set_position(position)

    # Phase 1.1: live data injection (paper-on-live). Default = MockMarketData
    # over bars_by_asset (backward-compatible). Injected market_data (e.g.
    # KISMarketData) is used verbatim — bars_by_asset is then ignored.
    effective_market_data: MarketDataPort = (
        market_data
        if market_data is not None
        else MockMarketData(ohlcv_by_asset=bars_by_asset)
    )

    effective_sell_config = sell_strategy_config or SellStrategyConfig(
        profit_target_pct=Decimal("10.0"),
        max_sells_per_day=7,
    )
    effective_reentry_params = (
        dict(reentry_parameters)
        if reentry_parameters is not None
        else {"cooldown_days": 60}
    )

    # ADR 0003 §7.3 / §19.4: uniform broadcast (per_asset_overrides=None) OR
    # per-asset params (Case A). Strategy TYPES stay uniform either way.
    asset_contexts = build_asset_contexts(
        assets=assets,
        buy_strategy_name=buy_strategy_name,
        reentry_strategy_name=reentry_strategy_name,
        market_data=effective_market_data,
        buy_config=strategy_config,
        sell_config=effective_sell_config,
        reentry_parameters=effective_reentry_params,
        per_asset_overrides=per_asset_overrides,
    )
    orchestrator = DailyOrchestrator(
        broker=broker,
        market_data=effective_market_data,
        signal=NullSignal(),
        asset_contexts=asset_contexts,
        clock=clock,
        uow_factory=uow_factory,
    )
    snapshot_builder = DailySnapshotBuilder(
        broker=broker,
        market_data=effective_market_data,
        uow_factory=uow_factory,
        clock=clock,
        initial_capital=initial_capital,
    )

    return PaperComponents(
        orchestrator=orchestrator,
        snapshot_builder=snapshot_builder,
        set_clock=set_clock,
        close=conn.close,
    )


def kodex200() -> Asset:
    """KODEX 200 (069500) — 편의 accessor. 정본 = config/assets.yaml (ADR 0021 §7.1).

    ADR 0005 §1.7 (market/listed_at) 박제 종목. listed_at = 2002-10-14 (KRX 공식).
    """
    return asset_from_code("069500")


def kodex_short_bond_plus() -> Asset:
    """Phase 0.7.1 — KODEX 단기채권 PLUS (214980).

    Asset-class: KR_ETF on KRX, KRW-settled. tick_size / lot_size are
    Phase 0.7.1 placeholders; Phase 1 KIS adapter will supply the real
    KRX market rules.

    Phase 0.9 (ADR 0005 §1.7.1 / §1.7.2 + §3 합병 박제): ``market`` /
    ``listed_at`` 필수 필드 추가. listed_at = 2014-04-22 (KRX 공식).
    """
    return asset_from_code("214980")


def kodex_gold() -> Asset:
    """Phase 0.7.3 — KODEX 골드선물(H) (132030).

    ADR 0003 §18 (라운드 #8) + §18.12 (fallback (d) 채택) 박제 종목.
    Asset-class: KR_ETF on KRX, KRW-settled. tick_size / lot_size 는
    Phase 0.7.3 placeholders; Phase 1 KIS adapter 가 KRX 시장 규칙 공급.

    Phase 0.9 (ADR 0005 §1.7.1 / §1.7.2 + §3 합병 박제): ``market`` /
    ``listed_at`` 필수 필드 추가. listed_at = 2010-10-01 (KRX 공식).
    """
    return asset_from_code("132030")


# ---------------------------------------------------------------------------
# Phase 0.9 — 개별 주식 5 종 (ADR 0005 §1.6.2 + §1.7 + §3 합병 박제)
# ---------------------------------------------------------------------------
# tick_size 필드는 KR_STOCK 분기에서 미사용 (Asset.round_to_tick 이 helper
# 호출). 의미적으로는 KRX 개별 주식 최소 호가 단위 = 1원 placeholder
# (ADR 0005 §3.3.1 박제). lot_size = 1 (KRX 개별 주식 표준).


def samsung_electronics() -> Asset:
    """Phase 0.9.1 — 005930 삼성전자 (반도체).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (반도체).
    listed_at = 1975-06-11 (KRX 공식). Phase 0.9 sub-step 0.9.c
    사전 검증 PASS (lookback 246 + 5-year 데이터 충족, ADR 0005 §2).
    """
    return asset_from_code("005930")


def hyundai_motor() -> Asset:
    """Phase 0.9.1 — 005380 현대차 (자동차).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (자동차).
    listed_at = 1974-06-28 (KRX 공식). Phase 0.9 sub-step 0.9.c
    사전 검증 PASS.
    """
    return asset_from_code("005380")


def shinhan_financial() -> Asset:
    """Phase 0.9.2 — 055550 신한지주 (금융).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (금융).
    listed_at = 2001-09-10 (지주사 전환 상장, KRX 공식).
    Phase 0.9 sub-step 0.9.c 사전 검증 PASS.
    """
    return asset_from_code("055550")


def cj_cheiljedang() -> Asset:
    """Phase 0.9.2 — 097950 CJ제일제당 (소비재).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (소비재 — 경기 방어).
    listed_at = 2007-09-19 (CJ 분할 후 재상장, KRX 공식).
    Phase 0.9 sub-step 0.9.c 사전 검증 PASS.
    """
    return asset_from_code("097950")


def kepco() -> Asset:
    """Phase 0.9.2 — 015760 한국전력 (에너지).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (에너지 / 유틸리티).
    listed_at = 1989-08-10 (KRX 공식). Phase 0.9 sub-step 0.9.c
    사전 검증 PASS.
    """
    return asset_from_code("015760")


def hyosung_heavy_industries() -> Asset:
    """Phase 0.10.x ad-hoc 사용자 분석 — 298040 효성중공업 (산업재).

    KOSPI 중대형주 (변압기 / 중전기). listed_at = 2018-07-13 (효성 인적분할
    재상장, KRX 공식, pykrx 검증). 2020-2024 백테스트 가능.
    """
    return asset_from_code("298040")


# Phase 1.1 data-driven registry (ADR 0021 §7.1 통합): 전 자산 메타데이터의
# 정본 = ``config/assets.yaml``. 하드코딩 _ASSET_FACTORIES 제거 — Phase 0 박제
# 9 종 포함 모든 종목을 yaml 에서 로드. 위 named accessor (kodex200 등) 는 본
# 함수를 호출하는 편의 wrapper. 경로는 repo root 기준 (composition.py =
# src/cli/composition.py → parents[2]) 으로 cwd 무관.
_DEFAULT_ASSETS_YAML = Path(__file__).resolve().parents[2] / "config" / "assets.yaml"


def asset_from_code(
    code: str, registry_path: Path | str | None = None
) -> Asset:
    """Look up an Asset by KRX code from ``config/assets.yaml`` (단일 정본).

    데이터 주도 (ADR 0021). 새 종목은 ``scripts/manage_strategies.py`` 로
    yaml 에 추가 — composition.py 수정 불요.

    Args:
        code: KRX asset code.
        registry_path: assets.yaml path override (tests / non-default config).
            Defaults to ``<repo>/config/assets.yaml``.

    Raises:
        KeyError: code 가 assets.yaml 에 없음.
    """
    path = Path(registry_path) if registry_path is not None else _DEFAULT_ASSETS_YAML
    registry = load_asset_registry(path)
    asset = registry.get(code)
    if asset is not None:
        return asset
    raise KeyError(
        f"No Asset metadata for code {code!r}. "
        f"config/assets.yaml: {sorted(registry.keys())}. "
        "Add a new asset via scripts/manage_strategies.py."
    )
