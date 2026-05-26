"""GridRunner — research end-to-end 동치 + 결정론 (ADR 0022 G1 증분 3b).

GridRunner(zero-cost) 가 research ``_DGTPaperAdaptiveRunner``(zero-cost) 와
trades(비용 분해 포함) + 최종 cash/holdings + 일별 total_value 까지 bit-identical
임을 잠근다 — 도메인 grid 엔진의 end-to-end 포트 충실성. + 결정론(G2 §7.4) +
with-cost 스모크.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from src.cli.composition import asset_from_code
from src.domain.cost_model import KoreanMarketCostModel
from src.domain.models import OHLCV, Currency, Money, OrderSide
from src.domain.strategies.grid import GridConfig
from src.research.dgt.adaptive_runner import _AdaptiveConfig
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.paper_adaptive_runner import _DGTPaperAdaptiveRunner
from src.research.dgt.runner import _DGTConfig
from src.use_cases.grid_runner import GridRunner

_ASSET = asset_from_code("069500")
_CAPITAL = Money(amount=Decimal("100000000"), currency=Currency.KRW)

_CLOSES = [
    "35000", "36400", "38200", "37100", "34500", "32800", "31000", "33200",
    "35600", "38800", "41200", "39500", "36900", "34100", "31500", "29800",
    "32400", "35100", "37800", "40500", "42100", "39700", "36300", "33800",
    "30900", "28500", "31200", "34600", "37200", "39900",
]
_VOLS = [Decimal("1000000")] * len(_CLOSES)
_VOLS[20] = Decimal("6000000")


def _bars() -> list[OHLCV]:
    base = date(2024, 1, 1)
    closes = [Decimal(c) for c in _CLOSES]
    out: list[OHLCV] = []
    for i, c in enumerate(closes):
        opn = closes[i - 1] if i > 0 else c
        out.append(
            OHLCV(
                asset=_ASSET,
                trade_date=base + timedelta(days=i),
                open=opn,
                high=max(opn, c) * Decimal("1.01"),
                low=min(opn, c) * Decimal("0.99"),
                close=c,
                volume=_VOLS[i],
            )
        )
    return out


def _domain_config() -> GridConfig:
    return GridConfig(
        grid_count=11,
        fallback_k=Decimal("0.05"),
        rebalance_mode="daily",
        volatility_measure="adr",
        atr_period=14,
        multiplier=Decimal("1.5"),
        k_min=Decimal("0.02"),
        k_max=Decimal("0.10"),
        volume_gate=True,
        volume_gate_period=10,
        volume_gate_multiplier=Decimal("1.5"),
    )


def _research_zero() -> _DGTPaperAdaptiveRunner:
    return _DGTPaperAdaptiveRunner(
        cost_model=_KoreanMarketCostModel(
            commission_rate=Decimal("0"),
            etf_tax_rate=Decimal("0"),
            stock_tax_rate=Decimal("0"),
        ),
        config=_DGTConfig(grid_count=11, grid_spacing_pct=Decimal("5"), levels_above=5),
        adaptive=_AdaptiveConfig(),
        rebalance_mode="daily",
        volatility_measure="adr",
        volume_gate=True,
        volume_gate_period=10,
        volume_gate_multiplier=Decimal("1.5"),
    )


class TestResearchEndToEndEquivalence:
    def test_trades_balance_daily_bit_identical_zero_cost(self):
        bars = _bars()
        zero_cost = KoreanMarketCostModel(
            commission_rate=Decimal("0"),
            etf_tax_rate=Decimal("0"),
            stock_tax_rate=Decimal("0"),
        )
        result = GridRunner(cost_model=zero_cost).run(
            asset=_ASSET, bars=bars, config=_domain_config(), initial_capital=_CAPITAL
        )
        res = _research_zero().run(
            _ASSET, bars[0].trade_date, bars[-1].trade_date, _CAPITAL, bars
        )

        my_trades = [
            (t.side.value, t.level_price, t.quantity, t.rounded_price,
             t.gross, t.tax, t.commission, t.cash_delta)
            for t in result.trades
        ]
        res_trades = [
            (t.side, t.grid_level_price, t.quantity, t.rounded_price,
             t.gross, t.tax, t.commission, t.cash_delta)
            for t in res.trades
        ]
        assert my_trades == res_trades
        assert result.final_cash == res.final_cash
        assert result.final_holdings == res.final_holdings
        assert [(d.trade_date, d.total_value) for d in result.daily_values] == [
            (s.trade_date, s.total_value) for s in res.daily_snapshots
        ]

    def test_non_trivial(self):
        bars = _bars()
        result = GridRunner().run(
            asset=_ASSET, bars=bars, config=_domain_config(), initial_capital=_CAPITAL
        )
        # non-vacuous: 실제 거래 발생 (zero-cost 동치 테스트가 양방향을 정밀 검증).
        assert len(result.trades) >= 2


class TestDeterminism:
    def test_same_bars_same_result(self):
        bars = _bars()
        cfg = _domain_config()
        r1 = GridRunner().run(asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL)
        r2 = GridRunner().run(asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL)
        assert r1 == r2


class TestWithCost:
    def test_cost_reduces_value_and_records_friction(self):
        bars = _bars()
        cfg = _domain_config()
        zero = GridRunner(
            cost_model=KoreanMarketCostModel(
                commission_rate=Decimal("0"),
                etf_tax_rate=Decimal("0"),
                stock_tax_rate=Decimal("0"),
            )
        ).run(asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL)
        costed = GridRunner().run(
            asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL
        )
        # 실비용 적용 시 매도 tax/commission > 0 기록.
        sells = [t for t in costed.trades if t.side.value == "SELL"]
        assert sells and all(t.tax > 0 and t.commission > 0 for t in sells)
        # 비용은 가치를 잠식 (동일 거래라면 final_value 비용판 <= 무비용판).
        assert costed.final_value <= zero.final_value

    def test_mdd_computable_from_daily(self):
        bars = _bars()
        result = GridRunner().run(
            asset=_ASSET, bars=bars, config=_domain_config(), initial_capital=_CAPITAL
        )
        values = [d.total_value for d in result.daily_values]
        peak = values[0]
        mdd = Decimal("0")
        for v in values:
            peak = max(peak, v)
            dd = (v - peak) / peak
            mdd = min(mdd, dd)
        assert mdd <= 0  # drawdown 은 음수 또는 0
        assert len(values) == len(bars)


class TestGuards:
    def test_empty_bars_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            GridRunner().run(
                asset=_ASSET, bars=[], config=_domain_config(), initial_capital=_CAPITAL
            )

    def test_currency_mismatch_raises(self):
        with pytest.raises(ValueError, match="currency"):
            GridRunner().run(
                asset=_ASSET,
                bars=_bars(),
                config=_domain_config(),
                initial_capital=Money(amount=Decimal("1000"), currency=Currency.USD),
            )


# ---------------------------------------------------------------------------
# profit_guard (ADR 0022 D7) — 평단 이하 매도 억제
# ---------------------------------------------------------------------------
def _below_avg_sells(trades: list) -> int:
    """체결가 ≤ 그 시점 가중평균 매수가인 SELL 개수 (GridRunner avg_cost 미러)."""
    hold = Decimal("0")
    avg = Decimal("0")
    count = 0
    for t in trades:
        if t.side is OrderSide.BUY:
            avg = (avg * hold + t.rounded_price * t.quantity) / (hold + t.quantity)
            hold += t.quantity
        else:
            if avg > 0 and t.rounded_price <= avg:
                count += 1
            hold -= t.quantity
    return count


class TestProfitGuard:
    def test_default_off(self):
        assert _domain_config().profit_guard is False

    def test_on_skips_all_below_avg_sells(self):
        # on_breach 모드 데이터엔 평단 이하 매도가 존재 (OFF 기준선).
        base = _domain_config().model_copy(update={"rebalance_mode": "on_breach"})
        off = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=base, initial_capital=_CAPITAL
        )
        assert _below_avg_sells(off.trades) > 0  # 데이터 유효성: OFF엔 평단 이하 매도 有

        on = GridRunner().run(
            asset=_ASSET, bars=_bars(),
            config=base.model_copy(update={"profit_guard": True}),
            initial_capital=_CAPITAL,
        )
        # 불변: profit_guard ON 이면 평단 이하 매도가 0
        assert _below_avg_sells(on.trades) == 0
        # guard 는 매도만 제거 (매수/총 매도 수 ≤ OFF)
        n_off = sum(t.side is OrderSide.SELL for t in off.trades)
        n_on = sum(t.side is OrderSide.SELL for t in on.trades)
        assert 0 < n_on < n_off

    def test_off_unchanged_regression(self):
        # profit_guard 기본(off) → 명시 off 와 동일 (회귀 invariant).
        cfg = _domain_config()
        r1 = GridRunner().run(asset=_ASSET, bars=_bars(), config=cfg, initial_capital=_CAPITAL)
        r2 = GridRunner().run(
            asset=_ASSET, bars=_bars(),
            config=cfg.model_copy(update={"profit_guard": False}),
            initial_capital=_CAPITAL,
        )
        assert r1.final_value == r2.final_value
        assert len(r1.trades) == len(r2.trades)


# ---------------------------------------------------------------------------
# 바별 활성 그리드 기록 (시변 차트용, ADR 0022 §11.8 A)
# ---------------------------------------------------------------------------
class TestDailyGridLevels:
    def test_each_daily_value_records_grid(self):
        res = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=_domain_config(), initial_capital=_CAPITAL
        )
        assert len(res.daily_values) == len(_bars())
        n_levels = _domain_config().grid_count + 1
        for d in res.daily_values:
            assert len(d.grid_levels) == n_levels  # 매 바 활성 그리드 기록

    def test_on_breach_grid_moves_across_resets(self):
        # on_breach: 가격이 envelope 이탈하면 재중심 → 바별 그리드가 달라짐.
        cfg = _domain_config().model_copy(update={"rebalance_mode": "on_breach"})
        res = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=cfg, initial_capital=_CAPITAL
        )
        distinct = {d.grid_levels for d in res.daily_values}
        assert len(distinct) > 1  # 리셋으로 그리드가 1개 이상 이동


# ---------------------------------------------------------------------------
# 게이트 억제 이벤트 표면화 (시각화용, ADR 0022 §11.10)
# ---------------------------------------------------------------------------
def _accumulate_then_jump_bars() -> list[OHLCV]:
    """하락(매수 누적) 후 급등 → bar_idx 6 에서 slope 게이트가 매도 억제."""
    base = date(2024, 1, 1)
    closes = ["30000", "29000", "28000", "27000", "26000", "25000", "33000"]
    out: list[OHLCV] = []
    for i, c in enumerate(closes):
        cc = Decimal(c)
        opn = Decimal(closes[i - 1]) if i > 0 else cc
        out.append(
            OHLCV(
                asset=_ASSET,
                trade_date=base + timedelta(days=i),
                open=opn,
                high=max(opn, cc) * Decimal("1.01"),
                low=min(opn, cc) * Decimal("0.99"),
                close=cc,
                volume=Decimal("1000000"),
            )
        )
    return out


class TestGateEvents:
    def _cfg(self, **kw: object) -> GridConfig:
        base: dict[str, object] = {
            "grid_count": 4,
            "fallback_k": Decimal("0.05"),
            "rebalance_mode": "daily",
            "volatility_measure": "adr",
            "slope_gate": False,
            "slope_gate_period": 5,
            "slope_gate_threshold": Decimal("0.05"),
            "volume_gate": False,
        }
        base.update(kw)
        return GridConfig(**base)  # type: ignore[arg-type]

    def test_slope_skip_surfaced_in_result(self):
        res = GridRunner().run(
            asset=_ASSET, bars=_accumulate_then_jump_bars(),
            config=self._cfg(slope_gate=True), initial_capital=_CAPITAL,
        )
        sells = [e for e in res.gate_events if e.side is OrderSide.SELL]
        assert sells  # 매도 억제가 결과에 표면화
        assert sells[0].reasoning["gate"] == "slope"
        assert sells[0].level_prices

    def test_no_gate_events_when_gates_off(self):
        res = GridRunner().run(
            asset=_ASSET, bars=_accumulate_then_jump_bars(),
            config=self._cfg(), initial_capital=_CAPITAL,
        )
        assert res.gate_events == []  # 게이트 off → 억제 이벤트 0 (회귀)


# ---------------------------------------------------------------------------
# 실현/미실현 손익 분해 (수익 로그 — ADR 0022 §11.11)
# ---------------------------------------------------------------------------
def _won_total(res: object) -> Decimal:
    """반올림 총손익 (정수 원) — pnl_split 합산 대상."""
    return (res.final_value - _CAPITAL.amount).quantize(  # type: ignore[attr-defined]
        Decimal("1"), rounding=ROUND_HALF_UP
    )


class TestPnlSplit:
    def test_sums_to_total_with_cost(self):
        # 핵심 불변: 실현 + 미실현 = round(final_value - 초기자본) (실비용에서도 정확).
        res = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=_domain_config(),
            initial_capital=_CAPITAL,
        )
        realized, unrealized = res.pnl_split()
        assert realized + unrealized == _won_total(res)

    def test_sums_to_total_zero_cost(self):
        zero = KoreanMarketCostModel(
            commission_rate=Decimal("0"),
            etf_tax_rate=Decimal("0"),
            stock_tax_rate=Decimal("0"),
        )
        res = GridRunner(cost_model=zero).run(
            asset=_ASSET, bars=_bars(), config=_domain_config(),
            initial_capital=_CAPITAL,
        )
        realized, unrealized = res.pnl_split()
        assert realized + unrealized == _won_total(res)

    def test_pnl_values_are_whole_won(self):
        # KRW 불가분 — 실현/미실현 모두 정수 원.
        res = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=_domain_config(),
            initial_capital=_CAPITAL,
        )
        realized, unrealized = res.pnl_split()
        assert realized == realized.quantize(Decimal("1"))
        assert unrealized == unrealized.quantize(Decimal("1"))

    def test_no_sells_means_zero_realized(self):
        # 단조 하락 + daily rebalance → 매수만 → 실현 0, 미실현 = 전체 손익.
        base = date(2024, 1, 1)
        closes = ["30000", "29000", "28000", "27000", "26000", "25000", "24000"]
        bars = [
            OHLCV(
                asset=_ASSET, trade_date=base + timedelta(days=i),
                open=Decimal(closes[i - 1]) if i > 0 else Decimal(c),
                high=max(Decimal(closes[i - 1]) if i > 0 else Decimal(c), Decimal(c))
                * Decimal("1.01"),
                low=min(Decimal(closes[i - 1]) if i > 0 else Decimal(c), Decimal(c))
                * Decimal("0.99"),
                close=Decimal(c), volume=Decimal("1000000"),
            )
            for i, c in enumerate(closes)
        ]
        cfg = _domain_config().model_copy(update={"volume_gate": False})
        res = GridRunner().run(
            asset=_ASSET, bars=bars, config=cfg, initial_capital=_CAPITAL
        )
        assert res.trades and all(t.side is OrderSide.BUY for t in res.trades)
        realized, unrealized = res.pnl_split()
        assert realized == Decimal("0")
        assert unrealized == _won_total(res)


# ---------------------------------------------------------------------------
# 매도 후 매수 쿨다운 (ADR 0022 §11.13)
# ---------------------------------------------------------------------------
def _buy_within_n_after_sell(trades: list, dates: list, n: int) -> bool:
    """매도 bar 후 n 거래일 이내 매수가 있으면 True (쿨다운 위반)."""
    idx = {d: i for i, d in enumerate(dates)}
    sells = [idx[t.trade_date] for t in trades if t.side is OrderSide.SELL]
    buys = [idx[t.trade_date] for t in trades if t.side is OrderSide.BUY]
    return any(s < b <= s + n for s in sells for b in buys)


# 타이트 진동 시퀀스 — on_breach 그리드 유지, 매수↔매도 교대 (쿨다운 노출).
_OSC = [
    "1000", "990", "980", "970", "980", "990", "1000", "1010", "1000", "990",
    "980", "990", "1000", "1010", "1020", "1010", "1000", "990", "980", "990",
]


def _osc_bars() -> list[OHLCV]:
    b0 = date(2024, 1, 1)
    cl = [Decimal(c) for c in _OSC]
    return [
        OHLCV(
            asset=_ASSET, trade_date=b0 + timedelta(days=i),
            open=cl[i - 1] if i > 0 else c,
            high=max(cl[i - 1] if i > 0 else c, c) * Decimal("1.01"),
            low=min(cl[i - 1] if i > 0 else c, c) * Decimal("0.99"),
            close=c, volume=Decimal("1000000"),
        )
        for i, c in enumerate(cl)
    ]


def _osc_cfg(**kw: object) -> GridConfig:
    base = GridConfig(
        grid_count=6, fallback_k=Decimal("0.01"), rebalance_mode="on_breach",
        volatility_measure="adr", k_min=Decimal("0.005"), k_max=Decimal("0.02"),
    )
    return base.model_copy(update=kw)


class TestSellCooldown:
    def test_default_off(self):
        assert _domain_config().sell_cooldown_bars == 0

    def test_off_unchanged_regression(self):
        bars = _osc_bars()
        r1 = GridRunner().run(
            asset=_ASSET, bars=bars, config=_osc_cfg(), initial_capital=_CAPITAL
        )
        r2 = GridRunner().run(
            asset=_ASSET, bars=bars,
            config=_osc_cfg(sell_cooldown_bars=0), initial_capital=_CAPITAL,
        )
        assert r1.final_value == r2.final_value
        assert len(r1.trades) == len(r2.trades)

    def test_blocks_buys_within_window(self):
        bars = _osc_bars()
        dates = [b.trade_date for b in bars]
        base = GridRunner().run(
            asset=_ASSET, bars=bars, config=_osc_cfg(), initial_capital=_CAPITAL
        )
        cd = GridRunner().run(
            asset=_ASSET, bars=bars,
            config=_osc_cfg(sell_cooldown_bars=5), initial_capital=_CAPITAL,
        )
        # 비자명성: 베이스라인엔 매도 후 5바 내 매수가 실제로 존재.
        assert _buy_within_n_after_sell(base.trades, dates, 5)
        # 불변: 쿨다운 run 은 매도 후 5바 내 매수 0.
        assert not _buy_within_n_after_sell(cd.trades, dates, 5)
        # 매수가 실제로 차단되어 줄어듦.
        n_base = sum(t.side is OrderSide.BUY for t in base.trades)
        n_cd = sum(t.side is OrderSide.BUY for t in cd.trades)
        assert n_cd < n_base

    def test_sells_not_blocked(self):
        # 쿨다운은 매수만 막고 매도는 그대로 (방향 비대칭).
        bars = _osc_bars()
        base = GridRunner().run(
            asset=_ASSET, bars=bars, config=_osc_cfg(), initial_capital=_CAPITAL
        )
        cd = GridRunner().run(
            asset=_ASSET, bars=bars,
            config=_osc_cfg(sell_cooldown_bars=5), initial_capital=_CAPITAL,
        )
        base_sells = [t.trade_date for t in base.trades if t.side is OrderSide.SELL]
        cd_sells = [t.trade_date for t in cd.trades if t.side is OrderSide.SELL]
        assert base_sells == cd_sells  # 매도는 쿨다운 영향 없음 (동일)

    def test_longer_cooldown_blocks_more(self):
        bars = _osc_bars()
        runs = {
            n: GridRunner().run(
                asset=_ASSET, bars=bars,
                config=_osc_cfg(sell_cooldown_bars=n), initial_capital=_CAPITAL,
            )
            for n in (0, 2, 10)
        }
        buys = {
            n: sum(t.side is OrderSide.BUY for t in r.trades)
            for n, r in runs.items()
        }
        assert buys[0] >= buys[2] >= buys[10]  # 긴 쿨다운일수록 매수 ≤


# ---------------------------------------------------------------------------
# 리포트 메트릭: 평단가(final_avg_cost) / 회전율(turnover) (ADR 0022 §11.14)
# ---------------------------------------------------------------------------
class TestReportingMetrics:
    def test_turnover_matches_gross_over_capital(self):
        res = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=_domain_config(),
            initial_capital=_CAPITAL,
        )
        gross = sum((t.gross for t in res.trades), Decimal("0"))
        assert res.turnover() == gross / _CAPITAL.amount
        assert res.turnover() >= 0

    def test_final_avg_cost_within_buy_range(self):
        res = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=_domain_config(),
            initial_capital=_CAPITAL,
        )
        buy_px = [t.rounded_price for t in res.trades if t.side is OrderSide.BUY]
        assert buy_px and res.final_holdings > 0
        # 평단 = 매수 체결가 가중평균 → [최저 매수가, 최고 매수가] 범위 내.
        assert min(buy_px) <= res.final_avg_cost <= max(buy_px)

    def test_avg_cost_default_zero(self):
        # 매수 없는(보유 0) 결과의 평단 기본값 0 — 회귀 안전.
        from src.use_cases.grid_runner import GridRunResult
        empty = GridRunResult(
            initial_capital=_CAPITAL, final_cash=_CAPITAL.amount,
            final_holdings=Decimal("0"), final_close_price=Decimal("1000"),
            final_value=_CAPITAL.amount, trades=[], daily_values=[],
        )
        assert empty.final_avg_cost == Decimal("0")
        assert empty.turnover() == Decimal("0")
        assert empty.realized_cost_basis() == Decimal("0")

    def test_realized_cost_basis_consistency(self):
        # 실현 = 순매도대금 - 매도분 원가 → 실현 + 매도분원가 = 순매도대금.
        res = GridRunner().run(
            asset=_ASSET, bars=_bars(), config=_domain_config(),
            initial_capital=_CAPITAL,
        )
        realized, _ = res.pnl_split()
        rbasis = res.realized_cost_basis()
        sells = [t for t in res.trades if t.side is OrderSide.SELL]
        assert sells and rbasis > 0  # 매도 존재 → 투입원가 > 0
        net_proceeds = sum((t.cash_delta for t in sells), Decimal("0"))
        # realized 는 정수 원 반올림이므로 근사(±1원) 비교.
        assert abs((net_proceeds - rbasis) - realized) <= Decimal("1")
