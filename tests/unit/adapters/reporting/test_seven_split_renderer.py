"""Unit tests for src.adapters.reporting.renderers.seven_split (Phase 0.10
— ADR 0006 §4.3.1).

PriceDropStrategy / SupportLevelStrategy 차수 (B1~B7 / S1~S7) 표기 검증.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.adapters.reporting.renderers.seven_split import (
    SevenSplitRenderer,
    _trades_in_episode,
)
from src.application.reporting.episode import DrawdownEpisode
from src.application.reporting.trade_view import TradeView


def _trade(
    *,
    side: str = "BUY",
    annotations: dict[str, str] | None = None,
    timestamp_date: date = date(2024, 1, 1),
) -> TradeView:
    return TradeView(
        timestamp=datetime(
            timestamp_date.year, timestamp_date.month, timestamp_date.day,
            6, 0, 0, tzinfo=UTC,
        ),
        symbol="069500",
        side=side,  # type: ignore[arg-type]
        price=Decimal("100"),
        quantity=Decimal("10"),
        strategy_id="price_drop",
        annotations=annotations or {},
    )


def _episode(
    *,
    peak: date = date(2024, 1, 1),
    trough: date = date(2024, 1, 5),
    recovery: date | None = date(2024, 1, 10),
    recovered: bool = True,
) -> DrawdownEpisode:
    return DrawdownEpisode(
        peak_date=peak,
        peak_value=Decimal("100"),
        trough_date=trough,
        trough_value=Decimal("85"),
        recovery_date=recovery,
        recovered=recovered,
        drawdown_pct=Decimal("-15"),
        duration_days=(recovery - peak).days if recovery else 30,
    )


class TestMarkerLabel:
    def test_buy_b1(self):
        r = SevenSplitRenderer()
        t = _trade(side="BUY", annotations={"slot_number": "1"})
        assert r.marker_label(t) == "B1"

    def test_buy_b7(self):
        r = SevenSplitRenderer()
        t = _trade(side="BUY", annotations={"slot_number": "7"})
        assert r.marker_label(t) == "B7"

    def test_sell_s3(self):
        r = SevenSplitRenderer()
        t = _trade(side="SELL", annotations={"slot_number": "3"})
        assert r.marker_label(t) == "S3"

    def test_buy_no_annotation_fallback_b0(self):
        r = SevenSplitRenderer()
        t = _trade(side="BUY", annotations={})
        assert r.marker_label(t) == "B0"

    def test_sell_no_annotation_fallback_s0(self):
        r = SevenSplitRenderer()
        t = _trade(side="SELL", annotations={})
        assert r.marker_label(t) == "S0"

    def test_buy_invalid_annotation_fallback_b0(self):
        r = SevenSplitRenderer()
        t = _trade(side="BUY", annotations={"slot_number": "not_a_number"})
        assert r.marker_label(t) == "B0"


class TestMarkerStyle:
    def test_buy_uses_split_color(self):
        r = SevenSplitRenderer()
        t = _trade(side="BUY", annotations={"slot_number": "1"})
        s = r.marker_style(t)
        assert s.color == "#1f77b4"  # split 1 = blue
        assert s.marker == "^"
        assert s.label == "B1"

    def test_sell_uses_slot_color(self):
        r = SevenSplitRenderer()
        t = _trade(side="SELL", annotations={"slot_number": "4"})
        s = r.marker_style(t)
        assert s.color == "#d62728"  # slot 4 = red
        assert s.marker == "v"
        assert s.label == "S4"

    def test_unknown_slot_default_color(self):
        r = SevenSplitRenderer()
        t = _trade(side="BUY", annotations={})
        s = r.marker_style(t)
        assert s.color == "#000000"  # fallback


class TestDiagnosticPanels:
    def test_returns_two_panels(self):
        r = SevenSplitRenderer()
        panels = r.diagnostic_panels([], _episode())
        assert len(panels) == 2
        assert panels[0].title == "Episode 요약"
        assert panels[1].title == "차수별 거래 횟수"

    def test_summary_includes_episode_metrics(self):
        r = SevenSplitRenderer()
        e = _episode()
        panels = r.diagnostic_panels([], e)
        rows = dict(panels[0].rows)
        # Phase 0.10.h — Money formatted via format_money (KRW prefix)
        assert rows["episode peak"] == "₩100"
        assert rows["episode trough"] == "₩85"
        assert "drawdown_pct" in rows
        assert rows["recovered"] == "yes"
        assert rows["total buys"] == "0"
        assert rows["total sells"] == "0"

    def test_unrecovered_summary(self):
        r = SevenSplitRenderer()
        e = _episode(recovery=None, recovered=False)
        rows = dict(r.diagnostic_panels([], e)[0].rows)
        assert rows["recovered"] == "no"

    def test_slot_counts_filtered_by_episode_range(self):
        r = SevenSplitRenderer()
        e = _episode(
            peak=date(2024, 1, 5),
            trough=date(2024, 1, 7),
            recovery=date(2024, 1, 10),
        )
        trades = [
            _trade(timestamp_date=date(2024, 1, 1),  # before peak — excluded
                   side="BUY", annotations={"slot_number": "1"}),
            _trade(timestamp_date=date(2024, 1, 6),  # in episode
                   side="BUY", annotations={"slot_number": "1"}),
            _trade(timestamp_date=date(2024, 1, 7),  # in episode
                   side="BUY", annotations={"slot_number": "2"}),
            _trade(timestamp_date=date(2024, 1, 8),  # in episode
                   side="SELL", annotations={"slot_number": "1"}),
            _trade(timestamp_date=date(2024, 1, 15),  # after recovery — excluded
                   side="BUY", annotations={"slot_number": "3"}),
        ]
        panels = r.diagnostic_panels(trades, e)
        summary = dict(panels[0].rows)
        assert summary["total buys"] == "2"
        assert summary["total sells"] == "1"
        slot_rows = dict(panels[1].rows)
        assert slot_rows["slot 1"] == "buys=1 / sells=1"
        assert slot_rows["slot 2"] == "buys=1 / sells=0"
        assert "slot 3" not in slot_rows  # before peak + after recovery 모두 제외

    def test_unrecovered_includes_all_post_peak_trades(self):
        r = SevenSplitRenderer()
        e = _episode(
            peak=date(2024, 1, 5),
            trough=date(2024, 1, 7),
            recovery=None,
            recovered=False,
        )
        trades = [
            _trade(timestamp_date=date(2024, 1, 1),  # before peak — excluded
                   side="BUY", annotations={"slot_number": "1"}),
            _trade(timestamp_date=date(2024, 1, 6),  # in episode
                   side="BUY", annotations={"slot_number": "2"}),
            _trade(timestamp_date=date(2024, 4, 10),  # post-peak (included for unrecovered)
                   side="BUY", annotations={"slot_number": "3"}),
        ]
        panels = r.diagnostic_panels(trades, e)
        summary = dict(panels[0].rows)
        assert summary["total buys"] == "2"


class TestTradesInEpisodeHelper:
    def test_filters_before_peak(self):
        e = _episode(peak=date(2024, 1, 5))
        trades = [
            _trade(timestamp_date=date(2024, 1, 1)),
            _trade(timestamp_date=date(2024, 1, 5)),  # equal — included
            _trade(timestamp_date=date(2024, 1, 6)),
        ]
        result = _trades_in_episode(trades, e)
        assert len(result) == 2

    def test_filters_after_recovery(self):
        e = _episode(
            peak=date(2024, 1, 5), recovery=date(2024, 1, 10), recovered=True,
        )
        trades = [
            _trade(timestamp_date=date(2024, 1, 5)),
            _trade(timestamp_date=date(2024, 1, 10)),  # equal — included
            _trade(timestamp_date=date(2024, 1, 11)),  # after — excluded
        ]
        result = _trades_in_episode(trades, e)
        assert len(result) == 2
