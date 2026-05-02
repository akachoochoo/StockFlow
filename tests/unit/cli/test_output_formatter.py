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
    BuyActionRecord,
    Currency,
    Decision,
    Exchange,
    Money,
    PortfolioSnapshot,
    PositionValuation,
    SkipReason,
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


def _buy_decision(slot_number: int = 1) -> Decision:
    return Decision(
        timestamp=datetime(2026, 4, 30, 6, 30, tzinfo=UTC),
        asset=_asset(),
        buy_action=BuyActionRecord(
            slot_number=slot_number,
            split_level_after=slot_number,
            filled_quantity=Decimal("28"),
            filled_price=Decimal("35000"),
            target_price=Decimal("35000"),
            idempotency_key=f"buy-{slot_number}",
            order_id="mock-1",
            reasoning={"strategy_reason": f"buy_split_{slot_number}"},
        ),
        reasoning={"current_price": "35000"},
    )


def _skip_decision(reason: SkipReason = SkipReason.CIRCUIT_BREAKER_HALT) -> Decision:
    return Decision(
        timestamp=datetime(2026, 4, 30, 6, 30, tzinfo=UTC),
        asset=_asset(),
        skip_reason=reason,
        reasoning={"signal_level": "HALT"},
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
        decisions=[_buy_decision()],
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
        # Nested decisions / snapshots — new Phase 0.5 shape
        assert len(payload["decisions"]) == 1
        decision = payload["decisions"][0]
        assert decision["buy_action"]["slot_number"] == 1
        assert decision["buy_action"]["filled_quantity"] == "28"
        assert decision["sell_actions"] == []
        assert decision["skip_reason"] is None
        assert len(payload["snapshots"]) == 1


# ---------------------------------------------------------------------------
# Paper decision
# ---------------------------------------------------------------------------
class TestFormatPaperDecisionText:
    def test_text_with_position(self):
        out = format_paper_decision(
            _buy_decision(),
            _snapshot_with_pos(),
            as_json=False,
        )
        assert "Paper trading" in out
        assert "Decision:" in out
        assert "buy_split_1" in out
        assert "Positions:" in out

    def test_text_without_position(self):
        out = format_paper_decision(
            _skip_decision(),
            _snapshot_no_pos(),
            as_json=False,
        )
        assert "skip:circuit_breaker_halt" in out
        assert "Positions:" not in out  # empty valuations → no section


class TestFormatPaperDecisionJSON:
    def test_json_round_trips(self):
        out = format_paper_decision(
            _buy_decision(),
            _snapshot_with_pos(),
            as_json=True,
        )
        payload = json.loads(out)
        assert payload["decision"]["buy_action"]["slot_number"] == 1
        assert payload["decision"]["skip_reason"] is None
        assert payload["snapshot"]["snapshot_date"] == "2026-04-30"
