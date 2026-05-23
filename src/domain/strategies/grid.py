"""GridStrategy — Dynamic Grid Trading (DGT) 도메인 전략 (Phase 1.x, ADR 0022 G1).

`src/research/dgt/paper_adaptive_runner.py` 의 검증된 그리드 로직을 inner ring
으로 **충실 포팅** (research → domain 승격, ADR 0022 D6 = 신규 grid 패러다임).
역할 = MDD 방어·횡보 수확 (D2). 일봉 daily/on_breach rebalance (D3 — 분봉 제외).

전략 ↔ 실행 분리 (Clean Architecture):
- 본 전략(``evaluate``)은 **비용 없이(cost-free)** 그리드 거래 결정을 emit 한다 —
  레벨 교차 감지 + trade gate + 매수/매도 수량 + 그리드 reset. 거래세/수수료 +
  실주문은 grid use_case + broker (D9, 증분 3) 가 적용한다.
- 동치(G2): SELL 수량은 비용 무관(holdings/(n+1)) → 항상 research 와 동일.
  BUY 는 비용=0 일 때 research 와 bit-identical (cash 진화가 gross 일치). 실거래
  비용은 use_case 에서 layered — backtest = full-fill-at-close 이상화(§8 Q8).

Domain 규칙 (CLAUDE.md §1.1/§2/§3.2): 외부 import 0, datetime.now() 0 (시점 =
bars/bar_idx 주입), Decimal-only. profit_guard(D7) / idempotency key(Q7) 는
후속 증분.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from src.domain.models import DomainModel, OrderSide, ValueObject
from src.domain.strategies.grid_math import adaptive_k, grid_levels

if TYPE_CHECKING:
    from src.domain.models import OHLCV, Asset, Money


class GridConfig(DomainModel):
    """DGT 그리드 설정 (research ``_DGTConfig`` + ``_AdaptiveConfig`` + gates 통합).

    ``grid_count`` = n (레벨 수 = n+1). ``levels_above`` 는 항상 n//2 재대칭화
    (paper S1.1.1) 이므로 필드 없음. ``fallback_k`` = 변동성 산출 불가 시 k.
    """

    grid_count: int = Field(ge=2)
    fallback_k: Decimal = Field(gt=Decimal(0))
    rebalance_mode: Literal["on_breach", "daily"] = "daily"
    volatility_measure: Literal["atr", "adr"] = "adr"
    atr_period: int = Field(default=14, ge=1)
    multiplier: Decimal = Field(default=Decimal("1.5"), gt=Decimal(0))
    k_min: Decimal = Field(default=Decimal("0.02"), gt=Decimal(0))
    k_max: Decimal = Field(default=Decimal("0.10"), gt=Decimal(0))
    # Trade gates (비대칭 — ADR 0018 / dgt-optimal-config).
    slope_gate: bool = False
    slope_gate_period: int = Field(default=5, ge=1)
    slope_gate_threshold: Decimal = Field(default=Decimal("0.05"), gt=Decimal(0))
    volume_gate: bool = False
    volume_gate_period: int = Field(default=20, ge=1)
    volume_gate_multiplier: Decimal = Field(default=Decimal("2.0"), gt=Decimal(0))

    @property
    def levels_above(self) -> int:
        return self.grid_count // 2


class GridState(ValueObject):
    """그리드 기하 상태 (불변). research ``_DGTGridState`` 의 cash/holdings 는

    Balance/Position 에서 오므로 제외 — 도메인 GridState 는 ``reference_price``
    + ``grid_levels`` (오름차순) 만 보유. reset 시 새 인스턴스 생성.
    """

    reference_price: Decimal = Field(gt=Decimal(0))
    grid_levels: tuple[Decimal, ...] = Field(min_length=2)


class GridDecision(ValueObject):
    """그리드 단일 거래 결정 (intent). 비용 미반영 — use_case 가 cost layered.

    ``level_index`` = ``grid_levels`` 내 인덱스 (Q7 idempotency key 재료).
    ``rounded_price`` = ``asset.round_to_tick(level_price)`` (체결가 기준).
    """

    side: OrderSide
    level_index: int = Field(ge=0)
    level_price: Decimal = Field(gt=Decimal(0))
    rounded_price: Decimal = Field(gt=Decimal(0))
    quantity: Decimal = Field(gt=Decimal(0))
    reasoning: dict[str, str]


class GridEvaluation(DomainModel):
    """GridStrategy.evaluate 출력 — 한 bar 의 그리드 결정 + 다음 그리드 상태.

    ``decisions`` 순서 = SELL(교차 오름차순) → BUY(교차 내림차순) (paper 자연
    순서). ``next_state`` = reset 후 그리드 (reset 없으면 입력 state 동일).
    """

    decisions: list[GridDecision]
    next_state: GridState
    reasoning: dict[str, str]


class GridStrategy:
    """DGT 그리드 전략 (stateless — 상태는 주입된 GridState + cash/holdings).

    한 거래일(bar) 단위 평가. research ``paper_adaptive_runner.run()`` 의 bar
    루프 1 회분을 cost-free 로 수행.
    """

    def evaluate(
        self,
        *,
        asset: Asset,
        bars: list[OHLCV],
        bar_idx: int,
        state: GridState,
        available_cash: Money,
        holdings: Decimal,
        config: GridConfig,
    ) -> GridEvaluation:
        if not (0 <= bar_idx < len(bars)):
            raise ValueError(f"bar_idx {bar_idx} out of range [0, {len(bars)})")
        if available_cash.currency != asset.currency:
            raise ValueError(
                f"available_cash.currency ({available_cash.currency.value}) != "
                f"asset.currency ({asset.currency.value})"
            )
        if holdings < 0:
            raise ValueError(f"holdings must be >= 0, got {holdings}")

        n = config.grid_count
        levels = list(state.grid_levels)
        curr_close = bars[bar_idx].close
        # bar_idx 0 → prev_close = curr (no crossing); else 전일 종가.
        prev_close = bars[bar_idx - 1].close if bar_idx > 0 else curr_close

        # 1. 교차 레벨 수집 (research run() 200-206 동일).
        crossed_up: list[tuple[int, Decimal]] = []
        crossed_down: list[tuple[int, Decimal]] = []
        for i, level in enumerate(levels):
            if prev_close < level <= curr_close:
                crossed_up.append((i, level))
            elif curr_close <= level < prev_close:
                crossed_down.append((i, level))

        # 2. Trade gates.
        sb_slope, ss_slope = self._slope_gate(bars, bar_idx, config)
        sb_vol, ss_vol = self._volume_gate(bars, bar_idx, config)
        skip_buy = sb_slope or sb_vol
        skip_sell = ss_slope or ss_vol

        # 3. 결정 emit — SELL(오름차순) → BUY(내림차순). cash/holdings 국소 진화.
        decisions: list[GridDecision] = []
        cash = available_cash.amount
        hold = holdings

        if not skip_sell:
            for i, level in crossed_up:
                dec = self._sell_decision(asset, i, level, hold, n)
                if dec is not None:
                    decisions.append(dec)
                    hold -= dec.quantity

        if not skip_buy:
            for i, level in reversed(crossed_down):
                dec = self._buy_decision(asset, i, level, cash, n)
                if dec is not None:
                    decisions.append(dec)
                    cash -= dec.rounded_price * dec.quantity

        # 4. Grid reset (research run() 228-245 동일).
        should_reset = config.rebalance_mode == "daily" or (
            len(levels) >= 2 and (curr_close > levels[-1] or curr_close < levels[0])
        )
        if should_reset:
            reference = curr_close
            k = adaptive_k(
                bars,
                bar_idx,
                curr_close,
                period=config.atr_period,
                multiplier=config.multiplier,
                k_min=config.k_min,
                k_max=config.k_max,
                fallback_k=config.fallback_k,
                measure=config.volatility_measure,
            )
            new_levels = grid_levels(n, reference, k, config.levels_above)
            next_state = GridState(
                reference_price=reference, grid_levels=tuple(new_levels)
            )
        else:
            next_state = state

        return GridEvaluation(
            decisions=decisions,
            next_state=next_state,
            reasoning={
                "asset": asset.fqn,
                "trade_date": bars[bar_idx].trade_date.isoformat(),
                "curr_close": str(curr_close),
                "prev_close": str(prev_close),
                "reference_price": str(state.reference_price),
                "crossed_up": str(len(crossed_up)),
                "crossed_down": str(len(crossed_down)),
                "skip_buy": str(skip_buy),
                "skip_sell": str(skip_sell),
                "reset": str(should_reset),
                "decisions": str(len(decisions)),
            },
        )

    # ------------------------------------------------------------------
    # Trade gates (research _check_slope_gate / _check_volume_gate 포팅)
    # ------------------------------------------------------------------
    def _slope_gate(
        self, bars: list[OHLCV], bar_idx: int, config: GridConfig
    ) -> tuple[bool, bool]:
        """(skip_buy, skip_sell) — 급락 시 매수 skip, 급등 시 매도 skip."""
        if not config.slope_gate or bar_idx < config.slope_gate_period:
            return False, False
        prev_close = bars[bar_idx - config.slope_gate_period].close
        curr_close = bars[bar_idx].close
        if prev_close <= 0:
            return False, False
        roc = (curr_close - prev_close) / prev_close
        skip_buy = roc < -config.slope_gate_threshold
        skip_sell = roc > config.slope_gate_threshold
        return skip_buy, skip_sell

    def _volume_gate(
        self, bars: list[OHLCV], bar_idx: int, config: GridConfig
    ) -> tuple[bool, bool]:
        """(skip_buy, skip_sell) — 거래량 급증+상승 시 매도 skip, 급증+하락 시 매수 skip."""
        if not config.volume_gate or bar_idx < config.volume_gate_period:
            return False, False
        start = bar_idx - config.volume_gate_period + 1
        vol_sum = sum(
            (bars[i].volume for i in range(start, bar_idx + 1)), Decimal("0")
        )
        vol_avg = vol_sum / Decimal(config.volume_gate_period)
        curr_vol = bars[bar_idx].volume
        if vol_avg <= 0 or curr_vol <= vol_avg * config.volume_gate_multiplier:
            return False, False
        prev_close = bars[bar_idx - 1].close if bar_idx > 0 else bars[bar_idx].close
        curr_close = bars[bar_idx].close
        if curr_close > prev_close:
            return False, True
        if curr_close < prev_close:
            return True, False
        return False, False

    # ------------------------------------------------------------------
    # 매수/매도 결정 (research _maybe_buy / _maybe_sell 포팅, cost-free)
    # ------------------------------------------------------------------
    def _sell_decision(
        self,
        asset: Asset,
        level_index: int,
        level_price: Decimal,
        holdings: Decimal,
        n: int,
    ) -> GridDecision | None:
        if holdings <= 0:
            return None
        quantity = (holdings / Decimal(n + 1)).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
        if quantity <= 0:
            return None
        rounded = asset.round_to_tick(level_price)
        return GridDecision(
            side=OrderSide.SELL,
            level_index=level_index,
            level_price=level_price,
            rounded_price=rounded,
            quantity=quantity,
            reasoning={
                "holdings": str(holdings),
                "n_plus_1": str(n + 1),
                "rounded_price": str(rounded),
            },
        )

    def _buy_decision(
        self,
        asset: Asset,
        level_index: int,
        level_price: Decimal,
        cash: Decimal,
        n: int,
    ) -> GridDecision | None:
        if level_price <= 0:
            return None
        allocation = cash / Decimal(n + 1)
        if allocation <= 0:
            return None
        quantity = (allocation / level_price).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
        if quantity <= 0:
            return None
        rounded = asset.round_to_tick(level_price)
        gross = rounded * quantity
        if gross > cash:  # 비용=0 가정 affordability (use_case 가 실비용 재검)
            return None
        return GridDecision(
            side=OrderSide.BUY,
            level_index=level_index,
            level_price=level_price,
            rounded_price=rounded,
            quantity=quantity,
            reasoning={
                "allocation": str(allocation),
                "n_plus_1": str(n + 1),
                "rounded_price": str(rounded),
                "gross": str(gross),
            },
        )
