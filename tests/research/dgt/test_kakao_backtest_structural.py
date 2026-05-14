"""Structural tests for kakao_dgt_backtest.py (Phase 0.11.f).

All tests work WITHOUT pykrx installed — pykrx is a lazy import
inside _build_asset() and _fetch_ohlcv() only.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
    OHLCV,
)
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot, _DGTTrade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset() -> Asset:
    return Asset(
        code="035720",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="카카오",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2000, 1, 1),
    )


def _make_snapshot(d: date, total_value: Decimal) -> _DGTSnapshot:
    return _DGTSnapshot(
        trade_date=d,
        cash=total_value,
        holdings=Decimal("0"),
        close_price=Decimal("50000"),
        total_value=total_value,
    )


def _make_trade(d: date, side: str = "BUY") -> _DGTTrade:
    return _DGTTrade(
        trade_date=d,
        side=side,
        grid_level_price=Decimal("50000"),
        quantity=Decimal("10"),
        rounded_price=Decimal("50000"),
        gross=Decimal("500000"),
        tax=Decimal("1500"),
        commission=Decimal("250"),
        cash_delta=Decimal("-501750") if side == "BUY" else Decimal("498500"),
    )


def _make_result(
    asset: Asset,
    capital: Money,
    trades: list[_DGTTrade] | None = None,
    snapshots: list[_DGTSnapshot] | None = None,
    final_amount: Decimal | None = None,
) -> _DGTBacktestResult:
    if trades is None:
        trades = []
    base = date(2025, 1, 2)
    if snapshots is None:
        snapshots = [_make_snapshot(base + timedelta(days=i), capital.amount) for i in range(5)]
    if final_amount is None:
        final_amount = capital.amount
    return _DGTBacktestResult(
        asset=asset,
        start=date(2025, 1, 2),
        end=date(2025, 1, 6),
        initial_capital=capital,
        final_cash=final_amount,
        final_holdings=Decimal("0"),
        final_close_price=Decimal("50000"),
        final_balance=Money(amount=final_amount, currency=capital.currency),
        wallet_total=Decimal("0"),
        reference_price=Decimal("50000"),
        grid_levels=[],
        trades=trades,
        daily_snapshots=snapshots,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestModuleImportable:
    def test_module_importable_without_pykrx(self) -> None:
        """Module-level import must succeed even if pykrx is absent."""
        import src.research.dgt.kakao_dgt_backtest  # noqa: F401


class TestBuildParser:
    def test_build_parser_defaults(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _build_parser

        parser = _build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

        # Parse with only the required arguments
        args = parser.parse_args(["--start", "2025-01-02", "--end", "2025-12-31"])
        assert args.code == "035720"
        assert args.grid_levels == 11
        assert args.grid_spacing_pct == "3"
        assert args.levels_above == 1
        assert args.initial_capital == "10000000"

    def test_build_parser_accepts_comma_codes(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "--code", "005930,005380",
            "--start", "2025-01-02",
            "--end", "2025-12-31",
        ])
        assert args.code == "005930,005380"
        # Confirm downstream split works
        codes = [c.strip() for c in args.code.split(",")]
        assert codes == ["005930", "005380"]


class TestFmtKrw:
    def test_fmt_krw_basic(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _fmt_krw

        result = _fmt_krw(Decimal("1234567"))
        # Must include comma-separated thousands
        assert "1,234,567" in result

    def test_fmt_krw_zero(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _fmt_krw

        result = _fmt_krw(Decimal("0"))
        assert result == "0"

    def test_fmt_krw_negative(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _fmt_krw

        result = _fmt_krw(Decimal("-50000"))
        assert "-" in result
        assert "50,000" in result


class TestFmtPct:
    def test_fmt_pct_two_decimals(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _fmt_pct

        result = _fmt_pct(Decimal("12.346"))
        assert result == "12.35%"

    def test_fmt_pct_zero(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _fmt_pct

        result = _fmt_pct(Decimal("0"))
        assert result == "0.00%"

    def test_fmt_pct_negative(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _fmt_pct

        result = _fmt_pct(Decimal("-5.5"))
        assert result == "-5.50%"


class TestResultSummary:
    def test_result_summary_keys(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _result_summary

        asset = _make_asset()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        trades = [
            _make_trade(date(2025, 1, 2), "BUY"),
            _make_trade(date(2025, 1, 3), "SELL"),
        ]
        result = _make_result(asset, capital, trades=trades)

        summary = _result_summary("TestLabel", result, capital)

        expected_keys = {"label", "final", "pnl", "pnl_pct", "trades", "buys", "sells",
                         "cagr", "mdd", "sharpe", "calmar"}
        assert expected_keys == set(summary.keys())

    def test_result_summary_label(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _result_summary

        asset = _make_asset()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        result = _make_result(asset, capital)

        summary = _result_summary("Paper-3%", result, capital)
        assert summary["label"] == "Paper-3%"

    def test_result_summary_trade_counts(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _result_summary

        asset = _make_asset()
        capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        trades = [
            _make_trade(date(2025, 1, 2), "BUY"),
            _make_trade(date(2025, 1, 3), "BUY"),
            _make_trade(date(2025, 1, 4), "SELL"),
        ]
        result = _make_result(asset, capital, trades=trades)

        summary = _result_summary("X", result, capital)
        assert summary["trades"] == "3"
        assert summary["buys"] == "2"
        assert summary["sells"] == "1"


class TestTradeRow:
    def test_trade_row_html_tags(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _trade_row

        trade = _make_trade(date(2025, 1, 2), "BUY")
        html = _trade_row(trade)

        assert "<tr>" in html
        assert "</tr>" in html
        assert "<td" in html
        assert "BUY" in html

    def test_trade_row_sell_side(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _trade_row

        trade = _make_trade(date(2025, 1, 3), "SELL")
        html = _trade_row(trade)

        assert "SELL" in html
        assert "side-sell" in html


class TestMergeMultiResults:
    def test_merge_multi_results_final_values_sum(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _merge_multi_results

        asset = _make_asset()
        capital_each = Money(amount=Decimal("5000000"), currency=Currency.KRW)
        total_capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        base = date(2025, 1, 2)

        r1 = _make_result(asset, capital_each, final_amount=Decimal("5100000"))
        r2 = _make_result(asset, capital_each, final_amount=Decimal("4900000"))

        merged = _merge_multi_results([r1, r2], total_capital, base, base + timedelta(days=4))

        assert merged.final_balance.amount == Decimal("10000000")

    def test_merge_multi_results_trade_counts_sum(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _merge_multi_results

        asset = _make_asset()
        capital_each = Money(amount=Decimal("5000000"), currency=Currency.KRW)
        total_capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        base = date(2025, 1, 2)

        trades1 = [_make_trade(base, "BUY"), _make_trade(base + timedelta(days=1), "SELL")]
        trades2 = [_make_trade(base, "BUY")]

        r1 = _make_result(asset, capital_each, trades=trades1, final_amount=Decimal("5000000"))
        r2 = _make_result(asset, capital_each, trades=trades2, final_amount=Decimal("5000000"))

        merged = _merge_multi_results([r1, r2], total_capital, base, base + timedelta(days=4))

        assert len(merged.trades) == 3

    def test_merge_multi_results_snapshot_dates_combined(self) -> None:
        from src.research.dgt.kakao_dgt_backtest import _merge_multi_results

        asset = _make_asset()
        capital_each = Money(amount=Decimal("5000000"), currency=Currency.KRW)
        total_capital = Money(amount=Decimal("10000000"), currency=Currency.KRW)
        base = date(2025, 1, 2)

        snaps1 = [_make_snapshot(base + timedelta(days=i), Decimal("5000000")) for i in range(3)]
        snaps2 = [_make_snapshot(base + timedelta(days=i), Decimal("5000000")) for i in range(3)]

        r1 = _make_result(asset, capital_each, snapshots=snaps1, final_amount=Decimal("5000000"))
        r2 = _make_result(asset, capital_each, snapshots=snaps2, final_amount=Decimal("5000000"))

        merged = _merge_multi_results([r1, r2], total_capital, base, base + timedelta(days=2))

        # 3 unique dates, each combined: 5M + 5M = 10M
        assert len(merged.daily_snapshots) == 3
        for snap in merged.daily_snapshots:
            assert snap.total_value == Decimal("10000000")
