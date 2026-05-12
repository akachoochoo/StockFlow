"""Phase 0.11.b — `_baseline` integration tests (AC1~AC5).

ADR 0008 §1.6 D7 4-way baseline 정합 검증.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.domain.models import OHLCV, Asset
from src.research.dgt.optimization._baseline import (
    _BaselineMetrics,
    _phase_073_baseline_verbatim,
    _run_baselines,
    _run_buy_and_hold,
    _run_dgt_best_full_period,
    _run_seven_split_dgt_proxy,
)
from src.research.dgt.optimization._grid_runner import _GridPointResult


def _synthesize_bars(asset: Asset, n: int = 400) -> list[OHLCV]:
    """N bars 합성 — drift up + oscillation."""
    bars: list[OHLCV] = []
    base_date = date(2020, 1, 2)
    base_price = Decimal("25000")
    for i in range(n):
        # Drift up + 2% oscillation
        drift = Decimal(i) * Decimal("5")
        osc = Decimal("500") if i % 4 < 2 else Decimal("-500")
        price = base_price + drift + osc
        if price < Decimal("10000"):
            price = Decimal("10000")
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base_date + timedelta(days=i),
                open=price,
                high=price + Decimal("100"),
                low=price - Decimal("100"),
                close=price,
                volume=Decimal("1000"),
            )
        )
    return bars


class TestAC1Phase073Verbatim:
    """(i) Phase 0.7.3 정본 수치 verbatim."""

    def test_verbatim_metrics(self) -> None:
        m = _phase_073_baseline_verbatim()
        assert m.cagr_pct == Decimal("2.5779")
        assert m.mdd_pct == Decimal("-8.2737")
        assert m.sharpe == Decimal("0.5255")
        assert m.calmar == Decimal("0.3116")
        assert m.trade_count == 28


class TestAC2BuyAndHold:
    """(ii) 069500 B&H — 2 trades (1 BUY + 1 SELL), 정합 metrics."""

    def test_buy_and_hold_runs(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=400)
        m = _run_buy_and_hold(bars, kr_etf_069500)
        assert isinstance(m, _BaselineMetrics)
        assert m.trade_count == 2
        assert isinstance(m.cagr_pct, Decimal)
        assert isinstance(m.mdd_pct, Decimal)
        assert isinstance(m.sharpe, Decimal)
        assert isinstance(m.calmar, Decimal)

    def test_buy_and_hold_label(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=400)
        m = _run_buy_and_hold(bars, kr_etf_069500)
        assert "Buy-and-Hold" in m.label


class TestAC3SevenSplit:
    """(iii) 069500 SevenSplit — PriceDropStrategy via BacktestRunner."""

    def test_seven_split_runs(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=400)
        m = _run_seven_split_dgt_proxy(bars, kr_etf_069500)
        assert isinstance(m, _BaselineMetrics)
        assert "SevenSplit" in m.label
        # trade_count >= 0 (synthesized 합성 데이터 의존)
        assert m.trade_count >= 0


class TestAC4DGTBestFromGrid:
    """(iv) DGT best full-period — `_GridPointResult` 입력으로 full-period 실행."""

    def test_dgt_best_runs(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=400)
        # Synthetic best point — n=7 k=5% m=2 (Phase 0.11.a 정합)
        best = _GridPointResult(
            config_n=7,
            config_k_pct=Decimal("5"),
            config_m=2,
            is_cagr_pct=Decimal("0"),
            is_mdd_pct=Decimal("0"),
            is_sharpe=Decimal("0"),
            is_calmar=Decimal("0"),
            oos_cagr_pct=Decimal("0"),
            oos_mdd_pct=Decimal("0"),
            oos_sharpe=Decimal("0"),
            oos_calmar=Decimal("0"),
            dsr=Decimal("0"),
            total_trade_count=0,
            median_holding_period_days=Decimal("0"),
            mean_holding_period_days=Decimal("0"),
        )
        m = _run_dgt_best_full_period(bars, kr_etf_069500, best)
        assert isinstance(m, _BaselineMetrics)
        assert "DGT-best" in m.label
        assert "n=7" in m.label
        assert "k=5%" in m.label
        assert "m=2" in m.label


class TestAC5AllMetricsDecimal:
    """모든 baseline metric Decimal 타입 — float 미경유 (CLAUDE.md §2.1)."""

    def test_all_metrics_decimal(self, kr_etf_069500: Asset) -> None:
        bars = _synthesize_bars(kr_etf_069500, n=400)
        best = _GridPointResult(
            config_n=7,
            config_k_pct=Decimal("5"),
            config_m=2,
            is_cagr_pct=Decimal("0"),
            is_mdd_pct=Decimal("0"),
            is_sharpe=Decimal("0"),
            is_calmar=Decimal("0"),
            oos_cagr_pct=Decimal("0"),
            oos_mdd_pct=Decimal("0"),
            oos_sharpe=Decimal("0"),
            oos_calmar=Decimal("0"),
            dsr=Decimal("0"),
            total_trade_count=0,
            median_holding_period_days=Decimal("0"),
            mean_holding_period_days=Decimal("0"),
        )
        baselines = _run_baselines(bars, kr_etf_069500, best)
        assert "(i) Phase 0.7.3 verbatim" in baselines
        assert "(ii) 069500 B&H" in baselines
        assert "(iii) 069500 SevenSplit" in baselines
        assert "(iv) 069500 DGT-best" in baselines
        for key, m in baselines.items():
            assert isinstance(m.cagr_pct, Decimal), key
            assert isinstance(m.mdd_pct, Decimal), key
            assert isinstance(m.sharpe, Decimal), key
            assert isinstance(m.calmar, Decimal), key
