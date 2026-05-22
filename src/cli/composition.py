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
from src.use_cases.asset_context import AssetContext
from src.use_cases.daily_orchestrator import DailyOrchestrator

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import date, time
    from pathlib import Path

    from src.adapters.kis._http import HttpClient
    from src.adapters.kis.broker import KISBroker
    from src.adapters.kis.config import KISConfig
    from src.adapters.kis.market_data import KISMarketData
    from src.domain.models import OHLCV, Asset, Money
    from src.domain.strategies.price_drop import SplitStrategyConfig
    from src.ports.market_data import MarketDataPort
    from src.ports.reentry_strategy import ReentryPriceStrategyPort


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
    reentry = (
        create_reentry_strategy(
            reentry_strategy_name,
            market_data=effective_market_data,
            **effective_reentry_params,
        )
        if buy_strategy_name == "price_drop"
        else None
    )

    # ADR 0004 §5.2: factory dispatches between PriceDropStrategy and
    # SupportLevelStrategy based on yaml `buy_strategy`. SupportLevelStrategy
    # ignores reentry (ADR §4.3 β-2).
    buy_strategy = create_buy_strategy(buy_strategy_name, reentry=reentry)

    # Build one AssetContext per asset; all share the same strategy instance
    # and configs (ADR 0003 §7.3 — policy uniformity checked by loader).
    asset_contexts = [
        AssetContext(
            asset=asset,
            strategy=buy_strategy,
            config=strategy_config,
            sell_strategy=ProfitTargetSell(),
            sell_config=effective_sell_config,
        )
        for asset in assets
    ]
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
    """Phase 0 single-asset definition.

    Hardcoded here so the CLI default works without a config file. When
    Phase 1 adds multiple assets this graduates to a YAML lookup.

    Phase 0.9 (ADR 0005 §1.7.1 / §1.7.2 + §3 합병 박제): ``market`` /
    ``listed_at`` 필수 필드 추가. listed_at = 2002-10-14 (KRX 공식).
    """
    from datetime import date  # local import: keeps top imports tight
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

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


def kodex_short_bond_plus() -> Asset:
    """Phase 0.7.1 — KODEX 단기채권 PLUS (214980).

    Asset-class: KR_ETF on KRX, KRW-settled. tick_size / lot_size are
    Phase 0.7.1 placeholders; Phase 1 KIS adapter will supply the real
    KRX market rules.

    Phase 0.9 (ADR 0005 §1.7.1 / §1.7.2 + §3 합병 박제): ``market`` /
    ``listed_at`` 필수 필드 추가. listed_at = 2014-04-22 (KRX 공식).
    """
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="214980",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 단기채권 PLUS",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2014, 4, 22),
    )


def kodex_gold() -> Asset:
    """Phase 0.7.3 — KODEX 골드선물(H) (132030).

    ADR 0003 §18 (라운드 #8) + §18.12 (fallback (d) 채택) 박제 종목.
    Asset-class: KR_ETF on KRX, KRW-settled. tick_size / lot_size 는
    Phase 0.7.3 placeholders; Phase 1 KIS adapter 가 KRX 시장 규칙 공급.

    Phase 0.9 (ADR 0005 §1.7.1 / §1.7.2 + §3 합병 박제): ``market`` /
    ``listed_at`` 필수 필드 추가. listed_at = 2010-10-01 (KRX 공식).
    """
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="132030",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 골드선물(H)",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2010, 10, 1),
    )


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
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="005930",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="삼성전자",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(1975, 6, 11),
    )


def hyundai_motor() -> Asset:
    """Phase 0.9.1 — 005380 현대차 (자동차).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (자동차).
    listed_at = 1974-06-28 (KRX 공식). Phase 0.9 sub-step 0.9.c
    사전 검증 PASS.
    """
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="005380",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="현대차",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(1974, 6, 28),
    )


def shinhan_financial() -> Asset:
    """Phase 0.9.2 — 055550 신한지주 (금융).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (금융).
    listed_at = 2001-09-10 (지주사 전환 상장, KRX 공식).
    Phase 0.9 sub-step 0.9.c 사전 검증 PASS.
    """
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="055550",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="신한지주",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2001, 9, 10),
    )


def cj_cheiljedang() -> Asset:
    """Phase 0.9.2 — 097950 CJ제일제당 (소비재).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (소비재 — 경기 방어).
    listed_at = 2007-09-19 (CJ 분할 후 재상장, KRX 공식).
    Phase 0.9 sub-step 0.9.c 사전 검증 PASS.
    """
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="097950",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="CJ제일제당",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2007, 9, 19),
    )


def kepco() -> Asset:
    """Phase 0.9.2 — 015760 한국전력 (에너지).

    ADR 0005 §1.6.2 박제 종목. KOSPI 대형주 (에너지 / 유틸리티).
    listed_at = 1989-08-10 (KRX 공식). Phase 0.9 sub-step 0.9.c
    사전 검증 PASS.
    """
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="015760",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="한국전력",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(1989, 8, 10),
    )


def hyosung_heavy_industries() -> Asset:
    """Phase 0.10.x ad-hoc 사용자 분석 — 298040 효성중공업 (산업재).

    KOSPI 중대형주 (변압기 / 중전기). listed_at = 2018-07-13 (효성 인적분할
    재상장, KRX 공식, pykrx 검증). 2020-2024 백테스트 가능.
    """
    from datetime import date
    from decimal import Decimal

    from src.domain.models import (
        Asset,
        AssetClass,
        Currency,
        Exchange,
        Market,
    )

    return Asset(
        code="298040",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="효성중공업",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2018, 7, 13),
    )


# Registry: code → factory. Phase 0.7.x: 3 ETF. Phase 0.9 (ADR 0005 §1.6.2
# + §3 합병 박제): + 5 KR_STOCK 추가 (Phase 0.9.1 = 005930 + 005380,
# Phase 0.9.2 = + 055550 + 097950 + 015760).
# Phase 0.10.x ad-hoc 분석: + 298040 효성중공업 (사용자 단일 종목 백테스트).
_ASSET_FACTORIES: dict[str, Callable[[], Asset]] = {
    "069500": kodex200,
    "214980": kodex_short_bond_plus,
    "132030": kodex_gold,
    "005930": samsung_electronics,
    "005380": hyundai_motor,
    "055550": shinhan_financial,
    "097950": cj_cheiljedang,
    "015760": kepco,
    "298040": hyosung_heavy_industries,
}


def asset_from_code(code: str) -> Asset:
    """Look up an Asset factory by KRX code and instantiate it.

    Raises KeyError with a helpful message when the code is not registered.
    New assets require a composition.py update (per Phase 0.7.1 design —
    asset metadata stays hardcoded until Phase 1+ KIS adapter arrives).
    """
    factory = _ASSET_FACTORIES.get(code)
    if factory is None:
        supported = list(_ASSET_FACTORIES.keys())
        raise KeyError(
            f"No Asset factory for code {code!r}. "
            f"Phase 0.7.1 supports {supported}; "
            "new codes need composition.py update."
        )
    return factory()
