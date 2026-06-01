"""Tests for `_GridMinuteStrategy` — ADR 0023 §10.2 / 세그먼트 1.2.2.b.

검증 전략:
1. 일봉 GridStrategy 와 동일 알고리즘 검증 — 같은 OHLC 패턴 + Asset 입력 시
   동일 grid 결정 emit (D17 보존 의미).
2. 분봉 특수 패턴:
   - 첫 bar (idx=0): prev=curr → 교차 zero
   - zero-volume 분봉: prev=curr → 교차 zero
3. rebalance_mode 분기 (on_breach / daily / per_n_bars)
4. Trade gates (slope / volume) 분봉 단위
5. 실 KIS 5/29 069500 분봉 391봉 fixture 로 sanity check (다음 1.2.2.c 후
   동치 검증).

CLAUDE.md §2.1 — 모든 가격 Decimal.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from src.cli.composition import kodex200
from src.domain.models import Currency, Money, OrderSide
from src.research.dgt_minute._grid_strategy import (
    _GridMinuteConfig,
    _GridMinuteDecision,
    _GridMinuteState,
    _GridMinuteStrategy,
)
from src.research.dgt_minute._kis_minute_downloader import _MinuteBar


def _bar(
    *,
    minute: int,
    open: int,
    high: int,
    low: int,
    close: int,
    volume: int = 100,
) -> _MinuteBar:
    return _MinuteBar(
        asset_code="069500",
        trade_date=date(2026, 5, 29),
        trade_time=time(9, minute, 0),
        open=Decimal(str(open)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
    )


def _make_state(
    *,
    reference: int = 100,
    levels: tuple[int, ...] = (90, 95, 100, 105, 110),
) -> _GridMinuteState:
    return _GridMinuteState(
        reference_price=Decimal(reference),
        grid_levels=tuple(Decimal(level) for level in levels),
    )


def _krw(amount: int) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


# --------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------- #
class TestValidation:
    def test_bar_idx_out_of_range_raises(self) -> None:
        strategy = _GridMinuteStrategy()
        bars = [_bar(minute=0, open=100, high=100, low=100, close=100)]
        with pytest.raises(ValueError, match="bar_idx"):
            strategy.evaluate(
                asset=kodex200(),
                bars=bars,
                bar_idx=5,
                state=_make_state(),
                available_cash=_krw(1_000_000),
                holdings=Decimal("0"),
                config=_GridMinuteConfig(grid_count=4, fallback_k=Decimal("0.01")),
            )

    def test_negative_holdings_raises(self) -> None:
        strategy = _GridMinuteStrategy()
        bars = [_bar(minute=0, open=100, high=100, low=100, close=100)]
        with pytest.raises(ValueError, match="holdings"):
            strategy.evaluate(
                asset=kodex200(),
                bars=bars,
                bar_idx=0,
                state=_make_state(),
                available_cash=_krw(1_000_000),
                holdings=Decimal("-1"),
                config=_GridMinuteConfig(grid_count=4, fallback_k=Decimal("0.01")),
            )


# --------------------------------------------------------------------- #
# 첫 bar (idx=0) — prev=curr → 교차 zero
# --------------------------------------------------------------------- #
class TestFirstBar:
    def test_first_bar_no_crossings(self) -> None:
        strategy = _GridMinuteStrategy()
        bars = [_bar(minute=0, open=100, high=120, low=80, close=105)]
        result = strategy.evaluate(
            asset=kodex200(),
            bars=bars,
            bar_idx=0,
            state=_make_state(),
            available_cash=_krw(1_000_000),
            holdings=Decimal("0"),
            config=_GridMinuteConfig(
                grid_count=4,
                fallback_k=Decimal("0.01"),
                rebalance_mode="on_breach",
            ),
        )
        assert result.decisions == []
        assert result.reasoning["crossed_up"] == "0"
        assert result.reasoning["crossed_down"] == "0"


# --------------------------------------------------------------------- #
# Crossings
# --------------------------------------------------------------------- #
class TestCrossings:
    def test_upward_crossing_emits_sell(self) -> None:
        strategy = _GridMinuteStrategy()
        # idx=0: close=98 / idx=1: close=102 → cross level 100 upward.
        bars = [
            _bar(minute=0, open=98, high=99, low=97, close=98),
            _bar(minute=1, open=98, high=103, low=98, close=102),
        ]
        result = strategy.evaluate(
            asset=kodex200(),
            bars=bars,
            bar_idx=1,
            state=_make_state(),
            available_cash=_krw(1_000_000),
            holdings=Decimal("100"),
            config=_GridMinuteConfig(
                grid_count=4,
                fallback_k=Decimal("0.01"),
                rebalance_mode="on_breach",
            ),
        )
        sells = [d for d in result.decisions if d.side == OrderSide.SELL]
        assert len(sells) == 1
        assert sells[0].level_price == Decimal("100")
        # quantity = holdings / (n+1) = 100/5 = 20
        assert sells[0].quantity == Decimal("20")

    def test_downward_crossing_emits_buy(self) -> None:
        strategy = _GridMinuteStrategy()
        # idx=0: close=102 / idx=1: close=98 → cross level 100 downward.
        bars = [
            _bar(minute=0, open=102, high=103, low=101, close=102),
            _bar(minute=1, open=102, high=102, low=97, close=98),
        ]
        result = strategy.evaluate(
            asset=kodex200(),
            bars=bars,
            bar_idx=1,
            state=_make_state(),
            available_cash=_krw(1_000_000),
            holdings=Decimal("0"),
            config=_GridMinuteConfig(
                grid_count=4,
                fallback_k=Decimal("0.01"),
                rebalance_mode="on_breach",
            ),
        )
        buys = [d for d in result.decisions if d.side == OrderSide.BUY]
        assert len(buys) == 1
        assert buys[0].level_price == Decimal("100")

    def test_zero_volume_no_crossing(self) -> None:
        """zero-volume 분봉 = prev=curr → 교차 zero."""
        strategy = _GridMinuteStrategy()
        bars = [
            _bar(minute=0, open=100, high=100, low=100, close=100),
            _bar(minute=1, open=100, high=100, low=100, close=100, volume=0),
        ]
        result = strategy.evaluate(
            asset=kodex200(),
            bars=bars,
            bar_idx=1,
            state=_make_state(),
            available_cash=_krw(1_000_000),
            holdings=Decimal("100"),
            config=_GridMinuteConfig(
                grid_count=4,
                fallback_k=Decimal("0.01"),
                rebalance_mode="on_breach",
            ),
        )
        assert result.decisions == []


# --------------------------------------------------------------------- #
# Rebalance modes
# --------------------------------------------------------------------- #
class TestRebalanceMode:
    def _eval(
        self, *, mode: str, period: int, bar_idx: int, curr_close: int
    ) -> bool:
        strategy = _GridMinuteStrategy()
        # bar 시계열: bar_idx+1 까지, 마지막 close 만 의미 있음.
        bars = [
            _bar(minute=i, open=100, high=100, low=100, close=100)
            for i in range(bar_idx)
        ]
        bars.append(
            _bar(
                minute=bar_idx,
                open=curr_close,
                high=curr_close,
                low=curr_close,
                close=curr_close,
            )
        )
        # grid 범위 = [90, 110], reference = 100.
        state = _make_state()
        result = strategy.evaluate(
            asset=kodex200(),
            bars=bars,
            bar_idx=bar_idx,
            state=state,
            available_cash=_krw(1_000_000),
            holdings=Decimal("100"),
            config=_GridMinuteConfig(
                grid_count=4,
                fallback_k=Decimal("0.01"),
                rebalance_mode=mode,  # type: ignore[arg-type]
                rebalance_period_bars=period,
            ),
        )
        return result.reasoning["reset"] == "True"

    def test_daily_always_resets(self) -> None:
        # daily = 매 bar reset
        assert self._eval(mode="daily", period=30, bar_idx=5, curr_close=100)

    def test_on_breach_inside_no_reset(self) -> None:
        # close=95 ∈ [90, 110] → no reset
        assert not self._eval(
            mode="on_breach", period=30, bar_idx=5, curr_close=95
        )

    def test_on_breach_above_resets(self) -> None:
        # close=120 > 110 → reset
        assert self._eval(
            mode="on_breach", period=30, bar_idx=5, curr_close=120
        )

    def test_on_breach_below_resets(self) -> None:
        # close=80 < 90 → reset
        assert self._eval(
            mode="on_breach", period=30, bar_idx=5, curr_close=80
        )

    def test_per_n_bars_mod_zero(self) -> None:
        # bar_idx=30, period=30 → reset (30 % 30 == 0)
        assert self._eval(
            mode="per_n_bars", period=30, bar_idx=30, curr_close=100
        )

    def test_per_n_bars_mod_non_zero(self) -> None:
        # bar_idx=15, period=30 → no reset
        assert not self._eval(
            mode="per_n_bars", period=30, bar_idx=15, curr_close=100
        )


# --------------------------------------------------------------------- #
# Trade gates
# --------------------------------------------------------------------- #
class TestSlopeGate:
    def test_slope_gate_off_no_skip(self) -> None:
        strategy = _GridMinuteStrategy()
        bars = [
            _bar(minute=i, open=100, high=100, low=100, close=100)
            for i in range(10)
        ]
        # 급등: idx=9 close=200 (5분 전 100 → roc=1.0)
        bars[9] = _bar(minute=9, open=100, high=200, low=100, close=200)
        result = strategy.evaluate(
            asset=kodex200(),
            bars=bars,
            bar_idx=9,
            state=_make_state(reference=200, levels=(80, 90, 100, 110, 120)),
            available_cash=_krw(1_000_000),
            holdings=Decimal("100"),
            config=_GridMinuteConfig(
                grid_count=4,
                fallback_k=Decimal("0.01"),
                rebalance_mode="on_breach",
                slope_gate=False,  # OFF
                slope_gate_period=5,
                slope_gate_threshold=Decimal("0.5"),
            ),
        )
        assert result.reasoning["skip_sell"] == "False"

    def test_slope_gate_sell_skip_on_rise(self) -> None:
        strategy = _GridMinuteStrategy()
        # idx=0~4: close=100, idx=5: close=200 → roc 5분=1.0 > 0.5 threshold
        bars = [
            _bar(minute=i, open=100, high=100, low=100, close=100)
            for i in range(5)
        ]
        bars.append(_bar(minute=5, open=100, high=200, low=100, close=200))
        result = strategy.evaluate(
            asset=kodex200(),
            bars=bars,
            bar_idx=5,
            state=_make_state(reference=100, levels=(150, 170)),
            available_cash=_krw(1_000_000),
            holdings=Decimal("100"),
            config=_GridMinuteConfig(
                grid_count=4,
                fallback_k=Decimal("0.01"),
                rebalance_mode="on_breach",
                slope_gate=True,
                slope_gate_period=5,
                slope_gate_threshold=Decimal("0.5"),
            ),
        )
        assert result.reasoning["skip_sell"] == "True"


# --------------------------------------------------------------------- #
# Decision helpers
# --------------------------------------------------------------------- #
class TestDecisionInternals:
    def test_sell_decision_zero_holdings_returns_none(self) -> None:
        strategy = _GridMinuteStrategy()
        dec = strategy._sell_decision(
            kodex200(), level_index=2, level_price=Decimal("100"),
            holdings=Decimal("0"), n=4,
        )
        assert dec is None

    def test_buy_decision_zero_cash_returns_none(self) -> None:
        strategy = _GridMinuteStrategy()
        dec = strategy._buy_decision(
            kodex200(), level_index=2, level_price=Decimal("100"),
            cash=Decimal("0"), n=4,
        )
        assert dec is None

    def test_sell_quantity_floor_division(self) -> None:
        strategy = _GridMinuteStrategy()
        # holdings=7, n+1=5 → 7/5 = 1.4 → floor = 1
        dec = strategy._sell_decision(
            kodex200(), level_index=2, level_price=Decimal("100"),
            holdings=Decimal("7"), n=4,
        )
        assert isinstance(dec, _GridMinuteDecision)
        assert dec.quantity == Decimal("1")
