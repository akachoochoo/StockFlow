"""ATR/ADR 도메인 지표 — research 동치 잠금 (ADR 0022 G1).

`src/domain/indicators/volatility.py` 가 `src/research/dgt/adaptive_runner.py`
의 ``_compute_atr`` / ``_compute_adr`` 와 **bit-identical Decimal 출력**을
내는지 잠근다 (research → domain 충실 포팅 검증, G2 동일성 토대).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.cli.composition import asset_from_code
from src.domain.indicators.volatility import (
    average_daily_range,
    average_true_range,
)
from src.domain.models import OHLCV
from src.research.dgt.adaptive_runner import _compute_adr, _compute_atr

_ASSET = asset_from_code("069500")

# (open, high, low, close, volume) — 변동성 변화가 있는 20 bar 합성 시리즈.
_ROWS: list[tuple[str, str, str, str, str]] = [
    ("100", "105", "99", "104", "1000"),
    ("104", "108", "103", "106", "1200"),
    ("106", "107", "101", "102", "1500"),
    ("102", "104", "98", "100", "2000"),
    ("100", "101", "95", "96", "2500"),
    ("96", "99", "94", "98", "1800"),
    ("98", "110", "97", "109", "5000"),
    ("109", "112", "108", "110", "3000"),
    ("110", "111", "104", "105", "2200"),
    ("105", "106", "100", "101", "1900"),
    ("101", "103", "100", "102", "1100"),
    ("102", "102", "99", "100", "1300"),
    ("100", "108", "100", "107", "4200"),
    ("107", "115", "106", "114", "6000"),
    ("114", "116", "112", "113", "2800"),
    ("113", "114", "107", "108", "2400"),
    ("108", "109", "103", "104", "2600"),
    ("104", "105", "100", "101", "2100"),
    ("101", "111", "101", "110", "5500"),
    ("110", "113", "109", "112", "3100"),
]


def _bars() -> list[OHLCV]:
    base = date(2024, 1, 1)
    return [
        OHLCV(
            asset=_ASSET,
            trade_date=base + timedelta(days=i),
            open=Decimal(o),
            high=Decimal(h),
            low=Decimal(low),
            close=Decimal(c),
            volume=Decimal(v),
        )
        for i, (o, h, low, c, v) in enumerate(_ROWS)
    ]


_PERIODS = [3, 5, 10, 14]
_END_IDXS = [1, 4, 9, 14, 19]


class TestATREquivalence:
    @pytest.mark.parametrize("period", _PERIODS)
    @pytest.mark.parametrize("end_idx", _END_IDXS)
    def test_matches_research(self, period: int, end_idx: int):
        bars = _bars()
        assert average_true_range(bars, period, end_idx) == _compute_atr(
            bars, period, end_idx
        )

    def test_insufficient_data_zero(self):
        bars = _bars()
        # end_idx 0 → prev_close 없음 → 0 (research 동일)
        assert average_true_range(bars, 14, 0) == Decimal("0")
        assert average_true_range(bars, 14, 0) == _compute_atr(bars, 14, 0)


class TestADREquivalence:
    @pytest.mark.parametrize("period", _PERIODS)
    @pytest.mark.parametrize("end_idx", _END_IDXS)
    def test_matches_research(self, period: int, end_idx: int):
        bars = _bars()
        assert average_daily_range(bars, period, end_idx) == _compute_adr(
            bars, period, end_idx
        )

    def test_idx0_single_bar_range(self):
        bars = _bars()
        # ADR 은 prev_close 불요 → idx 0 도 high-low 산출 (research 동일)
        assert average_daily_range(bars, 14, 0) == _compute_adr(bars, 14, 0)
        assert average_daily_range(bars, 14, 0) == bars[0].high - bars[0].low
