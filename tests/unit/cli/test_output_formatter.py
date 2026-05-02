"""Unit tests for src.cli.output_formatter."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.backtest_runner import BacktestResult
from src.cli.output_formatter import (
    format_backtest_result,
    format_paper_decision,
)
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Decision,
    Exchange,
    Money,
    PortfolioSnapshot,
    PositionValuation,
)


def _asset() -> Asset:
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


def _krw(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


def _decision(action: str = "buy_split_1") -> Decision:
    return Decision(
        timestamp=datetime(2026, 4, 30, 6, 30, tzinfo=UTC),
        asset=_asset(),
        action=action,
        reasoning={
            "filled_quantity": "28",
            "filled_price": "35000",
        },
        resulting_order_id="mock-1",
    )


def _snapshot_no_pos(d: date = date(2026, 4, 30)) -> PortfolioSnapshot:
    return PortfolioSnapshot.build(
        snapshot_date=d,
        snapshot_at=datetime(2026, 4, 30, 7, 0, tzinfo=UTC),
        initial_capital=_krw("4000000"),
        cash=_krw("4000000"),
        valuations=[],
    )


def _snapshot_with_pos(d: date = date(2026, 4, 30)) -> PortfolioSnapshot:
    asset = _asset()
    val = PositionValuation.from_position_market_price(
        asset=asset,
        quantity=Decimal("28"),
        avg_price=Decimal("35000"),
        market_price=Decimal("36000"),
        split_level=1,
    ) if hasattr(PositionValuation, "from_position_market_price") else PositionValuation(
        asset=asset,
        quantity=Decimal("28"),
        avg_price=Decimal("35000"),
        market_price=Decimal("36000"),
        market_value=_krw("1008000"),
        unrealized_pnl=_krw("28000"),
        split_level=1,
    )
    return PortfolioSnapshot.build(
        snapshot_date=d,
        snapshot_at=datetime(2026, 4, 30, 7, 0, tzinfo=UTC),
        initial_capital=_krw("4000000"),
        cash=_krw("3020000"),
        valuations=[val],
    )


def _backtest_result() -> BacktestResult:
    return BacktestResult.from_run(
        start_date=date(2026, 4, 30),
        end_date=date(2026, 4, 30),
        initial_capital=_krw("4000000"),
        decisions=[_decision()],
        snapshots=[_snapshot_with_pos()],
    )


# ---------------------------------------------------------------------------
# Backtest result
# ---------------------------------------------------------------------------
class TestFormatBacktestResultText:
    def test_text_contains_key_metrics(self):
        out = format_backtest_result(_backtest_result(), as_json=False)
        assert "Backtest result" in out
        assert "Trading days:" in out
        assert "CAGR:" in out
        assert "Max drawdown:" in out
        assert "Sharpe ratio:" in out
        assert "Calmar ratio:" in out
        assert "buy_split_1" in out  # buy decision listed

    def test_text_no_buys_section_when_only_skips(self):
        # Empty result (no decisions) → no buy section line
        empty = BacktestResult.from_run(
            start_date=date(2026, 4, 30),
            end_date=date(2026, 4, 30),
            initial_capital=_krw("4000000"),
            decisions=[],
            snapshots=[],
        )
        out = format_backtest_result(empty, as_json=False)
        assert "Buy decisions" not in out
        assert "Decisions by action" not in out


class TestFormatBacktestResultJSON:
    def test_json_round_trips(self):
        out = format_backtest_result(_backtest_result(), as_json=True)
        payload = json.loads(out)
        assert payload["start_date"] == "2026-04-30"
        assert payload["n_trading_days"] == 1
        assert payload["initial_capital"] == {
            "amount": "4000000",
            "currency": "KRW",
        }
        # Decimal preserved as string
        assert isinstance(payload["cagr_pct"], str)
        assert isinstance(payload["max_drawdown_pct"], str)
        assert isinstance(payload["sharpe_ratio"], str)
        assert isinstance(payload["calmar_ratio"], str)
        # Nested decisions / snapshots included
        assert len(payload["decisions"]) == 1
        assert payload["decisions"][0]["action"] == "buy_split_1"
        assert len(payload["snapshots"]) == 1


# ---------------------------------------------------------------------------
# Paper decision
# ---------------------------------------------------------------------------
class TestFormatPaperDecisionText:
    def test_text_with_position(self):
        out = format_paper_decision(
            _decision(),
            _snapshot_with_pos(),
            as_json=False,
        )
        assert "Paper trading" in out
        assert "Decision:" in out
        assert "buy_split_1" in out
        assert "Positions:" in out

    def test_text_without_position(self):
        out = format_paper_decision(
            _decision(action="skip:circuit_breaker_halt"),
            _snapshot_no_pos(),
            as_json=False,
        )
        assert "skip:circuit_breaker_halt" in out
        assert "Positions:" not in out  # empty valuations → no section


class TestFormatPaperDecisionJSON:
    def test_json_round_trips(self):
        out = format_paper_decision(
            _decision(),
            _snapshot_with_pos(),
            as_json=True,
        )
        payload = json.loads(out)
        assert payload["decision"]["action"] == "buy_split_1"
        assert payload["snapshot"]["snapshot_date"] == "2026-04-30"
