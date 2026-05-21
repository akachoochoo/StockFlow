"""Phase 0.11.j — Grid-envelope reconstruction helper (5th ring, underscore-private).

Single source of truth for per-bar DGT grid reconstruction used by:
  - static matplotlib path (_draw_grid_levels in kakao_dgt_backtest.py)
  - interactive chart path (kakao interactive builders, Step 5)

ADR 0017 Decision (i-A): extracted from _draw_grid_levels to prevent
divergent reconstructions. The ADR-measure branch (Step 1b) is applied
here once; both callers inherit the correction automatically.

Namespace: 5th ring — src/research/dgt/. Inner ring import = ZERO.
"""
from __future__ import annotations

__all__: list[str] = []

from datetime import date
from decimal import Decimal

from src.domain.models import OHLCV
from src.research.dgt.adaptive_runner import (
    _AdaptiveConfig,
    _compute_adr,
    _compute_atr,
)
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.results import _DGTBacktestResult
from src.research.dgt.runner import _DGTConfig


def _reconstruct_grid_envelope(
    result: _DGTBacktestResult,
    config: _DGTConfig,
    mode: str,
    ohlcv_bars: list[OHLCV] | None = None,
    adaptive_cfg: _AdaptiveConfig | None = None,
    volatility_measure: str = "atr",
) -> list[list[Decimal]]:
    """Per-bar grid levels (n+1 Decimal each), replaying rebalancing.

    Returns [] for mode == 'bh' or empty snapshots.
    len(return value) == len(result.daily_snapshots).

    Parameters
    ----------
    result:
        Backtest result whose daily_snapshots drive the reconstruction.
    config:
        DGT parameters (n, k, m).
    mode:
        Runner mode string — e.g. 'static', 'on_breach', 'daily',
        'adaptive', 'paper', 'paper_adaptive', 'paper_adaptive_daily', 'bh'.
    ohlcv_bars:
        OHLCV bars required for adaptive modes (ATR / ADR computation).
    adaptive_cfg:
        Adaptive k config; required for adaptive modes.
    volatility_measure:
        'atr' (default) or 'adr'. Selects the volatility function used
        to compute adaptive k. Step 1b: ADR branch added (ADR-0017-recorded
        intentional behaviour change for ADR-labelled strategies).
        'atr' path preserves Step 1 golden values exactly.
    """
    snapshots = result.daily_snapshots
    if not snapshots or mode == "bh":
        return []

    ref = snapshots[0].close_price
    k = config.k_ratio
    # Paper modes use symmetric placement (m = n//2); others use config.levels_above
    m = (
        config.grid_count // 2
        if mode in ("paper", "paper_adaptive")
        else config.levels_above
    )
    levels = grid_levels_table1(
        n=config.grid_count,
        reference_price=ref,
        k=k,
        levels_above=m,
    )

    envelope: list[list[Decimal]] = []
    for bar_idx, snap in enumerate(snapshots):
        close = snap.close_price
        should_rebalance = False
        if mode in ("on_breach", "paper", "paper_adaptive"):
            should_rebalance = close < levels[0] or close > levels[-1]
        elif mode in ("daily", "adaptive", "paper_adaptive_daily"):
            should_rebalance = True

        if should_rebalance:
            ref = close
            if mode in ("paper", "paper_adaptive", "paper_adaptive_daily"):
                m = config.grid_count // 2  # re-symmetrize on reset
            if (
                mode in ("adaptive", "paper_adaptive", "paper_adaptive_daily",
                         "on_breach")
                and ohlcv_bars
                and adaptive_cfg
            ):
                # Step 1b: ADR-measure branch (ADR-0017-recorded correction).
                # volatility_measure="adr" uses _compute_adr (ignores overnight
                # gaps → tighter range → smaller k in uptrends).
                # volatility_measure="atr" preserves Step 1 golden values.
                if volatility_measure == "adr":
                    vol = _compute_adr(ohlcv_bars, adaptive_cfg.atr_period, bar_idx)
                else:
                    vol = _compute_atr(ohlcv_bars, adaptive_cfg.atr_period, bar_idx)

                if vol > 0 and close > 0:
                    vol_pct = vol / close
                    k = max(
                        adaptive_cfg.k_min,
                        min(adaptive_cfg.k_max, vol_pct * adaptive_cfg.multiplier),
                    )
            levels = grid_levels_table1(
                n=config.grid_count,
                reference_price=ref,
                k=k,
                levels_above=m,
            )
        envelope.append(list(levels))

    return envelope
