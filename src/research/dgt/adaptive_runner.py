"""Phase 0.11.f — _DGTAdaptiveRunner (변동성 기반 동적 k).

ATR(N) 기반으로 grid spacing (k) 을 매 rebalance 시점마다 동적 조정.
변동성 높을 때 → k 넓어짐 → 연속 매수 방지.
변동성 낮을 때 → k 좁아짐 → 횡보 구간 거래 기회 확보.

Adaptive k 수식:
    atr_pct = ATR(N) / current_close
    k = clamp(atr_pct * multiplier, k_min, k_max)

공유 컴포넌트: _DGTConfig, _KoreanMarketCostModel, grid_levels_table1,
_DGTGridState, _DGTBacktestResult, _DGTTrade, _DGTSnapshot.

5th ring 격리 (src/research/) — inner ring 변경 zero.
Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from src.domain.models import Asset, Money, OHLCV
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot, _DGTTrade
from src.research.dgt.runner import _DGTConfig
from src.research.dgt.state import _DGTGridState


RebalanceMode = Literal["on_breach", "daily"]


@dataclass(frozen=True)
class _AdaptiveConfig:
    """Adaptive k parameters.

    - atr_period: ATR 계산 기간 (default 14)
    - multiplier: ATR% × multiplier = adaptive k (default 1.5)
    - k_min: k 하한 (default 0.02 = 2%)
    - k_max: k 상한 (default 0.10 = 10%)
    """
    atr_period: int = 14
    multiplier: Decimal = Decimal("1.5")
    k_min: Decimal = Decimal("0.02")
    k_max: Decimal = Decimal("0.10")


def _compute_atr(bars: list[OHLCV], period: int, end_idx: int) -> Decimal:
    """ATR(period) at end_idx (inclusive). Decimal-only.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    ATR = SMA of True Range over `period` bars.
    Returns Decimal("0") if insufficient data.
    """
    start = max(1, end_idx - period + 1)
    if start > end_idx or end_idx < 1:
        return Decimal("0")

    tr_sum = Decimal("0")
    count = 0
    for i in range(start, end_idx + 1):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        tr_sum += tr
        count += 1

    return tr_sum / Decimal(count) if count > 0 else Decimal("0")


@dataclass(frozen=True)
class _DGTAdaptiveRunner:
    """DGT runner with volatility-adaptive grid spacing (k).

    매 rebalance 시점마다 ATR 기반으로 k를 재계산하고 grid를 재생성.
    """

    cost_model: _KoreanMarketCostModel
    base_config: _DGTConfig
    adaptive: _AdaptiveConfig = _AdaptiveConfig()
    rebalance_mode: RebalanceMode = "daily"

    def _adaptive_k(self, bars: list[OHLCV], bar_idx: int, close: Decimal) -> Decimal:
        """현재 시점의 adaptive k 계산."""
        atr = _compute_atr(bars, self.adaptive.atr_period, bar_idx)
        if atr <= 0 or close <= 0:
            return self.base_config.k_ratio

        atr_pct = atr / close
        k = atr_pct * self.adaptive.multiplier
        # Clamp to [k_min, k_max]
        return max(self.adaptive.k_min, min(self.adaptive.k_max, k))

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

        reference = ohlcv[0].close
        initial_k = self._adaptive_k(ohlcv, 0, reference)
        levels = grid_levels_table1(
            n=self.base_config.grid_count,
            reference_price=reference,
            k=initial_k,
            levels_above=self.base_config.levels_above,
        )

        state = _DGTGridState(
            reference_price=reference,
            grid_levels=list(levels),
            cash=initial_capital.amount,
            holdings=Decimal("0"),
        )

        trades: list[_DGTTrade] = []
        snapshots: list[_DGTSnapshot] = []
        prev_close = reference

        for bar_idx, bar in enumerate(ohlcv):
            curr_close = bar.close

            # Grid crossing detection
            for level in levels:
                if prev_close < level <= curr_close:
                    trade = self._maybe_sell(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)
                elif curr_close <= level < prev_close:
                    trade = self._maybe_buy(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)

            # Rebalance check
            should_rebalance = False
            if self.rebalance_mode == "on_breach":
                should_rebalance = curr_close < levels[0] or curr_close > levels[-1]
            elif self.rebalance_mode == "daily":
                should_rebalance = True

            if should_rebalance:
                reference = curr_close
                current_k = self._adaptive_k(ohlcv, bar_idx, curr_close)
                levels = grid_levels_table1(
                    n=self.base_config.grid_count,
                    reference_price=reference,
                    k=current_k,
                    levels_above=self.base_config.levels_above,
                )
                state.reference_price = reference
                state.grid_levels = list(levels)

            snapshots.append(
                _DGTSnapshot(
                    trade_date=bar.trade_date,
                    cash=state.cash,
                    holdings=state.holdings,
                    close_price=curr_close,
                    total_value=state.cash + state.holdings * curr_close,
                )
            )
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
            reference_price=reference,
            grid_levels=list(levels),
            trades=trades,
            daily_snapshots=snapshots,
        )

    def _maybe_buy(
        self,
        state: _DGTGridState,
        asset: Asset,
        trade_date: date,
        level_price: Decimal,
    ) -> _DGTTrade | None:
        if level_price <= 0:
            return None
        allocation = state.cash / Decimal(self.base_config.grid_count + 1)
        if allocation <= 0:
            return None
        quantity = (allocation / level_price).quantize(Decimal("1"), rounding=ROUND_DOWN)
        if quantity <= 0:
            return None
        cost = self.cost_model.compute_buy_cost(
            price=level_price, quantity=quantity, asset=asset,
        )
        if cost.total_cost > state.cash:
            return None
        state.cash -= cost.total_cost
        state.holdings += quantity
        state.trades_count += 1
        return _DGTTrade(
            trade_date=trade_date,
            side="BUY",
            grid_level_price=level_price,
            quantity=quantity,
            rounded_price=cost.rounded_price,
            gross=cost.gross,
            tax=cost.tax,
            commission=cost.commission,
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
        quantity = (state.holdings / Decimal(self.base_config.grid_count + 1)).quantize(
            Decimal("1"), rounding=ROUND_DOWN,
        )
        if quantity <= 0:
            return None
        proceeds = self.cost_model.compute_sell_cost(
            price=level_price, quantity=quantity, asset=asset,
        )
        state.holdings -= quantity
        state.cash += proceeds.net_proceeds
        state.wallet += proceeds.net_proceeds - proceeds.gross
        state.trades_count += 1
        return _DGTTrade(
            trade_date=trade_date,
            side="SELL",
            grid_level_price=level_price,
            quantity=quantity,
            rounded_price=proceeds.rounded_price,
            gross=proceeds.gross,
            tax=proceeds.tax,
            commission=proceeds.commission,
            cash_delta=proceeds.net_proceeds,
        )
