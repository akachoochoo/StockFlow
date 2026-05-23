"""GridStrategy — research 동치 잠금 + 단위 검증 (ADR 0022 G1 증분 2).

핵심: GridStrategy 를 bar 별로 구동(cost-free)한 결과가 research
``_DGTPaperAdaptiveRunner`` 를 **zero-cost** 로 돌린 것과 trade-by-trade +
최종 cash/holdings 까지 bit-identical 임을 잠근다. SELL 수량은 비용 무관, BUY
는 비용=0 에서 일치 → 전략 로직이 research 와 동일함을 증명 (G2 토대).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

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
