"""Unit tests for src.domain.strategies.stop_loss.StopLossPolicy.

Pure domain logic — no mocks, no clock, no I/O (CLAUDE.md §1.1 / §3.2). The
policy is a price-vs-avg_price breach detector (ADR 0012 D2(b')); it NEVER
auto-sells (CLAUDE.md §11.4). Function names carry the ``stop_loss`` keyword.

Coverage targets StopLossPolicy + StopLossDecision per CLAUDE.md §7.1.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Position,
    SplitEntry,
    SplitSlot,
)
from src.domain.strategies.stop_loss import StopLossDecision, StopLossPolicy

UTC_NOW = datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)
ENTRY_DATE = date(2026, 4, 1)


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


def _position(*, avg_price: str, quantity: str = "10") -> Position:
    """A single-slot FILLED Position at the given avg_price."""
    asset = _asset()
    entry = SplitEntry(
        split_number=1,
        entry_date=ENTRY_DATE,
        quantity=Decimal(quantity),
        entry_price=Decimal(avg_price),
        idempotency_key="seed-1",
    )
    return Position(
        asset=asset,
        quantity=Decimal(quantity),
        avg_price=Decimal(avg_price),
        split_level=1,
        last_buy_at=UTC_NOW,
        slots=[
            SplitSlot.filled(entry),
            *[SplitSlot.empty(slot_number=i) for i in range(2, 8)],
        ],
    )


class TestStopLossBreach:
    def test_stop_loss_breached_below_threshold(self):
        # avg 10000, current 7900 → -21 % <= -20 % → breached
        policy = StopLossPolicy()
        decision = policy.evaluate(
            position=_position(avg_price="10000"),
            current_price=Decimal("7900"),
            max_loss_pct=Decimal("20"),
        )
        assert decision.breached is True
        assert decision.loss_pct == Decimal("-21")

    def test_stop_loss_breached_exactly_at_threshold(self):
        # avg 10000, current 8000 → exactly -20 % → breached (<=)
        policy = StopLossPolicy()
        decision = policy.evaluate(
            position=_position(avg_price="10000"),
            current_price=Decimal("8000"),
            max_loss_pct=Decimal("20"),
        )
        assert decision.breached is True
        assert decision.loss_pct == Decimal("-20")

    def test_stop_loss_not_breached_above_threshold(self):
        # avg 10000, current 8100 → -19 % > -20 % → not breached
        policy = StopLossPolicy()
        decision = policy.evaluate(
            position=_position(avg_price="10000"),
            current_price=Decimal("8100"),
            max_loss_pct=Decimal("20"),
        )
        assert decision.breached is False
        assert decision.loss_pct == Decimal("-19")

    def test_stop_loss_not_breached_when_in_profit(self):
        # avg 10000, current 12000 → +20 % gain → not breached, positive pct
        policy = StopLossPolicy()
        decision = policy.evaluate(
            position=_position(avg_price="10000"),
            current_price=Decimal("12000"),
            max_loss_pct=Decimal("20"),
        )
        assert decision.breached is False
        assert decision.loss_pct == Decimal("20")


class TestStopLossNoPosition:
    def test_stop_loss_no_position_quantity_zero(self):
        policy = StopLossPolicy()
        empty = Position.empty(_asset())
        decision = policy.evaluate(
            position=empty,
            current_price=Decimal("7900"),
            max_loss_pct=Decimal("20"),
        )
        assert decision.breached is False
        assert decision.loss_pct == Decimal(0)


class TestStopLossDecimalPrecision:
    def test_stop_loss_loss_pct_is_exact_decimal(self):
        # avg 30000, current 24990 → -16.7 % (exact Decimal, no float drift)
        policy = StopLossPolicy()
        decision = policy.evaluate(
            position=_position(avg_price="30000"),
            current_price=Decimal("24990"),
            max_loss_pct=Decimal("20"),
        )
        assert isinstance(decision.loss_pct, Decimal)
        assert decision.loss_pct == Decimal("-16.7")
        assert decision.breached is False

    def test_stop_loss_decision_rejects_float_loss_pct(self):
        # StopLossDecision._coerce_loss_pct rejects float (CLAUDE.md §2.3)
        with pytest.raises(ValidationError):
            StopLossDecision(breached=False, loss_pct=1.5)


class TestStopLossPurity:
    def test_stop_loss_is_deterministic_clock_independent(self):
        # Same inputs → identical output, no clock read (§3.2). Two calls equal.
        policy = StopLossPolicy()
        pos = _position(avg_price="10000")
        first = policy.evaluate(
            position=pos, current_price=Decimal("7900"), max_loss_pct=Decimal("20")
        )
        second = policy.evaluate(
            position=pos, current_price=Decimal("7900"), max_loss_pct=Decimal("20")
        )
        assert first == second

    def test_stop_loss_source_has_no_clock_or_io_imports(self):
        # Static guard via AST: the domain module reads no clock and does no
        # I/O in *executable code* (docstrings legitimately mention the
        # forbidden patterns, so a raw-string scan would false-positive).
        import ast
        import inspect

        from src.domain.strategies import stop_loss

        tree = ast.parse(inspect.getsource(stop_loss))

        # No forbidden external imports (only stdlib decimal/typing + pydantic
        # + src.domain.* are allowed in the domain ring, CLAUDE.md §1.1).
        forbidden_import_roots = {"requests", "httpx", "pandas", "numpy", "sqlite3"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in forbidden_import_roots
                    assert not root.startswith("src") or alias.name.startswith(
                        "src.domain"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".")[0]
                assert root not in forbidden_import_roots
                if root == "src":
                    assert module.startswith("src.domain")

        # No clock reads (datetime.now / date.today) in executable code.
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"now", "today"}, (
                    f"clock read found: .{node.attr}"
                )
