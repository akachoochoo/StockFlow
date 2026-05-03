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
from typing import TYPE_CHECKING, Any

import click
from click.core import ParameterSource

from src.application.backtest_runner import BacktestRunner
from src.cli import composition, output_formatter, safety
from src.domain.models import Currency, Money
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.domain.strategies.profit_target import SellStrategyConfig
from src.infrastructure.csv_market_data_loader import load_ohlcv_csv
from src.infrastructure.yaml_strategy_config_loader import load_strategy_config

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


# ADR §6.3 — names mutually exclusive with --config (only the strategy
# flags; meta options like --csv / --start / --end / --capital / --json
# stay permitted alongside --config). Listed in click parameter form
# (underscore) since that's what ``Context.get_parameter_source`` keys on.
_STRATEGY_FLAG_NAMES: tuple[str, ...] = (
    "drop_pct",
    "max_split",
    "per_split_amount",
    "max_split_per_day",
    "profit_target_pct",
    "max_sells_per_day",
    "reentry_strategy",
    "cooldown_days",
)


def _strategy_options(f: click.decorators.FC) -> click.decorators.FC:
    """Stack the strategy flags onto a click command (ADR §6.3).

    Phase 0 buy-side flags + Phase 0.5 new sell/reentry flags. ``--config``
    is mutually exclusive with all of these (validated at runtime via
    ``_check_mutually_exclusive_with_config``).
    """
    f = click.option(
        "--cooldown-days",
        type=click.IntRange(0, 365),
        default=60,
        show_default=True,
        help="Hybrid reentry cooldown days (used when "
        "--reentry-strategy=hybrid).",
    )(f)
    f = click.option(
        "--reentry-strategy",
        type=click.Choice(["hybrid", "moving_average"]),
        default="hybrid",
        show_default=True,
        help="Reentry policy. moving_average requires --config (window / "
        "ma_type must come from YAML; flag-only path supports hybrid only).",
    )(f)
    f = click.option(
        "--max-sells-per-day",
        type=click.IntRange(1, 7),
        default=7,
        show_default=True,
        help="Max slots that may be sold in a single evaluation.",
    )(f)
    f = click.option(
        "--profit-target-pct",
        type=str,
        default="10.0",
        show_default=True,
        help="Per-slot profit-target threshold percentage (Decimal as string).",
    )(f)
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
    f = click.option(
        "--config",
        "config_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
        help="YAML strategy config (ADR §6). Mutually exclusive with the "
        "individual strategy flags.",
    )(f)
    return f


def _check_mutually_exclusive_with_config(ctx: click.Context) -> None:
    """Raise click.UsageError if --config + any strategy flag (ADR §6.3)."""
    explicit: list[str] = []
    for name in _STRATEGY_FLAG_NAMES:
        try:
            source = ctx.get_parameter_source(name)
        except KeyError:
            continue
        if source is ParameterSource.COMMANDLINE:
            explicit.append(name)
    if explicit:
        flag_strs = ", ".join(f"--{n.replace('_', '-')}" for n in explicit)
        raise click.UsageError(
            f"--config and strategy flags ({flag_strs}) are mutually "
            "exclusive. Either pass --config PATH (recommended for "
            "reproducibility) or use the flag-only form."
        )


def _resolve_strategy_configs(
    ctx: click.Context,
    config_path: Path | None,
    *,
    drop_pct: str,
    max_split: int,
    per_split_amount: int,
    max_split_per_day: int,
    profit_target_pct: str,
    max_sells_per_day: int,
    reentry_strategy: str,
    cooldown_days: int,
    expected_asset_code: str,
) -> tuple[SplitStrategyConfig, SellStrategyConfig, str, dict[str, Any]]:
    """Resolve the four strategy configs from either --config or flags.

    Returns ``(buy_config, sell_config, reentry_name, reentry_params)``.
    Raises ``click.UsageError`` on conflict (--config + strategy flag),
    asset-code mismatch, or moving_average requested without --config.
    """
    if config_path is not None:
        _check_mutually_exclusive_with_config(ctx)
        bundles = load_strategy_config(config_path)
        # ADR §6.2: Phase 0.5 single-asset uses the first key only.
        bundle = next(iter(bundles.values()))
        if bundle.code != expected_asset_code:
            raise click.UsageError(
                f"YAML asset code {bundle.code!r} does not match Phase 0.5 "
                f"hardcoded asset {expected_asset_code!r}. Phase 0.7 ADR "
                "round will surface arbitrary codes from YAML."
            )
        return (
            bundle.buy_config,
            bundle.sell_config,
            bundle.reentry_strategy_name,
            dict(bundle.reentry_parameters),
        )

    if reentry_strategy == "moving_average":
        raise click.UsageError(
            "--reentry-strategy moving_average requires --config (window / "
            "ma_type are not flag-exposed). The flag-only path supports "
            "hybrid only."
        )

    return (
        _build_strategy_config(
            drop_pct=drop_pct,
            max_split=max_split,
            per_split_amount=per_split_amount,
            max_split_per_day=max_split_per_day,
        ),
        SellStrategyConfig(
            profit_target_pct=Decimal(profit_target_pct),
            max_sells_per_day=max_sells_per_day,
        ),
        "hybrid",
        {"cooldown_days": cooldown_days},
    )


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
@click.pass_context
def backtest(
    ctx: click.Context,
    csv_path: Path,
    start_date: datetime,
    end_date: datetime,
    capital: int,
    as_json: bool,
    config_path: Path | None,
    drop_pct: str,
    max_split: int,
    per_split_amount: int,
    max_split_per_day: int,
    profit_target_pct: str,
    max_sells_per_day: int,
    reentry_strategy: str,
    cooldown_days: int,
) -> None:
    """Replay historical OHLCV through the Phase 0 strategy + mock adapters."""
    with safety.lock_file():
        asset = composition.kodex200()
        buy_config, sell_config, reentry_name, reentry_params = (
            _resolve_strategy_configs(
                ctx,
                config_path,
                drop_pct=drop_pct,
                max_split=max_split,
                per_split_amount=per_split_amount,
                max_split_per_day=max_split_per_day,
                profit_target_pct=profit_target_pct,
                max_sells_per_day=max_sells_per_day,
                reentry_strategy=reentry_strategy,
                cooldown_days=cooldown_days,
                expected_asset_code=asset.code,
            )
        )
        bars = load_ohlcv_csv(csv_path, asset)
        runner = BacktestRunner(
            asset=asset,
            strategy_config=buy_config,
            sell_strategy_config=sell_config,
            reentry_strategy_name=reentry_name,
            reentry_parameters=reentry_params,
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
@click.pass_context
def paper(
    ctx: click.Context,
    csv_path: Path,
    trade_date: datetime,
    db_path: Path,
    capital: int,
    as_json: bool,
    config_path: Path | None,
    drop_pct: str,
    max_split: int,
    per_split_amount: int,
    max_split_per_day: int,
    profit_target_pct: str,
    max_sells_per_day: int,
    reentry_strategy: str,
    cooldown_days: int,
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
        buy_config, sell_config, reentry_name, reentry_params = (
            _resolve_strategy_configs(
                ctx,
                config_path,
                drop_pct=drop_pct,
                max_split=max_split,
                per_split_amount=per_split_amount,
                max_split_per_day=max_split_per_day,
                profit_target_pct=profit_target_pct,
                max_sells_per_day=max_sells_per_day,
                reentry_strategy=reentry_strategy,
                cooldown_days=cooldown_days,
                expected_asset_code=asset.code,
            )
        )
        bars = load_ohlcv_csv(csv_path, asset)
        decision_at = composition.utc_for(today, time(9, 0))
        snapshot_at = composition.utc_for(today, time(16, 0))
        components = composition.build_paper_components(
            asset=asset,
            bars=bars,
            db_path=db_path,
            initial_capital=_krw(capital),
            strategy_config=buy_config,
            sell_strategy_config=sell_config,
            reentry_strategy_name=reentry_name,
            reentry_parameters=reentry_params,
            initial_clock=decision_at,
        )
        try:
            decisions = components.orchestrator.run_for_date(today)
            decision = decisions[0]
            components.set_clock(snapshot_at)
            snapshot = components.snapshot_builder.build_and_save(today)
        finally:
            components.close()
    click.echo(
        output_formatter.format_paper_decision(decision, snapshot, as_json=as_json)
    )


@main.group()
def config() -> None:
    """Strategy config utilities (ADR §6)."""


@config.command("validate")
@click.option(
    "--config",
    "config_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML strategies file to validate.",
)
def config_validate(config_path: Path) -> None:
    """Validate a strategies YAML without running any trading flow.

    Calls the loader (ADR §6.2) and reports per-asset summary on success,
    or the validation error and exits with a non-zero status. Phase 0.5
    workflow: edit YAML → ``trading config validate --config x.yaml`` →
    iterate before running ``backtest`` / ``paper``.
    """
    from pydantic import ValidationError as _ValidationError

    from src.infrastructure.yaml_strategy_config_loader import (
        load_strategy_config as _load,
    )

    try:
        bundles = _load(config_path)
    except (ValueError, _ValidationError) as e:
        click.echo(f"Config invalid: {e}", err=True)
        raise click.exceptions.Exit(2) from e

    click.echo(f"Config valid: {len(bundles)} asset(s) in {config_path}")
    for code, bundle in bundles.items():
        reentry_summary = (
            f"{bundle.reentry_strategy_name}({bundle.reentry_parameters})"
        )
        click.echo(
            f"  {code}  {bundle.name}  enabled={bundle.enabled}\n"
            f"    buy={bundle.buy_strategy_name}  "
            f"drop={bundle.buy_config.drop_threshold_pct}%  "
            f"max_split={bundle.buy_config.max_split_count}  "
            f"per_split={bundle.buy_config.per_split_amount.amount}\n"
            f"    sell={bundle.sell_strategy_name}  "
            f"profit_target=+{bundle.sell_config.profit_target_pct}%  "
            f"max_sells_per_day={bundle.sell_config.max_sells_per_day}\n"
            f"    reentry={reentry_summary}"
        )


if __name__ == "__main__":
    main()
