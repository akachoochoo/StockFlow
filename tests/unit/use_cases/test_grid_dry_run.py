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
from src.use_cases.grid_dry_run import GridDryRunOrchestrator
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
