"""Tests for `_volatility` — ADR 0023 §10.2 / 세그먼트 1.2.2.a.

검증 전략:
1. 일봉 invariant 검증 (`src/domain/indicators/volatility.py` 와 동일 알고리즘
   → 같은 OHLC 패턴 입력 시 동일 출력) — D17 보존 의미.
2. 분봉 특수 패턴 — zero-volume 분봉 (high=low=close=직전) 영향.
3. 데이터 부족 / edge case (단일 bar, period > N).
4. 실 KIS 5/29 069500 분봉 391봉 fixture (CSV) 로 sanity check.

CLAUDE.md §2.1 — 모든 가격 Decimal.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from src.research.dgt_minute._csv_writer import _read_minute_csv
from src.research.dgt_minute._kis_minute_downloader import _MinuteBar
from src.research.dgt_minute._volatility import (
    _average_daily_range,
    _average_true_range,
)


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
        asset_code="TEST",
        trade_date=date(2026, 5, 29),
        trade_time=time(9, minute, 0),
        open=Decimal(str(open)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
    )


class TestATR:
    def test_empty_returns_zero(self) -> None:
        assert _average_true_range([], period=14, end_idx=0) == Decimal("0")

    def test_single_bar_returns_zero(self) -> None:
        """첫 bar (idx 0) 는 prev_close 부재 → 윈도 제외."""
        bars = [_bar(minute=0, open=100, high=110, low=90, close=105)]
        assert _average_true_range(bars, period=14, end_idx=0) == Decimal("0")

    def test_two_bars_simple_range(self) -> None:
        """2-bar: idx=1 의 TR = max(H-L, |H-prev_C|, |L-prev_C|).

        prev_close=105, high=120, low=95 → TR=max(25, 15, 10)=25.
        ATR(N=1, end=1) = 25 (단일 sample).
        """
        bars = [
            _bar(minute=0, open=100, high=110, low=90, close=105),
            _bar(minute=1, open=105, high=120, low=95, close=115),
        ]
        atr = _average_true_range(bars, period=1, end_idx=1)
        assert atr == Decimal("25")

    def test_zero_volume_bar_tr_zero(self) -> None:
        """high=low=close=직전 가격 → TR=0."""
        bars = [
            _bar(minute=0, open=100, high=110, low=90, close=105),
            _bar(minute=1, open=105, high=105, low=105, close=105, volume=0),
        ]
        atr = _average_true_range(bars, period=1, end_idx=1)
        assert atr == Decimal("0")

    def test_window_sma(self) -> None:
        """3 bars + idx=2, period=2 → idx 1,2 평균.

        idx=1: prev=105, H=120, L=95 → TR=25
        idx=2: prev=115, H=130, L=110 → TR=max(20, 15, 5)=20
        SMA = (25+20)/2 = 22.5
        """
        bars = [
            _bar(minute=0, open=100, high=110, low=90, close=105),
            _bar(minute=1, open=105, high=120, low=95, close=115),
            _bar(minute=2, open=115, high=130, low=110, close=125),
        ]
        atr = _average_true_range(bars, period=2, end_idx=2)
        assert atr == Decimal("22.5")

    def test_period_exceeds_data_clipped(self) -> None:
        """period 가 데이터보다 크면 사용 가능한 윈도만 평균."""
        bars = [
            _bar(minute=0, open=100, high=110, low=90, close=105),
            _bar(minute=1, open=105, high=120, low=95, close=115),
        ]
        # period=99, end=1 → start=max(1, 1-98)=1 → window=[1,1] → TR=25.
        atr = _average_true_range(bars, period=99, end_idx=1)
        assert atr == Decimal("25")


class TestADR:
    def test_empty_returns_zero(self) -> None:
        assert _average_daily_range([], period=14, end_idx=0) == Decimal("0")

    def test_single_bar_range(self) -> None:
        bars = [_bar(minute=0, open=100, high=110, low=90, close=105)]
        adr = _average_daily_range(bars, period=1, end_idx=0)
        assert adr == Decimal("20")

    def test_zero_volume_bar_range_zero(self) -> None:
        bars = [_bar(minute=0, open=100, high=100, low=100, close=100, volume=0)]
        adr = _average_daily_range(bars, period=1, end_idx=0)
        assert adr == Decimal("0")

    def test_sma_includes_first_bar(self) -> None:
        """ATR 과 달리 ADR 은 idx 0 포함 (prev_close 불필요)."""
        bars = [
            _bar(minute=0, open=100, high=110, low=90, close=105),  # range=20
            _bar(minute=1, open=105, high=120, low=95, close=115),  # range=25
        ]
        adr = _average_daily_range(bars, period=2, end_idx=1)
        assert adr == Decimal("22.5")

    def test_period_exceeds_data_uses_available(self) -> None:
        bars = [
            _bar(minute=0, open=100, high=110, low=90, close=105),  # range=20
            _bar(minute=1, open=105, high=120, low=95, close=115),  # range=25
        ]
        # period=99, end=1 → start=max(0, 1-98)=0 → window=[0,1] → SMA=22.5.
        adr = _average_daily_range(bars, period=99, end_idx=1)
        assert adr == Decimal("22.5")


class TestRealKisData:
    """실 KIS 5/29 069500 분봉 391봉 fixture (CSV 박제) sanity check."""

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

    def test_real_data_has_391_bars(
        self, real_bars: list[_MinuteBar]
    ) -> None:
        assert len(real_bars) == 391

    def test_real_atr_finite_positive(
        self, real_bars: list[_MinuteBar]
    ) -> None:
        atr = _average_true_range(real_bars, period=14, end_idx=len(real_bars) - 1)
        # 069500 5/29 가격 ~ 134000 KRW → ATR 최소 1 호가 (50원) 이상 기대.
        # zero-volume 분봉 다수라 작은 값 (수십 원~수백 원) 정상.
        assert atr >= Decimal("0")
        assert atr < Decimal("10000")  # 가격의 10% 미만 sanity

    def test_real_adr_finite_positive(
        self, real_bars: list[_MinuteBar]
    ) -> None:
        adr = _average_daily_range(real_bars, period=14, end_idx=len(real_bars) - 1)
        assert adr >= Decimal("0")
        assert adr < Decimal("10000")

    def test_real_atr_adr_relative_magnitude(
        self, real_bars: list[_MinuteBar]
    ) -> None:
        """일반적으로 ATR >= ADR (ATR 이 gap 포함). 분봉에서도 동일 패턴 기대."""
        end = len(real_bars) - 1
        atr = _average_true_range(real_bars, period=14, end_idx=end)
        adr = _average_daily_range(real_bars, period=14, end_idx=end)
        # 분봉서 prev_close ≈ close (zero-vol) 가 많아 ATR ≈ ADR 가능. 단
        # 가격 변동 봉이 있으면 ATR > ADR. 본 sanity 는 단순 ATR ≥ ADR (등호 허용).
        assert atr >= adr
