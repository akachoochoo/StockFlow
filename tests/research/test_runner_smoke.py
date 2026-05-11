"""Phase 0.11.a — _DGTPrototypeRunner smoke test (AC7).

ADR 0007 §1.10 AC7 oracle: runner correctness only (raise 안 함). IRR 수치
informational (R1 mitigation — 일봉 ≠ 분봉 본질).

Synthesized OHLCV (30 bars, up-down trajectory) — 5-year CSV 의존 zero,
AC8 e2e 와 격리.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import Asset, Currency, Money, OHLCV
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.results import _DGTBacktestResult
from src.research.dgt.runner import _DGTConfig, _DGTPrototypeRunner


@pytest.fixture
def synthesized_ohlcv(kr_etf_069500: Asset) -> list[OHLCV]:
    """30 bars: 100원 → 130원 (15 bars up) → 100원 (15 bars down).

    Triggers both UP-cross and DOWN-cross of grid levels around reference.
    """
    bars: list[OHLCV] = []
    base_date = date(2024, 1, 2)
    # Up leg: 100 → 130
    for i in range(15):
        price = Decimal(100 + 2 * i)  # 100, 102, ..., 128
        bars.append(
            OHLCV(
                asset=kr_etf_069500,
                trade_date=base_date + timedelta(days=i),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("1000"),
            )
        )
    # Down leg: 130 → 100
    for i in range(15):
        price = Decimal(130 - 2 * i)  # 130, 128, ..., 102
        bars.append(
            OHLCV(
                asset=kr_etf_069500,
                trade_date=base_date + timedelta(days=15 + i),
                open=price,
                high=price + Decimal("1"),
                low=price - Decimal("1"),
                close=price,
                volume=Decimal("1000"),
            )
        )
    return bars


@pytest.fixture
def dgt_runner(cost_model: _KoreanMarketCostModel) -> _DGTPrototypeRunner:
    config = _DGTConfig(
        grid_count=4,
        grid_spacing_pct=Decimal("5"),
        levels_above=2,
    )
    return _DGTPrototypeRunner(cost_model=cost_model, config=config)


class TestAC7RunnerSmoke:
    def test_runner_completes_without_raise(
        self,
        dgt_runner: _DGTPrototypeRunner,
        kr_etf_069500: Asset,
        synthesized_ohlcv: list[OHLCV],
    ) -> None:
        """AC7: 30 bars synthesized run — raise 없는 완주만 검증."""
        result = dgt_runner.run(
            asset=kr_etf_069500,
            start=date(2024, 1, 2),
            end=date(2024, 1, 31),
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
            ohlcv=synthesized_ohlcv,
        )
        # Result structure 검증 only — IRR 수치 assertion 없음 (informational)
        assert result is not None
        assert hasattr(result, "trades")
        assert hasattr(result, "final_balance")
        assert isinstance(result, _DGTBacktestResult)
        assert result.asset == kr_etf_069500
        assert result.final_balance.currency is Currency.KRW

    def test_grid_levels_count_n_plus_one(
        self,
        dgt_runner: _DGTPrototypeRunner,
        kr_etf_069500: Asset,
        synthesized_ohlcv: list[OHLCV],
    ) -> None:
        """grid_levels count = n + 1 invariant (논문 §)."""
        result = dgt_runner.run(
            asset=kr_etf_069500,
            start=date(2024, 1, 2),
            end=date(2024, 1, 31),
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
            ohlcv=synthesized_ohlcv,
        )
        assert len(result.grid_levels) == 4 + 1  # n=4 → 5 levels

    def test_empty_ohlcv_raises(
        self,
        dgt_runner: _DGTPrototypeRunner,
        kr_etf_069500: Asset,
    ) -> None:
        with pytest.raises(ValueError, match="ohlcv"):
            dgt_runner.run(
                asset=kr_etf_069500,
                start=date(2024, 1, 2),
                end=date(2024, 1, 31),
                initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
                ohlcv=[],
            )


class TestAC15Reproducibility:
    def test_two_runs_byte_identical(
        self,
        dgt_runner: _DGTPrototypeRunner,
        kr_etf_069500: Asset,
        synthesized_ohlcv: list[OHLCV],
    ) -> None:
        """AC15 (Critic Minor #6): 동일 입력 2회 실행 = byte-identical 결과.

        CLAUDE.md §7.4 (백테스트와 실거래 동일성 검증) 정신.
        """
        kwargs = dict(
            asset=kr_etf_069500,
            start=date(2024, 1, 2),
            end=date(2024, 1, 31),
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
            ohlcv=synthesized_ohlcv,
        )
        r1 = dgt_runner.run(**kwargs)
        r2 = dgt_runner.run(**kwargs)

        assert r1.final_cash == r2.final_cash
        assert r1.final_holdings == r2.final_holdings
        assert r1.final_balance.amount == r2.final_balance.amount
        assert r1.wallet_total == r2.wallet_total
        assert r1.grid_levels == r2.grid_levels
        assert len(r1.trades) == len(r2.trades)
        for t1, t2 in zip(r1.trades, r2.trades):
            assert t1 == t2
