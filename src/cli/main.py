"""Trading CLI — ``trading backtest`` and ``trading paper`` subcommands.

ADR §10.1 박제. Phase 0 single-asset (KODEX 200) entry point. Both
commands share the kill-switch (CLAUDE.md §11.1) + lock-file (§10.2)
safety wrap and the same strategy-config flags. Composition is delegated
to ``src.cli.composition`` so this module stays a thin parser/printer.
"""
from __future__ import annotations

from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import click

from src.application.backtest_runner import BacktestRunner
from src.cli import composition, output_formatter, safety
from src.domain.models import Currency, Money
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.infrastructure.csv_market_data_loader import load_ohlcv_csv

if TYPE_CHECKING:
    from datetime import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _krw(amount: int) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


def _build_strategy_config(
    *,
    drop_pct: str,
    max_split: int,
    per_split_amount: int,
    max_split_per_day: int,
) -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal(drop_pct),
        max_split_count=max_split,
        per_split_amount=_krw(per_split_amount),
        max_split_per_day=max_split_per_day,
    )


def _strategy_options(f: click.decorators.FC) -> click.decorators.FC:
    """Stack the four shared strategy flags onto a click command."""
    f = click.option(
        "--max-split-per-day",
        type=click.IntRange(1, 7),
        default=1,
        show_default=True,
        help="Max FULL fills allowed per calendar day (ADR §7.11).",
    )(f)
    f = click.option(
        "--per-split-amount",
        type=int,
        default=1_000_000,
        show_default=True,
        help="KRW spent per split entry.",
    )(f)
    f = click.option(
        "--max-split",
        type=click.IntRange(1, 7),
        default=7,
        show_default=True,
        help="Maximum split level (1..7).",
    )(f)
    f = click.option(
        "--drop-pct",
        type=str,
        default="7.0",
        show_default=True,
        help="Price-drop threshold percentage (Decimal as string).",
    )(f)
    return f


# ---------------------------------------------------------------------------
# Group + subcommands
# ---------------------------------------------------------------------------
@click.group()
def main() -> None:
    """SevenSplit trading CLI (Phase 0, single-asset)."""
    safety.check_kill_switch()


@main.command()
@click.option(
    "--csv",
    "csv_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="OHLCV CSV (date,open,high,low,close,volume).",
)
@click.option(
    "--start",
    "start_date",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Inclusive backtest start date (YYYY-MM-DD).",
)
@click.option(
    "--end",
    "end_date",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Inclusive backtest end date (YYYY-MM-DD).",
)
@click.option(
    "--capital",
    type=int,
    default=10_000_000,
    show_default=True,
    help="Initial KRW capital.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit JSON instead of human-readable text.",
)
@_strategy_options
def backtest(
    csv_path: Path,
    start_date: datetime,
    end_date: datetime,
    capital: int,
    as_json: bool,
    drop_pct: str,
    max_split: int,
    per_split_amount: int,
    max_split_per_day: int,
) -> None:
    """Replay historical OHLCV through the Phase 0 strategy + mock adapters."""
    with safety.lock_file():
        asset = composition.kodex200()
        bars = load_ohlcv_csv(csv_path, asset)
        runner = BacktestRunner(
            asset=asset,
            strategy_config=_build_strategy_config(
                drop_pct=drop_pct,
                max_split=max_split,
                per_split_amount=per_split_amount,
                max_split_per_day=max_split_per_day,
            ),
            initial_capital=_krw(capital),
            ohlcv_by_asset={asset: bars},
        )
        result = runner.run(start_date.date(), end_date.date())
    click.echo(output_formatter.format_backtest_result(result, as_json=as_json))


@main.command()
@click.option(
    "--csv",
    "csv_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="OHLCV CSV covering at least the trading date.",
)
@click.option(
    "--date",
    "trade_date",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="The KST trading date to evaluate (YYYY-MM-DD).",
)
@click.option(
    "--db",
    "db_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="SQLite DB path (created on first run).",
)
@click.option(
    "--capital",
    type=int,
    default=10_000_000,
    show_default=True,
    help="Initial KRW capital — used only on the very first run "
    "(no snapshot yet).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit JSON instead of human-readable text.",
)
@_strategy_options
def paper(
    csv_path: Path,
    trade_date: datetime,
    db_path: Path,
    capital: int,
    as_json: bool,
    drop_pct: str,
    max_split: int,
    per_split_amount: int,
    max_split_per_day: int,
) -> None:
    """Run a single paper-trading day with persistent SQLite state.

    Decision at 09:00 KST (T-1 close visible only — ADR §9.3), snapshot
    at 16:00 KST (T close available). Cash + positions restored from
    SQLite via the composition root (ADR §10.3). State is verified by
    the §10.4 sanity check before any new decision.
    """
    today = trade_date.date()
    with safety.lock_file():
        asset = composition.kodex200()
        bars = load_ohlcv_csv(csv_path, asset)
        decision_at = composition.utc_for(today, time(9, 0))
        snapshot_at = composition.utc_for(today, time(16, 0))
        components = composition.build_paper_components(
            asset=asset,
            bars=bars,
            db_path=db_path,
            initial_capital=_krw(capital),
            strategy_config=_build_strategy_config(
                drop_pct=drop_pct,
                max_split=max_split,
                per_split_amount=per_split_amount,
                max_split_per_day=max_split_per_day,
            ),
            initial_clock=decision_at,
        )
        try:
            decision = components.orchestrator.run_for_date(today)
            components.set_clock(snapshot_at)
            snapshot = components.snapshot_builder.build_and_save(today)
        finally:
            components.close()
    click.echo(
        output_formatter.format_paper_decision(decision, snapshot, as_json=as_json)
    )


if __name__ == "__main__":
    main()
