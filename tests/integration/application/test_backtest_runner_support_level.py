"""Integration test for BacktestRunner with SupportLevelStrategy (Phase 0.8.e).

Phase 0.8.e end-to-end smoke test (ADR 0004 §5.9.2). Wires:
- yaml-equivalent ``buy_strategy_name="support_level"``
- factory dispatch (``create_buy_strategy``)
- MockBroker with ``slot_model=SupportSlot``
- DailyOrchestrator's isinstance dispatch + ohlcv_history fetch

The test does NOT validate strategy semantics (slot mapping correctness
is unit-tested in ``tests/unit/strategies/test_support_level.py``).
Goal: verify the cascade — yaml schema → factory → broker → orchestrator
→ runner → results — runs end-to-end without errors and produces
SupportSlot-based final positions.

The 5-year backtest with real KRX data is Phase 0.8.f's responsibility.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.application.backtest_runner import BacktestRunner
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
    SupportSlot,
)
from src.domain.strategies.price_drop import SplitStrategyConfig


def _asset() -> Asset:
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


def _config(max_split: int = 5, per_split: str = "1000000") -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal("5"),  # ignored by SupportLevelStrategy
        max_split_count=max_split,
        per_split_amount=Money(amount=Decimal(per_split), currency=Currency.KRW),
    )


def _capital(amount: str = "10000000") -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


class TestBacktestRunnerSupportLevel:
    def test_end_to_end_runs_and_produces_support_slots(self):
        """Phase 0.8.e cascade smoke test.

        Synthetic 100 days of warmup at flat 30000 + 5 backtest days with
        descending price (to trigger MA breaches). Expects:
        - runner completes without error
        - decisions/snapshots produced
        - final position uses SupportSlot
        """
        asset = _asset()

        # 100 days warmup (lookback) at flat 30000 — slots 2~4 (MA5/10/20)
        # and slot 5 (recent_high(60)) all become evaluable.
        warmup_start = date(2026, 1, 1)
        warmup_bars = [
            _bar(asset, warmup_start + timedelta(days=i), "30000")
            for i in range(100)
        ]

        # 5 backtest days — descending close to break MA.
        backtest_start = warmup_start + timedelta(days=100)
        backtest_closes = ["29800", "29600", "29400", "29200", "29000"]
        backtest_bars = [
            _bar(asset, backtest_start + timedelta(days=i), c)
            for i, c in enumerate(backtest_closes)
        ]

        all_bars = warmup_bars + backtest_bars
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=_config(),
            initial_capital=_capital(),
            ohlcv_by_asset={asset: all_bars},
            buy_strategy_name="support_level",
        )
        result = runner.run(
            start=backtest_start,
            end=backtest_start + timedelta(days=4),
        )

        # Cascade smoke: runner completes + produces decisions/snapshots.
        assert result.n_trading_days == 5
        assert len(result.decisions) == 5
        assert len(result.snapshots) == 5

        # First-buy or indicator trigger should fire on day 1 (split_level==0
        # → slot 1 first-buy bypass).
        day1 = result.decisions[0]
        # Either bought (slot 1 first_buy) or skipped — at minimum no error.
        # SupportLevelStrategy's slot 1 first-buy fires when split_level==0,
        # so we expect a buy on day 1.
        assert day1.action_kinds() == ["buy_split_1"]

        # Final position uses SupportSlot (ADR 0004 §1.3 B-1 + §5.6).
        final_positions = result.final_positions
        assert len(final_positions) == 1
        position = final_positions[0]
        assert position.asset == asset
        assert all(isinstance(s, SupportSlot) for s in position.slots)

    def test_default_buy_strategy_is_price_drop_regression(self):
        """Phase 0.7.3 baseline regression: default buy_strategy_name preserves
        PriceDropStrategy + SplitSlot path (ADR 0004 §5.9.1).
        """
        asset = _asset()
        days = [date(2026, 4, 23) + timedelta(days=i) for i in range(6)]
        bars = [
            _bar(asset, days[0], "35000"),
            _bar(asset, days[1], "35000"),
            _bar(asset, days[2], "30000"),  # ~14% drop → buy
            _bar(asset, days[3], "30000"),
            _bar(asset, days[4], "30000"),
            _bar(asset, days[5], "30000"),
        ]
        runner = BacktestRunner(
            assets=[asset],
            strategy_config=SplitStrategyConfig(
                drop_threshold_pct=Decimal("7"),
                max_split_count=7,
                per_split_amount=Money(
                    amount=Decimal("1000000"), currency=Currency.KRW
                ),
            ),
            initial_capital=_capital("4000000"),
            ohlcv_by_asset={asset: bars},
            # buy_strategy_name omitted → default "price_drop"
        )
        result = runner.run(start=days[1], end=days[5])

        # Cascade unchanged for default → same as Phase 0.7.3 baseline path.
        assert result.n_trading_days == 5
        assert len(result.decisions) == 5

        # Final position uses SplitSlot (default slot_model).
        final_positions = result.final_positions
        if final_positions:
            from src.domain.models import SplitSlot

            for position in final_positions:
                assert all(isinstance(s, SplitSlot) for s in position.slots)
