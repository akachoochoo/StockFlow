"""Phase 0.11.g — _HybridCoreRunner (Core-Satellite: B&H core + DGT satellite).

핵심 질문: B&H core + DGT satellite 간 주기적 리밸런싱이
정적 배분 대비 알파를 생성하는가?

메커니즘:
1. 자본을 core_ratio (B&H) + (1-core_ratio) (DGT) 로 분할
2. B&H core: 초기 매수 후 보유 (rebalancing 시에만 거래)
3. DGT satellite: 기존 paper_adaptive_runner 로직 사용
4. Rebalancing:
   - drift-based: 실제 비율이 target에서 drift_threshold 이상 벗어나면 실행
   - cooldown: 최소 N 거래일 간격
   - 비용 모델 적용 (double-counting 방지: rebalancing = portfolio-level event)

5th ring 격리 (src/research/) — inner ring 변경 zero.
Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from src.domain.models import Asset, Money, OHLCV
from src.research.dgt.adaptive_runner import _AdaptiveConfig, _compute_adr
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.results import _DGTSnapshot, _DGTTrade
from src.research.dgt.runner import _DGTConfig
from src.research.dgt.state import _DGTGridState


RebalanceMode = Literal["static", "drift", "calendar"]


@dataclass(frozen=True)
class _RebalanceEvent:
    """Portfolio-level rebalancing event (distinct from DGT grid trades)."""

    trade_date: date
    direction: str  # "core_to_satellite" or "satellite_to_core"
    amount: Decimal  # cash moved (gross, before costs)
    cost: Decimal  # total transaction cost for the rebalance
    core_ratio_before: Decimal
    core_ratio_after: Decimal


@dataclass(frozen=True)
class _HybridBacktestResult:
    """Core-Satellite hybrid runner result.

    Composes B&H core tracking + DGT satellite result + combined portfolio.
    """

    asset: Asset
    start: date
    end: date
    initial_capital: Money
    core_ratio: Decimal
    rebalance_mode: RebalanceMode
    # Final state
    final_core_value: Decimal
    final_satellite_value: Decimal
    final_total_value: Decimal
    # Performance
    total_return_pct: Decimal
    # Components
    dgt_trades: list[_DGTTrade]
    rebalance_events: list[_RebalanceEvent]
    daily_snapshots: list[_HybridSnapshot]
    # Alpha
    rebalancing_alpha_annualized: Decimal  # vs static same-ratio


@dataclass(frozen=True)
class _HybridSnapshot:
    """Daily portfolio snapshot with core/satellite breakdown."""

    trade_date: date
    core_value: Decimal
    satellite_value: Decimal
    total_value: Decimal
    actual_core_ratio: Decimal


@dataclass
class _CoreState:
    """B&H core state — holds shares, only trades on rebalance."""

    cash: Decimal
    holdings: Decimal  # number of shares

    def value(self, price: Decimal) -> Decimal:
        return self.cash + self.holdings * price


@dataclass(frozen=True)
class _HybridConfig:
    """Core-Satellite configuration."""

    core_ratio: Decimal = Decimal("0.7")  # B&H portion (0.5~0.8)
    rebalance_mode: RebalanceMode = "drift"
    drift_threshold: Decimal = Decimal("0.05")  # 5% drift triggers rebalance
    cooldown_days: int = 20  # minimum trading days between rebalances
    calendar_period: int = 60  # for calendar mode: every N trading days


@dataclass(frozen=True)
class _HybridCoreRunner:
    """Core-Satellite DGT runner.

    B&H core + DGT satellite with optional drift-based rebalancing.
    """

    cost_model: _KoreanMarketCostModel
    dgt_config: _DGTConfig
    adaptive: _AdaptiveConfig = _AdaptiveConfig()
    hybrid: _HybridConfig = _HybridConfig()
    # Volume gate (pass-through to DGT satellite)
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
    ) -> _HybridBacktestResult:
        if not ohlcv:
            raise ValueError("ohlcv must be non-empty")

        capital = initial_capital.amount
        core_capital = capital * self.hybrid.core_ratio
        satellite_capital = capital * (Decimal("1") - self.hybrid.core_ratio)

        # Initialize B&H core: buy shares at first close
        first_close = ohlcv[0].close
        core_shares = (core_capital / first_close).quantize(
            Decimal("1"), rounding=ROUND_DOWN,
        )
        core_state = _CoreState(
            cash=core_capital - core_shares * first_close,
            holdings=core_shares,
        )

        # Initialize DGT satellite
        n = self.dgt_config.grid_count
        m = n // 2
        k = self._adaptive_k(ohlcv, 0, first_close)
        levels = grid_levels_table1(
            n=n, reference_price=first_close, k=k, levels_above=m,
        )
        sat_state = _DGTGridState(
            reference_price=first_close,
            grid_levels=list(levels),
            cash=satellite_capital,
            holdings=Decimal("0"),
        )

        dgt_trades: list[_DGTTrade] = []
        rebalance_events: list[_RebalanceEvent] = []
        snapshots: list[_HybridSnapshot] = []
        prev_close = first_close
        bars_since_rebalance = 0

        for bar_idx, bar in enumerate(ohlcv):
            curr_close = bar.close

            # === DGT Satellite trading ===
            crossed_up: list[tuple[int, Decimal]] = []
            crossed_down: list[tuple[int, Decimal]] = []
            for i, level in enumerate(levels):
                if prev_close < level <= curr_close:
                    crossed_up.append((i, level))
                elif curr_close <= level < prev_close:
                    crossed_down.append((i, level))

            # Volume gate
            skip_buy, skip_sell = self._check_volume_gate(ohlcv, bar_idx)

            if not skip_sell:
                for _i, level in crossed_up:
                    trade = self._maybe_sell(sat_state, asset, bar.trade_date, level)
                    if trade is not None:
                        dgt_trades.append(trade)

            if not skip_buy:
                for _i, level in reversed(crossed_down):
                    trade = self._maybe_buy(sat_state, asset, bar.trade_date, level)
                    if trade is not None:
                        dgt_trades.append(trade)

            # Daily grid reset (Hyb-Daily mode)
            reference = curr_close
            k = self._adaptive_k(ohlcv, bar_idx, curr_close)
            levels = grid_levels_table1(
                n=n, reference_price=reference, k=k, levels_above=m,
            )
            sat_state.reference_price = reference
            sat_state.grid_levels = list(levels)

            # === Rebalancing check ===
            bars_since_rebalance += 1
            core_val = core_state.value(curr_close)
            sat_val = sat_state.cash + sat_state.holdings * curr_close
            total_val = core_val + sat_val

            if total_val > 0 and self._should_rebalance(
                core_val, total_val, bars_since_rebalance, bar_idx,
            ):
                event = self._execute_rebalance(
                    core_state, sat_state, asset, curr_close,
                    core_val, sat_val, total_val, bar.trade_date,
                )
                if event is not None:
                    rebalance_events.append(event)
                    bars_since_rebalance = 0

            # Snapshot
            core_val = core_state.value(curr_close)
            sat_val = sat_state.cash + sat_state.holdings * curr_close
            total_val = core_val + sat_val
            actual_ratio = core_val / total_val if total_val > 0 else Decimal("0")

            snapshots.append(_HybridSnapshot(
                trade_date=bar.trade_date,
                core_value=core_val,
                satellite_value=sat_val,
                total_value=total_val,
                actual_core_ratio=actual_ratio,
            ))
            prev_close = curr_close

        # Compute results
        final_total = snapshots[-1].total_value if snapshots else capital
        total_return_pct = (final_total - capital) / capital * Decimal("100")

        # Compute annualized alpha vs static (static = no rebalancing, same ratio)
        alpha = self._compute_alpha(snapshots, ohlcv, asset, initial_capital)

        return _HybridBacktestResult(
            asset=asset,
            start=start,
            end=end,
            initial_capital=initial_capital,
            core_ratio=self.hybrid.core_ratio,
            rebalance_mode=self.hybrid.rebalance_mode,
            final_core_value=snapshots[-1].core_value if snapshots else Decimal("0"),
            final_satellite_value=snapshots[-1].satellite_value if snapshots else Decimal("0"),
            final_total_value=final_total,
            total_return_pct=total_return_pct,
            dgt_trades=dgt_trades,
            rebalance_events=rebalance_events,
            daily_snapshots=snapshots,
            rebalancing_alpha_annualized=alpha,
        )

    def _should_rebalance(
        self,
        core_val: Decimal,
        total_val: Decimal,
        bars_since: int,
        bar_idx: int,
    ) -> bool:
        if self.hybrid.rebalance_mode == "static":
            return False
        if bars_since < self.hybrid.cooldown_days:
            return False

        if self.hybrid.rebalance_mode == "drift":
            actual_ratio = core_val / total_val
            drift = abs(actual_ratio - self.hybrid.core_ratio)
            return drift >= self.hybrid.drift_threshold

        if self.hybrid.rebalance_mode == "calendar":
            return bars_since >= self.hybrid.calendar_period

        return False

    def _execute_rebalance(
        self,
        core: _CoreState,
        satellite: _DGTGridState,
        asset: Asset,
        price: Decimal,
        core_val: Decimal,
        sat_val: Decimal,
        total_val: Decimal,
        trade_date: date,
    ) -> _RebalanceEvent | None:
        """Execute rebalancing to restore target ratio."""
        target_core_val = total_val * self.hybrid.core_ratio
        diff = target_core_val - core_val  # positive = need more in core

        if abs(diff) < price:  # less than 1 share worth, skip
            return None

        ratio_before = core_val / total_val if total_val > 0 else Decimal("0")
        total_cost = Decimal("0")

        if diff > 0:
            # Move from satellite to core: sell satellite holdings, buy core shares
            shares_to_move = (diff / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if shares_to_move <= 0 or satellite.holdings < shares_to_move:
                shares_to_move = min(shares_to_move, satellite.holdings)
            if shares_to_move <= 0:
                return None

            # Sell from satellite (cost applied)
            sell_cost = self.cost_model.compute_sell_cost(price, shares_to_move, asset)
            satellite.holdings -= shares_to_move
            satellite.cash += sell_cost.net_proceeds
            total_cost += sell_cost.tax + sell_cost.commission

            # Buy into core (cost applied)
            buy_cost = self.cost_model.compute_buy_cost(price, shares_to_move, asset)
            # Transfer cash from satellite to core for the purchase
            transfer = buy_cost.total_cost
            if satellite.cash >= transfer:
                satellite.cash -= transfer
                core.holdings += shares_to_move
                total_cost += buy_cost.commission
            else:
                # Not enough satellite cash, partially revert
                satellite.holdings += shares_to_move
                satellite.cash -= sell_cost.net_proceeds
                return None

            direction = "satellite_to_core"
            amount = shares_to_move * price

        else:
            # Move from core to satellite: sell core holdings, give cash to satellite
            shares_to_move = (abs(diff) / price).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if shares_to_move <= 0 or core.holdings < shares_to_move:
                shares_to_move = min(shares_to_move, core.holdings)
            if shares_to_move <= 0:
                return None

            # Sell from core
            sell_cost = self.cost_model.compute_sell_cost(price, shares_to_move, asset)
            core.holdings -= shares_to_move
            core.cash += sell_cost.net_proceeds
            total_cost += sell_cost.tax + sell_cost.commission

            # Transfer cash to satellite
            transfer = sell_cost.net_proceeds
            core.cash -= transfer
            satellite.cash += transfer

            direction = "core_to_satellite"
            amount = shares_to_move * price

        # Compute ratio after
        new_core_val = core.value(price)
        new_total = new_core_val + satellite.cash + satellite.holdings * price
        ratio_after = new_core_val / new_total if new_total > 0 else Decimal("0")

        return _RebalanceEvent(
            trade_date=trade_date,
            direction=direction,
            amount=amount,
            cost=total_cost,
            core_ratio_before=ratio_before,
            core_ratio_after=ratio_after,
        )

    def _compute_alpha(
        self,
        snapshots: list[_HybridSnapshot],
        ohlcv: list[OHLCV],
        asset: Asset,
        initial_capital: Money,
    ) -> Decimal:
        """Compute annualized alpha vs static (no rebalancing) same-ratio allocation.

        Runs a static version internally and compares final values.
        """
        if not snapshots or len(ohlcv) < 2:
            return Decimal("0")

        # Static baseline: same ratio, no rebalancing
        # B&H core return = (final_close / first_close - 1)
        # DGT satellite return = taken from actual DGT performance (satellite trades still happen)
        # For true comparison, we compare this runner's result vs static mode
        if self.hybrid.rebalance_mode == "static":
            return Decimal("0")  # static vs static = 0 alpha

        # Run static version for comparison
        static_runner = _HybridCoreRunner(
            cost_model=self.cost_model,
            dgt_config=self.dgt_config,
            adaptive=self.adaptive,
            hybrid=_HybridConfig(
                core_ratio=self.hybrid.core_ratio,
                rebalance_mode="static",
            ),
            volume_gate=self.volume_gate,
            volume_gate_period=self.volume_gate_period,
            volume_gate_multiplier=self.volume_gate_multiplier,
        )
        static_result = static_runner.run(
            asset=asset,
            start=snapshots[0].trade_date,
            end=snapshots[-1].trade_date,
            initial_capital=initial_capital,
            ohlcv=ohlcv,
        )

        # Annualized alpha
        days = len(ohlcv)
        if days <= 0:
            return Decimal("0")

        capital = initial_capital.amount
        if capital <= 0:
            return Decimal("0")

        final_rebal = snapshots[-1].total_value
        final_static = static_result.final_total_value

        # Simple annualized difference
        rebal_return = (final_rebal - capital) / capital
        static_return = (final_static - capital) / capital
        alpha_total = rebal_return - static_return

        # Annualize (approximate: 250 trading days/year)
        years = Decimal(days) / Decimal("250")
        if years > 0:
            return (alpha_total / years) * Decimal("100")  # as percentage
        return Decimal("0")

    def _adaptive_k(self, bars: list[OHLCV], bar_idx: int, close: Decimal) -> Decimal:
        adr = _compute_adr(bars, self.adaptive.atr_period, bar_idx)
        if adr <= 0 or close <= 0:
            return Decimal("0.01")  # fallback
        atr_pct = adr / close
        k = atr_pct * self.adaptive.multiplier
        return max(self.adaptive.k_min, min(self.adaptive.k_max, k))

    def _check_volume_gate(
        self, bars: list[OHLCV], bar_idx: int,
    ) -> tuple[bool, bool]:
        """Returns (skip_buy, skip_sell) based on volume spike."""
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
        allocation = state.cash / Decimal(self.dgt_config.grid_count + 1)
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
        quantity = (state.holdings / Decimal(self.dgt_config.grid_count + 1)).quantize(
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
