"""Acceptance Criteria 3 — 신규 dummy strategy 추가 시 코어 reporting
모듈 코드 변경 없이 마커 렌더링 동작 검증 (sub-step 0.10.e, ADR 0006 §1.3).

Setup: register a dummy "ma_cross" strategy renderer (or use default
fallback) → run end-to-end pipeline → verify markers / panels rendered.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from src.adapters.reporting.renderer_registry import StrategyRendererRegistry
from src.application.backtest_runner import BacktestResult
from src.application.reporting.report import generate_episode_report
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
)
from src.ports.strategy_renderer import MarkerStyle, Panel

if TYPE_CHECKING:
    from pathlib import Path


def _asset() -> Asset:
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="X",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _bars(n: int = 80) -> list[OHLCV]:
    asset = _asset()
    start = date(2024, 1, 1)
    bars: list[OHLCV] = []
    for i in range(n):
        price = (
            100 - (i * 20 / 30) if i < 30
            else 80 + ((i - 30) * 20 / (n - 30))
        )
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


def _build_backtest_result() -> BacktestResult:
    initial = 10000000
    snapshots: list[PortfolioSnapshot] = []
    n_days = 80
    start = date(2024, 1, 1)
    for i in range(n_days):
        mult = 1.0 - (i * 0.30 / 30) if i < 30 else 0.70 + ((i - 30) * 0.40 / 50)
        total = int(initial * mult)
        snapshots.append(
            PortfolioSnapshot(
                snapshot_date=start + timedelta(days=i),
                snapshot_at=datetime.combine(
                    start + timedelta(days=i),
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
                initial_capital=Money(
                    amount=Decimal(initial), currency=Currency.KRW,
                ),
                cash=Money(amount=Decimal(total), currency=Currency.KRW),
                valuations=[],
                total_market_value=Money(
                    amount=Decimal(0), currency=Currency.KRW,
                ),
                total_value=Money(
                    amount=Decimal(total), currency=Currency.KRW,
                ),
                total_cost_basis=Money(
                    amount=Decimal(0), currency=Currency.KRW,
                ),
                total_unrealized_pnl=Money(
                    amount=Decimal(0), currency=Currency.KRW,
                ),
            )
        )

    # Dummy MA cross trade: signal=golden_cross, fast=20, slow=60
    decision = Decision(
        timestamp=datetime(2024, 1, 25, tzinfo=UTC),
        asset=_asset(),
        buy_action=BuyActionRecord(
            slot_number=1,
            split_level_after=1,
            filled_quantity=Decimal("10"),
            filled_price=Decimal("85"),
            target_price=Decimal("85"),
            idempotency_key="ma-1",
            order_id="ord-1",
            reasoning={
                "signal": "golden_cross",
                "fast": "20",
                "slow": "60",
            },
        ),
        sell_actions=[],
        skip_reason=None,
        reasoning={"strategy": "ma_cross"},
    )

    return BacktestResult.from_run(
        start_date=start,
        end_date=start + timedelta(days=n_days - 1),
        initial_capital=Money(amount=Decimal(initial), currency=Currency.KRW),
        decisions=[decision],
        snapshots=snapshots,
    )


class TestAcceptanceCriteria3:
    """신규 dummy strategy 추가 시 코어 reporting 모듈 코드 변경 없이 동작."""

    def test_unregistered_dummy_strategy_uses_default_fallback(
        self, tmp_path: Path,
    ):
        """등록 안 한 신규 strategy → DefaultRenderer fallback → 정상 동작."""
        result = _build_backtest_result()
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="ma_cross_unregistered",  # 미등록
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars()},
        )
        # 코어 module 변경 zero — pipeline 정상 동작
        assert report.index_html_path.exists()
        assert len(report.episodes) >= 1

    def test_runtime_register_custom_renderer_works_end_to_end(
        self, tmp_path: Path,
    ):
        """Runtime register API 로 신규 dummy strategy 등록 → end-to-end 동작."""

        class MaCrossRenderer:
            """Dummy MA cross renderer — strategy-specific labels."""

            def marker_label(self, trade):
                signal = trade.annotations.get("signal", "?")
                tag = "GC" if signal == "golden_cross" else "DC"
                return f"{tag}({trade.annotations.get('fast', '?')}/{trade.annotations.get('slow', '?')})"

            def marker_style(self, trade):
                signal = trade.annotations.get("signal", "")
                return MarkerStyle(
                    color="#28a745" if signal == "golden_cross" else "#dc3545",
                    marker="^" if trade.side == "BUY" else "v",
                    size=12,
                    label=self.marker_label(trade),
                )

            def diagnostic_panels(self, trades, episode):
                # Filter trades to episode window manually
                ep_trades = [
                    t for t in trades
                    if t.timestamp.date() >= episode.peak_date
                    and (
                        episode.recovery_date is None
                        or t.timestamp.date() <= episode.recovery_date
                    )
                ]
                gc = sum(
                    1 for t in ep_trades
                    if t.annotations.get("signal") == "golden_cross"
                )
                dc = sum(
                    1 for t in ep_trades
                    if t.annotations.get("signal") == "death_cross"
                )
                return [
                    Panel(
                        title="MA Cross 신호",
                        rows=[
                            ("golden_cross", str(gc)),
                            ("death_cross", str(dc)),
                            ("total", str(len(ep_trades))),
                        ],
                    ),
                ]

        # Register custom renderer
        registry = StrategyRendererRegistry()
        registry.register("ma_cross", MaCrossRenderer())

        result = _build_backtest_result()
        report = generate_episode_report(
            backtest_result=result,
            strategy_id="ma_cross",
            output_dir=tmp_path,
            bars_by_asset={"069500": _bars()},
            registry=registry,
        )

        # Verify pipeline succeeded
        assert report.index_html_path.exists()
        assert len(report.episodes) >= 1

        # Verify custom renderer's panel rendered in HTML
        episode_html = report.episode_html_paths[0].read_text(encoding="utf-8")
        assert "MA Cross 신호" in episode_html
        assert "golden_cross" in episode_html
        # 코어 reporting module (`src/application/reporting/`) 코드 변경 zero
        # 검증 = 본 테스트가 패스 = 신규 strategy 추가에 코어 변경 zero 입증
