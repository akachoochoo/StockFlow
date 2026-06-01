"""Tests for `_MinuteGridRunner` — ADR 0023 §10.2 / 세그먼트 1.2.2.c.

검증 전략:
1. 기본 invariant (empty bars / currency mismatch / 빈 거래 시 보존)
2. 단순 BUY/SELL 시나리오 (cost 무 / cost 적용)
3. Runtime state 게이트:
   - sell_cooldown_bars: 매도 후 N분 매수 금지
   - price_based_reentry: last_sell_price 이상 매수 차단
   - profit_guard: 평단 이하 매도 스킵
4. pnl_split / turnover / max_drawdown 계산
5. 실 KIS 5/29 069500 분봉 391봉 sanity (작동 가능 + 결정론)
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from src.cli.composition import kodex200
from src.domain.models import Currency, Money, OrderSide
from src.research.dgt_minute._csv_writer import _read_minute_csv
from src.research.dgt_minute._grid_strategy import _GridMinuteConfig
from src.research.dgt_minute._kis_minute_downloader import _MinuteBar
from src.research.dgt_minute._runner import _MinuteGridRunner


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


def _krw(amount: int) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.KRW)


def _config(**overrides: object) -> _GridMinuteConfig:
    base = {
        "grid_count": 4,
        "fallback_k": Decimal("0.01"),
        "rebalance_mode": "on_breach",
        "k_min": Decimal("0.001"),
        "k_max": Decimal("0.1"),
        "multiplier": Decimal("1.5"),
    }
    base.update(overrides)
    return _GridMinuteConfig(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------- #
class TestValidation:
    def test_empty_bars_raises(self) -> None:
        runner = _MinuteGridRunner()
        with pytest.raises(ValueError, match="non-empty"):
            runner.run(
                asset=kodex200(),
                bars=[],
                config=_config(),
                initial_capital=_krw(1_000_000),
            )

    def test_currency_mismatch_raises(self) -> None:
        runner = _MinuteGridRunner()
        bars = [_bar(minute=0, open=100, high=100, low=100, close=100)]
        with pytest.raises(ValueError, match="currency"):
            runner.run(
                asset=kodex200(),  # KRW
                bars=bars,
                config=_config(),
                initial_capital=Money(
                    amount=Decimal("1000"), currency=Currency.USD
                ),
            )


# --------------------------------------------------------------------- #
# Quiet bars — no trades
# --------------------------------------------------------------------- #
class TestQuietRun:
    def test_no_crossings_no_trades(self) -> None:
        runner = _MinuteGridRunner()
        # 일정한 close → 교차 zero (모든 bar prev=curr).
        bars = [
            _bar(minute=i, open=100, high=100, low=100, close=100)
            for i in range(5)
        ]
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=_config(),
            initial_capital=_krw(1_000_000),
        )
        assert result.trades == []
        assert result.final_cash == Decimal("1000000")
        assert result.final_holdings == Decimal("0")
        assert result.final_value == Decimal("1000000")
        # bar별 가치 = 모든 bar 동일.
        assert len(result.bar_values) == 5
        assert all(bv.total_value == Decimal("1000000") for bv in result.bar_values)


# --------------------------------------------------------------------- #
# Single SELL flow
# --------------------------------------------------------------------- #
class TestSellFlow:
    def test_holdings_decrement_on_sell(self) -> None:
        # initial holdings 시뮬: 첫 bar 에서 매수 → 다음 bar 에서 상향 교차 매도.
        # 그러나 _MinuteGridRunner.run 은 initial_capital 만 받음 (holdings=0 시작).
        # → SELL 만 시뮬 위해서는 첫 bar 에서 매수가 발생하도록 가격 구조 설계.
        # idx=0: close=98 (reference) → grid 형성 ~ 98 주변, k 작아 ±1.
        # 단순화: 0번째 close=100 (reference) → grid = [100*(1-2k), ..., 100*(1+2k)].
        # idx=1: close=80 → 하향 교차 → 첫 매수, idx=2: close=120 → 상향 교차 → 매도.
        bars = [
            _bar(minute=0, open=100, high=100, low=100, close=100),
            _bar(minute=1, open=100, high=100, low=80, close=80),
            _bar(minute=2, open=80, high=120, low=80, close=120),
        ]
        runner = _MinuteGridRunner()
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=_config(
                grid_count=4, fallback_k=Decimal("0.05"),  # 5% spacing → grid ≈ [90, 95, 100, 105, 110]
                rebalance_mode="on_breach",
            ),
            initial_capital=_krw(10_000_000),
        )
        # 적어도 1 BUY + 1 SELL 발생 기대 (가격이 grid 통과).
        buys = [t for t in result.trades if t.side == OrderSide.BUY]
        sells = [t for t in result.trades if t.side == OrderSide.SELL]
        assert len(buys) >= 1
        assert len(sells) >= 1


# --------------------------------------------------------------------- #
# Cooldown gate
# --------------------------------------------------------------------- #
class TestCooldownGate:
    def test_buy_blocked_during_cooldown(self) -> None:
        """매도 후 sell_cooldown_bars 동안 매수 차단 검증."""
        # 매도 트리거 → 다음 N bar 동안 매수 금지.
        # 시나리오: 매수→매도→직후 매수 시도 (cooldown 동안).
        bars = [
            _bar(minute=0, open=100, high=100, low=100, close=100),  # ref
            _bar(minute=1, open=100, high=100, low=80, close=80),    # BUY at 90 (cross down)
            _bar(minute=2, open=80, high=120, low=80, close=120),    # SELL at 110 (cross up)
            _bar(minute=3, open=120, high=120, low=80, close=85),    # BUY 시도 — cooldown 차단
            _bar(minute=4, open=85, high=85, low=80, close=80),      # BUY 시도 — cooldown 차단
            _bar(minute=5, open=80, high=80, low=75, close=78),      # cooldown 만료 — BUY 가능
        ]
        config = _config(
            grid_count=4,
            fallback_k=Decimal("0.05"),
            rebalance_mode="on_breach",
            sell_cooldown_bars=2,
        )
        runner = _MinuteGridRunner()
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=config,
            initial_capital=_krw(10_000_000),
        )
        # idx=1 BUY + idx=2 SELL + idx=3,4 차단 + idx=5 BUY 가능.
        # 실제 거래 발생은 grid 동작에 의존 — invariant 만 검증: 매도 직후
        # 매수가 cooldown 만큼 차단됐는가.
        sells_at = [t.trade_time.minute for t in result.trades if t.side == OrderSide.SELL]
        buys_at = [t.trade_time.minute for t in result.trades if t.side == OrderSide.BUY]
        # 적어도 1 매도 발생 후, cooldown 내 매수는 없어야 함.
        if sells_at:
            first_sell = sells_at[0]
            buys_during_cd = [
                m for m in buys_at if first_sell < m <= first_sell + 2
            ]
            assert buys_during_cd == [], (
                f"cooldown 위반: 매도 {first_sell}분 후 차단 동안 매수 {buys_during_cd}"
            )


# --------------------------------------------------------------------- #
# Price-based reentry gate
# --------------------------------------------------------------------- #
class TestPriceReentryGate:
    def test_buy_blocked_above_last_sell_price(self) -> None:
        """last_sell_price 이상의 가격에서 매수 차단."""
        bars = [
            _bar(minute=0, open=100, high=100, low=100, close=100),
            _bar(minute=1, open=100, high=100, low=80, close=80),    # BUY
            _bar(minute=2, open=80, high=120, low=80, close=120),    # SELL at ~110
            _bar(minute=3, open=120, high=120, low=80, close=115),   # 115 > 110 → 매수 차단
            _bar(minute=4, open=115, high=115, low=80, close=105),   # 105 < 110 → 매수 가능
        ]
        config = _config(
            grid_count=4,
            fallback_k=Decimal("0.05"),
            rebalance_mode="on_breach",
            price_based_reentry=True,
        )
        runner = _MinuteGridRunner()
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=config,
            initial_capital=_krw(10_000_000),
        )
        # invariant: 매도 후 last_sell_price 이상 가격 bar 에서는 BUY zero.
        sells = [t for t in result.trades if t.side == OrderSide.SELL]
        if sells:
            last_sell_price = sells[0].rounded_price
            # 매도 후 매수 중 close > last_sell_price 인 bar 의 매수는 없어야 함.
            buys_after = [
                t for t in result.trades
                if t.side == OrderSide.BUY and t.trade_time > sells[0].trade_time
            ]
            for t in buys_after:
                # 해당 bar 의 close 가 last_sell_price 이하여야 함.
                bar_close = next(
                    bv.close_price for bv in result.bar_values
                    if bv.trade_time == t.trade_time
                )
                assert bar_close <= last_sell_price, (
                    f"reentry 위반: 매수 가격 {bar_close} > last_sell_price "
                    f"{last_sell_price}"
                )


# --------------------------------------------------------------------- #
# Profit guard
# --------------------------------------------------------------------- #
class TestProfitGuard:
    def test_sell_skipped_below_avg_cost(self) -> None:
        """평단 이하 매도 스킵."""
        # 시나리오: 100 에 매수 → 90 으로 하락 → 매도 트리거 → profit_guard 스킵.
        bars = [
            _bar(minute=0, open=100, high=100, low=100, close=100),
            _bar(minute=1, open=100, high=100, low=90, close=90),    # BUY at ~95
            _bar(minute=2, open=90, high=92, low=85, close=85),      # 평단 이하 — SELL skip
        ]
        config = _config(
            grid_count=4,
            fallback_k=Decimal("0.05"),
            rebalance_mode="on_breach",
            profit_guard=True,
        )
        runner = _MinuteGridRunner()
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=config,
            initial_capital=_krw(10_000_000),
        )
        # profit_guard 활성 시 평단 이하 매도 없어야 함.
        for t in result.trades:
            if t.side == OrderSide.SELL:
                # 평단 이상 가격에서만 매도.
                assert t.rounded_price > result.final_avg_cost or result.final_holdings == 0


# --------------------------------------------------------------------- #
# Result metrics
# --------------------------------------------------------------------- #
class TestResultMetrics:
    def test_pnl_split_no_trades(self) -> None:
        runner = _MinuteGridRunner()
        bars = [
            _bar(minute=i, open=100, high=100, low=100, close=100)
            for i in range(3)
        ]
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=_config(),
            initial_capital=_krw(1_000_000),
        )
        realized, unrealized = result.pnl_split()
        assert realized == Decimal("0")
        assert unrealized == Decimal("0")

    def test_turnover_no_trades_zero(self) -> None:
        runner = _MinuteGridRunner()
        bars = [_bar(minute=0, open=100, high=100, low=100, close=100)]
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=_config(),
            initial_capital=_krw(1_000_000),
        )
        assert result.turnover() == Decimal("0")

    def test_max_drawdown_no_decline_zero(self) -> None:
        runner = _MinuteGridRunner()
        bars = [
            _bar(minute=i, open=100, high=100, low=100, close=100)
            for i in range(5)
        ]
        result = runner.run(
            asset=kodex200(),
            bars=bars,
            config=_config(),
            initial_capital=_krw(1_000_000),
        )
        assert result.max_drawdown() == Decimal("0")


# --------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------- #
class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        bars = [
            _bar(minute=0, open=100, high=100, low=100, close=100),
            _bar(minute=1, open=100, high=110, low=80, close=80),
            _bar(minute=2, open=80, high=120, low=80, close=120),
        ]
        config = _config(grid_count=4, fallback_k=Decimal("0.05"))
        runner_a = _MinuteGridRunner()
        runner_b = _MinuteGridRunner()
        r1 = runner_a.run(
            asset=kodex200(), bars=bars, config=config,
            initial_capital=_krw(10_000_000),
        )
        r2 = runner_b.run(
            asset=kodex200(), bars=bars, config=config,
            initial_capital=_krw(10_000_000),
        )
        assert r1.trades == r2.trades
        assert r1.final_cash == r2.final_cash
        assert r1.final_holdings == r2.final_holdings


# --------------------------------------------------------------------- #
# 실 KIS 5/29 069500 sanity
# --------------------------------------------------------------------- #
class TestRealKisData:
    @pytest.fixture
    def real_bars(self) -> list[_MinuteBar]:
        repo_root = Path(__file__).resolve().parent.parent.parent
        csv_path = (
            repo_root / "data" / "historical" / "minute" / "069500"
            / "2026-05-29.csv"
        )
        if not csv_path.exists():
            pytest.skip(f"{csv_path.name} not present (cron 1회 이상 실행 필요)")
        return _read_minute_csv(csv_path, asset_code="069500")

    def test_run_completes_without_error(
        self, real_bars: list[_MinuteBar]
    ) -> None:
        """391봉 실 데이터로 runner 가 결과를 반환 (crash zero)."""
        runner = _MinuteGridRunner()
        config = _config(
            grid_count=10,  # 11 levels
            fallback_k=Decimal("0.005"),  # 0.5%
            rebalance_mode="on_breach",
        )
        result = runner.run(
            asset=kodex200(),
            bars=real_bars,
            config=config,
            initial_capital=_krw(5_000_000),  # ADR 0023 D13 종목당 500만
        )
        assert len(result.bar_values) == 391
        assert result.final_value > Decimal("0")
        # MDD 는 sanity 만 — 0 ~ 1 범위.
        mdd = result.max_drawdown()
        assert Decimal("0") <= mdd <= Decimal("1")

    def test_determinism_with_real_data(
        self, real_bars: list[_MinuteBar]
    ) -> None:
        config = _config(
            grid_count=10, fallback_k=Decimal("0.005"),
            rebalance_mode="on_breach",
        )
        runner = _MinuteGridRunner()
        r1 = runner.run(
            asset=kodex200(), bars=real_bars, config=config,
            initial_capital=_krw(5_000_000),
        )
        r2 = runner.run(
            asset=kodex200(), bars=real_bars, config=config,
            initial_capital=_krw(5_000_000),
        )
        assert r1.trades == r2.trades
        assert r1.final_value == r2.final_value
