"""Smoke tests for src.ports.*.

Phase 0 ports are pure Protocol definitions — no executable behavior to test
behaviorally. These tests verify each Protocol imports cleanly and exposes
the expected method names, so accidental renames are caught.

Structural conformance of concrete implementations against these Protocols is
verified by mypy when adapters land (Phase 0 step 5).
"""
from __future__ import annotations

from src.ports.broker import BrokerPort
from src.ports.market_data import MarketDataPort
from src.ports.repositories import (
    DecisionRepoPort,
    OrderRepoPort,
    PortfolioSnapshotRepoPort,
    PositionRepoPort,
)
from src.ports.signals import SignalPort
from src.ports.unit_of_work import UnitOfWorkPort


class TestBrokerPort:
    def test_methods_present(self):
        expected = {
            "get_balance",
            "get_positions",
            "get_holdings",
            "place_order",
            "get_order_status",
            "cancel_order",
        }
        for name in expected:
            assert hasattr(BrokerPort, name), f"BrokerPort missing {name}"


class TestMarketDataPort:
    def test_methods_present(self):
        expected = {
            "get_price",
            "get_ohlcv",
            "is_market_open",
            "next_market_close",
        }
        for name in expected:
            assert hasattr(MarketDataPort, name), f"MarketDataPort missing {name}"


class TestSignalPort:
    def test_methods_present(self):
        assert hasattr(SignalPort, "collect")


class TestPositionRepoPort:
    def test_methods_present(self):
        for name in ("get", "save", "list_all", "delete"):
            assert hasattr(PositionRepoPort, name), (
                f"PositionRepoPort missing {name}"
            )


class TestOrderRepoPort:
    def test_methods_present(self):
        for name in ("save", "get_by_idempotency_key", "list_pending", "list_by_date"):
            assert hasattr(OrderRepoPort, name), f"OrderRepoPort missing {name}"


class TestDecisionRepoPort:
    def test_methods_present(self):
        for name in ("save", "list_by_date_range", "get_last_for_asset"):
            assert hasattr(DecisionRepoPort, name), f"DecisionRepoPort missing {name}"


class TestPortfolioSnapshotRepoPort:
    def test_methods_present(self):
        for name in ("save", "get_by_date", "list_by_date_range"):
            assert hasattr(PortfolioSnapshotRepoPort, name), (
                f"PortfolioSnapshotRepoPort missing {name}"
            )


class TestUnitOfWorkPort:
    def test_methods_present(self):
        for name in ("__enter__", "__exit__", "commit", "rollback"):
            assert hasattr(UnitOfWorkPort, name), f"UnitOfWorkPort missing {name}"

    def test_repository_attributes_typed(self):
        # The Protocol declares 4 repo attributes; mypy ensures presence at
        # implementation sites. Here we just confirm the attribute names exist
        # on the class annotations.
        annotations = UnitOfWorkPort.__annotations__
        for name in ("positions", "orders", "decisions", "snapshots"):
            assert name in annotations, (
                f"UnitOfWorkPort missing attribute annotation: {name}"
            )
