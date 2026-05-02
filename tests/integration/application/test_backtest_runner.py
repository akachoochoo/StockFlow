"""Integration tests for BacktestRunner.

End-to-end smoke tests that wire the same Mock adapter set the runner uses
in production (Phase 0). Each scenario validates one design property of
ADR §9: trading-day iteration, look-ahead prevention, holiday handling,
empty-data robustness, split-count exhaustion, and signal blocking.

Lower-level concerns (broker timeout recovery, partial-fill semantics,
strategy-side skip mapping, etc.) are already covered by the
DailyOrchestrator integration suite — not duplicated here.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from src.application.backtest_runner import BacktestRunner
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    CircuitBreakerSignal,
    Currency,
    Exchange,
    Money,
    SignalLevel,
    SignalSource,
)
from src.domain.strategies.price_drop import SplitStrategyConfig


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def _asset() -> Asset:
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


def _bar(asset: Asset, d: date, close: str) -> OHLCV:
    price = Decimal(close)
    return OHLCV(
        asset=asset,
        trade_date=d,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000000"),
    )


def _config(
    drop_pct: str = "7",
    max_split: int = 7,
    per_split: str = "1000000",
) -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal(drop_pct),
        max_split_count=max_split,
        per_split_amount=Money(amount=Decimal(per_split), currency=Currency.KRW),
    )


def _capital(amount: str = "4000000") -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


class _AlwaysHaltSignal:
    """SignalPort that returns HALT for every collect() — used to verify the
    orchestrator short-circuits across the entire backtest."""

    def collect(
        self, asset_class: AssetClass, as_of: datetime
    ) -> CircuitBreakerSignal:
        return CircuitBreakerSignal(
            level=SignalLevel.HALT,
            source=SignalSource.MANUAL,
            asset_class=asset_class,
            evaluated_at=as_of,
            triggered_by=["test_halt"],
            reasoning={},
            valid_until=as_of + timedelta(days=1),
        )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
class TestBacktestRunner:
    def test_basic_5day_scenario_with_one_buy(self):
        # Setup: Day0 is the T-1 fixture (outside [start, end]) so Day1's
        # decision has prior-close data. Days 2-5 have small drops < 7%
        # threshold so only one buy fires.
        asset = _asset()
        days = [date(2026, 4, 23) + timedelta(days=i) for i in range(6)]
        bars = [
            _bar(asset, days[0], "35000"),  # T-1 fixture
            _bar(asset, days[1], "35000"),  # decision sees 35000 → buy
            _bar(asset, days[2], "34000"),  # decision sees 35000 → 0% drop, skip
            _bar(asset, days[3], "34500"),  # decision sees 34000 → ~2.86%, skip
            _bar(asset, days[4], "34000"),  # decision sees 34500 → ~1.43%, skip
            _bar(asset, days[5], "33500"),  # decision sees 34000 → ~2.86%, skip
        ]
        runner = BacktestRunner(
            asset=asset,
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start=days[1], end=days[5])

        assert result.n_trading_days == 5
        assert len(result.decisions) == 5
        assert len(result.snapshots) == 5

        # Day 1: first split buy
        assert result.decisions[0].action_kinds() == ["buy_split_1"]
        # Days 2-5: drop insufficient → strategy_no_buy
        for decision in result.decisions[1:]:
            assert decision.is_skip()

        # Final snapshot: 28 shares @ 35000 (1M/35000 floor lot=1) at last
        # close 33500 → market_value 28*33500 = 938000.
        final = result.final_snapshot
        assert final is not None
        assert final.snapshot_date == days[5]
        assert len(final.valuations) == 1
        assert final.valuations[0].quantity == Decimal("28")
        assert final.valuations[0].market_price == Decimal("33500")
        assert final.total_market_value.amount == Decimal("938000")

    def test_no_lookahead_at_decision_time(self):
        # Day1 decision must use Day0 close (50000), NOT Day1 close (30000).
        # If lookahead occurred, the buy would size 33 shares at 30000;
        # without lookahead, it's 20 shares at 50000.
        asset = _asset()
        d_prev = date(2026, 4, 27)
        d_today = date(2026, 4, 28)
        bars = [
            _bar(asset, d_prev, "50000"),
            _bar(asset, d_today, "30000"),
        ]
        runner = BacktestRunner(
            asset=asset,
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start=d_today, end=d_today)

        assert result.n_trading_days == 1
        decision = result.decisions[0]
        assert decision.action_kinds() == ["buy_split_1"]
        # Decisive evidence the runner used T-1 data:
        assert decision.buy_action is not None
        assert decision.buy_action.filled_quantity == Decimal("20")
        assert decision.buy_action.filled_price == Decimal("50000")
        assert decision.reasoning["current_price"] == "50000"

        # And the snapshot at Day1 close uses the T close (30000) → 20*30000.
        snap = result.snapshots[0]
        assert snap.valuations[0].market_price == Decimal("30000")
        assert snap.total_market_value.amount == Decimal("600000")

    def test_holiday_skip_when_no_ohlcv(self):
        # Days without OHLCV bars must not be iterated. Trading days come
        # from the bar list, not from a calendar query.
        asset = _asset()
        d0 = date(2026, 4, 23)  # T-1 fixture
        d1 = date(2026, 4, 24)
        # d2 (Apr 25) missing — represents holiday / weekend / data gap
        d3 = date(2026, 4, 27)
        d4 = date(2026, 4, 28)
        bars = [
            _bar(asset, d0, "35000"),
            _bar(asset, d1, "35000"),
            _bar(asset, d3, "34800"),
            _bar(asset, d4, "34700"),
        ]
        runner = BacktestRunner(
            asset=asset,
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start=d1, end=d4)

        # 3 trading days iterated (d1, d3, d4); d2 skipped because no bar.
        assert result.n_trading_days == 3
        snap_dates = [s.snapshot_date for s in result.snapshots]
        assert snap_dates == [d1, d3, d4]

    def test_empty_ohlcv_returns_clean_result(self):
        asset = _asset()
        runner = BacktestRunner(
            asset=asset,
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={},
        )
        result = runner.run(start=date(2026, 4, 1), end=date(2026, 4, 30))

        assert result.n_trading_days == 0
        assert result.decisions == []
        assert result.snapshots == []
        # All metrics fall back to 0 (no series to compute on)
        assert result.cagr_pct == Decimal(0)
        assert result.max_drawdown_pct == Decimal(0)
        assert result.sharpe_ratio == Decimal(0)
        assert result.calmar_ratio == Decimal(0)
        # final_value falls back to initial_capital, total_return_pct = 0
        assert result.final_value == _capital()
        assert result.total_return_pct == Decimal(0)

    def test_capital_exhausted_after_split_count_buys(self):
        # max_split_count=3 with steep drops: 3 buys fire, then subsequent
        # days hit max_split_reached and skip.
        asset = _asset()
        days = [date(2026, 4, 20) + timedelta(days=i) for i in range(7)]
        bars = [
            _bar(asset, days[0], "35000"),  # T-1
            _bar(asset, days[1], "35000"),  # buy_split_1 @ 35000
            _bar(asset, days[2], "30000"),  # decision sees 35000 → 0%, skip
            _bar(asset, days[3], "28000"),  # decision sees 30000 → ~14%, buy_2
            _bar(asset, days[4], "25000"),  # decision sees 28000 → ~13%, buy_3
            _bar(asset, days[5], "22000"),  # at max_split=3 → skip
            _bar(asset, days[6], "20000"),  # at max_split=3 → skip
        ]
        runner = BacktestRunner(
            asset=asset,
            strategy_config=_config(drop_pct="10", max_split=3),
            initial_capital=_capital(amount="100000000"),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start=days[1], end=days[6])

        assert result.n_trading_days == 6
        actions = [d.action_kinds() for d in result.decisions]
        assert actions[0] == ["buy_split_1"]
        assert result.decisions[1].is_skip()
        assert actions[2] == ["buy_split_2"]
        assert actions[3] == ["buy_split_3"]
        # Days 5 & 6: max_split_reached. Strategy emits STRATEGY_NO_BUY
        # with reasoning["max_split_reached"] = "True" (Phase 0.5).
        for idx in (4, 5):
            assert result.decisions[idx].is_skip()
            assert (
                result.decisions[idx].reasoning.get("max_split_reached")
                == "True"
            )

        # Final position has split_level == 3 (max)
        final = result.final_snapshot
        assert final is not None
        assert final.valuations[0].split_level == 3

    def test_halt_signal_blocks_all_decisions(self):
        # Custom signal_factory returns HALT for every day. Every decision
        # must short-circuit before broker; no fills, no Position changes,
        # cash unchanged through every snapshot.
        asset = _asset()
        days = [date(2026, 4, 20) + timedelta(days=i) for i in range(6)]
        bars = [
            _bar(asset, days[0], "35000"),
            _bar(asset, days[1], "32000"),  # Would buy if NORMAL signal
            _bar(asset, days[2], "28000"),
            _bar(asset, days[3], "25000"),
            _bar(asset, days[4], "22000"),
            _bar(asset, days[5], "20000"),
        ]
        runner = BacktestRunner(
            asset=asset,
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: bars},
            signal_factory=lambda: _AlwaysHaltSignal(),
        )
        result = runner.run(start=days[1], end=days[5])

        assert result.n_trading_days == 5
        for decision in result.decisions:
            assert decision.action_kinds() == ["skip:circuit_breaker_halt"]

        # Cash never moves; no positions ever opened.
        initial_cash = _capital().amount
        for snap in result.snapshots:
            assert snap.cash.amount == initial_cash
            assert snap.valuations == []
            assert snap.total_value.amount == initial_cash
