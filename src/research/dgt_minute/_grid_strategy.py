"""분봉 grid strategy — `_MinuteBar` 시계열 평가 (5th ring 격리).

ADR 0023 §10.2 / 세그먼트 1.2.2.b 산출. 일봉 `src/domain/strategies/grid.py`
의 `GridStrategy` 와 알고리즘 동일, 입력 타입만 `_MinuteBar` 로. inner ring
변경 zero (D17 일봉 invariant 보존). 1.2.2.c grid_minute_runner 의 의존성.

5th ring 격리 (D15): inner ring `GridStrategy` 와 별도 모듈. 분봉이 inner
ring production 진입 시점 (1.2.4 직전) 에 별도 ADR 박제 후 production
strategy 신규.

D6 (일봉 권고 직접 적용 금지): 모든 정책 옵션 = `_GridMinuteConfig` 노출 →
1.2.2.e sweep parameter. 일봉 §11.21 권고 A (cd=5d, N=9~10, price reentry)
은 분봉 의미 unproven — sweep 후 결정.

분봉 단위 의미 매핑:
- `sell_cooldown_bars` = 분 단위 (일봉 cd=5d ≈ 분봉 cd=5x390=1950)
- `slope_gate_period` = 분 단위
- `volume_gate_period` = 분 단위
- `atr_period` = 분 단위
- `rebalance_mode`: "daily" (매 bar = 매 분, 거의 미사용) / "on_breach" (분봉서 유효)
  / **"per_n_minutes"** (분봉 신규 — N분마다 재중심, sweep parameter `rebalance_period_bars`)

CLAUDE.md §2.1 (Decimal 전용) / §3.2 (시계 의존 zero, bar_idx 주입).
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from src.domain.models import DomainModel, OrderSide, ValueObject
from src.domain.strategies.grid_math import grid_levels

if TYPE_CHECKING:
    from src.domain.models import Asset, Money
    from src.research.dgt_minute._kis_minute_downloader import _MinuteBar


class _GridMinuteConfig(DomainModel):
    """분봉 DGT 그리드 설정 — 일봉 GridConfig 의 분봉 mirror.

    sweep parameter 영역 (1.2.2.e). 모든 단위 = 분봉 (period = 분).

    rebalance_mode:
    - "daily": 매 bar 후 재중심 (분봉 = 매 분, 노이즈 ↑)
    - "on_breach": grid 범위 밖 가격일 때만 재중심 (분봉서 가장 유효한 mode)
    - "per_n_bars": rebalance_period_bars 마다 재중심 (분봉 신규)
    """

    grid_count: int = Field(ge=2)
    fallback_k: Decimal = Field(gt=Decimal(0))
    rebalance_mode: Literal["on_breach", "daily", "per_n_bars"] = "on_breach"
    rebalance_period_bars: int = Field(default=30, ge=1)
    volatility_measure: Literal["atr", "adr"] = "adr"
    atr_period: int = Field(default=14, ge=1)
    multiplier: Decimal = Field(default=Decimal("1.5"), gt=Decimal(0))
    k_min: Decimal = Field(default=Decimal("0.001"), gt=Decimal(0))
    k_max: Decimal = Field(default=Decimal("0.05"), gt=Decimal(0))
    # Trade gates (분봉 단위, 일봉 §11.21 권고 직접 적용 금지 — sweep 영역).
    slope_gate: bool = False
    slope_gate_period: int = Field(default=5, ge=1)
    slope_gate_threshold: Decimal = Field(default=Decimal("0.005"), gt=Decimal(0))
    volume_gate: bool = False
    volume_gate_period: int = Field(default=20, ge=1)
    volume_gate_multiplier: Decimal = Field(default=Decimal("2.0"), gt=Decimal(0))
    profit_guard: bool = False
    sell_cooldown_bars: int = Field(default=0, ge=0)
    price_based_reentry: bool = False

    @property
    def levels_above(self) -> int:
        return self.grid_count // 2


class _GridMinuteState(ValueObject):
    """그리드 기하 상태 (불변) — 일봉 `GridState` 와 동일 구조.

    reset 시 새 인스턴스. cash/holdings 은 runner (1.2.2.c) 영역.
    """

    reference_price: Decimal = Field(gt=Decimal(0))
    grid_levels: tuple[Decimal, ...] = Field(min_length=2)


class _GridMinuteDecision(ValueObject):
    """그리드 단일 거래 결정 — `level_index` + `rounded_price` 매도/매수 의도."""

    side: OrderSide
    level_index: int = Field(ge=0)
    level_price: Decimal = Field(gt=Decimal(0))
    rounded_price: Decimal = Field(gt=Decimal(0))
    quantity: Decimal = Field(gt=Decimal(0))
    reasoning: dict[str, str]


class _GridMinuteEvaluation(DomainModel):
    """한 분봉의 grid 결정 + 다음 grid 상태.

    decisions 순서 = SELL(오름차순) → BUY(내림차순). next_state = reset 후
    grid (reset 없으면 입력 state 동일).
    """

    decisions: list[_GridMinuteDecision]
    next_state: _GridMinuteState
    reasoning: dict[str, str]


class _GridMinuteStrategy:
    """분봉 DGT 그리드 전략 (stateless — 일봉 GridStrategy mirror).

    한 분봉 단위 평가. 일봉 GridStrategy.evaluate 와 동일 알고리즘. bar_idx
    주입 (CLAUDE.md §3.2 시계 의존 zero).

    분봉 특수성:
    - 첫 bar (bar_idx=0) 의 prev_close = curr_close → 교차 zero (정상)
    - zero-volume 분봉 다수 → curr_close = prev_close → 교차 zero
    - rebalance_mode="per_n_bars" 분봉 신규: bar_idx % rebalance_period_bars == 0 시 재중심
    """

    def evaluate(
        self,
        *,
        asset: Asset,
        bars: list[_MinuteBar],
        bar_idx: int,
        state: _GridMinuteState,
        available_cash: Money,
        holdings: Decimal,
        config: _GridMinuteConfig,
    ) -> _GridMinuteEvaluation:
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
        prev_close = bars[bar_idx - 1].close if bar_idx > 0 else curr_close

        # 1. 교차 레벨 수집 (일봉 GridStrategy 와 동일).
        crossed_up: list[tuple[int, Decimal]] = []
        crossed_down: list[tuple[int, Decimal]] = []
        for i, level in enumerate(levels):
            if prev_close < level <= curr_close:
                crossed_up.append((i, level))
            elif curr_close <= level < prev_close:
                crossed_down.append((i, level))

        # 2. Trade gates (slope / volume 분봉 단위).
        skip_buy_slope, skip_sell_slope = self._slope_gate(bars, bar_idx, config)
        skip_buy_vol, skip_sell_vol = self._volume_gate(bars, bar_idx, config)
        skip_buy = skip_buy_slope or skip_buy_vol
        skip_sell = skip_sell_slope or skip_sell_vol

        # 3. 결정 emit — SELL(오름차순) → BUY(내림차순).
        decisions: list[_GridMinuteDecision] = []
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

        # 4. Grid reset 결정 (mode 별).
        should_reset = self._should_reset(
            config=config, bar_idx=bar_idx, curr_close=curr_close, levels=levels
        )
        if should_reset:
            reference = curr_close
            # `adaptive_k` 는 일봉 도메인용 (`list[OHLCV]` 기대). 분봉 bars 와
            # 시그니처 호환 안 됨 → 별도 5th ring helper (1.2.2.a 의
            # _volatility.py) 호출 패턴으로 변경. 다만 _volatility 는 raw value
            # 만 반환. adaptive k clamping 은 본 함수에서 직접 처리.
            k = self._compute_k(bars=bars, bar_idx=bar_idx, config=config)
            new_levels = grid_levels(n, reference, k, config.levels_above)
            next_state = _GridMinuteState(
                reference_price=reference, grid_levels=tuple(new_levels)
            )
        else:
            next_state = state

        return _GridMinuteEvaluation(
            decisions=decisions,
            next_state=next_state,
            reasoning={
                "asset": asset.fqn,
                "trade_date": bars[bar_idx].trade_date.isoformat(),
                "trade_time": bars[bar_idx].trade_time.isoformat(timespec="seconds"),
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
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _should_reset(
        *,
        config: _GridMinuteConfig,
        bar_idx: int,
        curr_close: Decimal,
        levels: list[Decimal],
    ) -> bool:
        """rebalance_mode 별 reset 판정."""
        if config.rebalance_mode == "daily":
            # 분봉서 "daily" = 매 bar reset (의미 상 per_n_bars=1 와 동일).
            return True
        if config.rebalance_mode == "per_n_bars":
            return bar_idx % config.rebalance_period_bars == 0
        # "on_breach": 가격이 grid 범위 밖일 때만.
        return len(levels) >= 2 and (
            curr_close > levels[-1] or curr_close < levels[0]
        )

    def _compute_k(
        self,
        *,
        bars: list[_MinuteBar],
        bar_idx: int,
        config: _GridMinuteConfig,
    ) -> Decimal:
        """adaptive_k 의 분봉 mirror — k = clamp(multiplier x vol/price, k_min, k_max).

        일봉 `adaptive_k` 의 `bars: list[OHLCV]` 시그니처 호환 불가 → 본 함수
        로 분봉 도메인 처리. fallback = config.fallback_k.
        """
        from src.research.dgt_minute._volatility import (
            _average_daily_range,
            _average_true_range,
        )

        if config.volatility_measure == "atr":
            vol = _average_true_range(bars, config.atr_period, bar_idx)
        else:
            vol = _average_daily_range(bars, config.atr_period, bar_idx)

        price = bars[bar_idx].close
        if vol <= 0 or price <= 0:
            return config.fallback_k
        k = config.multiplier * vol / price
        if k < config.k_min:
            return config.k_min
        if k > config.k_max:
            return config.k_max
        return k

    def _slope_gate(
        self,
        bars: list[_MinuteBar],
        bar_idx: int,
        config: _GridMinuteConfig,
    ) -> tuple[bool, bool]:
        """(skip_buy, skip_sell) — 분봉 N분 ROC 기준."""
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
        self,
        bars: list[_MinuteBar],
        bar_idx: int,
        config: _GridMinuteConfig,
    ) -> tuple[bool, bool]:
        """(skip_buy, skip_sell) — 거래량 급증+방향성 기준 (분봉 단위)."""
        if not config.volume_gate or bar_idx < config.volume_gate_period:
            return False, False
        start = bar_idx - config.volume_gate_period + 1
        vol_sum = sum(bars[i].volume for i in range(start, bar_idx + 1))
        vol_avg = Decimal(vol_sum) / Decimal(config.volume_gate_period)
        curr_vol = Decimal(bars[bar_idx].volume)
        if vol_avg <= 0 or curr_vol <= vol_avg * config.volume_gate_multiplier:
            return False, False
        prev_close = (
            bars[bar_idx - 1].close if bar_idx > 0 else bars[bar_idx].close
        )
        curr_close = bars[bar_idx].close
        if curr_close > prev_close:
            return False, True
        if curr_close < prev_close:
            return True, False
        return False, False

    def _sell_decision(
        self,
        asset: Asset,
        level_index: int,
        level_price: Decimal,
        holdings: Decimal,
        n: int,
    ) -> _GridMinuteDecision | None:
        if holdings <= 0:
            return None
        quantity = (holdings / Decimal(n + 1)).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
        if quantity <= 0:
            return None
        rounded = asset.round_to_tick(level_price)
        return _GridMinuteDecision(
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
    ) -> _GridMinuteDecision | None:
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
        if gross > cash:
            return None
        return _GridMinuteDecision(
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
