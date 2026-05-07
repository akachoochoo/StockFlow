"""Unit tests for src.ports.strategy_renderer (Phase 0.10 — ADR 0006 §4.2).

Protocol + dataclass spec 검증. 실제 구현체 (SevenSplit / Default) 테스트는
src/adapters/reporting/renderers/ 별도.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.application.reporting.episode import DrawdownEpisode
from src.application.reporting.trade_view import TradeView
from src.ports.strategy_renderer import MarkerStyle, Panel, StrategyRenderer


def _trade(side: str = "BUY") -> TradeView:
    return TradeView(
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        symbol="069500",
        side=side,  # type: ignore[arg-type]
        price=Decimal("100"),
        quantity=Decimal("10"),
        strategy_id="test",
        annotations={},
    )


def _episode() -> DrawdownEpisode:
    return DrawdownEpisode(
        peak_date=date(2024, 1, 1),
        peak_value=Decimal("100"),
        trough_date=date(2024, 1, 2),
        trough_value=Decimal("90"),
        recovery_date=date(2024, 1, 3),
        recovered=True,
        drawdown_pct=Decimal("-10"),
        duration_days=2,
    )


class TestMarkerStyle:
    def test_construct(self):
        m = MarkerStyle(color="#000000", marker="^", size=10, label="B")
        assert m.color == "#000000"
        assert m.marker == "^"
        assert m.size == 10
        assert m.label == "B"

    def test_frozen(self):
        m = MarkerStyle(color="#000", marker="^", size=10, label="B")
        with pytest.raises((AttributeError, Exception)):
            m.color = "#fff"  # type: ignore[misc]


class TestPanel:
    def test_construct(self):
        p = Panel(title="Summary", rows=[("k", "v")])
        assert p.title == "Summary"
        assert p.rows == [("k", "v")]

    def test_frozen(self):
        p = Panel(title="x", rows=[])
        with pytest.raises((AttributeError, Exception)):
            p.title = "y"  # type: ignore[misc]


class TestStrategyRendererProtocol:
    def test_runtime_checkable(self):
        """runtime_checkable Protocol — isinstance 검사 가능."""

        class Good:
            def marker_label(self, trade):
                return "x"

            def marker_style(self, trade):
                return MarkerStyle(color="#000", marker="^", size=1, label="x")

            def diagnostic_panels(self, trades, episode):
                return []

        assert isinstance(Good(), StrategyRenderer)

    def test_missing_method_fails_isinstance(self):
        class Bad:
            def marker_label(self, trade):
                return "x"

        # Protocol runtime_checkable: 메서드 부재 시 isinstance False
        assert not isinstance(Bad(), StrategyRenderer)

    def test_protocol_used_in_test_helpers(self):
        """trade + episode helper 가 정상 생성됨 (downstream 테스트 정합 검증)."""
        t = _trade()
        e = _episode()
        assert t.side == "BUY"
        assert e.recovered is True
