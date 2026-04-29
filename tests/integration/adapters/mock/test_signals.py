"""Tests for src.adapters.mock.signals.NullSignal."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.adapters.mock.signals import NullSignal
from src.domain.models import AssetClass, SignalLevel, SignalSource

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)


class TestNullSignal:
    def test_returns_normal_null_for_each_asset_class(self):
        adapter = NullSignal()
        for asset_class in (AssetClass.KR_ETF, AssetClass.KR_STOCK):
            sig = adapter.collect(asset_class, UTC_NOW)
            assert sig.level is SignalLevel.NORMAL
            assert sig.source is SignalSource.NULL
            assert sig.asset_class is asset_class
            assert sig.triggered_by == []
            assert sig.reasoning == {}
            assert sig.evaluated_at == UTC_NOW

    def test_validity_window_is_one_day(self):
        adapter = NullSignal()
        sig = adapter.collect(AssetClass.KR_ETF, UTC_NOW)
        assert sig.valid_until == UTC_NOW + timedelta(days=1)
