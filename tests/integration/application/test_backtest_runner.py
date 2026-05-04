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

import pytest

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
    SkipReason,
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
            assets=[asset],
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
            assets=[asset],
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
            assets=[asset],
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
            assets=[asset],
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
            assets=[asset],
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
            assets=[asset],
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


# ---------------------------------------------------------------------------
# Phase 0.5 sells-then-buys scenarios (ADR §11.e step 0.5.17)
# ---------------------------------------------------------------------------
class TestSellsThenBuysScenarios:
    """Phase 0.5 cascade flow at the runner level. The orchestrator
    integration suite covers fault injection + skip classification; here
    we verify that the runner's day-by-day trading-date iteration produces
    the same Decision sequences end-to-end on representative price paths.
    """

    def test_buy_then_sell_at_recovery_with_cascade_buy(self):
        # Day1 buys slot 1 @ 35000 (T-1 close). Days 2-3 hold (no profit
        # yet). Day4's decision sees Day3's close 38500 → slot 1 hits +10 %
        # and sells; the same evaluation's BUY step then fires on slot 2
        # via the post-sell first-buy bypass (§4.7) — Decision Invariant 3
        # holds because excluded={1} forces the cascade buy onto slot 2.
        asset = _asset()
        days = [date(2026, 4, 20) + timedelta(days=i) for i in range(5)]
        bars = [
            _bar(asset, days[0], "35000"),  # T-1
            _bar(asset, days[1], "35000"),  # Day1 snap; Day2 dec sees this
            _bar(asset, days[2], "35000"),  # Day2 snap; Day3 dec sees this
            _bar(asset, days[3], "38500"),  # Day3 snap; Day4 dec sees this
            _bar(asset, days[4], "38500"),  # Day4 snap
        ]
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=_config(),
            initial_capital=_capital(amount="10000000"),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start=days[1], end=days[4])

        assert result.n_trading_days == 4
        actions = [d.action_kinds() for d in result.decisions]
        # Day1 buys; Days 2-3 idle; Day4 sells slot 1 + buys slot 2.
        assert actions[0] == ["buy_split_1"]
        assert result.decisions[1].is_skip()
        assert result.decisions[2].is_skip()
        assert actions[3] == ["sell_slot_1", "buy_split_2"]

        # Day4's sell records the +10 % profit on slot 1.
        sell_action = result.decisions[3].sell_actions[0]
        assert sell_action.slot_number == 1
        assert sell_action.profit_pct == Decimal("10")

        # Final position carries slot 1 EMPTY (with last_exit_*) + slot 2
        # FILLED at 38500 — the cascade buy landed in a fresh slot.
        final = result.final_snapshot
        assert final is not None
        position_qty = final.valuations[0].quantity
        # Slot 2 holds 25 shares (1M / 38500 floor) at 38500.
        assert position_qty == Decimal("25")
        assert final.valuations[0].avg_price == Decimal("38500")

    def test_multiple_sells_no_cascade_buy_when_drop_insufficient(self):
        # Build slots 1, 2, 3 at descending entry prices, then a partial
        # recovery to 33000 triggers sells on slots 2 (+10 %) and 3 (+18 %)
        # while slot 1 (-5.7 %) holds. Buy step skipped because Hybrid's
        # fresh-slot fallback uses post-sell avg=35000 → trigger=32550 >
        # current 33000 → no fire. Result: two sells on a single day, no
        # cascade buy.
        asset = _asset()
        days = [date(2026, 4, 20) + timedelta(days=i) for i in range(5)]
        bars = [
            _bar(asset, days[0], "35000"),  # T-1
            _bar(asset, days[1], "30000"),  # Day1 snap; slot 1 fills @35000
            _bar(asset, days[2], "28000"),  # Day2 snap; slot 2 fills @30000
            _bar(asset, days[3], "33000"),  # Day3 snap; slot 3 fills @28000
            _bar(asset, days[4], "33000"),  # Day4 snap; sells slots 2,3
        ]
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=_config(),
            initial_capital=_capital(amount="10000000"),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start=days[1], end=days[4])

        assert result.n_trading_days == 4
        # Days 1-3: progressive splits.
        assert result.decisions[0].action_kinds() == ["buy_split_1"]
        assert result.decisions[1].action_kinds() == ["buy_split_2"]
        assert result.decisions[2].action_kinds() == ["buy_split_3"]
        # Day4: two sells, no buy.
        day4 = result.decisions[3]
        assert day4.action_kinds() == ["sell_slot_2", "sell_slot_3"]
        assert day4.buy_action is None
        # skip_reason is None because sell_actions are present (Invariant 1).
        assert day4.skip_reason is None
        # Strategy emitted STRATEGY_NO_BUY (drop insufficient, mixed state)
        # — visible in reasoning as the buy-side fingerprint.
        assert (
            day4.reasoning["buy_skip_reason_emitted"]
            == SkipReason.STRATEGY_NO_BUY.value
        )

        # Final position holds only slot 1 (the un-sold survivor).
        final = result.final_snapshot
        assert final is not None
        assert final.valuations[0].split_level == 1
        # cross-check via Position.slots: 1 FILLED, 2 & 3 EMPTY w/ last_exit.
        position = final.valuations[0]
        # PositionValuation doesn't carry slots; verify quantity/avg instead.
        assert position.quantity == Decimal("28")
        assert position.avg_price == Decimal("35000")

    def test_all_filled_no_profit_skip_during_dormancy(self):
        # max_split_count=3 + sustained drops without recovery: 3 buys
        # fire then the position sits underwater. Days 4-5 surface the
        # ALL_SLOTS_FILLED_NO_PROFIT classification (ADR §5.6) — the Phase
        # 0.5 retrospective uses this enum as the dormancy KPI denominator.
        asset = _asset()
        days = [date(2026, 4, 20) + timedelta(days=i) for i in range(6)]
        bars = [
            _bar(asset, days[0], "35000"),  # T-1
            _bar(asset, days[1], "30000"),  # slot 1 fills @35000
            _bar(asset, days[2], "28000"),  # slot 2 fills @30000
            _bar(asset, days[3], "25000"),  # slot 3 fills @28000 (max=3)
            _bar(asset, days[4], "23000"),  # all FILLED, no profit anywhere
            _bar(asset, days[5], "23000"),  # same — dormancy
        ]
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=_config(max_split=3),
            initial_capital=_capital(amount="10000000"),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start=days[1], end=days[5])

        assert result.n_trading_days == 5
        # Days 1-3: progressive splits.
        for idx, expected in enumerate(["buy_split_1", "buy_split_2", "buy_split_3"]):
            assert result.decisions[idx].action_kinds() == [expected]
        # Days 4-5: dormancy — all FILLED + no sells + no buys.
        for idx in (3, 4):
            decision = result.decisions[idx]
            assert decision.skip_reason is SkipReason.ALL_SLOTS_FILLED_NO_PROFIT
            assert decision.sell_actions == []
            assert decision.buy_action is None
            # Strategy's STRATEGY_NO_BUY (max_split_reached) preserved
            # in reasoning even though the orchestrator surfaces the
            # retrospective category as the top-level skip_reason.
            assert (
                decision.reasoning["buy_skip_reason_emitted"]
                == SkipReason.STRATEGY_NO_BUY.value
            )
            assert decision.reasoning.get("max_split_reached") == "True"

        # Final position has split_level == max (3).
        final = result.final_snapshot
        assert final is not None
        assert final.valuations[0].split_level == 3


# ---------------------------------------------------------------------------
# Phase 0.7.2 per_asset_strategy_overrides — ADR 0003 §16.13.9 (4b.2)
# ---------------------------------------------------------------------------
def _asset_bond() -> Asset:
    """Phase 0.7.2 두 번째 자산 — KODEX 단기채권 PLUS (214980)."""
    return Asset(
        code="214980",
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 단기채권 PLUS",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


class TestPerAssetStrategyOverrides:
    """ADR 0003 §16.13.9 — runner 의 per_asset_strategy_overrides
    옵셔널 인자. None default → Phase 0.7.1 회귀 invariant.
    """

    def test_no_override_preserves_phase_0_7_1(self):
        """None default 시 단일 strategy_config 적용 — Phase 0.7.1 동작."""
        asset = _asset()
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: []},
        )
        # instance 변수 None 박제 — AssetContext 생성 시 단일 fallback.
        assert runner._per_asset_overrides is None

    def test_override_none_default_signature(self):
        """signature default = None 검증 (kwarg 미전달 시)."""
        asset = _asset()
        # per_asset_strategy_overrides 인자 안 넘기고 생성 가능해야 함.
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: []},
        )
        assert runner._per_asset_overrides is None

    def test_override_dict_validation_extra_key_raises(self):
        """dict 키에 assets 외 자산 fqn 있으면 ValueError."""
        asset = _asset()
        with pytest.raises(ValueError, match="extra="):
            BacktestRunner(
                assets=[asset],
                strategy_config=_config(),
                initial_capital=_capital(),
                ohlcv_by_asset={asset: []},
                per_asset_strategy_overrides={
                    "KRX:069500": _config(per_split="500000"),
                    "KRX:UNKNOWN": _config(per_split="500000"),
                },
            )

    def test_override_dict_validation_missing_key_raises(self):
        """dict 에 assets 중 일부 누락 시 ValueError."""
        asset_a = _asset()
        asset_b = _asset_bond()
        with pytest.raises(ValueError, match="missing="):
            BacktestRunner(
                assets=[asset_a, asset_b],
                strategy_config=_config(),
                initial_capital=_capital(),
                ohlcv_by_asset={asset_a: [], asset_b: []},
                # 069500 만 있고 214980 누락
                per_asset_strategy_overrides={
                    "KRX:069500": _config(per_split="500000"),
                },
            )

    def test_override_dict_with_correct_keys_succeeds(self):
        """dict 키가 모든 assets fqn 정확히 일치 시 인스턴스 생성 OK."""
        asset_a = _asset()
        asset_b = _asset_bond()
        cfg_a = _config(per_split="2857142")  # INV_VOL 069500 예시
        cfg_b = _config(per_split="11428571")  # INV_VOL 214980 예시
        runner = BacktestRunner(
            assets=[asset_a, asset_b],
            strategy_config=_config(),  # fallback (사용 안 됨)
            initial_capital=_capital(amount="100000000"),
            ohlcv_by_asset={asset_a: [], asset_b: []},
            per_asset_strategy_overrides={
                "KRX:069500": cfg_a,
                "KRX:214980": cfg_b,
            },
        )
        # instance 변수 dict 박제. copy 본 (mutation 방어).
        assert runner._per_asset_overrides is not None
        assert runner._per_asset_overrides["KRX:069500"] is cfg_a
        assert runner._per_asset_overrides["KRX:214980"] is cfg_b

    def test_override_dict_is_copied_not_aliased(self):
        """입력 dict mutation 시 instance 변수 영향 없어야 함."""
        asset = _asset()
        cfg = _config(per_split="500000")
        override = {"KRX:069500": cfg}
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: []},
            per_asset_strategy_overrides=override,
        )
        override["KRX:069500"] = _config(per_split="999")
        # Runner 의 dict 는 영향받지 않음 — 원본 cfg 보존.
        assert runner._per_asset_overrides is not None
        assert runner._per_asset_overrides["KRX:069500"] is cfg
