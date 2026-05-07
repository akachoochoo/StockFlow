"""Unit tests for src.adapters.reporting.renderers.default (Phase 0.10
— ADR 0006 §4.3.2).

Annotation 무관 fallback renderer — 신규 strategy 추가 시 코어 변경 zero
보장 (Acceptance Criteria 3).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.adapters.reporting.renderers.default import DefaultRenderer
from src.application.reporting.episode import DrawdownEpisode
from src.application.reporting.trade_view import TradeView


def _trade(
    side: str = "BUY", timestamp_date: date = date(2024, 1, 1),
) -> TradeView:
    return TradeView(
        timestamp=datetime(
            timestamp_date.year, timestamp_date.month, timestamp_date.day,
            6, 0, 0, tzinfo=UTC,
        ),
        symbol="ANY",
        side=side,  # type: ignore[arg-type]
        price=Decimal("100"),
        quantity=Decimal("1"),
        strategy_id="some_new_strategy",
        annotations={"signal": "golden_cross", "fast": "20"},  # 무관
    )


def _episode() -> DrawdownEpisode:
    return DrawdownEpisode(
        peak_date=date(2024, 1, 1),
        peak_value=Decimal("100"),
        trough_date=date(2024, 1, 5),
        trough_value=Decimal("88"),
        recovery_date=date(2024, 1, 10),
        recovered=True,
        drawdown_pct=Decimal("-12"),
        duration_days=9,
    )


class TestMarkerLabel:
    def test_buy_label(self):
        assert DefaultRenderer().marker_label(_trade(side="BUY")) == "B"

    def test_sell_label(self):
        assert DefaultRenderer().marker_label(_trade(side="SELL")) == "S"

    def test_annotation_ignored(self):
        # Annotation 키 무관 — 항상 단순 B/S
        t = _trade(side="BUY")
        assert DefaultRenderer().marker_label(t) == "B"


class TestMarkerStyle:
    def test_buy_green_up(self):
        s = DefaultRenderer().marker_style(_trade(side="BUY"))
        assert s.color == "#2ca02c"  # green
        assert s.marker == "^"
        assert s.label == "B"

    def test_sell_red_down(self):
        s = DefaultRenderer().marker_style(_trade(side="SELL"))
        assert s.color == "#d62728"  # red
        assert s.marker == "v"
        assert s.label == "S"


class TestDiagnosticPanels:
    def test_returns_single_summary_panel(self):
        panels = DefaultRenderer().diagnostic_panels([], _episode())
        assert len(panels) == 1
        assert panels[0].title == "Episode 요약"

    def test_summary_includes_metrics(self):
        panels = DefaultRenderer().diagnostic_panels([], _episode())
        rows = dict(panels[0].rows)
        assert rows["episode peak"] == "100"
        assert rows["episode trough"] == "88"
        assert "drawdown_pct" in rows
        assert rows["recovered"] == "yes"
        assert rows["total buys"] == "0"
        assert rows["total sells"] == "0"

    def test_filters_trades_to_episode_range(self):
        e = _episode()
        trades = [
            _trade(side="BUY", timestamp_date=date(2023, 12, 31)),  # before peak
            _trade(side="BUY", timestamp_date=date(2024, 1, 5)),    # in
            _trade(side="SELL", timestamp_date=date(2024, 1, 7)),   # in
            _trade(side="BUY", timestamp_date=date(2024, 1, 11)),   # after recovery
        ]
        rows = dict(DefaultRenderer().diagnostic_panels(trades, e)[0].rows)
        assert rows["total buys"] == "1"
        assert rows["total sells"] == "1"
