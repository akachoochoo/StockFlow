"""AssetContext — per-asset bundle for multi-asset orchestration.

Phase 0.7.1 / ADR 0003 §8.2 박제. Bundles every per-asset dependency
(asset, buy strategy + config, sell strategy + config) into a single
frozen dataclass so the orchestrator's ``list[AssetContext]`` shape can
iterate cleanly while preserving each asset's independent policy.

Phase 0.7.1.a is a pure addition — no callers yet. 0.7.1.b wires this
into ``DailyOrchestrator`` (signature change + helper parameterisation
landed in one all-or-nothing commit per Phase 0.5 회고 §5.4.1 lesson).

Per ADR 0003 §7.3 (Phase 0.7.1 정신) every AssetContext in a single
orchestrator run must share the same buy/sell/reentry policy *type*
(only the ``asset`` differs across contexts). The YAML loader (0.7.1.c)
enforces this; the dataclass itself is policy-shape-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.models import Asset
    from src.domain.strategies.price_drop import (
        PriceDropStrategy,
        SplitStrategyConfig,
    )
    from src.domain.strategies.profit_target import SellStrategyConfig
    from src.ports.sell_strategy import SellStrategyPort


__all__ = ["AssetContext"]


@dataclass(frozen=True)
class AssetContext:
    """Per-asset dependency bundle for ``DailyOrchestrator``.

    Frozen so context identity is stable across a single orchestrator run
    (no in-flight policy mutation between assets). Construct one
    ``AssetContext`` per asset at composition time; the orchestrator
    iterates ``list[AssetContext]`` in declaration order — that order is
    the §5.1 priority for same-day buy-trigger collisions.
    """

    asset: Asset
    strategy: PriceDropStrategy
    config: SplitStrategyConfig
    sell_strategy: SellStrategyPort
    sell_config: SellStrategyConfig
