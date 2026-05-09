"""StrategyInfo view model for backtest reporting (Phase 0.10.y — ADR 0006 §15.5).

Application-layer view model — NOT a domain entity, NOT a Protocol member.
Mirrors ``TradeView`` pattern (frozen dataclass, in-memory only, no
persistence) per ADR 0006 §3.2 박제.

Frozen contract surface (Patch S2): the factory ``from_strategy_bundle``
explicitly enumerates the bundle field names it reads. Phase 1+ ADR 0007
must consciously update the docstring + factory + tests if new bundle
fields (e.g. tax_config / commission_config / partial-fill policy) need
to surface in the report.

NO ``asset_uniformity`` field — yaml ``_RootSchema._check_policy_uniformity``
already enforces uniformity at load time (loader-enforced precondition).
Multi-strategy / per-asset wiring is Phase 1+ ADR 0007 trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from src.infrastructure.yaml_strategy_config_loader import (
        AssetStrategyBundle,
    )


def _fmt_pct(value: Decimal, *, places: int = 2) -> str:
    """Decimal % → "5.00%" (places-bounded, ROUND_HALF_UP).

    Inlined here (no adapter import) to preserve Clean Architecture
    application/reporting/ ← adapters/reporting/ forbidden direction
    (ADR 0006 §8 dependency diagram).
    """
    quant = (
        Decimal("1") if places <= 0
        else Decimal("0." + ("0" * (places - 1)) + "1")
    )
    return f"{value.quantize(quant, rounding=ROUND_HALF_UP):,.{places}f}%"


def _fmt_money(amount: Decimal, currency: str) -> str:
    """Decimal money → "₩5,000,000" (KRW) or "USD 5,000.00" (other).

    Inlined here (no adapter import) per ADR 0006 §8.
    """
    if currency == "KRW":
        whole = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return f"₩{whole:,}"
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{currency} {quantized:,.2f}"


@dataclass(frozen=True)
class StrategyInfo:
    """전략 정보 view model — single-strategy assumption (loader-enforced).

    Fields:
        buy_strategy_name: e.g. ``"price_drop"``
        buy_parameters: pre-formatted str values (already display-ready —
            ``"5.0%"``, ``"₩5,000,000"``, etc.). Caller (factory) handles
            Decimal/Money → str conversion via formatters.
        sell_strategy_name: e.g. ``"profit_target"``
        sell_parameters: pre-formatted str values
        reentry_strategy_name: e.g. ``"hybrid"``, ``"moving_average"``
        reentry_parameters: pre-formatted str values
        config_source: yaml path string
            (e.g. ``"config/strategies-0.9.2.yaml"``)
        asset_codes: sorted list of enabled asset codes (loader-enforced
            uniform policy)
    """

    buy_strategy_name: str
    buy_parameters: dict[str, str]
    sell_strategy_name: str
    sell_parameters: dict[str, str]
    reentry_strategy_name: str
    reentry_parameters: dict[str, str]
    config_source: str
    asset_codes: tuple[str, ...]


def from_strategy_bundle(
    bundle: AssetStrategyBundle,
    config_source: str | Path,
    *,
    asset_codes: Mapping[str, object] | None = None,
) -> StrategyInfo:
    """Build a StrategyInfo from one ``AssetStrategyBundle`` (loader-enforced uniform).

    **Frozen contract surface (Phase 0.10.y §15.5 / Patch S2)**: this factory
    reads exactly these bundle attributes. Phase 1+ ADR 0007 must
    consciously update the list when adding new bundle fields:

    - ``bundle.buy_strategy_name``
    - ``bundle.buy_config`` — `SplitStrategyConfig` (drop_threshold_pct,
      max_split_count, per_split_amount [Money], max_split_per_day,
      max_loss_pct)
    - ``bundle.sell_strategy_name``
    - ``bundle.sell_config`` — `SellStrategyConfig` (profit_target_pct,
      max_sells_per_day)
    - ``bundle.reentry_strategy_name``
    - ``bundle.reentry_parameters`` — `dict[str, Any]`

    Args:
        bundle: One representative bundle (loader's ``_check_policy_uniformity``
            guarantees all enabled assets share identical policy).
        config_source: yaml path (str or Path; converted to str for display).
        asset_codes: optional mapping of all enabled asset codes — used to
            populate ``StrategyInfo.asset_codes``. None → tuple of just
            ``(bundle.code,)``.

    Returns:
        StrategyInfo with display-ready parameter strings.
    """
    return StrategyInfo(
        buy_strategy_name=bundle.buy_strategy_name,
        buy_parameters=_format_buy_parameters(bundle.buy_config),
        sell_strategy_name=bundle.sell_strategy_name,
        sell_parameters=_format_sell_parameters(bundle.sell_config),
        reentry_strategy_name=bundle.reentry_strategy_name,
        reentry_parameters=_format_reentry_parameters(
            bundle.reentry_parameters,
        ),
        config_source=str(config_source),
        asset_codes=(
            tuple(sorted(asset_codes.keys()))
            if asset_codes is not None
            else (bundle.code,)
        ),
    )


def _format_buy_parameters(config: object) -> dict[str, str]:
    """SplitStrategyConfig → display-ready dict[str, str]."""
    out: dict[str, str] = {}
    drop = getattr(config, "drop_threshold_pct", None)
    if isinstance(drop, Decimal):
        out["drop_threshold_pct"] = _fmt_pct(drop)
    max_split = getattr(config, "max_split_count", None)
    if max_split is not None:
        out["max_split_count"] = str(max_split)
    per_split = getattr(config, "per_split_amount", None)
    if per_split is not None:
        amount = getattr(per_split, "amount", None)
        currency = getattr(per_split, "currency", None)
        currency_code = getattr(currency, "value", None) or "KRW"
        if isinstance(amount, Decimal):
            out["per_split_amount"] = _fmt_money(amount, currency_code)
    max_per_day = getattr(config, "max_split_per_day", None)
    if max_per_day is not None:
        out["max_split_per_day"] = str(max_per_day)
    max_loss = getattr(config, "max_loss_pct", None)
    if isinstance(max_loss, Decimal):
        out["max_loss_pct"] = _fmt_pct(max_loss)
    return out


def _format_sell_parameters(config: object) -> dict[str, str]:
    """SellStrategyConfig → display-ready dict[str, str]."""
    out: dict[str, str] = {}
    target = getattr(config, "profit_target_pct", None)
    if isinstance(target, Decimal):
        out["profit_target_pct"] = _fmt_pct(target)
    max_sells = getattr(config, "max_sells_per_day", None)
    if max_sells is not None:
        out["max_sells_per_day"] = str(max_sells)
    return out


def _format_reentry_parameters(params: Mapping[str, object]) -> dict[str, str]:
    """reentry_parameters dict → display-ready dict[str, str]."""
    out: dict[str, str] = {}
    for key, value in params.items():
        if isinstance(value, Decimal):
            out[key] = str(value)
        else:
            out[key] = str(value)
    return out
