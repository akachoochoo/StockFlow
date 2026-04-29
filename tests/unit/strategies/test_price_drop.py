"""Unit tests for src.domain.strategies.price_drop.

Domain logic — pure functions, no mocks. Targets 100% coverage of the
PriceDropStrategy.evaluate() decision tree.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models import (
    Asset,
    AssetClass,
    Balance,
    CircuitBreakerSignal,
    Currency,
    Exchange,
    Money,
    Position,
    Price,
    SignalLevel,
    SignalSource,
)
from src.domain.strategies.price_drop import (
    PriceDropStrategy,
    SplitStrategyConfig,
    StrategyEvaluation,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
UTC_LATER = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
TODAY = date(2026, 4, 30)


def _asset(
    code: str = "069500",
    asset_class: AssetClass = AssetClass.KR_ETF,
    currency: Currency = Currency.KRW,
    lot_size: str = "1",
) -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=asset_class,
        currency=currency,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal(lot_size),
    )


def _signal(
    level: SignalLevel = SignalLevel.NORMAL,
    source: SignalSource = SignalSource.NULL,
    asset_class: AssetClass = AssetClass.KR_ETF,
) -> CircuitBreakerSignal:
    return CircuitBreakerSignal(
        level=level,
        source=source,
        asset_class=asset_class,
        evaluated_at=UTC_NOW,
        triggered_by=[],
        reasoning={},
        valid_until=UTC_LATER,
    )


def _config(
    drop_threshold_pct: str = "7.0",
    max_split_count: int = 7,
    per_split_amount_krw: str = "1000000",
) -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal(drop_threshold_pct),
        max_split_count=max_split_count,
        per_split_amount=Money(
            amount=Decimal(per_split_amount_krw), currency=Currency.KRW
        ),
    )


def _balance(amount_krw: str = "100000000") -> Balance:
    return Balance(cash=Money(amount=Decimal(amount_krw), currency=Currency.KRW))


def _price(value: str, asset: Asset | None = None) -> Price:
    return Price(asset=asset or _asset(), value=Decimal(value), timestamp=UTC_NOW)


def _filled_position(
    asset: Asset,
    *,
    quantity: str,
    avg_price: str,
    split_level: int,
) -> Position:
    return Position(
        asset=asset,
        quantity=Decimal(quantity),
        avg_price=Decimal(avg_price),
        split_level=split_level,
        last_buy_at=UTC_NOW,
    )


# ---------------------------------------------------------------------------
# StrategyEvaluation invariants
# ---------------------------------------------------------------------------
class TestStrategyEvaluation:
    def test_buy_requires_target_fields(self):
        with pytest.raises(ValidationError):
            StrategyEvaluation(
                should_buy=True,
                reason="buy_split_1",
                target_quantity=None,
                target_price=None,
                reasoning={},
            )

    def test_skip_must_have_none_targets(self):
        with pytest.raises(ValidationError):
            StrategyEvaluation(
                should_buy=False,
                reason="skip:x",
                target_quantity=Decimal("10"),
                target_price=Decimal("35000"),
                reasoning={},
            )


# ---------------------------------------------------------------------------
# Circuit breaker handling
# ---------------------------------------------------------------------------
class TestCircuitBreaker:
    def setup_method(self):
        self.strategy = PriceDropStrategy()
        self.asset = _asset()

    def test_halt_skips_buy(self):
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(level=SignalLevel.HALT),
        )
        assert result.should_buy is False
        assert result.reason == "skip:circuit_breaker_halt"

    def test_emergency_skips_buy(self):
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(level=SignalLevel.EMERGENCY),
        )
        assert result.should_buy is False
        assert result.reason == "skip:circuit_breaker_emergency"

    def test_caution_halves_spend_amount(self):
        # per_split_amount = 1,000,000 KRW. CAUTION halves to 500,000.
        # price = 35,000. quantity = floor(500,000 / 35,000) = 14.
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(per_split_amount_krw="1000000"),
            today=TODAY,
            signal=_signal(level=SignalLevel.CAUTION),
        )
        assert result.should_buy is True
        assert result.target_quantity == Decimal("14")
        assert result.target_price == Decimal("35000")
        assert result.reasoning["caution_reduction_applied"] == "True"
        assert result.reasoning["spend_amount"] == "500000.0"


# ---------------------------------------------------------------------------
# First-split (no position) buy path
# ---------------------------------------------------------------------------
class TestFirstSplit:
    def setup_method(self):
        self.strategy = PriceDropStrategy()
        self.asset = _asset()

    def test_no_position_triggers_first_split(self):
        # 1,000,000 / 35,000 = 28.57... → floor → 28
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is True
        assert result.reason == "buy_split_1"
        assert result.target_quantity == Decimal("28")
        assert result.target_price == Decimal("35000")
        assert result.reasoning["next_split_level"] == "1"
        assert result.reasoning["actual_cost"] == "980000"
        assert "avg_price" not in result.reasoning  # no position yet

    def test_empty_position_treated_as_no_position(self):
        empty = Position.empty(self.asset)
        result = self.strategy.evaluate(
            position=empty,
            current_price=_price("35000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is True
        assert result.reason == "buy_split_1"


# ---------------------------------------------------------------------------
# Subsequent-split buy / skip path
# ---------------------------------------------------------------------------
class TestSubsequentSplit:
    def setup_method(self):
        self.strategy = PriceDropStrategy()
        self.asset = _asset()
        self.position = _filled_position(
            self.asset,
            quantity="28",
            avg_price="35000",
            split_level=1,
        )

    def test_drop_above_threshold_triggers_next_split(self):
        # avg_price=35000, current=32000 → drop = 8.57% > 7%
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("32000", self.asset),
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is True
        assert result.reason == "buy_split_2"
        # 1,000,000 / 32,000 = 31.25 → floor → 31
        assert result.target_quantity == Decimal("31")
        assert result.target_price == Decimal("32000")
        assert result.reasoning["next_split_level"] == "2"
        assert result.reasoning["avg_price"] == "35000"
        assert "drop_pct" in result.reasoning

    def test_drop_at_exact_threshold_triggers_next_split(self):
        # avg_price=35000, current=32550 → drop = (35000-32550)/35000*100 = 7.0%
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("32550", self.asset),
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is True

    def test_drop_below_threshold_skips(self):
        # avg=35000, current=33500 → drop ≈ 4.28% < 7%
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("33500", self.asset),
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is False
        assert result.reason == "skip:drop_insufficient"
        assert "drop_pct" in result.reasoning
        assert result.reasoning["current_split_level"] == "1"

    def test_price_above_avg_skips(self):
        # current > avg → drop is negative
        result = self.strategy.evaluate(
            position=self.position,
            current_price=_price("36000", self.asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is False
        assert result.reason == "skip:drop_insufficient"

    def test_max_split_reached_skips(self):
        position = _filled_position(
            self.asset,
            quantity="100",
            avg_price="30000",
            split_level=7,  # at the cap
        )
        result = self.strategy.evaluate(
            position=position,
            current_price=_price("20000", self.asset),  # huge drop, but maxed
            balance=_balance(),
            config=_config(max_split_count=7),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is False
        assert result.reason == "skip:max_split_reached"
        assert result.reasoning["current_split_level"] == "7"


# ---------------------------------------------------------------------------
# Quantity / balance constraints
# ---------------------------------------------------------------------------
class TestQuantityConstraints:
    def setup_method(self):
        self.strategy = PriceDropStrategy()

    def test_quantity_rounds_below_lot_size_skips(self):
        # lot_size = 100, spend = 1,000,000, price = 35,000
        # raw_qty = 28.57; floor to 100-multiple = 0
        asset = _asset(lot_size="100")
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is False
        assert result.reason == "skip:quantity_below_lot_size"
        assert "raw_qty" in result.reasoning

    def test_lot_size_rounding(self):
        # lot_size = 10, spend = 1,000,000, price = 35,000
        # raw_qty = 28.57; floor to 10-multiple = 20
        asset = _asset(lot_size="10")
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is True
        assert result.target_quantity == Decimal("20")

    def test_insufficient_balance_skips(self):
        # spend 1,000,000 but balance only 500,000
        asset = _asset()
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(amount_krw="500000"),
            config=_config(per_split_amount_krw="1000000"),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is False
        assert result.reason == "skip:insufficient_balance"
        assert result.reasoning["actual_cost"] == "980000"

    def test_balance_exactly_equal_to_cost_buys(self):
        # cost = 28 * 35000 = 980,000. balance = 980,000.
        asset = _asset()
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(amount_krw="980000"),
            config=_config(per_split_amount_krw="1000000"),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is True


# ---------------------------------------------------------------------------
# Precondition checks (caller errors)
# ---------------------------------------------------------------------------
class TestPreconditions:
    def setup_method(self):
        self.strategy = PriceDropStrategy()

    def test_position_asset_mismatch_raises(self):
        asset_a = _asset(code="069500")
        asset_b = _asset(code="105190")  # different ETF
        position_a = _filled_position(
            asset_a, quantity="10", avg_price="35000", split_level=1
        )
        with pytest.raises(ValueError, match=r"position\.asset"):
            self.strategy.evaluate(
                position=position_a,
                current_price=_price("35000", asset_b),
                balance=_balance(),
                config=_config(),
                today=TODAY,
                signal=_signal(),
            )

    def test_signal_asset_class_mismatch_raises(self):
        asset = _asset(asset_class=AssetClass.KR_ETF)
        with pytest.raises(ValueError, match=r"signal\.asset_class"):
            self.strategy.evaluate(
                position=None,
                current_price=_price("35000", asset),
                balance=_balance(),
                config=_config(),
                today=TODAY,
                signal=_signal(asset_class=AssetClass.KR_STOCK),
            )

    def test_config_currency_mismatch_raises(self):
        asset = _asset(currency=Currency.KRW)
        config = SplitStrategyConfig(
            drop_threshold_pct=Decimal("7.0"),
            max_split_count=7,
            per_split_amount=Money(amount=Decimal("1000"), currency=Currency.USD),
        )
        with pytest.raises(ValueError, match=r"config\.per_split_amount\.currency"):
            self.strategy.evaluate(
                position=None,
                current_price=_price("35000", asset),
                balance=_balance(),
                config=config,
                today=TODAY,
                signal=_signal(),
            )

    def test_balance_currency_mismatch_raises(self):
        asset = _asset(currency=Currency.KRW)
        balance = Balance(
            cash=Money(amount=Decimal("1000"), currency=Currency.USD)
        )
        with pytest.raises(ValueError, match=r"balance\.cash\.currency"):
            self.strategy.evaluate(
                position=None,
                current_price=_price("35000", asset),
                balance=balance,
                config=_config(),
                today=TODAY,
                signal=_signal(),
            )


# ---------------------------------------------------------------------------
# Reasoning content
# ---------------------------------------------------------------------------
class TestReasoning:
    def setup_method(self):
        self.strategy = PriceDropStrategy()

    def test_buy_reasoning_contains_required_keys(self):
        asset = _asset()
        result = self.strategy.evaluate(
            position=None,
            current_price=_price("35000", asset),
            balance=_balance(),
            config=_config(),
            today=TODAY,
            signal=_signal(),
        )
        for key in (
            "today",
            "asset",
            "current_price",
            "signal_level",
            "signal_source",
            "drop_threshold_pct",
            "max_split_count",
            "per_split_amount",
            "available_cash",
            "next_split_level",
            "target_quantity",
            "target_price",
            "actual_cost",
            "spend_amount",
        ):
            assert key in result.reasoning, f"missing key: {key}"
        assert result.reasoning["today"] == TODAY.isoformat()
        assert result.reasoning["asset"] == "KRX:069500"

    def test_skip_reasoning_contains_decision_inputs(self):
        asset = _asset()
        position = _filled_position(
            asset, quantity="28", avg_price="35000", split_level=1
        )
        result = self.strategy.evaluate(
            position=position,
            current_price=_price("33500", asset),
            balance=_balance(),
            config=_config(drop_threshold_pct="7.0"),
            today=TODAY,
            signal=_signal(),
        )
        assert result.should_buy is False
        for key in ("avg_price", "drop_pct", "current_split_level"):
            assert key in result.reasoning
