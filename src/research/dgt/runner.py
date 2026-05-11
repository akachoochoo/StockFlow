"""Phase 0.11.a — _DGTPrototypeRunner (일봉 informational runner).

ADR 0007 §1.4 G2 INFORMATIONAL. AC7 = runner correctness only (raise 안 함,
IRR 수치 informational).

Registry 미등록 (R5) — DGTStrategy 는 BuyStrategy / SellStrategy registry
미등록. create_buy_strategy factory grep = 0 검증 (CLAUDE.md §16.1.4 단일
sell strategy 가정 보존). DGTPrototypeRunner 가 직접 instantiate.

Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal

from src.domain.models import Asset, Money, OHLCV
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.results import _DGTBacktestResult, _DGTTrade
from src.research.dgt.state import _DGTGridState


@dataclass(frozen=True)
class _DGTConfig:
    """DGT 파라미터 — n / k / m (논문 § 표기).

    - grid_count (n): 그리드 개수, 레벨 수 = n + 1.
    - grid_spacing_pct (k as %): 등비 간격 percent (예: Decimal("5") = 5%).
    - levels_above (m): current price 위 grid 수.
    """

    grid_count: int
    grid_spacing_pct: Decimal
    levels_above: int

    @property
    def k_ratio(self) -> Decimal:
        """k as decimal ratio (5% → 0.05)."""
        return self.grid_spacing_pct / Decimal(100)


@dataclass(frozen=True)
class _DGTPrototypeRunner:
    """일봉 informational prototype.

    `run()` 은 _DGTBacktestResult 반환 — IRR 수치 informational only (R1).
    Smoke test (AC7) 는 raise 없는 완주만 검증.
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
        """일봉 backtest. ohlcv = list of OHLCV bars, ascending trade_date.

        Algorithm (paper Algorithm 1 의 일봉 단순화):
            - 초기 reference_price = ohlcv[0].close.
            - n+1 grid levels (geometric spacing, formulas.grid_levels_table1).
            - 각 bar 의 prev_close → curr_close 사이 level crossing 탐지:
              - UP-cross: SELL at level (holdings / (n+1) quantity).
              - DOWN-cross: BUY at level (cash / (n+1) allocation).
            - cost_model 로 tax/commission 적용 (KoreanMarketCostModel).

        Simplification (R1 informational):
            - wallet 회계 근사 (사용자 ADR Implementation Notes §5).
            - 한 bar 안 multiple grid crossing 시 level 순차 처리 (paper 명시 zero).
        """
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
        prev_close = reference
        for bar in ohlcv:
            curr_close = bar.close
            for level in levels:
                if prev_close < level <= curr_close:
                    trade = self._maybe_sell(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)
                elif curr_close <= level < prev_close:
                    trade = self._maybe_buy(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)
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
        )

    def _maybe_buy(
        self,
        state: _DGTGridState,
        asset: Asset,
        trade_date: date,
        level_price: Decimal,
    ) -> _DGTTrade | None:
        """DOWN-cross 시 매수. allocation = cash / (n+1), quantity = floor."""
        if level_price <= 0:
            return None
        allocation = state.cash / Decimal(self.config.grid_count + 1)
        if allocation <= 0:
            return None
        quantity = (allocation / level_price).quantize(Decimal("1"), rounding=ROUND_DOWN)
        if quantity <= 0:
            return None
        cost = self.cost_model.compute_buy_cost(
            price=level_price,
            quantity=quantity,
            asset=asset,
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
        """UP-cross 시 매도. quantity = holdings / (n+1), floor."""
        if state.holdings <= 0:
            return None
        quantity = (state.holdings / Decimal(self.config.grid_count + 1)).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
        if quantity <= 0:
            return None
        proceeds = self.cost_model.compute_sell_cost(
            price=level_price,
            quantity=quantity,
            asset=asset,
        )
        state.holdings -= quantity
        state.cash += proceeds.net_proceeds
        # wallet 근사: net of fees (gross - tax - commission - gross = -(tax+commission))
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
