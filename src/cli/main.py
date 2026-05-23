"""Trading CLI — ``trading backtest`` and ``trading paper`` subcommands.

ADR §10.1 박제. Phase 0.7.1 multi-asset entry point. Both commands share
the kill-switch (CLAUDE.md §11.1) + lock-file (§10.2) safety wrap and the
same strategy-config flags. Composition is delegated to
``src.cli.composition`` so this module stays a thin parser/printer.

Multi-asset CSV mapping (0.7.1.f):
  --csv CODE=path.csv   maps asset code to CSV path (--config mode)
  --csv path.csv        single-asset backward compat (flag-only mode)
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
from src.use_cases.asset_context import AssetPolicyOverride

if TYPE_CHECKING:
    from datetime import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _krw(amount: int) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


def _parse_csv_paths(
    csv_values: tuple[str, ...],
) -> dict[str | None, Path]:
    """Parse --csv values into a {code_or_None: Path} mapping.

    Two forms are accepted:
      - ``path.csv``        — single-asset (flag-only) path; key = None.
      - ``CODE=path.csv``   — asset-code mapping (--config mode); key = CODE.

    Mixed forms raise click.UsageError. Multiple plain paths (no ``=``) also
    raise click.UsageError — only one is allowed in flag-only mode.
    """
    if not csv_values:
        # click required=True guards this; included for completeness.
        raise click.UsageError("At least one --csv value is required.")

    has_mapped = any("=" in v for v in csv_values)
    has_plain = any("=" not in v for v in csv_values)

    if has_mapped and has_plain:
        raise click.UsageError(
            "Cannot mix '--csv path' and '--csv CODE=path' forms. "
            "Use '--csv path.csv' for a single asset (flag-only mode) or "
            "'--csv CODE=path.csv' for each asset (--config mode)."
        )

    if has_plain:
        if len(csv_values) > 1:
            raise click.UsageError(
                "Flag-only mode accepts exactly one '--csv path.csv'. "
                "For multiple assets use '--csv CODE=path.csv' with --config."
            )
        p = Path(csv_values[0])
        if not p.exists():
            raise click.UsageError(f"CSV file does not exist: {p}")
        return {None: p}

    # CODE=path form
    result: dict[str | None, Path] = {}
    for v in csv_values:
        code, _, raw_path = v.partition("=")
        code = code.strip()
        raw_path = raw_path.strip()
        if not code or not raw_path:
            raise click.UsageError(
                f"Invalid --csv value {v!r}: expected CODE=path.csv"
            )
        p = Path(raw_path)
        if not p.exists():
            raise click.UsageError(
                f"CSV file does not exist for asset {code!r}: {p}"
            )
        if code in result:
            raise click.UsageError(
                f"Duplicate --csv mapping for asset code {code!r}."
            )
        result[code] = p
    return result


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


def _resolve_assets_and_bars(
    asset_codes: list[str],
    csv_map: dict[str | None, Path],
) -> tuple[list[Any], dict[Any, list[Any]]]:
    """Validate asset_codes vs csv_map and build (assets, ohlcv_by_asset).

    Two modes:
    - Flag-only (csv_map key = None): single asset, single CSV.
    - --config mode (csv_map keys = codes): asset codes must match YAML
      enabled codes exactly — missing or extra codes raise UsageError.
    """
    from src.domain.models import Asset  # noqa: F401 — type hint only

    if None in csv_map:
        # Flag-only mode: single asset.
        if len(asset_codes) != 1:
            raise click.UsageError(
                f"Flag-only '--csv path.csv' requires exactly one enabled "
                f"asset, but YAML has {len(asset_codes)}: {asset_codes}. "
                "Use '--csv CODE=path.csv' for each asset."
            )
        try:
            asset = composition.asset_from_code(asset_codes[0])
        except KeyError as e:
            raise click.UsageError(str(e)) from e
        bars = load_ohlcv_csv(csv_map[None], asset)
        return [asset], {asset: bars}

    # --config mode: CODE=path form.
    # At this point None is not in csv_map (handled above); all keys are str.
    csv_codes: set[str] = {k for k in csv_map if k is not None}
    yaml_set = set(asset_codes)
    if yaml_set != csv_codes:
        missing = yaml_set - csv_codes
        extra = csv_codes - yaml_set
        parts: list[str] = []
        if missing:
            parts.append(f"missing --csv for {sorted(missing)}")
        if extra:
            parts.append(f"extra --csv codes not in YAML {sorted(extra)}")
        raise click.UsageError(
            f"Asset codes mismatch: YAML enabled = {sorted(yaml_set)}, "
            f"--csv mappings = {sorted(csv_codes)}. "
            + "; ".join(parts) + "."
        )

    assets = []
    ohlcv_by_asset: dict[Any, list[Any]] = {}
    for code in asset_codes:  # preserve YAML order (ADR §5.1)
        try:
            asset = composition.asset_from_code(code)
        except KeyError as e:
            raise click.UsageError(str(e)) from e
        bars = load_ohlcv_csv(csv_map[code], asset)
        assets.append(asset)
        ohlcv_by_asset[asset] = bars
    return assets, ohlcv_by_asset


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
) -> tuple[list[str], SplitStrategyConfig, SellStrategyConfig, str, dict[str, Any]]:
    """Resolve strategy configs from either --config or flags.

    Returns ``(asset_codes, buy_config, sell_config, reentry_name,
    reentry_params)``.

    - ``asset_codes``: ordered list of enabled asset codes from YAML, or
      ``["069500"]`` for the flag-only (backward-compat) path.
    - Policy fields come from the first enabled bundle (uniformity
      validated by the YAML loader — ADR 0003 §7.3).

    Raises ``click.UsageError`` on conflict (--config + strategy flag) or
    moving_average requested without --config.
    """
    if config_path is not None:
        _check_mutually_exclusive_with_config(ctx)
        bundles = load_strategy_config(config_path)
        enabled_items = [
            (code, b) for code, b in bundles.items() if b.enabled
        ]
        if not enabled_items:
            raise click.UsageError(
                f"No enabled assets in {config_path}. "
                "Set enabled: true for at least one asset."
            )
        asset_codes = [code for code, _ in enabled_items]
        # Policy is uniform (loader validates); use first bundle's params.
        bundle = enabled_items[0][1]
        return (
            asset_codes,
            bundle.buy_config,
            bundle.sell_config,
            bundle.reentry_strategy_name,
            dict(bundle.reentry_parameters),
        )

    # Flag-only path: KODEX 200 backward compat (single asset).
    if reentry_strategy == "moving_average":
        raise click.UsageError(
            "--reentry-strategy moving_average requires --config (window / "
            "ma_type are not flag-exposed). The flag-only path supports "
            "hybrid only."
        )

    return (
        ["069500"],
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


def _resolve_per_asset_overrides(
    config_path: Path | None,
) -> dict[str, AssetPolicyOverride] | None:
    """Build per-asset overrides (keyed by code) from a --config YAML.

    Phase 1.1 Case A. Returns None for flag-only mode, a single enabled asset,
    or when all enabled bundles share identical policy params (broadcast —
    byte-identical regression). When enabled bundles' buy/sell/reentry params
    differ (allowed only with ``allow_per_asset_params: true``, which the loader
    already gated + TYPE-uniformity enforced), returns one AssetPolicyOverride
    per enabled asset.
    """
    if config_path is None:
        return None
    bundles = load_strategy_config(config_path)
    enabled = [(code, b) for code, b in bundles.items() if b.enabled]
    if len(enabled) <= 1:
        return None
    first = enabled[0][1]
    homogeneous = all(
        (b.buy_config, b.sell_config, b.reentry_parameters)
        == (first.buy_config, first.sell_config, first.reentry_parameters)
        for _, b in enabled[1:]
    )
    if homogeneous:
        return None
    return {
        code: AssetPolicyOverride(
            buy_config=b.buy_config,
            sell_config=b.sell_config,
            reentry_parameters=dict(b.reentry_parameters),
        )
        for code, b in enabled
    }


# ---------------------------------------------------------------------------
# Group + subcommands
# ---------------------------------------------------------------------------
# Operator-recovery commands must stay reachable while halted, otherwise a
# halt would lock out its own resume. Everything else (trading + utilities) is
# blocked by the entry-time halt check (fail-safe default).
_HALT_EXEMPT_SUBCOMMANDS: frozenset[str] = frozenset({"halt", "resume"})


@click.group()
@click.pass_context
def main(ctx: click.Context) -> None:
    """SevenSplit trading CLI (Phase 0, single-asset)."""
    safety.check_kill_switch()
    if ctx.invoked_subcommand not in _HALT_EXEMPT_SUBCOMMANDS:
        safety.check_halt()


@main.command()
@click.option(
    "--csv",
    "csv_values",
    required=True,
    multiple=True,
    help=(
        "OHLCV CSV path(s). "
        "Flag-only mode: '--csv path.csv' (single asset). "
        "--config mode: '--csv CODE=path.csv' for each enabled asset."
    ),
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
    csv_values: tuple[str, ...],
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
    """Replay historical OHLCV through the strategy + mock adapters."""
    with safety.lock_file():
        asset_codes, buy_config, sell_config, reentry_name, reentry_params = (
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
            )
        )
        csv_map = _parse_csv_paths(csv_values)
        assets, ohlcv_by_asset = _resolve_assets_and_bars(
            asset_codes, csv_map
        )
        runner = BacktestRunner(
            assets=assets,
            strategy_config=buy_config,
            sell_strategy_config=sell_config,
            reentry_strategy_name=reentry_name,
            reentry_parameters=reentry_params,
            initial_capital=_krw(capital),
            ohlcv_by_asset=ohlcv_by_asset,
            per_asset_overrides=_resolve_per_asset_overrides(config_path),
        )
        result = runner.run(start_date.date(), end_date.date())
    click.echo(output_formatter.format_backtest_result(result, as_json=as_json))


@main.command()
@click.option(
    "--csv",
    "csv_values",
    required=True,
    multiple=True,
    help=(
        "OHLCV CSV path(s). "
        "Flag-only mode: '--csv path.csv' (single asset). "
        "--config mode: '--csv CODE=path.csv' for each enabled asset."
    ),
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
    csv_values: tuple[str, ...],
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
        # CLAUDE.md §3.3 — verify clock sync before any live trade. Fail-closed
        # (raises ClockSkewError → halt). Backtest skips this (historical data).
        safety.verify_ntp_sync()
        asset_codes, buy_config, sell_config, reentry_name, reentry_params = (
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
            )
        )
        csv_map = _parse_csv_paths(csv_values)
        assets, bars_by_asset = _resolve_assets_and_bars(
            asset_codes, csv_map
        )
        decision_at = composition.utc_for(today, time(9, 0))
        snapshot_at = composition.utc_for(today, time(16, 0))
        components = composition.build_paper_components(
            assets=assets,
            bars_by_asset=bars_by_asset,
            db_path=db_path,
            initial_capital=_krw(capital),
            strategy_config=buy_config,
            sell_strategy_config=sell_config,
            reentry_strategy_name=reentry_name,
            reentry_parameters=reentry_params,
            initial_clock=decision_at,
            per_asset_overrides=_resolve_per_asset_overrides(config_path),
        )
        try:
            decisions = components.orchestrator.run_for_date(today)
            # Single-asset: decisions[0]; multi-asset: first asset's decision
            # (paper formatter only shows one decision — Phase 0.7.1 scope).
            decision = decisions[0]
            components.set_clock(snapshot_at)
            snapshot = components.snapshot_builder.build_and_save(today)
        finally:
            components.close()
    click.echo(
        output_formatter.format_paper_decision(decision, snapshot, as_json=as_json)
    )


@main.command("kis-check")
@click.option(
    "--code",
    default="069500",
    show_default=True,
    help="Asset code used to verify get_price (current quote).",
)
def kis_check(code: str) -> None:
    """Read-only KIS connectivity smoke test (Phase 1.1 Stage 2.3).

    Verifies the ``.env`` credentials + 모의투자 (VTS) server reachability by
    issuing a token and three READ calls — balance / holdings / current price.
    **Zero orders** (KISBroker has no write surface) and **zero state change**:
    no DB, no lock file (read-only diagnostic). The NTP gate is intentionally
    NOT invoked — this is a connectivity check, not a trade.

    Output prints the trading mode / host / masked appkey so the operator can
    confirm a 모의투자 (VTS) connection; the appsecret and access token are
    NEVER printed (CLAUDE.md §8.3 / ADR 0012 R10).
    """
    from datetime import UTC, datetime

    from src.adapters.kis._client import KISApiError
    from src.adapters.kis.auth import KISAuthError
    from src.domain.exceptions import (
        BrokerConnectionError,
        ConfigurationError,
        DataIntegrityError,
        MarketDataUnavailableError,
    )

    try:
        components = composition.build_kis_read_components()
    except ConfigurationError as exc:
        click.echo(
            f"KIS config error — set the missing key(s) in .env "
            f"(see .env.example): {exc}",
            err=True,
        )
        raise click.exceptions.Exit(1) from exc

    config = components.config
    click.echo(
        f"KIS mode={config.mode.value} host={config.base_url} "
        f"appkey={config.masked_appkey}"
    )

    try:
        balance = components.broker.get_balance()
        click.echo(f"예수금(cash): {balance.cash.amount} {balance.cash.currency.value}")

        holdings = components.broker.get_holdings()
        click.echo(f"보유 종목 수(holdings): {len(holdings)}")
        for holding in holdings:
            click.echo(
                f"  {holding.asset_code}  qty={holding.quantity}  "
                f"avg_price={holding.avg_price}"
            )

        asset = composition.asset_from_code(code)
        price = components.market_data.get_price(asset, datetime.now(UTC))
        click.echo(f"현재가({asset.code}): {price.value} {asset.currency.value}")
    except KISAuthError as exc:
        click.echo(f"KIS auth failed (token issue): {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    except (BrokerConnectionError, KISApiError) as exc:
        click.echo(f"KIS balance/holdings query failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    except DataIntegrityError as exc:
        click.echo(f"KIS price integrity check failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    except MarketDataUnavailableError as exc:
        click.echo(f"KIS get_price failed: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc
    except KeyError as exc:
        # asset_from_code: unknown --code.
        click.echo(f"Unknown --code: {exc}", err=True)
        raise click.exceptions.Exit(1) from exc

    click.echo("✅ KIS read 연결 정상")


@main.command("reconcile")
@click.option(
    "--db",
    "db_path",
    default="trading.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="실거래 상태 SQLite DB path (created on first run). ⚠️ 실거래 상태 DB — "
    "dry-run.db(시뮬) 를 가리키지 말 것 (실계좌 0보유와 불일치 → 오halt).",
)
def reconcile(db_path: Path) -> None:
    """DB 포지션 vs 실 KIS 보유(get_holdings, read-only) 대조.

    불일치 시 영속 halt + 텔레그램 CRITICAL + 비정상 종료(자동수정 zero, §11.2).
    실주문 zero, 실계좌 read만. ⚠️ --db 는 실거래 상태 DB — dry-run.db(시뮬) 가리키지
    말 것(실계좌 0보유와 불일치 → 오halt).

    NTP 게이트는 호출하지 않음 (read-only 대조, 주문이 아님). lock file 은 잡는다
    (로컬 DB 상태 보호). 일치 시 ``✅ reconciliation matched`` exit 0; 불일치 시
    Reconciler 가 이미 notify + halt 한 뒤 ``StateMismatchError`` → 비정상 종료
    (자동 수정 zero, CLAUDE.md §11.2). 조사 후 ``trading resume`` 으로 재개.
    """
    from src.adapters.kis._client import KISApiError
    from src.adapters.kis.auth import KISAuthError
    from src.domain.exceptions import (
        BrokerConnectionError,
        ConfigurationError,
        StateMismatchError,
    )

    with safety.lock_file():
        # NTP 게이트 미호출: read-only 대조(get_holdings)이지 주문이 아님.
        try:
            reconciler, close, config = composition.build_reconciler(db_path)
        except ConfigurationError as exc:
            click.echo(
                f"KIS config error — set the missing key(s) in .env "
                f"(see .env.example): {exc}",
                err=True,
            )
            raise click.exceptions.Exit(1) from exc

        # mode / host (실보유 출처 확인) — never the secret.
        click.echo(
            f"KIS mode={config.mode.value} host={config.base_url} "
            f"appkey={config.masked_appkey}"
        )

        try:
            result = reconciler.reconcile()
        except StateMismatchError as exc:
            # Reconciler 가 이미 notify(CRITICAL) + halt(영속 sentinel) 함.
            click.echo(
                "❌ reconciliation 불일치 — 영속 halt 기록됨. 조사 후 "
                "`trading resume`. 자동수정 zero (CLAUDE.md §11.2).",
                err=True,
            )
            click.echo(f"  불일치 상세: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except KISAuthError as exc:
            click.echo(f"KIS auth failed (token issue): {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except (BrokerConnectionError, KISApiError) as exc:
            click.echo(f"KIS holdings query failed: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        finally:
            close()

    # result.matched is True here (mismatch raises above before reaching this).
    assert result.matched, "matched path reached with mismatches"
    click.echo("✅ reconciliation matched (DB positions = broker holdings)")


@main.command("dry-run")
@click.option(
    "--code",
    "codes",
    multiple=True,
    default=("069500", "132030"),
    show_default=True,
    help="Asset code(s) to evaluate (repeatable). Default = KODEX 200 + 골드.",
)
@click.option(
    "--db",
    "db_path",
    default="dry-run.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="SQLite DB path for the simulated broker state (created on first run).",
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
    "--date",
    "trade_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="KST trading date to evaluate (YYYY-MM-DD). Default = today (KST).",
)
@_strategy_options
@click.pass_context
def dry_run(
    ctx: click.Context,
    codes: tuple[str, ...],
    db_path: Path,
    capital: int,
    trade_date: datetime | None,
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
    """Paper-on-live dry run — live KIS quotes + simulated (Mock) fills.

    **This is NOT real trading.** Market data is the LIVE KIS server
    (``get_price`` / ``get_ohlcv`` read-only), but every order is filled by an
    in-memory ``MockBroker`` against a local SQLite balance — **zero real
    orders, zero real account access** (balance / holdings are the MockBroker's
    virtual state; the KIS account is never queried). Running successive days
    accumulates state in the SQLite DB so multi-day behaviour can be observed.

    Verified: live-quote integration + decision pipeline + simulated fills +
    multi-day state. NOT verified (limitation): the real KIS order-send / fill
    (write) path — that is gated separately (ADR 0012 D6, the 모의투자 server
    step this dry run substitutes for while VTS is unavailable).

    The NTP gate is intentionally NOT invoked — a dry run is a simulation, not
    a live trade. The lock file IS taken (it protects the local DB state).
    """
    from datetime import datetime as _dt

    from src.adapters.kis._client import KISApiError
    from src.adapters.kis.auth import KISAuthError
    from src.adapters.kis.config import KISConfig
    from src.adapters.telegram.notifier import build_notifier
    from src.domain.constants import KST
    from src.domain.exceptions import (
        BrokerConnectionError,
        ConfigurationError,
        DataIntegrityError,
        MarketDataUnavailableError,
    )
    from src.ports.notifications import NotificationLevel

    # Phase 1.1 default: 매도 +15% when the flag-only path is used and the
    # operator did not explicitly override --profit-target-pct (config mode
    # takes the YAML value verbatim; explicit flag wins over the default).
    if config_path is None:
        try:
            source = ctx.get_parameter_source("profit_target_pct")
        except KeyError:
            source = None
        if source is not ParameterSource.COMMANDLINE:
            profit_target_pct = "15.0"

    today = trade_date.date() if trade_date is not None else _dt.now(KST).date()

    with safety.lock_file():
        asset_codes, buy_config, sell_config, reentry_name, reentry_params = (
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
            )
        )
        # In flag-only mode _resolve_strategy_configs returns ["069500"]; the
        # dry-run command drives its own --code list instead (config mode still
        # binds the YAML-enabled codes, which the operator must match).
        effective_codes = (
            asset_codes if config_path is not None else list(codes)
        )
        try:
            assets = [composition.asset_from_code(c) for c in effective_codes]
        except KeyError as exc:
            click.echo(f"Unknown --code: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc

        try:
            # Resolve config once for the banner (mode / host — never secret),
            # then wire the read-only KIS market data adapter.
            kis_config = KISConfig.from_env()
            market_data = composition.build_kis_market_data()
        except ConfigurationError as exc:
            click.echo(
                f"KIS config error — set the missing key(s) in .env "
                f"(see .env.example): {exc}",
                err=True,
            )
            raise click.exceptions.Exit(1) from exc

        notifier = build_notifier()
        decision_at = composition.utc_for(today, time(9, 0))
        snapshot_at = composition.utc_for(today, time(16, 0))
        components = composition.build_paper_components(
            assets=assets,
            bars_by_asset={},
            db_path=db_path,
            initial_capital=_krw(capital),
            strategy_config=buy_config,
            sell_strategy_config=sell_config,
            reentry_strategy_name=reentry_name,
            reentry_parameters=reentry_params,
            initial_clock=decision_at,
            market_data=market_data,
            per_asset_overrides=_resolve_per_asset_overrides(config_path),
        )
        try:
            decisions = components.orchestrator.run_for_date(today)
            components.set_clock(snapshot_at)
            snapshot = components.snapshot_builder.build_and_save(today)
        except KISAuthError as exc:
            click.echo(f"KIS auth failed (token issue): {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except DataIntegrityError as exc:
            click.echo(f"KIS price integrity check failed: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except (
            MarketDataUnavailableError,
            BrokerConnectionError,
            KISApiError,
        ) as exc:
            click.echo(f"KIS market-data read failed: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        finally:
            components.close()

    # Banner + live-data source (host) — never the secret.
    click.echo("=" * 64)
    click.echo("DRY-RUN — 실주문 없음, 실계좌 미사용 (MockBroker 시뮬 체결)")
    click.echo("=" * 64)
    click.echo(
        f"mode=paper-on-live  market_data=KIS(mode={kis_config.mode.value} "
        f"host={kis_config.base_url})  date={today}"
    )

    # Notify + print each asset's intended decision (buy / sell / skip). The
    # orchestrator does not own a notifier; we notify at the command level so
    # its signature stays unchanged.
    for decision in decisions:
        kinds = " / ".join(decision.action_kinds())
        title = f"[DRY-RUN] {decision.asset.fqn}"
        body = f"intended: {kinds}"
        notifier.notify(level=NotificationLevel.INFO, title=title, body=body)
        click.echo(f"  {decision.asset.fqn}: intended {kinds}")

    click.echo(
        f"Cash (simulated): {snapshot.cash.amount} "
        f"{snapshot.cash.currency.value}"
    )
    click.echo(
        f"Total value (simulated): {snapshot.total_value.amount} "
        f"{snapshot.total_value.currency.value} "
        f"(return {snapshot.total_return_pct:.4f}%)"
    )
    if snapshot.valuations:
        click.echo("Positions (simulated):")
        for v in snapshot.valuations:
            click.echo(
                f"  {v.asset.fqn}  level={v.split_level}  qty={v.quantity}  "
                f"avg={v.avg_price}  mkt={v.market_price}  "
                f"PnL={v.unrealized_pnl.amount} ({v.unrealized_pnl_pct:.2f}%)"
            )


@main.command("live")
@click.option(
    "--code",
    "codes",
    multiple=True,
    default=("069500", "132030"),
    show_default=True,
    help="Asset code(s) to trade (repeatable). Default = KODEX 200 + 골드.",
)
@click.option(
    "--db",
    "db_path",
    default="trading.db",
    show_default=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="실거래 상태 SQLite DB path (created on first run).",
)
@click.option(
    "--date",
    "trade_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    default=None,
    help="KST trading date (YYYY-MM-DD). Default = today (KST).",
)
@click.option(
    "--tier",
    required=True,
    type=click.Choice(["200", "300", "500"]),
    help="Intended capital tier (만원, ADR 0012 D10). Must be ≤ --arm-live cap "
    "to place orders.",
)
@click.option(
    "--arm-live",
    "arm_tier",
    type=click.Choice(["200", "300", "500"]),
    default=None,
    help="ARM live orders up to this tier. Requires TRADING_ARM_LIVE=<tier> env "
    "too (double-confirm). Omit = no orders (settle + reconcile only).",
)
@click.option(
    "--max-loss-pct",
    default="20.0",
    show_default=True,
    help="Stop-loss breach alert threshold magnitude (ADR 0012 D2(b'); "
    "alert only, never auto-sells).",
)
@click.option(
    "--supervised-first-order",
    is_flag=True,
    default=False,
    help="Supervised first-order (ADR 0012 §2.5(b)): after this run places an "
    "order, write a halt sentinel so the NEXT run is blocked until you confirm "
    "the fill and run `trading resume`.",
)
@_strategy_options
@click.pass_context
def live(
    ctx: click.Context,
    codes: tuple[str, ...],
    db_path: Path,
    trade_date: datetime | None,
    tier: str,
    arm_tier: str | None,
    max_loss_pct: str,
    supervised_first_order: bool,
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
    """실거래 일일 runner — settle → reconcile → arm → decide (Phase 1.1 Stage 8).

    ⚠️ **실주문 진입점.** Real orders go out ONLY when armed: pass
    ``--arm-live <tier>`` AND set ``TRADING_ARM_LIVE=<tier>`` in the env
    (double-confirm), with the intended ``--tier`` ≤ the armed cap, plus NTP
    sync + no halt + today's reconciliation matched (the 5-AND arming gate,
    Stage 8-3). Without arming the run does settle + reconcile only and exits
    non-zero — **실주문 zero**.

    Order sequence is hard-coded (ADR 0012): settle (confirm prior PENDING
    fills) → reconcile (DB vs broker; mismatch halts) → arm gate → decide
    (place orders). A -max-loss-pct breach raises a Telegram/Console WARNING
    (사람 매도 검토 권고); it never auto-sells (CLAUDE.md §11.4).
    """
    import os
    from datetime import datetime as _dt

    from src.adapters.kis._client import KISApiError
    from src.adapters.kis.auth import KISAuthError
    from src.cli.live_gate import (
        LiveArmingError,
        assert_capital_within_tier,
        build_arming_token,
        capital_tier_from_str,
    )
    from src.cli.live_runner import run_live_pipeline
    from src.domain.constants import KST
    from src.domain.exceptions import (
        BrokerConnectionError,
        ClockSkewError,
        ConfigurationError,
        DataIntegrityError,
        MarketDataUnavailableError,
        StateMismatchError,
    )

    # Phase 1.1 default: 매도 +15% in flag-only mode unless explicitly overridden
    # (config mode takes the YAML value verbatim). Mirrors dry-run.
    if config_path is None:
        try:
            source = ctx.get_parameter_source("profit_target_pct")
        except KeyError:
            source = None
        if source is not ParameterSource.COMMANDLINE:
            profit_target_pct = "15.0"

    today = trade_date.date() if trade_date is not None else _dt.now(KST).date()
    intended_tier = capital_tier_from_str(tier)
    arm_token = build_arming_token(
        capital_tier_from_str(arm_tier) if arm_tier is not None else None,
        env=os.environ,
    )
    armed = arm_token is not None and arm_token.env_confirmed

    with safety.lock_file():
        # CLAUDE.md §3.3 — NTP gate before any live trade (fail-closed).
        try:
            safety.verify_ntp_sync()
        except ClockSkewError as exc:
            click.echo(
                f"❌ NTP 동기화 실패 — 실거래 거부 (fail-closed): {exc}", err=True
            )
            raise click.exceptions.Exit(1) from exc

        asset_codes, buy_config, sell_config, reentry_name, reentry_params = (
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
            )
        )
        effective_codes = (
            asset_codes if config_path is not None else list(codes)
        )
        try:
            assets = [composition.asset_from_code(c) for c in effective_codes]
        except KeyError as exc:
            click.echo(f"Unknown --code: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc

        per_asset_overrides = _resolve_per_asset_overrides(config_path)

        # D3 — per-asset 자본 과노출 방지 (armed 일 때만; 미무장이면 주문 zero라
        # 무관): sum(per_split_amount * max_split_count) <= intended tier KRW.
        if armed:
            cap_configs = (
                [per_asset_overrides[a.code].buy_config for a in assets]
                if per_asset_overrides is not None
                else [buy_config for _ in assets]
            )
            try:
                assert_capital_within_tier(
                    configs=cap_configs, intended_tier=intended_tier
                )
            except LiveArmingError as exc:
                click.echo(f"❌ 자본 과노출 — 실주문 거부: {exc}", err=True)
                raise click.exceptions.Exit(1) from exc

        try:
            components = composition.build_live_components(
                assets=assets,
                db_path=db_path,
                strategy_config=buy_config,
                sell_strategy_config=sell_config,
                reentry_strategy_name=reentry_name,
                reentry_parameters=reentry_params,
                per_asset_overrides=per_asset_overrides,
            )
        except ConfigurationError as exc:
            click.echo(
                f"KIS config error — set the missing key(s) in .env "
                f"(see .env.example): {exc}",
                err=True,
            )
            raise click.exceptions.Exit(1) from exc

        config = components.config
        click.echo("=" * 64)
        click.echo("LIVE — 실거래 runner (settle → reconcile → arm → decide)")
        click.echo("=" * 64)
        click.echo(
            f"KIS mode={config.mode.value} host={config.base_url} "
            f"appkey={config.masked_appkey}"
        )
        click.echo(
            f"date={today}  intended_tier={tier}만  "
            f"armed={'YES' if armed else 'NO (settle+reconcile only, 실주문 zero)'}"
        )

        def _orders_today_count() -> int:
            with components.uow_factory() as uow:
                return len(uow.orders.list_by_date(today))

        def _write_halt(reason: str) -> None:
            # Discard the returned Path so the signature is Callable[[str], None].
            safety.write_halt(reason)

        try:
            result = run_live_pipeline(
                settler=components.settler,
                reconciler=components.reconciler,
                orchestrator=components.orchestrator,
                position_source=components.position_source,
                notifier=components.notifier,
                today=today,
                intended_tier=intended_tier,
                arm_token=arm_token,
                halt_active=safety.is_halted(),
                ntp_synced=True,
                max_loss_pct=Decimal(max_loss_pct),
                supervised_first_order=supervised_first_order,
                orders_today_count=_orders_today_count,
                halt_writer=_write_halt,
            )
            click.echo(
                f"settled: buys={len(result.settle.settled_buys)} "
                f"sells={len(result.settle.settled_sells)} "
                f"still_pending={len(result.settle.still_pending_keys)}"
            )
            for decision in result.decisions:
                click.echo(
                    f"  {decision.asset.fqn}: "
                    f"{' / '.join(decision.action_kinds())}"
                )
            if result.stop_loss_breaches:
                click.echo("⚠️ 손절 임계 도달 (사람 매도 검토 권고):")
                for fqn, loss in result.stop_loss_breaches:
                    click.echo(f"  {fqn}: {loss:.2f}%")
            if result.supervised_hold:
                click.echo(
                    "🛑 supervised first-order — 첫 주문 후 halt 기록됨. 체결 확인 "
                    "후 `trading resume` 로 다음 run 허용."
                )
            click.echo("✅ live run 완료")
        except LiveArmingError as exc:
            click.echo(
                f"⚠️ 라이브 무장 안됨 — 실주문 zero (settle + reconcile 는 완료). "
                f"{exc}",
                err=True,
            )
            raise click.exceptions.Exit(1) from exc
        except ClockSkewError as exc:
            click.echo(f"❌ NTP 게이트 실패 — 실주문 거부: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except StateMismatchError as exc:
            click.echo(
                "❌ reconciliation 불일치 — 영속 halt 기록됨 (Reconciler). "
                "조사 후 `trading resume`. 자동수정 zero (CLAUDE.md §11.2).",
                err=True,
            )
            click.echo(f"  상세: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except KISAuthError as exc:
            click.echo(f"KIS auth failed (token issue): {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except (BrokerConnectionError, KISApiError) as exc:
            click.echo(f"KIS call failed: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except DataIntegrityError as exc:
            click.echo(f"KIS price integrity check failed: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        except MarketDataUnavailableError as exc:
            click.echo(f"KIS market-data unavailable: {exc}", err=True)
            raise click.exceptions.Exit(1) from exc
        finally:
            components.close()


@main.command("halt")
@click.option(
    "--reason",
    required=True,
    help="Why trading is being halted (recorded in the sentinel for audit).",
)
def halt(reason: str) -> None:
    """Write the persistent halt sentinel — blocks all commands until resume.

    Survives across cron processes (env vars do not). The first halt reason is
    preserved if a sentinel already exists (CLAUDE.md §11.2).
    """
    path = safety.write_halt(reason)
    if safety.halt_reason(path=path) == reason:
        click.echo(f"Trading HALTED. Sentinel: {path}\n  reason: {reason}")
    else:
        existing = safety.halt_reason(path=path)
        click.echo(
            f"Already halted (sentinel exists: {path}).\n"
            f"  preserved reason: {existing}"
        )


@main.command("resume")
def resume() -> None:
    """Clear the persistent halt sentinel (explicit human resume)."""
    path = safety.default_halt_path()
    was_halted = safety.is_halted(path=path)
    safety.clear_halt(path=path)
    if was_halted:
        click.echo(f"Trading RESUMED. Sentinel removed: {path}")
    else:
        click.echo(f"No halt sentinel present ({path}) — nothing to clear.")


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
