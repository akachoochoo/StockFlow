"""분봉 grid runner — cost-aware backtest 엔진 (5th ring 격리).

ADR 0023 §10.2 / 세그먼트 1.2.2.c 산출. 일봉 `src/use_cases/grid_runner.py`
의 `GridRunner` 의 분봉 mirror. 1.2.2.b `_GridMinuteStrategy` 와 inner ring
`KoreanMarketCostModel` (outer→inner read) 조립.

본 모듈의 본질:
1. `_GridMinuteStrategy.evaluate(...)` 를 분봉 N개 iterate.
2. `KoreanMarketCostModel` 로 실 비용 (commission, tax) 적용 → cash/holdings 진화.
3. Runtime state (cooldown_remaining / last_sell_price / avg_cost) 영속.
4. `profit_guard` / `price_based_reentry` / `sell_cooldown_bars` 게이트 적용.
5. Full-fill-at-close 이상화 (일봉 GridRunner 와 동일, G2 base).
6. 결과 = `_MinuteRunResult` (trades + bar values + final PnL).

5th ring 격리 (D15): inner ring `GridRunner` 와 별도 모듈. 분봉이 inner ring
production 진입 시점 (1.2.4) 에 별도 ADR 박제 후 production runner 신규.

분봉 특수성:
- 391봉/일 x N영업일 = 큰 iteration. bar_values 메모리 ↑ — 1.2.2.d backtest
  engine 에서 streaming 검토. 본 runner 는 in-memory 단순 path.
- `_BarValue.trade_date + trade_time` 둘 다 박제 (분봉 identity).

CLAUDE.md §2.1 (Decimal) / §3.2 (bar iteration, 시계 의존 zero).
"""
from __future__ import annotations

from datetime import date, time  # noqa: TC003 — pydantic 런타임 해석
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from src.domain.cost_model import KoreanMarketCostModel
from src.domain.models import DomainModel, Money, OrderSide, ValueObject
from src.domain.strategies.grid_math import grid_levels
from src.research.dgt_minute._grid_strategy import (
    _GridMinuteState,
    _GridMinuteStrategy,
)

if TYPE_CHECKING:
    from src.domain.models import Asset
    from src.research.dgt_minute._grid_strategy import _GridMinuteConfig
    from src.research.dgt_minute._kis_minute_downloader import _MinuteBar


class _MinuteTrade(ValueObject):
    """한 그리드 체결 (비용 반영) — 분봉 timestamp."""

    trade_date: date
    trade_time: time
    side: OrderSide
    level_price: Decimal
    rounded_price: Decimal
    quantity: Decimal
    gross: Decimal
    commission: Decimal
    tax: Decimal
    cash_delta: Decimal  # 매수 음수(-total_cost), 매도 양수(+net_proceeds)


class _BarValue(ValueObject):
    """분봉별 포트폴리오 가치 (MDD/수익 산출용)."""

    trade_date: date
    trade_time: time
    cash: Decimal
    holdings: Decimal
    close_price: Decimal
    total_value: Decimal


class _MinuteRunResult(DomainModel):
    """`_MinuteGridRunner.run` 출력."""

    initial_capital: Money
    final_cash: Decimal
    final_holdings: Decimal
    final_close_price: Decimal
    final_value: Decimal
    trades: list[_MinuteTrade]
    bar_values: list[_BarValue]
    final_avg_cost: Decimal = Decimal("0")

    def pnl_split(self) -> tuple[Decimal, Decimal]:
        """(실현, 미실현) 정수 원 — 합 = round(final_value - 초기자본).

        일봉 `GridRunResult.pnl_split` 와 동일 알고리즘 (평균원가법).
        """
        hold = Decimal("0")
        cost_basis = Decimal("0")
        realized = Decimal("0")
        for t in self.trades:
            if t.side is OrderSide.BUY:
                cost_basis += -t.cash_delta
                hold += t.quantity
            else:
                basis_sold = (
                    cost_basis / hold * t.quantity if hold > 0 else Decimal("0")
                )
                realized += t.cash_delta - basis_sold
                cost_basis -= basis_sold
                hold -= t.quantity
        total = (self.final_value - self.initial_capital.amount).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        realized = realized.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return realized, total - realized

    def turnover(self) -> Decimal:
        if self.initial_capital.amount <= 0:
            return Decimal("0")
        gross_sum = sum((t.gross for t in self.trades), Decimal("0"))
        return gross_sum / self.initial_capital.amount

    def max_drawdown(self) -> Decimal:
        """MDD = max((peak - value) / peak) over bar_values. peak<=0 시 0."""
        if not self.bar_values:
            return Decimal("0")
        peak = Decimal("0")
        mdd = Decimal("0")
        for bv in self.bar_values:
            if bv.total_value > peak:
                peak = bv.total_value
            if peak > 0:
                dd = (peak - bv.total_value) / peak
                if dd > mdd:
                    mdd = dd
        return mdd


class _MinuteGridRunner:
    """분봉 grid backtest 엔진 (결정론적, 자기완결 회계).

    일봉 `GridRunner` mirror. 동일 알고리즘 — within-bar full-fill-at-close
    이상화.
    """

    def __init__(
        self,
        cost_model: KoreanMarketCostModel | None = None,
        strategy: _GridMinuteStrategy | None = None,
    ) -> None:
        self._cost_model = cost_model or KoreanMarketCostModel()
        self._strategy = strategy or _GridMinuteStrategy()

    def run(
        self,
        *,
        asset: Asset,
        bars: list[_MinuteBar],
        config: _GridMinuteConfig,
        initial_capital: Money,
    ) -> _MinuteRunResult:
        if not bars:
            raise ValueError("bars must be non-empty")
        if initial_capital.currency != asset.currency:
            raise ValueError(
                f"initial_capital.currency ({initial_capital.currency.value}) "
                f"!= asset.currency ({asset.currency.value})"
            )

        n = config.grid_count
        reference = bars[0].close
        k0 = self._strategy._compute_k(bars=bars, bar_idx=0, config=config)
        state = _GridMinuteState(
            reference_price=reference,
            grid_levels=tuple(grid_levels(n, reference, k0, config.levels_above)),
        )

        cash = initial_capital.amount
        holdings = Decimal("0")
        avg_cost = Decimal("0")
        trades: list[_MinuteTrade] = []
        bar_values: list[_BarValue] = []
        cooldown_remaining = 0
        last_sell_price = Decimal("0")

        for bar_idx, bar in enumerate(bars):
            cooling = cooldown_remaining > 0
            price_blocks_buys = (
                config.price_based_reentry
                and last_sell_price > 0
                and bar.close > last_sell_price
            )
            sold_this_bar = False

            ev = self._strategy.evaluate(
                asset=asset,
                bars=bars,
                bar_idx=bar_idx,
                state=state,
                available_cash=Money(amount=cash, currency=asset.currency),
                holdings=holdings,
                config=config,
            )

            for dec in ev.decisions:
                if dec.side is OrderSide.BUY:
                    if cooling:
                        continue
                    if price_blocks_buys:
                        continue
                    bc = self._cost_model.compute_buy_cost(
                        price=dec.level_price,
                        quantity=dec.quantity,
                        asset=asset,
                    )
                    if bc.total_cost > cash:
                        continue
                    avg_cost = (
                        (avg_cost * holdings + bc.rounded_price * dec.quantity)
                        / (holdings + dec.quantity)
                    )
                    cash -= bc.total_cost
                    holdings += dec.quantity
                    trades.append(
                        _MinuteTrade(
                            trade_date=bar.trade_date,
                            trade_time=bar.trade_time,
                            side=OrderSide.BUY,
                            level_price=dec.level_price,
                            rounded_price=bc.rounded_price,
                            quantity=dec.quantity,
                            gross=bc.gross,
                            commission=bc.commission,
                            tax=bc.tax,
                            cash_delta=-bc.total_cost,
                        )
                    )
                else:  # SELL
                    sc = self._cost_model.compute_sell_cost(
                        price=dec.level_price,
                        quantity=dec.quantity,
                        asset=asset,
                    )
                    if (
                        config.profit_guard
                        and avg_cost > 0
                        and sc.rounded_price <= avg_cost
                    ):
                        continue
                    cash += sc.net_proceeds
                    holdings -= dec.quantity
                    sold_this_bar = True
                    last_sell_price = sc.rounded_price
                    trades.append(
                        _MinuteTrade(
                            trade_date=bar.trade_date,
                            trade_time=bar.trade_time,
                            side=OrderSide.SELL,
                            level_price=dec.level_price,
                            rounded_price=sc.rounded_price,
                            quantity=dec.quantity,
                            gross=sc.gross,
                            commission=sc.commission,
                            tax=sc.tax,
                            cash_delta=sc.net_proceeds,
                        )
                    )

            if config.sell_cooldown_bars > 0:
                if sold_this_bar:
                    cooldown_remaining = config.sell_cooldown_bars
                elif cooldown_remaining > 0:
                    cooldown_remaining -= 1

            state = ev.next_state
            total = cash + holdings * bar.close
            bar_values.append(
                _BarValue(
                    trade_date=bar.trade_date,
                    trade_time=bar.trade_time,
                    cash=cash,
                    holdings=holdings,
                    close_price=bar.close,
                    total_value=total,
                )
            )

        final_close = bars[-1].close
        return _MinuteRunResult(
            initial_capital=initial_capital,
            final_cash=cash,
            final_holdings=holdings,
            final_close_price=final_close,
            final_value=cash + holdings * final_close,
            trades=trades,
            bar_values=bar_values,
            final_avg_cost=avg_cost,
        )
