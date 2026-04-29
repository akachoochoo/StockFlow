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
from src.ports.signals import SignalPort


class TestBrokerPort:
    def test_methods_present(self):
        expected = {
            "get_balance",
            "get_positions",
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
