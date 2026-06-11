"""Strategy factory functions — composition helpers for buy strategy dispatch.

Moved from src/cli/composition.py so that src/application/backtest_runner.py
can import them without crossing into the cli ring (ADR clean-arch fix).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.models import SplitSlot, SupportSlot
from src.domain.strategies.price_drop import PriceDropStrategy, SplitStrategyConfig
from src.domain.strategies.profit_target import ProfitTargetSell, SellStrategyConfig
from src.domain.strategies.reentry import create_reentry_strategy
from src.domain.strategies.support_level import SupportLevelStrategy
from src.use_cases.asset_context import AssetContext

if TYPE_CHECKING:
    from src.domain.models import Asset
    from src.ports.market_data import MarketDataPort
    from src.ports.reentry_strategy import ReentryPriceStrategyPort
    from src.use_cases.asset_context import AssetPolicyOverride


def create_buy_strategy(
    name: str,
    *,
    reentry: ReentryPriceStrategyPort | None = None,
) -> PriceDropStrategy | SupportLevelStrategy:
    """Composition factory for buy strategies (ADR 0004 §5.2).

    yaml ``buy_strategy`` field dispatches here:
        - ``price_drop`` → ``PriceDropStrategy(reentry=...)`` (Phase 0~0.7)
        - ``support_level`` → ``SupportLevelStrategy()`` (Phase 0.8+)

    SupportLevelStrategy doesn't take a reentry policy (ADR §4.3 β-2 —
    each slot's trigger is its own indicator condition). ``reentry``
    parameter is required for ``price_drop`` and ignored for
    ``support_level``.
    """
    if name == "price_drop":
        if reentry is None:
            raise ValueError(
                "buy_strategy 'price_drop' requires reentry policy"
            )
        return PriceDropStrategy(reentry=reentry)
    if name == "support_level":
        return SupportLevelStrategy()
    raise ValueError(
        f"unknown buy_strategy {name!r}; "
        "expected 'price_drop' or 'support_level'"
    )


def slot_model_for_buy_strategy(
    name: str,
) -> type[SplitSlot] | type[SupportSlot]:
    """Slot model dispatch for ``MockBroker`` (ADR 0004 §5.6).

    Phase 0.8 (B-1, ADR §1.3): a Position's slot model is determined by
    the buy strategy. yaml ``buy_strategy`` field selects the slot type.
    """
    if name == "price_drop":
        return SplitSlot
    if name == "support_level":
        return SupportSlot
    raise ValueError(
        f"unknown buy_strategy {name!r}; "
        "expected 'price_drop' or 'support_level'"
    )


def build_asset_contexts(
    *,
    assets: list[Asset],
    buy_strategy_name: str,
    reentry_strategy_name: str,
    market_data: MarketDataPort,
    buy_config: SplitStrategyConfig,
    sell_config: SellStrategyConfig,
    reentry_parameters: dict[str, Any],
    per_asset_overrides: dict[str, AssetPolicyOverride] | None = None,
) -> list[AssetContext]:
    """Build one AssetContext per asset (Phase 1.1 per-asset params, Case A).

    ``per_asset_overrides`` (keyed by ``asset.code``) supplies per-asset
    buy/sell/reentry **parameters** when set; the strategy *types*
    (``buy_strategy_name`` / ``reentry_strategy_name`` / profit_target) stay
    uniform. When None, every asset uses the shared default configs (the
    Phase 0.7.1 broadcast — strategies are stateless, so per-asset instances
    are byte-identical in behaviour). Reentry/buy strategy instances are built
    per asset so each can carry its own reentry parameters.
    """
    if per_asset_overrides is not None:
        expected = {a.code for a in assets}
        if set(per_asset_overrides) != expected:
            raise ValueError(
                "per_asset_overrides keys must match asset codes exactly: "
                f"expected {sorted(expected)}, got {sorted(per_asset_overrides)}"
            )

    contexts: list[AssetContext] = []
    for asset in assets:
        override = (
            per_asset_overrides.get(asset.code)
            if per_asset_overrides is not None
            else None
        )
        eff_buy = override.buy_config if override is not None else buy_config
        eff_sell = override.sell_config if override is not None else sell_config
        eff_reentry_params = (
            override.reentry_parameters
            if override is not None
            else reentry_parameters
        )
        reentry = (
            create_reentry_strategy(
                reentry_strategy_name,
                market_data=market_data,
                **eff_reentry_params,
            )
            if buy_strategy_name == "price_drop"
            else None
        )
        contexts.append(
            AssetContext(
                asset=asset,
                strategy=create_buy_strategy(buy_strategy_name, reentry=reentry),
                config=eff_buy,
                sell_strategy=ProfitTargetSell(),
                sell_config=eff_sell,
            )
        )
    return contexts
