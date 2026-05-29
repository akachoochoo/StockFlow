"""Tests for GridDryRunOrchestrator + G2 진성 동등성 (ADR 0022 §12 D23).

Verifies that the broker-driven dry-run path produces the *same* trade
sequence as the in-memory backtest GridRunner — closing the §7.4 backtest↔
dry-run identity gap. Fakes only (no KIS network).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.adapters.mock.broker import MockBroker
from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Balance,
    Currency,
    Exchange,
    Market,
    Money,
    OrderSide,
)
from src.domain.strategies.grid import GridConfig
from src.use_cases.grid_dry_run import (
    GridDryRunOrchestrator,
    make_grid_holdings_provider,
    reconstruct_grid_broker_state,
)
from src.use_cases.grid_runner import GridRunner

DAY0 = date(2026, 5, 1)
ASSET = Asset(
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


def _bar(idx: int, *, close: int, volume: int = 1_000_000) -> OHLCV:
    """Synthetic daily OHLCV — open/high/low fan out around close."""
    return OHLCV(
        asset=ASSET,
        trade_date=date(2026, 5, 1 + idx),
        open=Decimal(close - 50),
        high=Decimal(close + 100),
        low=Decimal(close - 100),
        close=Decimal(close),
        volume=Decimal(volume),
    )


def _bars_oscillating() -> list[OHLCV]:
    """Synthetic price path that crosses grid levels both directions.

    Triangular wave around 30,000: up 5%, down 5%, up 5%, down 5% — generates
    multiple grid crossings for both BUY and SELL emissions.
    """
    closes = [
        30000, 30200, 30400, 30700, 31000, 31500,  # up
        31200, 30700, 30200, 29700, 29200,         # down
        29700, 30200, 30700, 31200,                # up
        30800, 30300, 29800, 29400, 29000,         # down
    ]
    return [_bar(i, close=c) for i, c in enumerate(closes)]


def _config() -> GridConfig:
    return GridConfig(
        grid_count=6,
        fallback_k=Decimal("0.01"),
        rebalance_mode="on_breach",
        k_min=Decimal("0.005"),
        k_max=Decimal("0.02"),
        profit_guard=True,
        sell_cooldown_bars=0,  # 단순화 — D23 first commit
        price_based_reentry=False,
        volatility_measure="adr",
    )


def _make_broker(initial_capital: int = 10_000_000) -> MockBroker:
    return MockBroker(
        initial_balance=Balance(
            cash=Money(amount=Decimal(initial_capital), currency=Currency.KRW)
        ),
        clock=lambda: datetime(2026, 5, 28, 6, tzinfo=UTC),
    )


def _ts_for_bar(bar: OHLCV) -> datetime:
    """Map bar -> trading-time UTC timestamp (한국 종가 ≈ 06:30 UTC)."""
    d = bar.trade_date
    return datetime(d.year, d.month, d.day, 6, 30, tzinfo=UTC)


class TestG2TradeEquivalence:
    """GridRunner backtest ↔ GridDryRunOrchestrator broker-driven 동치성."""

    def test_same_trade_count(self) -> None:
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        backtest = GridRunner().run(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )

        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        dryrun_decisions = orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )

        assert len(dryrun_decisions) == len(backtest.trades), (
            f"trade count mismatch — backtest={len(backtest.trades)}, "
            f"dryrun={len(dryrun_decisions)}"
        )

    def test_same_side_sequence(self) -> None:
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        backtest = GridRunner().run(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        dryrun = orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )

        assert [d.side for d in dryrun] == [t.side for t in backtest.trades]

    def test_same_rounded_price_sequence(self) -> None:
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        backtest = GridRunner().run(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        dryrun = orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        # 가격은 GridDecision.rounded_price ↔ GridTrade.rounded_price 비교.
        assert [d.rounded_price for d in dryrun] == [
            t.rounded_price for t in backtest.trades
        ]

    def test_same_quantity_sequence(self) -> None:
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        backtest = GridRunner().run(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        dryrun = orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        assert [d.quantity for d in dryrun] == [t.quantity for t in backtest.trades]

    def test_broker_cash_equals_backtest_gross_only(self) -> None:
        """Broker cash = gross only (commission/tax 미반영). GridRunner 의
        final_cash = cost-inclusive. 차이 = 총 friction 비용 (의도된
        아이덜라이제이션, ADR 0022 §12 D20 + grid_runner.py:14-15).

        본 테스트는 broker 가 *gross* 동치를 유지함을 박제 — 실거래 KIS 도
        체결 응답은 gross 기준, commission/tax 는 별도 필드/일별 합계 (ADR
        0020 §4 thdt_tlex_amt).
        """
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        backtest = GridRunner().run(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        # Gross-only cash 계산: initial - Σ(buy gross) + Σ(sell gross).
        gross_buy = sum(
            (t.gross for t in backtest.trades if t.side is OrderSide.BUY),
            Decimal("0"),
        )
        gross_sell = sum(
            (t.gross for t in backtest.trades if t.side is OrderSide.SELL),
            Decimal("0"),
        )
        expected_gross_cash = capital.amount - gross_buy + gross_sell
        assert broker.get_balance().cash.amount == expected_gross_cash

    def test_broker_final_holdings_match_backtest(self) -> None:
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        backtest = GridRunner().run(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        holding = broker.get_grid_holding(ASSET.fqn)
        backtest_qty = backtest.final_holdings
        if backtest_qty == 0:
            assert holding is None
        else:
            assert holding is not None
            assert holding.quantity == backtest_qty


class TestPersistence:
    def test_grid_decisions_saved_to_uow(self) -> None:
        """uow.grid_decisions 에 dry-run 결정이 timestamp 순으로 저장."""
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        executed = orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        saved = uow.grid_decisions.list_by_date_range(
            ASSET.fqn, bars[0].trade_date, bars[-1].trade_date
        )
        # 저장 count 와 executed count 일치.
        assert len(saved) == len(executed)
        # 저장 시퀀스 (시간 정렬) 가 executed 시퀀스와 동일.
        for s, e in zip(saved, executed, strict=True):
            assert s.side == e.side
            assert s.level_index == e.level_index
            assert s.quantity == e.quantity


class TestStepTodayEquivalence:
    """``replay_bars(all bars)`` ≡ N invocations of ``step_today(bars[:i+1])``.

    크론 모드의 결정론 박제 — single-step state persistence 가 batch 와 동일한
    trade sequence 를 produce 함을 측정 가능하게 검증.
    """

    def test_step_per_bar_equals_replay_bars(self) -> None:
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)

        # Path A: replay_bars (batch)
        broker_a = _make_broker()
        uow_a = InMemoryUnitOfWork()
        orch_a = GridDryRunOrchestrator(
            broker=broker_a,
            uow_factory=lambda: uow_a,
            timestamp_for_bar=_ts_for_bar,
        )
        batch_decisions = orch_a.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )

        # Path B: step_today over a growing bars prefix (cron mode)
        broker_b = _make_broker()
        uow_b = InMemoryUnitOfWork()
        orch_b = GridDryRunOrchestrator(
            broker=broker_b,
            uow_factory=lambda: uow_b,
            timestamp_for_bar=_ts_for_bar,
        )
        cron_decisions: list = []
        for i in range(len(bars)):
            decs_today = orch_b.step_today(
                asset=ASSET,
                bars=bars[: i + 1],
                config=config,
                initial_capital=capital,
            )
            cron_decisions.extend(decs_today)

        # 동치성: 두 시퀀스 trade-by-trade 동일.
        assert len(cron_decisions) == len(batch_decisions)
        for a, b in zip(cron_decisions, batch_decisions, strict=True):
            assert a.side == b.side
            assert a.level_index == b.level_index
            assert a.rounded_price == b.rounded_price
            assert a.quantity == b.quantity

        # 최종 broker cash + holdings 도 동일.
        assert (
            broker_b.get_balance().cash.amount == broker_a.get_balance().cash.amount
        )
        h_a = broker_a.get_grid_holding(ASSET.fqn)
        h_b = broker_b.get_grid_holding(ASSET.fqn)
        if h_a is None:
            assert h_b is None
        else:
            assert h_b is not None
            assert h_b.quantity == h_a.quantity
            assert h_b.avg_price == h_a.avg_price

    def test_step_today_first_call_bootstraps_grid_state(self) -> None:
        """No prior state → bootstrap from bars[0].close (cold start).

        Bar 0 만 처리 — bar_idx=0 은 prev_close 가 없어 결정 zero → grid_state
        는 bootstrap 그대로 (on_breach 재중심 없음).
        """
        bars = _bars_oscillating()[:1]
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        # 사전에 grid_states 비어있어야 함.
        assert uow.grid_states.get(ASSET.fqn) is None
        executed = orch.step_today(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        # Day 0 = 결정 zero (no prev_close).
        assert executed == []
        # 호출 후 grid_states 에 상태 저장됨 — reference_price = bars[0].close.
        saved = uow.grid_states.get(ASSET.fqn)
        assert saved is not None
        assert saved.grid_state.reference_price == bars[0].close
        assert saved.cooldown_remaining == 0
        assert saved.last_sell_price == Decimal("0")
        assert saved.avg_cost == Decimal("0")

    def test_step_today_persists_runtime_fields(self) -> None:
        """매도 발생 시 cooldown / last_sell_price 가 grid_states 에 보존."""
        bars = _bars_oscillating()
        config = _config().model_copy(update={"sell_cooldown_bars": 3})
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        # 전체 처리 시 매도 1+ 회 발생함을 batch path 로 확인.
        replayed = orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        any_sells = any(d.side == OrderSide.SELL for d in replayed)
        assert any_sells, "test premise: 매도 발생 시나리오 필요"
        # Cron 모드로 다시 처리 → grid_states 에 cooldown / last_sell_price 가
        # 매도 발생 이후 의도대로 갱신되는지 확인.
        broker2 = _make_broker()
        uow2 = InMemoryUnitOfWork()
        orch2 = GridDryRunOrchestrator(
            broker=broker2,
            uow_factory=lambda: uow2,
            timestamp_for_bar=_ts_for_bar,
        )
        for i in range(len(bars)):
            orch2.step_today(
                asset=ASSET,
                bars=bars[: i + 1],
                config=config,
                initial_capital=capital,
            )
        final = uow2.grid_states.get(ASSET.fqn)
        # 매도가 한 번이라도 있었으므로 last_sell_price > 0.
        assert final is not None
        assert final.last_sell_price > 0


class TestReconstructBrokerState:
    """grid_decisions 시퀀스 → broker (cash, _GridHolding) 결정론적 재생산."""

    def test_empty_decisions_returns_initial(self) -> None:
        cash, holding = reconstruct_grid_broker_state(
            asset=ASSET,
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
            decisions=[],
        )
        assert cash.amount == Decimal("10000000")
        assert holding is None

    def test_full_replay_matches_replay_bars_state(self) -> None:
        """replay_bars 후 broker 상태 == 그 결과 grid_decisions 를 재생한 state."""
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
        )
        orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        saved = uow.grid_decisions.list_by_date_range(
            ASSET.fqn, bars[0].trade_date, bars[-1].trade_date
        )
        # Reconstruct from grid_decisions
        cash, holding = reconstruct_grid_broker_state(
            asset=ASSET,
            initial_capital=capital,
            decisions=saved,
        )
        # 재생 결과 broker 와 일치
        assert cash.amount == broker.get_balance().cash.amount
        broker_holding = broker.get_grid_holding(ASSET.fqn)
        if broker_holding is None:
            assert holding is None
        else:
            assert holding is not None
            assert holding.quantity == broker_holding.quantity
            assert holding.avg_price == broker_holding.avg_price

    def test_oversell_raises(self) -> None:
        """잘못된 시퀀스 (sell qty > holding) → ValueError."""
        from src.domain.strategies.grid import GridDecision

        buy = GridDecision(
            side=OrderSide.BUY,
            level_index=3,
            level_price=Decimal("30000"),
            rounded_price=Decimal("30000"),
            quantity=Decimal("10"),
            reasoning={},
        )
        sell = GridDecision(
            side=OrderSide.SELL,
            level_index=4,
            level_price=Decimal("30300"),
            rounded_price=Decimal("30300"),
            quantity=Decimal("20"),
            reasoning={},
        )
        import pytest

        with pytest.raises(ValueError, match="exceeds holding"):
            reconstruct_grid_broker_state(
                asset=ASSET,
                initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
                decisions=[buy, sell],
            )


# ===========================================================================
# Multi-asset equivalence (CLI grid-dry-run + grid-backtest, ADR 0022 §11.21)
# ===========================================================================

# 2번째 자산 — 동일 currency / market, 다른 code + listed_at.
ASSET2 = Asset(
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


def _bar_for(asset: Asset, idx: int, *, close: int, volume: int = 1_000_000) -> OHLCV:
    """Generic bar builder — asset 명시 (ASSET2 등 다른 자산 용)."""
    return OHLCV(
        asset=asset,
        trade_date=date(2026, 5, 1 + idx),
        open=Decimal(close - 50),
        high=Decimal(close + 100),
        low=Decimal(close - 100),
        close=Decimal(close),
        volume=Decimal(volume),
    )


def _bars2_distinct() -> list[OHLCV]:
    """ASSET2 용 다른 가격 시퀀스 — ASSET 와 다른 가격대 + 진폭."""
    closes = [
        60000, 60300, 60800, 61500, 62000, 62800,  # up
        62300, 61500, 60700, 59800, 59000,         # down
        59500, 60200, 61000, 61800,                # up
        61300, 60500, 59600, 58800, 58000,         # down
    ]
    return [_bar_for(ASSET2, i, close=c) for i, c in enumerate(closes)]


class TestMultiAssetEquivalence:
    """Multi-asset 처리 시 per-asset 격리 + 단일자산 G2 동치성 유지."""

    def test_multi_asset_decisions_equal_isolated_single_asset(self) -> None:
        """Multi-asset (shared uow) per-asset 결정 == isolated single-asset 결정.

        Per-asset 격리 보장 — multi-asset 처리 시 한 자산의 결정 시퀀스가 그
        자산 단독 dry-run 과 동일. (backtest GridRunner 와의 비교는 cost-coupling
        idealization 차이로 인해 trade-by-trade 동치성 미보장 — D23 문서화 정합.)
        """
        bars1 = _bars_oscillating()
        bars2 = _bars2_distinct()
        config = _config()
        per_asset_capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)

        # Path A — 자산 1 isolated dry-run
        broker_a1 = _make_broker()
        uow_a1 = InMemoryUnitOfWork()
        orch_a1 = GridDryRunOrchestrator(
            broker=broker_a1,
            uow_factory=lambda: uow_a1,
            timestamp_for_bar=_ts_for_bar,
        )
        isolated1 = orch_a1.replay_bars(
            asset=ASSET, bars=bars1, config=config, initial_capital=per_asset_capital
        )

        # Path A — 자산 2 isolated dry-run
        broker_a2 = _make_broker()
        uow_a2 = InMemoryUnitOfWork()
        orch_a2 = GridDryRunOrchestrator(
            broker=broker_a2,
            uow_factory=lambda: uow_a2,
            timestamp_for_bar=_ts_for_bar,
        )
        isolated2 = orch_a2.replay_bars(
            asset=ASSET2, bars=bars2, config=config, initial_capital=per_asset_capital
        )

        # Path B — multi-asset (shared uow, separate brokers, 순차 처리)
        uow_b = InMemoryUnitOfWork()
        broker_b1 = _make_broker()
        orch_b1 = GridDryRunOrchestrator(
            broker=broker_b1,
            uow_factory=lambda: uow_b,
            timestamp_for_bar=_ts_for_bar,
        )
        multi1 = orch_b1.replay_bars(
            asset=ASSET, bars=bars1, config=config, initial_capital=per_asset_capital
        )
        broker_b2 = _make_broker()
        orch_b2 = GridDryRunOrchestrator(
            broker=broker_b2,
            uow_factory=lambda: uow_b,
            timestamp_for_bar=_ts_for_bar,
        )
        multi2 = orch_b2.replay_bars(
            asset=ASSET2, bars=bars2, config=config, initial_capital=per_asset_capital
        )

        # 자산 1 — multi-asset 처리 시 단독 처리와 trade-by-trade 동치
        assert len(multi1) == len(isolated1)
        for m, i in zip(multi1, isolated1, strict=True):
            assert m.side == i.side
            assert m.level_index == i.level_index
            assert m.rounded_price == i.rounded_price
            assert m.quantity == i.quantity
        # 자산 2 — 동일
        assert len(multi2) == len(isolated2)
        for m, i in zip(multi2, isolated2, strict=True):
            assert m.side == i.side
            assert m.level_index == i.level_index
            assert m.rounded_price == i.rounded_price
            assert m.quantity == i.quantity

    def test_grid_decisions_isolated_by_asset(self) -> None:
        """uow.grid_decisions 가 자산별 격리 — list_by_date_range 호출 시 다른 자산 누설 zero."""
        bars1 = _bars_oscillating()
        bars2 = _bars2_distinct()
        config = _config()
        per_asset_capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)

        uow = InMemoryUnitOfWork()
        for asset, bars in [(ASSET, bars1), (ASSET2, bars2)]:
            broker = _make_broker()
            orch = GridDryRunOrchestrator(
                broker=broker,
                uow_factory=lambda: uow,
                timestamp_for_bar=_ts_for_bar,
            )
            orch.replay_bars(
                asset=asset, bars=bars, config=config, initial_capital=per_asset_capital
            )

        saved1 = uow.grid_decisions.list_by_date_range(
            ASSET.fqn, bars1[0].trade_date, bars1[-1].trade_date
        )
        saved2 = uow.grid_decisions.list_by_date_range(
            ASSET2.fqn, bars2[0].trade_date, bars2[-1].trade_date
        )
        # 격리 확인 — 누설 zero
        assert len(saved1) > 0 and len(saved2) > 0
        # 모든 saved1 의 가격대 == ASSET 의 가격대 범위 (30000 근처)
        for d in saved1:
            assert Decimal("28000") <= d.rounded_price <= Decimal("32500")
        # 모든 saved2 의 가격대 == ASSET2 가격대 (58000~63000)
        for d in saved2:
            assert Decimal("57000") <= d.rounded_price <= Decimal("63000")

    def test_per_asset_reconstruct_does_not_leak(self) -> None:
        """shared uow 에서 자산 A 의 broker state 재구성 시 자산 B 의 결정 영향 zero."""
        bars1 = _bars_oscillating()
        bars2 = _bars2_distinct()
        config = _config()
        per_asset_capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)

        uow = InMemoryUnitOfWork()
        for asset, bars in [(ASSET, bars1), (ASSET2, bars2)]:
            broker = _make_broker()
            orch = GridDryRunOrchestrator(
                broker=broker,
                uow_factory=lambda: uow,
                timestamp_for_bar=_ts_for_bar,
            )
            orch.replay_bars(
                asset=asset, bars=bars, config=config, initial_capital=per_asset_capital
            )

        # ASSET 의 reconstruct — ASSET 의 grid_decisions 만 사용해야 함.
        saved1 = uow.grid_decisions.list_by_date_range(
            ASSET.fqn, bars1[0].trade_date, bars1[-1].trade_date
        )
        cash1, hold1 = reconstruct_grid_broker_state(
            asset=ASSET, initial_capital=per_asset_capital, decisions=saved1,
        )
        # ASSET2 의 reconstruct — ASSET2 의 grid_decisions 만.
        saved2 = uow.grid_decisions.list_by_date_range(
            ASSET2.fqn, bars2[0].trade_date, bars2[-1].trade_date
        )
        cash2, hold2 = reconstruct_grid_broker_state(
            asset=ASSET2, initial_capital=per_asset_capital, decisions=saved2,
        )

        # 두 자산의 cash 변동이 독립적 (서로 다른 가격대로 다른 trades).
        assert cash1 != cash2  # 같을 확률 0% (다른 가격대)
        # 두 자산 모두 자기 가격대에서만 거래 (위 saved1/saved2 검증 정합).
        if hold1 is not None:
            assert hold1.asset.fqn == ASSET.fqn
        if hold2 is not None:
            assert hold2.asset.fqn == ASSET2.fqn

    def test_grid_states_isolated_by_asset(self) -> None:
        """grid_states 가 자산별 1행 — step_today 호출 시 자산별 독립."""
        bars1 = _bars_oscillating()
        bars2 = _bars2_distinct()
        config = _config()
        per_asset_capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)

        uow = InMemoryUnitOfWork()
        # 각 자산 1 bar 처리 — bar_idx=0 부터 시작.
        for asset, bars in [(ASSET, bars1), (ASSET2, bars2)]:
            broker = _make_broker()
            orch = GridDryRunOrchestrator(
                broker=broker,
                uow_factory=lambda: uow,
                timestamp_for_bar=_ts_for_bar,
            )
            orch.step_today(
                asset=asset, bars=bars[:5], config=config,
                initial_capital=per_asset_capital,
            )

        # 자산별 grid_states 행 존재
        state1 = uow.grid_states.get(ASSET.fqn)
        state2 = uow.grid_states.get(ASSET2.fqn)
        assert state1 is not None and state2 is not None
        # reference_price 가 서로 다름 (다른 가격대)
        assert state1.grid_state.reference_price != state2.grid_state.reference_price
        # ASSET 의 reference ≈ 30K, ASSET2 의 reference ≈ 60K (bootstrap from bars[0])
        assert Decimal("28000") <= state1.grid_state.reference_price <= Decimal("32000")
        assert Decimal("58000") <= state2.grid_state.reference_price <= Decimal("63000")


# ===========================================================================
# ADR 0022 §13 D25 — holdings_provider 추상화 (live 경로 토대)
# ===========================================================================


class TestHoldingsProvider:
    """orchestrator 가 broker.get_grid_holding 대신 추상화된 provider 호출."""

    def test_default_provider_uses_broker_get_grid_holding(self) -> None:
        """holdings_provider 미주입 시 broker.get_grid_holding 사용 (회귀 zero)."""
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        broker = _make_broker()
        uow = InMemoryUnitOfWork()
        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
            # holdings_provider 미지정 → 기본 broker fallback
        )
        executed = orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        assert len(executed) > 0  # 결정 발생 = 기본 provider 동작 정상

    def test_custom_provider_overrides_broker(self) -> None:
        """provider 가 broker fallback 을 override — broker 호출 없이 holdings 결정."""
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        broker = _make_broker()
        uow = InMemoryUnitOfWork()

        # provider 호출 추적
        calls: list[str] = []

        def fake_provider(asset) -> Decimal:
            calls.append(asset.fqn)
            return Decimal("0")

        orch = GridDryRunOrchestrator(
            broker=broker,
            uow_factory=lambda: uow,
            timestamp_for_bar=_ts_for_bar,
            holdings_provider=fake_provider,
        )
        orch.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )
        # bar 수 만큼 provider 호출 (각 bar 의 _process_one_bar 가 1회 호출)
        assert len(calls) == len(bars)
        assert all(fqn == ASSET.fqn for fqn in calls)

    def test_make_grid_holdings_provider_replays_decisions(self) -> None:
        """make_grid_holdings_provider 가 grid_decisions.list_net_quantities 재생."""
        uow = InMemoryUnitOfWork()
        # ASSET 에 BUY 15 - SELL 3 = net 12 저장
        from src.domain.strategies.grid import GridDecision  # noqa: PLC0415

        ts = datetime(2026, 5, 28, 6, tzinfo=UTC)
        with uow:
            uow.grid_decisions.save(
                asset=ASSET, timestamp=ts,
                decision=GridDecision(
                    side=OrderSide.BUY, level_index=3,
                    level_price=Decimal("30000"),
                    rounded_price=Decimal("30000"),
                    quantity=Decimal("15"), reasoning={},
                ),
            )
            uow.grid_decisions.save(
                asset=ASSET, timestamp=ts.replace(minute=1),
                decision=GridDecision(
                    side=OrderSide.SELL, level_index=4,
                    level_price=Decimal("30300"),
                    rounded_price=Decimal("30300"),
                    quantity=Decimal("3"), reasoning={},
                ),
            )
            uow.commit()

        provider = make_grid_holdings_provider(lambda: uow)
        assert provider(ASSET) == Decimal("12")
        # 결정 없는 자산 → 0 (디폴트)
        from src.domain.models import Asset as _Asset  # noqa: PLC0415

        other = _Asset(
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
        assert provider(other) == Decimal("0")

    def test_live_provider_decisions_match_broker_path(self) -> None:
        """동일 시나리오에서 live provider (grid_decisions 재생) ≡ broker fallback.

        replay_bars 를 두 가지 provider 로 실행 — 결정 시퀀스가 trade-by-trade
        동일해야 함 (G2 진성 동등성의 live 측 부설).
        """
        bars = _bars_oscillating()
        config = _config()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)

        # Path A — 기본 broker provider
        broker_a = _make_broker()
        uow_a = InMemoryUnitOfWork()
        orch_a = GridDryRunOrchestrator(
            broker=broker_a,
            uow_factory=lambda: uow_a,
            timestamp_for_bar=_ts_for_bar,
        )
        decisions_a = orch_a.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )

        # Path B — live provider (grid_decisions 재생)
        broker_b = _make_broker()
        uow_b = InMemoryUnitOfWork()
        orch_b = GridDryRunOrchestrator(
            broker=broker_b,
            uow_factory=lambda: uow_b,
            timestamp_for_bar=_ts_for_bar,
            holdings_provider=make_grid_holdings_provider(lambda: uow_b),
        )
        decisions_b = orch_b.replay_bars(
            asset=ASSET, bars=bars, config=config, initial_capital=capital
        )

        # 결정 시퀀스 trade-by-trade 동치
        assert len(decisions_a) == len(decisions_b)
        for a, b in zip(decisions_a, decisions_b, strict=True):
            assert a.side == b.side
            assert a.level_index == b.level_index
            assert a.rounded_price == b.rounded_price
            assert a.quantity == b.quantity
