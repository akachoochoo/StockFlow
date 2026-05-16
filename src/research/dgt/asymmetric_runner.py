"""Phase 0.11.g.3 — _AsymmetricGridRunner (INFORMATIONAL).

Asymmetric grid: sell levels spaced at wider intervals than buy levels.
Goal: reduce premature selling in uptrends while keeping tight buy grid.

Mechanism:
1. Buy grid: standard k spacing (ADR-based)
2. Sell grid: k_sell = k_buy * sell_multiplier (wider spacing)
3. Optional trailing stop: once price passes a sell level, track HWM
   and only sell when price drops trailing_pct from HWM.

INFORMATIONAL: breaks DGT symmetric spacing invariant.
Time-boxed. MDD 18% hard stop (if breached, mark as invalidated).

5th ring research-only. Underscore-prefix private.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from src.domain.models import Asset, Money, OHLCV
from src.research.dgt.adaptive_runner import _AdaptiveConfig, _compute_adr
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot, _DGTTrade
from src.research.dgt.runner import _DGTConfig
from src.research.dgt.state import _DGTGridState


@dataclass
class _TrailingState:
    """Trailing stop state per position.

    Tracks high-water mark after a sell level is crossed upward.
    Sell triggers when price drops trailing_pct from HWM.
    """

    high_water_mark: Decimal = Decimal("0")
    trailing_pct: Decimal = Decimal("0.05")  # 5% trailing stop
    activated: bool = False
    activation_level: Decimal = Decimal("0")  # the sell level that was crossed

    def update(self, current_close: Decimal) -> tuple[bool, Decimal]:
        """Update HWM and check if trailing stop triggers.

        Returns (should_sell, sell_price).
        """
        if not self.activated:
            return False, Decimal("0")

        if current_close > self.high_water_mark:
            self.high_water_mark = current_close

        trail_price = self.high_water_mark * (Decimal("1") - self.trailing_pct)
        if current_close <= trail_price:
            self.activated = False
            self.high_water_mark = Decimal("0")
            return True, current_close

        return False, Decimal("0")

    def activate(self, level_price: Decimal, current_close: Decimal) -> None:
        """Activate trailing stop when price crosses a sell level."""
        self.activated = True
        self.activation_level = level_price
        self.high_water_mark = current_close


def _grid_levels_asymmetric(
    n: int,
    reference_price: Decimal,
    k_buy: Decimal,
    k_sell: Decimal,
    levels_above: int,
) -> tuple[list[Decimal], list[Decimal]]:
    """Generate asymmetric grid levels.

    Returns (buy_levels, sell_levels) separately.
    Buy levels use k_buy spacing below reference.
    Sell levels use k_sell spacing above reference.
    """
    levels_below = n - levels_above

    buy_levels: list[Decimal] = []
    for i in range(1, levels_below + 1):
        level = reference_price * (Decimal("1") - k_buy * Decimal(str(i)))
        if level > 0:
            buy_levels.append(level)
    buy_levels.sort()  # ascending

    sell_levels: list[Decimal] = []
    for i in range(1, levels_above + 1):
        level = reference_price * (Decimal("1") + k_sell * Decimal(str(i)))
        sell_levels.append(level)
    sell_levels.sort()  # ascending

    return buy_levels, sell_levels


@dataclass(frozen=True)
class _AsymmetricGridRunner:
    """Asymmetric grid DGT runner (INFORMATIONAL).

    sell_multiplier: sell grid spacing = k_buy * sell_multiplier.
    use_trailing: if True, sell levels trigger trailing stop instead of immediate sell.
    trailing_pct: trailing stop percentage (only used if use_trailing=True).
    """

    cost_model: _KoreanMarketCostModel
    config: _DGTConfig
    adaptive: _AdaptiveConfig = _AdaptiveConfig()
    sell_multiplier: Decimal = Decimal("2.0")  # sell spacing = 2x buy spacing
    use_trailing: bool = False
    trailing_pct: Decimal = Decimal("0.05")
    # Volume gate
    volume_gate: bool = True
    volume_gate_period: int = 10
    volume_gate_multiplier: Decimal = Decimal("1.5")

    def run(
        self,
        asset: Asset,
        start: date,
        end: date,
        initial_capital: Money,
        ohlcv: list[OHLCV],
    ) -> _DGTBacktestResult:
        if not ohlcv:
            raise ValueError("ohlcv must be non-empty")

        n = self.config.grid_count
        m = n // 2
        first_close = ohlcv[0].close
        k_buy = self._adaptive_k(ohlcv, 0, first_close)
        k_sell = k_buy * self.sell_multiplier

        buy_levels, sell_levels = _grid_levels_asymmetric(
            n=n, reference_price=first_close, k_buy=k_buy, k_sell=k_sell, levels_above=m,
        )

        state = _DGTGridState(
            reference_price=first_close,
            grid_levels=buy_levels + sell_levels,  # combined for state tracking
            cash=initial_capital.amount,
            holdings=Decimal("0"),
        )

        trailing = _TrailingState(trailing_pct=self.trailing_pct)
        trades: list[_DGTTrade] = []
        snapshots: list[_DGTSnapshot] = []
        prev_close = first_close

        for bar_idx, bar in enumerate(ohlcv):
            curr_close = bar.close

            # Check trailing stop first
            if self.use_trailing and trailing.activated:
                should_sell, sell_price = trailing.update(curr_close)
                if should_sell and state.holdings > 0:
                    trade = self._maybe_sell(state, asset, bar.trade_date, sell_price)
                    if trade is not None:
                        trades.append(trade)

            # Volume gate
            skip_buy, skip_sell = self._check_volume_gate(ohlcv, bar_idx)

            # Sell level crossings (upward)
            if not skip_sell:
                for level in sell_levels:
                    if prev_close < level <= curr_close:
                        if self.use_trailing:
                            trailing.activate(level, curr_close)
                        else:
                            trade = self._maybe_sell(state, asset, bar.trade_date, level)
                            if trade is not None:
                                trades.append(trade)

            # Buy level crossings (downward)
            if not skip_buy:
                for level in reversed(buy_levels):
                    if curr_close <= level < prev_close:
                        trade = self._maybe_buy(state, asset, bar.trade_date, level)
                        if trade is not None:
                            trades.append(trade)

            # Daily grid reset
            k_buy = self._adaptive_k(ohlcv, bar_idx, curr_close)
            k_sell = k_buy * self.sell_multiplier
            buy_levels, sell_levels = _grid_levels_asymmetric(
                n=n, reference_price=curr_close, k_buy=k_buy, k_sell=k_sell, levels_above=m,
            )
            state.reference_price = curr_close
            state.grid_levels = buy_levels + sell_levels

            snapshots.append(_DGTSnapshot(
                trade_date=bar.trade_date,
                cash=state.cash,
                holdings=state.holdings,
                close_price=curr_close,
                total_value=state.cash + state.holdings * curr_close,
            ))
            prev_close = curr_close

        final_close = ohlcv[-1].close
        final_amount = state.cash + state.holdings * final_close
        return _DGTBacktestResult(
            asset=asset,
            start=start,
            end=end,
            initial_capital=initial_capital,
            final_cash=state.cash,
            final_holdings=state.holdings,
            final_close_price=final_close,
            final_balance=Money(amount=final_amount, currency=initial_capital.currency),
            wallet_total=state.wallet,
            reference_price=state.reference_price,
            grid_levels=state.grid_levels,
            trades=trades,
            daily_snapshots=snapshots,
        )

    def _adaptive_k(self, bars: list[OHLCV], bar_idx: int, close: Decimal) -> Decimal:
        adr = _compute_adr(bars, self.adaptive.atr_period, bar_idx)
        if adr <= 0 or close <= 0:
            return Decimal("0.01")
        atr_pct = adr / close
        k = atr_pct * self.adaptive.multiplier
        return max(self.adaptive.k_min, min(self.adaptive.k_max, k))

    def _check_volume_gate(
        self, bars: list[OHLCV], bar_idx: int,
    ) -> tuple[bool, bool]:
        if not self.volume_gate or bar_idx < self.volume_gate_period:
            return False, False
        start = bar_idx - self.volume_gate_period + 1
        vol_sum = sum(bars[i].volume for i in range(start, bar_idx + 1))
        vol_avg = vol_sum / Decimal(self.volume_gate_period)
        curr_vol = bars[bar_idx].volume
        if vol_avg <= 0 or curr_vol <= vol_avg * self.volume_gate_multiplier:
            return False, False
        prev_close = bars[bar_idx - 1].close if bar_idx > 0 else bars[bar_idx].close
        curr_close = bars[bar_idx].close
        if curr_close > prev_close:
            return False, True
        elif curr_close < prev_close:
            return True, False
        return False, False

    def _maybe_buy(
        self,
        state: _DGTGridState,
        asset: Asset,
        trade_date: date,
        level_price: Decimal,
    ) -> _DGTTrade | None:
        if level_price <= 0:
            return None
        allocation = state.cash / Decimal(self.config.grid_count + 1)
        if allocation <= 0:
            return None
        quantity = (allocation / level_price).quantize(Decimal("1"), rounding=ROUND_DOWN)
        if quantity <= 0:
            return None
        cost = self.cost_model.compute_buy_cost(price=level_price, quantity=quantity, asset=asset)
        if cost.total_cost > state.cash:
            return None
        state.cash -= cost.total_cost
        state.holdings += quantity
        state.trades_count += 1
        return _DGTTrade(
            trade_date=trade_date, side="BUY", grid_level_price=level_price,
            quantity=quantity, rounded_price=cost.rounded_price,
            gross=cost.gross, tax=cost.tax, commission=cost.commission,
            cash_delta=-cost.total_cost,
        )

    def _maybe_sell(
        self,
        state: _DGTGridState,
        asset: Asset,
        trade_date: date,
        level_price: Decimal,
    ) -> _DGTTrade | None:
        if state.holdings <= 0:
            return None
        quantity = (state.holdings / Decimal(self.config.grid_count + 1)).quantize(
            Decimal("1"), rounding=ROUND_DOWN,
        )
        if quantity <= 0:
            return None
        proceeds = self.cost_model.compute_sell_cost(price=level_price, quantity=quantity, asset=asset)
        state.holdings -= quantity
        state.cash += proceeds.net_proceeds
        state.wallet += proceeds.net_proceeds - proceeds.gross
        state.trades_count += 1
        return _DGTTrade(
            trade_date=trade_date, side="SELL", grid_level_price=level_price,
            quantity=quantity, rounded_price=proceeds.rounded_price,
            gross=proceeds.gross, tax=proceeds.tax, commission=proceeds.commission,
            cash_delta=proceeds.net_proceeds,
        )
