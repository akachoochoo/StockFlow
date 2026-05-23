"""Volatility indicators — ATR / ADR (Phase 1.x, ADR 0022 G1).

DGT grid spacing(k) 의 변동성 입력. `src/research/dgt/adaptive_runner.py` 의
``_compute_atr`` / ``_compute_adr`` 를 inner ring 으로 **충실 포팅**한 것
(research → domain 승격, ADR 0022 D6). 순수 Decimal, 시계 의존 zero (시점은
``end_idx`` 주입). research 버전과의 출력 동치는 테스트로 잠근다 (G2 backtest↔
paper 동일성 토대).

ATR ≠ ADR:
- ATR(True Range) = max(high-low, |high-prev_close|, |low-prev_close|) 의 SMA —
  overnight gap 반영.
- ADR(Daily Range) = (high-low) 의 SMA — gap 무시 (DGT 최적 구성 = ADR).
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.models import OHLCV


def average_true_range(bars: list[OHLCV], period: int, end_idx: int) -> Decimal:
    """ATR(period) at ``end_idx`` (inclusive). Decimal-only.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    ATR = SMA of True Range over the window. prev_close 가 필요하므로 첫 bar
    (idx 0) 는 윈도우에서 제외 (start = max(1, ...)). 데이터 부족 시 Decimal("0").
    """
    start = max(1, end_idx - period + 1)
    if start > end_idx or end_idx < 1:
        return Decimal("0")

    tr_sum = Decimal("0")
    count = 0
    for i in range(start, end_idx + 1):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        tr_sum += tr
        count += 1

    return tr_sum / Decimal(count) if count > 0 else Decimal("0")


def average_daily_range(bars: list[OHLCV], period: int, end_idx: int) -> Decimal:
    """ADR(period) at ``end_idx`` (inclusive). Decimal-only.

    Average Daily Range = SMA of (high - low) over the window. ATR 와 달리
    overnight gap 미반영 (장중 범위만). 데이터 부족 시 Decimal("0").
    """
    start = max(0, end_idx - period + 1)
    if start > end_idx:
        return Decimal("0")

    dr_sum = Decimal("0")
    count = 0
    for i in range(start, end_idx + 1):
        dr_sum += bars[i].high - bars[i].low
        count += 1

    return dr_sum / Decimal(count) if count > 0 else Decimal("0")
