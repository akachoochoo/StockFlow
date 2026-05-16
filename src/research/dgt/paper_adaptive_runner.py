"""Phase 0.11.f -- _DGTPaperAdaptiveRunner (Paper + ATR-adaptive k hybrid).

Paper-faithful boundary reset (S3.1) + ATR-based dynamic k 결합.

핵심 메커니즘:
1. Grid reset = boundary breach only (paper S3.1)
2. Reset 시 m = n//2 재대칭화 (paper S1.1.1)
3. Reset 시 ATR(14) 기반 k 재계산 (adaptive)
   - 하락장(고변동) -> ATR 큼 -> k 넓음 -> 매수 간격 벌어짐 -> 거래 감소
   - 상승장(저변동) -> ATR 작음 -> k 좁음 -> 거래 기회 확보
4. Interior reference tracking + natural crossing order (paper S1.1.2)
5. Cash/holdings carry over as-is on reset (paper S3.1)

5th ring 격리 (src/research/) -- inner ring 변경 zero.
Underscore-prefix private (ADR 0007 S1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from src.domain.models import Asset, Money, OHLCV
from src.research.dgt.adaptive_runner import _AdaptiveConfig, _compute_adr, _compute_atr
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot, _DGTTrade
from src.research.dgt.runner import _DGTConfig
from src.research.dgt.state import _DGTGridState


def _compute_slope(bars: list[OHLCV], period: int, end_idx: int) -> Decimal:
    """Linear regression slope of close prices over `period` bars, normalized by price.

    Returns slope as percentage: positive = uptrend, negative = downtrend.
    Returns Decimal("0") if insufficient data.
    """
    start = end_idx - period + 1
    if start < 0 or period < 2:
        return Decimal("0")

    # Simple linear regression: slope = Σ((x-x̄)(y-ȳ)) / Σ((x-x̄)²)
    n = period
    prices = [bars[i].close for i in range(start, end_idx + 1)]
    x_mean = Decimal(n - 1) / Decimal(2)
    y_mean = sum(prices) / Decimal(n)

    if y_mean <= 0:
        return Decimal("0")

    num = Decimal("0")
    den = Decimal("0")
    for i in range(n):
        x_diff = Decimal(i) - x_mean
        y_diff = prices[i] - y_mean
        num += x_diff * y_diff
        den += x_diff * x_diff

    if den == 0:
        return Decimal("0")

    slope = num / den  # price change per bar
    return slope / y_mean  # normalized as pct of avg price


@dataclass(frozen=True)
class _DGTPaperAdaptiveRunner:
    """Paper-faithful DGT + ATR-adaptive k hybrid.

    Paper boundary reset + ATR-based dynamic k.
    rebalance_mode:
      - "on_breach": grid reset on boundary breach only (paper S3.1)
      - "daily": grid reset every bar (always re-center + ATR k)
    config.grid_spacing_pct = base k (ATR unavailable 시 fallback).
    config.levels_above = ignored (always m = n//2).
    """

    cost_model: _KoreanMarketCostModel
    config: _DGTConfig
    adaptive: _AdaptiveConfig = _AdaptiveConfig()
    rebalance_mode: Literal["on_breach", "daily"] = "on_breach"
    volatility_measure: Literal["atr", "adr"] = "atr"
    # --- Trade gates ---
    # B: Asymmetric Slope Gate — skip sell on surge, skip buy on plunge
    slope_gate: bool = False
    slope_gate_period: int = 5  # ROC lookback period (bars)
    slope_gate_threshold: Decimal = Decimal("0.05")  # 5% ROC threshold
    # D: Volume Gate — skip sell on volume spike + up, skip buy on spike + down
    volume_gate: bool = False
    volume_gate_period: int = 20  # volume SMA lookback
    volume_gate_multiplier: Decimal = Decimal("2.0")  # spike = volume > N * SMA
    # --- Legacy trend (D3 invalidated, kept for reference) ---
    use_trend: bool = False  # True = slope-based k adjustment
    trend_period: int = 20  # slope 계산 기간
    trend_sensitivity: Decimal = Decimal("10")  # slope 영향 배율

    def _check_slope_gate(
        self, bars: list[OHLCV], bar_idx: int,
    ) -> tuple[bool, bool]:
        """Returns (skip_buy, skip_sell) based on ROC over slope_gate_period.

        Asymmetric: surge (ROC > threshold) → skip sell only,
                    plunge (ROC < -threshold) → skip buy only.
        """
        if not self.slope_gate or bar_idx < self.slope_gate_period:
            return False, False
        prev_close = bars[bar_idx - self.slope_gate_period].close
        curr_close = bars[bar_idx].close
        if prev_close <= 0:
            return False, False
        roc = (curr_close - prev_close) / prev_close
        skip_buy = roc < -self.slope_gate_threshold   # plunge → don't buy
        skip_sell = roc > self.slope_gate_threshold    # surge → don't sell
        return skip_buy, skip_sell

    def _check_volume_gate(
        self, bars: list[OHLCV], bar_idx: int,
    ) -> tuple[bool, bool]:
        """Returns (skip_buy, skip_sell) based on volume spike.

        Volume spike + price up → skip sell (let it ride),
        Volume spike + price down → skip buy (avoid falling knife).
        """
        if not self.volume_gate or bar_idx < self.volume_gate_period:
            return False, False
        start = bar_idx - self.volume_gate_period + 1
        vol_sum = sum(bars[i].volume for i in range(start, bar_idx + 1))
        vol_avg = vol_sum / Decimal(self.volume_gate_period)
        curr_vol = bars[bar_idx].volume
        if vol_avg <= 0 or curr_vol <= vol_avg * self.volume_gate_multiplier:
            return False, False  # no spike
        # Volume spike detected — check price direction
        prev_close = bars[bar_idx - 1].close if bar_idx > 0 else bars[bar_idx].close
        curr_close = bars[bar_idx].close
        if curr_close > prev_close:
            return False, True   # spike + up → skip sell
        elif curr_close < prev_close:
            return True, False   # spike + down → skip buy
        return False, False

    def _adaptive_k(
        self, bars: list[OHLCV], bar_idx: int, close: Decimal,
    ) -> Decimal:
        if self.volatility_measure == "adr":
            atr = _compute_adr(bars, self.adaptive.atr_period, bar_idx)
        else:
            atr = _compute_atr(bars, self.adaptive.atr_period, bar_idx)
        if atr <= 0 or close <= 0:
            return self.config.k_ratio
        atr_pct = atr / close
        k = atr_pct * self.adaptive.multiplier

        if self.use_trend:
            slope = _compute_slope(bars, self.trend_period, bar_idx)
            # slope > 0 (uptrend) → trend_factor < 1 → k narrower
            # slope < 0 (downtrend) → trend_factor > 1 → k wider
            trend_factor = Decimal("1") - slope * self.trend_sensitivity
            # clamp trend_factor to [0.3, 3.0] for safety
            trend_factor = max(Decimal("0.3"), min(Decimal("3.0"), trend_factor))
            k = k * trend_factor

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

        n = self.config.grid_count
        reference = ohlcv[0].close
        m = n // 2
        k = self._adaptive_k(ohlcv, 0, reference)

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
        prev_close = reference

        for bar_idx, bar in enumerate(ohlcv):
            curr_close = bar.close

            # Collect crossed levels
            crossed_up: list[tuple[int, Decimal]] = []
            crossed_down: list[tuple[int, Decimal]] = []
            for i, level in enumerate(levels):
                if prev_close < level <= curr_close:
                    crossed_up.append((i, level))
                elif curr_close <= level < prev_close:
                    crossed_down.append((i, level))

            # Trade gates
            sb_slope, ss_slope = self._check_slope_gate(ohlcv, bar_idx)
            sb_vol, ss_vol = self._check_volume_gate(ohlcv, bar_idx)
            skip_buy = sb_slope or sb_vol
            skip_sell = ss_slope or ss_vol

            # UP crosses ascending (natural order)
            if not skip_sell:
                for _i, level in crossed_up:
                    trade = self._maybe_sell(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)

            # DOWN crosses descending (natural order)
            if not skip_buy:
                for _i, level in reversed(crossed_down):
                    trade = self._maybe_buy(state, asset, bar.trade_date, level)
                    if trade is not None:
                        trades.append(trade)

            # Grid reset logic
            should_reset = False
            if self.rebalance_mode == "daily":
                should_reset = True
            elif len(levels) >= 2 and (
                curr_close > levels[-1] or curr_close < levels[0]
            ):
                should_reset = True

            if should_reset:
                reference = curr_close
                m = n // 2
                k = self._adaptive_k(ohlcv, bar_idx, curr_close)
                levels = grid_levels_table1(
                    n=n, reference_price=reference, k=k, levels_above=m,
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
