"""GridRunner — DGT 그리드 backtest/paper 엔진 (Phase 1.x, ADR 0022 G1 증분 3b).

별도 grid use_case (D9 — DailyOrchestrator 우회). ``GridStrategy`` (cost-free
결정) 를 bar 별로 구동하고 ``KoreanMarketCostModel`` 로 마찰비용을 적용해
cash/holdings 를 추적한다. 결정론적 — 동일 bars → 동일 결과 (G2 §7.4 backtest↔
paper 동일성의 토대; backtest 와 paper 가 같은 엔진을 쓰므로 trivially 일치).

페이퍼/백테스트 먼저 (사용자 결정 2026-05-23): slot 기반 주문/정산 인프라
(`order_keys` / `OrderRequest` / broker / `PendingSettler`) 와의 충돌을 피해
live 주문 배선은 별도 승인 증분으로 미룬다. 본 엔진은 자기완결 회계.

비용 모델 idealization (ADR §8 Q8): 매수 affordability 는 실비용(total_cost)
으로 재검하되, GridStrategy 의 within-bar 할당은 gross 기준 → 한 bar 다중매수
시 research 의 cost-coupled 할당과 미세 차이(commission). full-fill-at-close
이상화로 박제. zero-cost 에서는 research 와 bit-identical.

Clean Architecture: domain (GridStrategy / KoreanMarketCostModel / grid_math /
models) 만 inward 의존. 외부 import 0, 시계 0 (시점 = bars 주입).
"""
from __future__ import annotations

from datetime import date  # noqa: TC003 — pydantic 가 결과 모델 필드 타입을 런타임 해석
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.cost_model import KoreanMarketCostModel
from src.domain.models import DomainModel, Money, OrderSide, ValueObject
from src.domain.strategies.grid import GridState, GridStrategy
from src.domain.strategies.grid_math import adaptive_k, grid_levels

if TYPE_CHECKING:
    from src.domain.models import OHLCV, Asset
    from src.domain.strategies.grid import GridConfig


class GridTrade(ValueObject):
    """한 그리드 체결 (비용 반영)."""

    trade_date: date
    side: OrderSide
    level_price: Decimal
    rounded_price: Decimal
    quantity: Decimal
    gross: Decimal
    commission: Decimal
    tax: Decimal
    cash_delta: Decimal  # 매수 음수(-total_cost), 매도 양수(+net_proceeds)


class GridDailyValue(ValueObject):
    """일별 포트폴리오 가치 (MDD/수익 산출용)."""

    trade_date: date
    cash: Decimal
    holdings: Decimal
    close_price: Decimal
    total_value: Decimal
    # 그날 거래에 적용된 활성 그리드 레벨 (리셋 전). 시변 그리드 차트용
    # (ADR 0022 §11.8 — on_breach 재중심을 차트에 반영). 기본 () = 미기록.
    grid_levels: tuple[Decimal, ...] = ()


class GridRunResult(DomainModel):
    """GridRunner.run 출력."""

    initial_capital: Money
    final_cash: Decimal
    final_holdings: Decimal
    final_close_price: Decimal
    final_value: Decimal
    trades: list[GridTrade]
    daily_values: list[GridDailyValue]


class GridRunner:
    """그리드 backtest/paper 실행 엔진 (결정론적, 자기완결 회계)."""

    def __init__(
        self, cost_model: KoreanMarketCostModel | None = None
    ) -> None:
        self._cost_model = cost_model or KoreanMarketCostModel()
        self._strategy = GridStrategy()

    def run(
        self,
        *,
        asset: Asset,
        bars: list[OHLCV],
        config: GridConfig,
        initial_capital: Money,
    ) -> GridRunResult:
        if not bars:
            raise ValueError("bars must be non-empty")
        if initial_capital.currency != asset.currency:
            raise ValueError(
                f"initial_capital.currency ({initial_capital.currency.value}) "
                f"!= asset.currency ({asset.currency.value})"
            )

        n = config.grid_count
        reference = bars[0].close
        k0 = adaptive_k(
            bars,
            0,
            reference,
            period=config.atr_period,
            multiplier=config.multiplier,
            k_min=config.k_min,
            k_max=config.k_max,
            fallback_k=config.fallback_k,
            measure=config.volatility_measure,
        )
        state = GridState(
            reference_price=reference,
            grid_levels=tuple(grid_levels(n, reference, k0, config.levels_above)),
        )

        cash = initial_capital.amount
        holdings = Decimal("0")
        avg_cost = Decimal("0")  # 가중평균 매수 체결가 (profit_guard, ADR 0022 D7)
        trades: list[GridTrade] = []
        daily: list[GridDailyValue] = []

        for bar_idx, bar in enumerate(bars):
            # 이 바 거래에 적용된 그리드 (evaluate 의 reset 전) — 시변 차트용.
            active_grid = state.grid_levels
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
                    bc = self._cost_model.compute_buy_cost(
                        price=dec.level_price, quantity=dec.quantity, asset=asset
                    )
                    if bc.total_cost > cash:
                        # 실비용 affordability 재검 (cost-coupled edge — §8 Q8).
                        continue
                    # 가중평균 매수 체결가 갱신 (profit_guard 기준 — research
                    # dynamic_runner.py:213-218 동치).
                    avg_cost = (
                        (avg_cost * holdings + bc.rounded_price * dec.quantity)
                        / (holdings + dec.quantity)
                    )
                    cash -= bc.total_cost
                    holdings += dec.quantity
                    trades.append(
                        GridTrade(
                            trade_date=bar.trade_date,
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
                else:
                    sc = self._cost_model.compute_sell_cost(
                        price=dec.level_price, quantity=dec.quantity, asset=asset
                    )
                    # profit_guard (ADR 0022 D7): 체결가 ≤ 평단이면 매도 스킵 —
                    # 손실 실현 방지 (research dynamic_runner.py:255-260 동치).
                    if (
                        config.profit_guard
                        and avg_cost > 0
                        and sc.rounded_price <= avg_cost
                    ):
                        continue
                    cash += sc.net_proceeds
                    holdings -= dec.quantity
                    trades.append(
                        GridTrade(
                            trade_date=bar.trade_date,
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
            state = ev.next_state
            total = cash + holdings * bar.close
            daily.append(
                GridDailyValue(
                    trade_date=bar.trade_date,
                    cash=cash,
                    holdings=holdings,
                    close_price=bar.close,
                    total_value=total,
                    grid_levels=active_grid,
                )
            )

        final_close = bars[-1].close
        return GridRunResult(
            initial_capital=initial_capital,
            final_cash=cash,
            final_holdings=holdings,
            final_close_price=final_close,
            final_value=cash + holdings * final_close,
            trades=trades,
            daily_values=daily,
        )
