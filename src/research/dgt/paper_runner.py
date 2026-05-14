"""Phase 0.11.f -- _DGTPaperRunner (논문 충실 DGT).

Chen, Chen, Jang (2025, arXiv:2506.11921) S1.1 + S3.1 충실 구현.

기존 _DGTPrototypeRunner / _DGTDynamicRunner 와의 핵심 차이:

1. Interior reference tracking (S1.1.2):
   가격이 grid level 을 통과하면 해당 level 이 새 reference (black) 가 됨.
   기존 구현은 reference 고정 (reset 시에만 변경).

2. Dynamic m (S1.1.1):
   m (상단 grid 수) 은 가격 이동에 따라 변화.
   가격 상승 -> m 감소, 가격 하락 -> m 증가.
   기존 구현은 m = config.levels_above (고정).

3. Boundary breach reset (S3.1):
   가격이 Top/Bottom 경계 벗어날 때만 grid 재생성.
   Reset 시 m = n//2 로 재대칭화.
   Cash/holdings 는 그대로 유지 (비대칭 자연 상태).

4. Natural crossing order:
   UP move -> ascending order (낮은 level 먼저 sell).
   DOWN move -> descending order (높은 level 먼저 buy).

5th ring 격리 (src/research/) -- inner ring 변경 zero.
Underscore-prefix private (ADR 0007 S1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal

from src.domain.models import Asset, Money, OHLCV
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot, _DGTTrade
from src.research.dgt.runner import _DGTConfig
from src.research.dgt.state import _DGTGridState


@dataclass(frozen=True)
class _DGTPaperRunner:
    """Paper-faithful DGT runner (Chen, Chen, Jang 2025).

    기존 runner 들과의 차이:
    - config.levels_above 는 무시, 항상 m = n//2 로 시작 및 reset.
    - Interior crossing 시 reference 이동 (m 동적 변화).
    - Boundary breach 시에만 grid reset.
    - UP/DOWN crossing 을 자연 순서로 처리.
    """

    cost_model: _KoreanMarketCostModel
    config: _DGTConfig

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
        k = self.config.k_ratio
        reference = ohlcv[0].close
        m = n // 2  # Paper: initial symmetric

        levels = grid_levels_table1(
            n=n, reference_price=reference, k=k, levels_above=m,
        )

        state = _DGTGridState(
            reference_price=reference,
            grid_levels=list(levels),
            cash=initial_capital.amount,
            holdings=Decimal("0"),
        )

        trades: list[_DGTTrade] = []
        snapshots: list[_DGTSnapshot] = []
        upper_resets = 0
        lower_resets = 0
        prev_close = reference

        for bar in ohlcv:
            curr_close = bar.close

            # Collect crossed levels with natural ordering
            crossed_up: list[tuple[int, Decimal]] = []
            crossed_down: list[tuple[int, Decimal]] = []

            for i, level in enumerate(levels):
                if prev_close < level <= curr_close:
                    crossed_up.append((i, level))
                elif curr_close <= level < prev_close:
                    crossed_down.append((i, level))

            # Process UP crosses ascending (low -> high, natural price movement)
            for _i, level in crossed_up:
                trade = self._maybe_sell(state, asset, bar.trade_date, level)
                if trade is not None:
                    trades.append(trade)

            # Process DOWN crosses descending (high -> low, natural price movement)
            for _i, level in reversed(crossed_down):
                trade = self._maybe_buy(state, asset, bar.trade_date, level)
                if trade is not None:
                    trades.append(trade)

            # Update reference to last crossed level (paper S1.1.2)
            if crossed_up:
                last_idx = crossed_up[-1][0]
                m = len(levels) - 1 - last_idx
            elif crossed_down:
                first_idx = crossed_down[0][0]  # after reverse, this is the lowest
                m = len(levels) - 1 - first_idx

            # Boundary breach check (paper S3.1)
            if len(levels) >= 2 and (
                curr_close > levels[-1] or curr_close < levels[0]
            ):
                is_upper = curr_close > levels[-1]
                if is_upper:
                    upper_resets += 1
                else:
                    lower_resets += 1

                # Reset: re-center on current price, m = n//2 (re-symmetrize)
                reference = curr_close
                m = n // 2
                levels = grid_levels_table1(
                    n=n, reference_price=reference, k=k, levels_above=m,
                )
                state.reference_price = reference
                state.grid_levels = list(levels)
                # Cash/holdings carry over as-is (paper S3.1 asymmetry)

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
