"""End-to-end integration test for episode report pipeline (sub-step 0.10.e).

Synthetic BacktestResult → generate_episode_report → reports/episode_*.html
+ index.html. mplfinance + matplotlib 외부 lib 호출 → integration.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.application.backtest_runner import BacktestResult
from src.application.reporting.report import (
    EpisodeReportResult,
    extract_portfolio_equity_curve,
    generate_episode_report,
)
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    BuyActionRecord,
    Currency,
    Decision,
    Exchange,
    Market,
    Money,
    PortfolioSnapshot,
    PositionValuation,
    SellActionRecord,
)

if TYPE_CHECKING:
    from pathlib import Path


def _asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name=f"Asset-{code}",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _krw(amount: int) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


def _bars(
    n: int = 80, start: date = date(2024, 1, 1), trough_at: int = 30,
    asset_code: str = "069500",
) -> list[OHLCV]:
    """Synthetic bars with V-shape — peak → trough at index trough_at → recovery."""
    asset = _asset(asset_code)
    bars: list[OHLCV] = []
    for i in range(n):
        # V-shape: 100 → 80 (-20% at trough_at) → 100
        if i < trough_at:
            price = 100 - (i * 20 / trough_at)
        else:
            price = 80 + ((i - trough_at) * 20 / (n - trough_at))
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=start + timedelta(days=i),
                open=Decimal(int(price)),
                high=Decimal(int(price + 1)),
                low=Decimal(int(price - 1)),
                close=Decimal(int(price)),
                volume=Decimal("1000000"),
            )
        )
    return bars


def _snapshot(
    *,
    snap_date: date,
    cash: int = 1000000,
    market_value: int = 0,
    initial: int = 10000000,
) -> PortfolioSnapshot:
    """Synthetic single-asset snapshot."""
    asset = _asset()
    if market_value > 0:
        valuations = [
            PositionValuation(
                asset=asset,
                quantity=Decimal("100"),
                avg_price=Decimal("100"),
                market_price=Decimal(market_value // 100),
                market_value=_krw(market_value),
                unrealized_pnl=_krw(market_value - 10000),
                split_level=1,
            ),
        ]
        cost_basis = 10000
        unr_pnl = market_value - 10000
    else:
        valuations = []
        cost_basis = 0
        unr_pnl = 0

    return PortfolioSnapshot(
        snapshot_date=snap_date,
        snapshot_at=datetime.combine(snap_date, datetime.min.time(), tzinfo=UTC),
        initial_capital=_krw(initial),
        cash=_krw(cash),
        valuations=valuations,
        total_market_value=_krw(market_value),
        total_value=_krw(cash + market_value),
        total_cost_basis=_krw(cost_basis),
        total_unrealized_pnl=_krw(unr_pnl),
    )


def _equity_to_snapshot(
    snap_date: date, total_value: int, *, initial: int = 10000000,
) -> PortfolioSnapshot:
    return _snapshot(
        snap_date=snap_date,
        cash=total_value,
        market_value=0,
        initial=initial,
    )


def _decision_buy(
    *,
    timestamp: datetime,
    slot: int = 1,
    price: int = 95,
    quantity: int = 10,
) -> Decision:
    return Decision(
        timestamp=timestamp,
        asset=_asset(),
        buy_action=BuyActionRecord(
            slot_number=slot,
            split_level_after=slot,
            filled_quantity=Decimal(quantity),
            filled_price=Decimal(price),
            target_price=Decimal(price),
            idempotency_key=f"buy-{slot}-{timestamp.isoformat()}",
            order_id=f"ord-{slot}",
            reasoning={"split_number": str(slot)},
        ),
        sell_actions=[],
        skip_reason=None,
        reasoning={"current_price": str(price)},
    )


def _decision_sell(
    *,
    timestamp: datetime,
    slot: int = 1,
    price: int = 105,
    quantity: int = 10,
) -> Decision:
    return Decision(
        timestamp=timestamp,
        asset=_asset(),
        buy_action=None,
        sell_actions=[
            SellActionRecord(
                slot_number=slot,
                filled_quantity=Decimal(quantity),
                filled_price=Decimal(price),
                profit_pct=Decimal("10.0"),
                idempotency_key=f"sell-{slot}-{timestamp.isoformat()}",
                order_id=f"sord-{slot}",
                reasoning={"slot_number": str(slot)},
            ),
        ],
        skip_reason=None,
        reasoning={"current_price": str(price)},
    )


def _build_backtest_result(
    *,
    n_days: int = 80,
    start: date = date(2024, 1, 1),
    trough_at: int = 30,
    n_trades: int = 4,
) -> BacktestResult:
    """V-shape equity curve (100% → 70% → 110%) + N decisions."""
    snapshots: list[PortfolioSnapshot] = []
    initial = 10000000
    for i in range(n_days):
        if i < trough_at:
            mult = 1.0 - (i * 0.30 / trough_at)
        else:
            mult = 0.70 + ((i - trough_at) * 0.40 / (n_days - trough_at))
        total = int(initial * mult)
        snapshots.append(_equity_to_snapshot(start + timedelta(days=i), total))

    decisions: list[Decision] = []
    # Some buys around trough + sells near recovery
    for k in range(n_trades):
        d_idx = trough_at - 4 + k
        if 0 <= d_idx < n_days:
            ts = datetime.combine(
                start + timedelta(days=d_idx),
                datetime.min.time(),
                tzinfo=UTC,
            )
            decisions.append(
                _decision_buy(timestamp=ts, slot=k + 1, price=80 + k * 2),
            )
    # 1 sell post-trough
    sell_idx = trough_at + 10
    if sell_idx < n_days:
        ts = datetime.combine(
            start + timedelta(days=sell_idx),
            datetime.min.time(),
            tzinfo=UTC,
        )
        decisions.append(_decision_sell(timestamp=ts, slot=1, price=95))

    return BacktestResult.from_run(
        start_date=start,
        end_date=start + timedelta(days=n_days - 1),
        initial_capital=_krw(initial),
        decisions=decisions,
        snapshots=snapshots,
    )


class TestExtractPortfolioEquityCurve:
    def test_sorted_by_date(self):
        result = _build_backtest_result(n_days=10)
        curve = extract_portfolio_equity_curve(result.snapshots)
        dates = [d for d, _ in curve]
        assert dates == sorted(dates)

    def test_returns_total_value(self):
        result = _build_backtest_result(n_days=5)
        curve = extract_portfolio_equity_curve(result.snapshots)
        # Day 0 = initial * 1.0
        assert curve[0][1] == Decimal("10000000")


class TestGenerateEpisodeReportPipeline:
    def test_creates_index_html(self, tmp_path: Path):
        result = _build_backtest_result()
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="price_drop",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars(n=80)},
        )
        assert report.index_html_path == tmp_path / "index.html"
        assert report.index_html_path.exists()

    def test_creates_per_episode_html(self, tmp_path: Path):
        result = _build_backtest_result()
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="price_drop",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars(n=80)},
        )
        # V-shape with -30% drawdown → at least 1 episode at -5% threshold
        assert len(report.episodes) >= 1
        assert len(report.episode_html_paths) == len(report.episodes)
        for path in report.episode_html_paths:
            assert path.exists()
            assert path.read_bytes()[:1] == b"<"  # HTML

    def test_index_links_match_episodes(self, tmp_path: Path):
        result = _build_backtest_result()
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="price_drop",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars(n=80)},
        )
        index_html = report.index_html_path.read_text(encoding="utf-8")
        for path in report.episode_html_paths:
            assert path.name in index_html

    def test_returns_trade_count(self, tmp_path: Path):
        result = _build_backtest_result(n_trades=3)
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="price_drop",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars(n=80)},
        )
        # 3 buys + 1 sell = 4 trades
        assert report.trade_count == 4

    def test_default_threshold_minus_5(self, tmp_path: Path):
        result = _build_backtest_result()
        # Default -5% with V-shape -30% → episodes detected
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="price_drop",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars(n=80)},
        )
        assert len(report.episodes) >= 1

    def test_strict_threshold_yields_no_episodes(self, tmp_path: Path):
        # tighter -50% threshold against -30% drawdown → no episodes
        result = _build_backtest_result()
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="price_drop",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars(n=80)},
            threshold_pct=Decimal("-50"),
        )
        assert report.episodes == []
        assert report.episode_html_paths == []
        # Index still written (with empty placeholder)
        assert report.index_html_path.exists()

    def test_returns_episode_report_result(self, tmp_path: Path):
        result = _build_backtest_result()
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="price_drop",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars(n=80)},
        )
        assert isinstance(report, EpisodeReportResult)


class TestErrorHandling:
    def test_asset_scope_raises_not_implemented(self, tmp_path: Path):
        result = _build_backtest_result()
        with pytest.raises(NotImplementedError, match="scope"):
            generate_episode_report(
                backtest_result=result,
                strategy_id="price_drop",
                output_dir=tmp_path,
                bars_by_asset={"069500": _bars(n=80)},
                scope="asset",
            )

    def test_both_scope_raises_not_implemented(self, tmp_path: Path):
        result = _build_backtest_result()
        with pytest.raises(NotImplementedError):
            generate_episode_report(
                backtest_result=result,
                strategy_id="price_drop",
                output_dir=tmp_path,
                bars_by_asset={"069500": _bars(n=80)},
                scope="both",
            )

    def test_empty_bars_by_asset_rejected(self, tmp_path: Path):
        result = _build_backtest_result()
        with pytest.raises(ValueError, match="empty"):
            generate_episode_report(
                backtest_result=result,
                strategy_id="price_drop",
                output_dir=tmp_path,
                bars_by_asset={},
            )

    def test_unknown_chart_symbol_rejected(self, tmp_path: Path):
        result = _build_backtest_result()
        with pytest.raises(ValueError, match="not in bars_by_asset"):
            generate_episode_report(
                backtest_result=result,
                strategy_id="price_drop",
                output_dir=tmp_path,
                bars_by_asset={"069500": _bars(n=80)},
                chart_symbol="999999",
            )
