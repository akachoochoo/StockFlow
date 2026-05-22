"""Decision equivalence — backtest vs live Decision identity (Phase 1.1 Stage 6).

ADR 0012 §2.3 B2 / G2(d): a backtest and the live system must produce the
*same* Decision for the same inputs. "Same" is defined by a canonical
*projection* of the Decision down to its decision-relevant fields, deliberately
EXCLUDING fields that legitimately differ between a recorded backtest and a
live run:

    - ``timestamp``            — wall-clock of the evaluation
    - top-level ``reasoning``  — free-form context dict
    - per-action ``filled_price`` / ``order_id`` — live fill economics + broker
      ids that a backtest cannot reproduce identically

These excluded fields are simply absent from the projection, so they are
auto-excluded — there is no separate filtering step. ``target_price`` IS
compared, normalized through ``Asset.round_to_tick`` so a live tick-rounded
price matches the backtest's tick-rounded price (``filled_price`` stays
excluded).

Determinism premise: equivalence assumes the live evaluation reuses the
*recorded* live close price (no re-fetch) so that backtest and live see the
same price input.

Layering (CLAUDE.md §1.1): this use-case imports only the domain (Decision /
Asset, inward dependency). It does NOT import adapters or cli. Monitoring
integration (alerting on divergence) is Stage 8.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

    from src.domain.models import Decision, SkipReason

# Canonical projection type: (skip_reason, sorted sell tuples, optional buy tuple).
_SellProjection = tuple[tuple[int, "Decimal"], ...]
_BuyProjection = tuple[int, int, "Decimal", "Decimal"] | None
_DecisionProjection = tuple["SkipReason | None", _SellProjection, _BuyProjection]


def decision_projection(d: Decision) -> _DecisionProjection:
    """Project ``d`` to its canonical decision-relevant fields (ADR §2.3 B2).

    Returns a tuple of:
        (
          skip_reason,
          sorted ((slot_number, filled_quantity) for each sell action),
          None if no buy else
            (slot_number, split_level_after, filled_quantity,
             asset.round_to_tick(target_price)),
        )

    Excluded (and therefore auto-excluded from equivalence): timestamp,
    top-level reasoning, per-action filled_price / order_id. Sell actions are
    canonically sorted so ordering differences do not affect equivalence.
    """
    return (
        d.skip_reason,
        tuple(
            sorted(
                (s.slot_number, s.filled_quantity) for s in d.sell_actions
            )
        ),
        None
        if d.buy_action is None
        else (
            d.buy_action.slot_number,
            d.buy_action.split_level_after,
            d.buy_action.filled_quantity,
            d.asset.round_to_tick(d.buy_action.target_price),
        ),
    )


def decisions_equivalent(a: Decision, b: Decision) -> bool:
    """True when ``a`` and ``b`` project to the same canonical decision.

    ADR 0012 §2.3 B2 / G2(d) — backtest vs live Decision identity. Two
    Decisions that differ only in timestamp / reasoning / per-action
    filled_price / order_id are equivalent (those fields are excluded from the
    projection).
    """
    return decision_projection(a) == decision_projection(b)
