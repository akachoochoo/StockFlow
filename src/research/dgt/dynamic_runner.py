"""Phase 0.11.f — _DGTDynamicRunner (grid rebalancing 지원).

기존 _DGTPrototypeRunner (static grid) 와 동일한 DGT 알고리즘이지만,
가격이 grid 범위를 이탈하거나 매일(bar마다) grid를 재구성하는 옵션 지원.

Rebalance modes:
- "on_breach": 종가가 grid 최소/최대 레벨 밖으로 이탈 시에만 rebalance
- "daily": 매 bar 종가 기준으로 grid 재생성

Rebalance 시 reference_price = 현재 종가, grid_levels 재생성.
cash/holdings 상태는 유지 (grid만 재구성).

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
class _DGTDynamicRunner:
    """DGT runner with grid rebalancing.

    _DGTPrototypeRunner 와 동일한 매수/매도 로직이지만, run loop 에서
    grid rebalancing 을 수행.
    """

    cost_model: _KoreanMarketCostModel
    config: _DGTConfig
    rebalance_mode: RebalanceMode = "on_breach"

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
        levels = grid_levels_table1(
            n=self.config.grid_count,
            reference_price=reference,
            k=self.config.k_ratio,
            levels_above=self.config.levels_above,
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

        for bar in ohlcv:
            curr_close = bar.close

            # Grid crossing detection (current levels)
            for level in levels:
                if prev_close < level <= curr_close:
                    trade = self._maybe_sell(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)
                elif curr_close <= level < prev_close:
                    trade = self._maybe_buy(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)

            # Rebalance check (after trades, before snapshot)
            should_rebalance = False
            if self.rebalance_mode == "on_breach":
                grid_min = levels[0]
                grid_max = levels[-1]
                should_rebalance = curr_close < grid_min or curr_close > grid_max
            elif self.rebalance_mode == "daily":
                should_rebalance = True

            if should_rebalance:
                reference = curr_close
                levels = grid_levels_table1(
                    n=self.config.grid_count,
                    reference_price=reference,
                    k=self.config.k_ratio,
                    levels_above=self.config.levels_above,
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
        allocation = state.cash / Decimal(self.config.grid_count + 1)
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
        quantity = (state.holdings / Decimal(self.config.grid_count + 1)).quantize(
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
