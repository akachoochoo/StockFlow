"""Unit tests for src.adapters.reporting.renderer_registry (Phase 0.10
— ADR 0006 §4.4).

Registry lookup + DefaultRenderer fallback (Acceptance Criteria 3) +
runtime register API.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.adapters.reporting.renderer_registry import StrategyRendererRegistry
from src.adapters.reporting.renderers.default import DefaultRenderer
from src.adapters.reporting.renderers.seven_split import SevenSplitRenderer
from src.application.reporting.trade_view import TradeView
from src.ports.strategy_renderer import MarkerStyle, Panel, StrategyRenderer


class TestBuiltinMapping:
    def test_price_drop_returns_seven_split(self):
        r = StrategyRendererRegistry()
        assert isinstance(r.get("price_drop"), SevenSplitRenderer)

    def test_support_level_returns_seven_split(self):
        r = StrategyRendererRegistry()
        assert isinstance(r.get("support_level"), SevenSplitRenderer)

    def test_price_drop_and_support_level_share_instance(self):
        """Phase 0.10 = SevenSplitRenderer 단일 인스턴스 (메모리 + 동작 동일)."""
        r = StrategyRendererRegistry()
        assert r.get("price_drop") is r.get("support_level")

    def test_registered_ids(self):
        r = StrategyRendererRegistry()
        ids = r.registered_ids()
        assert "price_drop" in ids
        assert "support_level" in ids


class TestDefaultFallback:
    """Acceptance Criteria 3 — 신규 strategy 추가 시 코어 변경 zero."""

    def test_unknown_strategy_returns_default(self):
        r = StrategyRendererRegistry()
        assert isinstance(r.get("ma_cross_dummy"), DefaultRenderer)

    def test_unknown_strategy_can_render(self):
        """Default fallback 으로 신규 strategy 의 trade 도 정상 렌더 가능."""
        r = StrategyRendererRegistry()
        renderer = r.get("brand_new_strategy")
        trade = TradeView(
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            symbol="X",
            side="BUY",
            price=Decimal("100"),
            quantity=Decimal("1"),
            strategy_id="brand_new_strategy",
            annotations={"foo": "bar"},
        )
        assert renderer.marker_label(trade) == "B"
        assert renderer.marker_style(trade).color == "#2ca02c"

    def test_default_not_registered_in_registered_ids(self):
        """Default fallback 은 registered_ids() 에 미포함 (별도 보유)."""
        r = StrategyRendererRegistry()
        # default 자체는 strategy_id 등록 X — fallback 만
        assert "_default" not in r.registered_ids()
        assert "default" not in r.registered_ids()


class TestRuntimeRegister:
    def test_register_custom_renderer(self):
        class CustomRenderer:
            def marker_label(self, trade):
                return "X"

            def marker_style(self, trade):
                return MarkerStyle(color="#fff", marker="o", size=5, label="X")

            def diagnostic_panels(self, trades, episode):
                return [Panel(title="custom", rows=[])]

        r = StrategyRendererRegistry()
        custom = CustomRenderer()
        r.register("custom_strategy", custom)
        assert r.get("custom_strategy") is custom

    def test_register_overrides_existing(self):
        class Override:
            def marker_label(self, trade):
                return "OVR"

            def marker_style(self, trade):
                return MarkerStyle(color="#000", marker=".", size=1, label="OVR")

            def diagnostic_panels(self, trades, episode):
                return []

        r = StrategyRendererRegistry()
        original = r.get("price_drop")
        assert isinstance(original, SevenSplitRenderer)
        r.register("price_drop", Override())
        new = r.get("price_drop")
        assert not isinstance(new, SevenSplitRenderer)
        # 기존 default fallback 은 영향 없음
        assert isinstance(r.get("brand_new"), DefaultRenderer)

    def test_isolation_between_instances(self):
        """Registry 인스턴스 간 격리 — 한쪽 register 가 다른쪽 영향 없음."""
        r1 = StrategyRendererRegistry()
        r2 = StrategyRendererRegistry()

        class Mock:
            def marker_label(self, trade):
                return "M"

            def marker_style(self, trade):
                return MarkerStyle(color="#0", marker=".", size=1, label="M")

            def diagnostic_panels(self, trades, episode):
                return []

        r1.register("custom", Mock())
        # r2 는 영향 없음 — fallback Default
        assert isinstance(r2.get("custom"), DefaultRenderer)


class TestProtocolConformance:
    def test_seven_split_satisfies_protocol(self):
        assert isinstance(SevenSplitRenderer(), StrategyRenderer)

    def test_default_satisfies_protocol(self):
        assert isinstance(DefaultRenderer(), StrategyRenderer)
