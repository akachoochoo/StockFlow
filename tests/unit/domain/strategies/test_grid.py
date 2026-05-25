"""GridStrategy — research 동치 잠금 + 단위 검증 (ADR 0022 G1 증분 2).

핵심: GridStrategy 를 bar 별로 구동(cost-free)한 결과가 research
``_DGTPaperAdaptiveRunner`` 를 **zero-cost** 로 돌린 것과 trade-by-trade +
최종 cash/holdings 까지 bit-identical 임을 잠근다. SELL 수량은 비용 무관, BUY
는 비용=0 에서 일치 → 전략 로직이 research 와 동일함을 증명 (G2 토대).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar

import pytest

from src.cli.composition import asset_from_code
from src.domain.models import OHLCV, Currency, Money, OrderSide
from src.domain.strategies.grid import (
    GridConfig,
    GridDecision,
    GridState,
    GridStrategy,
)
from src.domain.strategies.grid_math import adaptive_k, grid_levels
from src.research.dgt.adaptive_runner import _AdaptiveConfig
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.paper_adaptive_runner import _DGTPaperAdaptiveRunner
from src.research.dgt.runner import _DGTConfig

_ASSET = asset_from_code("069500")  # KR_ETF, tick 5, lot 1
_CAPITAL = Decimal("100000000")

# 35000 기준 ±swing 종가 시퀀스 — 다방향 교차 + reset 유발.
_CLOSES = [
    "35000", "36400", "38200", "37100", "34500", "32800", "31000", "33200",
    "35600", "38800", "41200", "39500", "36900", "34100", "31500", "29800",
    "32400", "35100", "37800", "40500", "42100", "39700", "36300", "33800",
    "30900", "28500", "31200", "34600", "37200", "39900", "41800", "38600",
    "35400", "32700", "30100", "33500", "36800", "39200", "37500", "34900",
    "32200", "35800", "38400", "40900", "38100",
]
# 거래량 — index 20, 25 에 spike (volume_gate 발화).
_VOLS = [Decimal("1000000")] * len(_CLOSES)
_VOLS[20] = Decimal("5000000")
_VOLS[25] = Decimal("6000000")


def _bars() -> list[OHLCV]:
    base = date(2024, 1, 1)
    closes = [Decimal(c) for c in _CLOSES]
    out: list[OHLCV] = []
    for i, c in enumerate(closes):
        opn = closes[i - 1] if i > 0 else c
        hi = max(opn, c) * Decimal("1.01")
        lo = min(opn, c) * Decimal("0.99")
        out.append(
            OHLCV(
                asset=_ASSET,
                trade_date=base + timedelta(days=i),
                open=opn,
                high=hi,
                low=lo,
                close=c,
                volume=_VOLS[i],
            )
        )
    return out


def _research_runner(
    *, rebalance: str, measure: str, volume_gate: bool, n: int = 11
) -> _DGTPaperAdaptiveRunner:
    return _DGTPaperAdaptiveRunner(
        cost_model=_KoreanMarketCostModel(
            commission_rate=Decimal("0"),
            etf_tax_rate=Decimal("0"),
            stock_tax_rate=Decimal("0"),
        ),
        config=_DGTConfig(
            grid_count=n, grid_spacing_pct=Decimal("5"), levels_above=n // 2
        ),
        adaptive=_AdaptiveConfig(),
        rebalance_mode=rebalance,  # type: ignore[arg-type]
        volatility_measure=measure,  # type: ignore[arg-type]
        volume_gate=volume_gate,
        volume_gate_period=10,
        volume_gate_multiplier=Decimal("1.5"),
    )


def _domain_config(
    *, rebalance: str, measure: str, volume_gate: bool, n: int = 11
) -> GridConfig:
    return GridConfig(
        grid_count=n,
        fallback_k=Decimal("0.05"),  # = grid_spacing_pct/100
        rebalance_mode=rebalance,  # type: ignore[arg-type]
        volatility_measure=measure,  # type: ignore[arg-type]
        atr_period=14,
        multiplier=Decimal("1.5"),
        k_min=Decimal("0.02"),
        k_max=Decimal("0.10"),
        volume_gate=volume_gate,
        volume_gate_period=10,
        volume_gate_multiplier=Decimal("1.5"),
    )


def _drive_domain(
    bars: list[OHLCV], cfg: GridConfig
) -> tuple[list[tuple], Decimal, Decimal]:
    """research run() 와 동일 초기화 후 GridStrategy 를 bar 별 구동 (cost-free)."""
    n = cfg.grid_count
    reference = bars[0].close
    k0 = adaptive_k(
        bars, 0, reference,
        period=cfg.atr_period, multiplier=cfg.multiplier,
        k_min=cfg.k_min, k_max=cfg.k_max,
        fallback_k=cfg.fallback_k, measure=cfg.volatility_measure,
    )
    state = GridState(
        reference_price=reference,
        grid_levels=tuple(grid_levels(n, reference, k0, cfg.levels_above)),
    )
    strat = GridStrategy()
    cash = _CAPITAL
    hold = Decimal("0")
    trades: list[tuple] = []
    for i in range(len(bars)):
        ev = strat.evaluate(
            asset=_ASSET,
            bars=bars,
            bar_idx=i,
            state=state,
            available_cash=Money(amount=cash, currency=Currency.KRW),
            holdings=hold,
            config=cfg,
        )
        for d in ev.decisions:
            gross = d.rounded_price * d.quantity
            if d.side is OrderSide.BUY:
                cash -= gross
                hold += d.quantity
            else:
                cash += gross  # zero-cost: net = gross
                hold -= d.quantity
            trades.append((d.side.value, d.level_price, d.quantity, d.rounded_price))
        state = ev.next_state
    return trades, cash, hold


class TestResearchEquivalence:
    @pytest.mark.parametrize(
        "rebalance,measure,volume_gate",
        [
            ("daily", "adr", True),    # 최적 구성 경로
            ("daily", "atr", False),
            ("on_breach", "adr", False),
            ("on_breach", "atr", True),
        ],
    )
    def test_trades_and_balance_bit_identical(
        self, rebalance: str, measure: str, volume_gate: bool
    ):
        bars = _bars()
        runner = _research_runner(
            rebalance=rebalance, measure=measure, volume_gate=volume_gate
        )
        res = runner.run(
            _ASSET, bars[0].trade_date, bars[-1].trade_date,
            Money(amount=_CAPITAL, currency=Currency.KRW), bars,
        )
        research_trades = [
            (t.side, t.grid_level_price, t.quantity, t.rounded_price)
            for t in res.trades
        ]

        cfg = _domain_config(
            rebalance=rebalance, measure=measure, volume_gate=volume_gate
        )
        domain_trades, cash, hold = _drive_domain(bars, cfg)

        assert domain_trades == research_trades
        assert cash == res.final_cash
        assert hold == res.final_holdings

    def test_actually_trades(self):
        # 동치가 trivial (0 trade) 이 아님을 보장.
        bars = _bars()
        cfg = _domain_config(rebalance="daily", measure="adr", volume_gate=True)
        trades, _, _ = _drive_domain(bars, cfg)
        # 동치가 vacuous(0 trade) 가 아님을 보장 — 양방향 거래 발생.
        assert len(trades) >= 4
        assert any(s == "BUY" for s, *_ in trades)
        assert any(s == "SELL" for s, *_ in trades)


class TestGridModels:
    def test_levels_above_is_half(self):
        cfg = GridConfig(grid_count=11, fallback_k=Decimal("0.05"))
        assert cfg.levels_above == 5

    def test_state_requires_two_levels(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            GridState(reference_price=Decimal("100"), grid_levels=(Decimal("100"),))


class TestEvaluateGuards:
    def _state(self) -> GridState:
        return GridState(
            reference_price=Decimal("35000"),
            grid_levels=(Decimal("33000"), Decimal("35000"), Decimal("37000")),
        )

    def test_bar_idx_out_of_range(self):
        bars = _bars()
        with pytest.raises(ValueError, match="out of range"):
            GridStrategy().evaluate(
                asset=_ASSET, bars=bars, bar_idx=len(bars),
                state=self._state(),
                available_cash=Money(amount=_CAPITAL, currency=Currency.KRW),
                holdings=Decimal("0"),
                config=_domain_config(rebalance="daily", measure="adr", volume_gate=False),
            )

    def test_currency_mismatch(self):
        bars = _bars()
        with pytest.raises(ValueError, match="currency"):
            GridStrategy().evaluate(
                asset=_ASSET, bars=bars, bar_idx=1,
                state=self._state(),
                available_cash=Money(amount=_CAPITAL, currency=Currency.USD),
                holdings=Decimal("0"),
                config=_domain_config(rebalance="daily", measure="adr", volume_gate=False),
            )

    def test_negative_holdings(self):
        bars = _bars()
        with pytest.raises(ValueError, match="holdings"):
            GridStrategy().evaluate(
                asset=_ASSET, bars=bars, bar_idx=1,
                state=self._state(),
                available_cash=Money(amount=_CAPITAL, currency=Currency.KRW),
                holdings=Decimal("-1"),
                config=_domain_config(rebalance="daily", measure="adr", volume_gate=False),
            )

    def test_sell_emits_when_holdings_and_up_cross(self):
        # 보유분 있고 상향 교차 → SELL 결정 (holdings/(n+1) floor).
        bars = _bars()
        cfg = _domain_config(rebalance="on_breach", measure="adr", volume_gate=False)
        # 상향 교차 유도: prev=33000 < level 35000 <= curr=37000
        state = GridState(
            reference_price=Decimal("35000"),
            grid_levels=(Decimal("33000"), Decimal("35000"), Decimal("37000")),
        )
        # bar_idx 3: close 37100, prev close 38200 → 하향. 대신 직접 결정 검증은
        # 동치 테스트가 커버 — 여기선 sell 분할 수량 산식만.
        ev = GridStrategy().evaluate(
            asset=_ASSET, bars=bars, bar_idx=2,  # close 38200, prev 36400 (상승)
            state=state,
            available_cash=Money(amount=Decimal("0"), currency=Currency.KRW),
            holdings=Decimal("120"),
            config=cfg,
        )
        sells = [d for d in ev.decisions if d.side is OrderSide.SELL]
        # 35000, 37000 상향 교차 (36400<lvl<=38200) → 2 sells, 각 floor(120/12)=10
        assert all(isinstance(d, GridDecision) for d in sells)
        assert sells and sells[0].quantity == Decimal("10")


def _bars_from_closes(
    closes: list[str], vols: list[Decimal] | None = None
) -> list[OHLCV]:
    """종가 시퀀스 → OHLCV bars (gate 테스트용 통제 입력)."""
    base = date(2024, 1, 1)
    cl = [Decimal(c) for c in closes]
    out: list[OHLCV] = []
    for i, c in enumerate(cl):
        opn = cl[i - 1] if i > 0 else c
        out.append(
            OHLCV(
                asset=_ASSET,
                trade_date=base + timedelta(days=i),
                open=opn,
                high=max(opn, c) * Decimal("1.01"),
                low=min(opn, c) * Decimal("0.99"),
                close=c,
                volume=(vols[i] if vols else Decimal("1000000")),
            )
        )
    return out


class TestGateSkips:
    """게이트 억제 이벤트 (ADR 0022 §11.10) — '억제된 거래만' 기록."""

    # 6 bar flat(100) 후 jump/crash → bar_idx 6 에서 slope(period 5) 발화.
    _RALLY: ClassVar[list[str]] = ["100", "100", "100", "100", "100", "100", "130"]
    _CRASH: ClassVar[list[str]] = ["100", "100", "100", "100", "100", "100", "70"]

    def _state(self) -> GridState:
        return GridState(
            reference_price=Decimal("110"),
            grid_levels=(Decimal("90"), Decimal("110"), Decimal("130")),
        )

    def _cfg(self, **kw: object) -> GridConfig:
        base: dict[str, object] = {
            "grid_count": 2,
            "fallback_k": Decimal("0.05"),
            "rebalance_mode": "on_breach",
            "volatility_measure": "adr",
            "slope_gate": False,
            "slope_gate_period": 5,
            "slope_gate_threshold": Decimal("0.05"),
            "volume_gate": False,
            "volume_gate_period": 5,
            "volume_gate_multiplier": Decimal("1.5"),
        }
        base.update(kw)
        return GridConfig(**base)  # type: ignore[arg-type]

    def _eval(
        self, bars: list[OHLCV], cfg: GridConfig, *, holdings: Decimal,
        cash: Decimal = Decimal("0"), state: GridState | None = None,
    ):
        return GridStrategy().evaluate(
            asset=_ASSET, bars=bars, bar_idx=6, state=state or self._state(),
            available_cash=Money(amount=cash, currency=Currency.KRW),
            holdings=holdings, config=cfg,
        )

    def test_slope_gate_records_suppressed_sell(self):
        ev = self._eval(
            _bars_from_closes(self._RALLY), self._cfg(slope_gate=True),
            holdings=Decimal("120"),
        )
        assert [d for d in ev.decisions if d.side is OrderSide.SELL] == []
        assert len(ev.gate_skips) == 1
        gs = ev.gate_skips[0]
        assert gs.side is OrderSide.SELL
        assert gs.reasoning["gate"] == "slope"
        assert gs.level_prices == (Decimal("110"), Decimal("130"))
        assert Decimal(gs.reasoning["slope_roc"]) > Decimal("0.05")

    def test_slope_gate_records_suppressed_buy(self):
        ev = self._eval(
            _bars_from_closes(self._CRASH), self._cfg(slope_gate=True),
            holdings=Decimal("0"), cash=Decimal("100000000"),
        )
        assert [d for d in ev.decisions if d.side is OrderSide.BUY] == []
        assert len(ev.gate_skips) == 1
        gs = ev.gate_skips[0]
        assert gs.side is OrderSide.BUY
        assert gs.reasoning["gate"] == "slope"
        assert gs.level_prices == (Decimal("90"),)
        assert Decimal(gs.reasoning["slope_roc"]) < Decimal("-0.05")

    def test_volume_gate_records_suppressed_sell(self):
        vols = [Decimal("1000000")] * 6 + [Decimal("5000000")]
        ev = self._eval(
            _bars_from_closes(self._RALLY, vols),
            self._cfg(volume_gate=True),
            holdings=Decimal("120"),
        )
        assert len(ev.gate_skips) == 1
        gs = ev.gate_skips[0]
        assert gs.reasoning["gate"] == "volume"
        assert Decimal(gs.reasoning["volume_ratio"]) > Decimal("1.5")

    def test_no_skip_when_no_holdings(self):
        # 게이트 활성 + 상향 교차지만 보유분 0 → 가정 매도 없음 → 미기록.
        ev = self._eval(
            _bars_from_closes(self._RALLY), self._cfg(slope_gate=True),
            holdings=Decimal("0"),
        )
        assert ev.gate_skips == []

    def test_no_skip_when_no_crossing(self):
        # 게이트 활성이지만 그리드가 전부 위(교차 없음) → 미기록.
        far = GridState(
            reference_price=Decimal("220"),
            grid_levels=(Decimal("200"), Decimal("220"), Decimal("240")),
        )
        ev = self._eval(
            _bars_from_closes(self._RALLY), self._cfg(slope_gate=True),
            holdings=Decimal("120"), state=far,
        )
        assert ev.gate_skips == []

    def test_no_skip_when_gates_off(self):
        # 게이트 off → 억제 없음 + 매도 실제 발생 (would-trade 검증).
        ev = self._eval(
            _bars_from_closes(self._RALLY), self._cfg(), holdings=Decimal("120")
        )
        assert ev.gate_skips == []
        assert [d for d in ev.decisions if d.side is OrderSide.SELL]
