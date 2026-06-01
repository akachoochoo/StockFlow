"""분봉 ATR / ADR — `_MinuteBar` 시계열에 대한 변동성 helper.

ADR 0023 §10.2 / 세그먼트 1.2.2.a 산출. 일봉 `src/domain/indicators/volatility.py`
와 알고리즘 동일, 입력 타입만 `_MinuteBar` 로 변경. inner ring 변경 zero
(D17 일봉 invariant 보존).

분봉 ATR/ADR 의미 (일봉과 차이 명시 — 1.2.2.e sweep 검증 영역):
- 분봉 ATR (period N): 인접 N분봉 사이 (high, low, prev_close) True Range SMA.
  분 단위 gap (zero 빈도 ↑, zero-volume 분봉서 high=low=close → TR=0).
- 분봉 ADR (period N): 인접 N분봉 (high-low) SMA.
  분 단위 intra-bar range. zero-volume 분봉서 0.

D6 (일봉 권고 직접 적용 금지): 일봉 sweep 의 ADR k=[0.5%, 5%] 권고가 분봉에
그대로 유효하지 않음 — 분봉 high-low ≈ tick 단위 (zero-vol 빈도 ↑) →
ADR 값 분포 자체 다름. 1.2.2.e 분봉 sweep 에서 재검증.

5th ring 격리 (D15): inner ring `volatility.py` 와 별도. 분봉이 inner ring
production 진입 시점 (1.2.4 직전) 에 별도 ADR 박제 후 production 함수 신규.

CLAUDE.md §2.1 (Decimal 전용) / §3.2 (시계 의존 zero, `end_idx` 주입).
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.research.dgt_minute._kis_minute_downloader import _MinuteBar


def _average_true_range(
    bars: list[_MinuteBar], period: int, end_idx: int
) -> Decimal:
    """ATR(period) at ``end_idx`` (inclusive). Decimal-only.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    ATR = SMA of True Range over the window. prev_close 가 필요하므로 첫 bar
    (idx 0) 는 윈도우에서 제외 (start = max(1, ...)). 데이터 부족 시 Decimal("0").

    분봉 특수성:
    - zero-volume 분봉 (high=low=close=직전 가격) 의 TR = 0.
    - 결과 = (overnight gap 미반영) ≈ 분 단위 호가 변동 평균.
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


def _average_daily_range(
    bars: list[_MinuteBar], period: int, end_idx: int
) -> Decimal:
    """ADR(period) at ``end_idx`` (inclusive). Decimal-only.

    이름은 'Daily' Range 지만 분봉 시계열에 적용 시 단순 SMA of (high - low).
    분봉 도메인에서는 'Average Bar Range' 가 의미상 정확하나, 일봉 `volatility.py`
    의 함수명 그대로 계승 (1:1 매핑 명시 — 단위만 분).

    분봉 특수성:
    - zero-volume 분봉 (high=low) 의 range = 0 → SMA 끌어내림.
    - period N 이 클수록 zero-bar 평균화 영향 ↑.

    데이터 부족 시 Decimal("0").
    """
    if not bars:
        return Decimal("0")
    start = max(0, end_idx - period + 1)
    if start > end_idx:
        return Decimal("0")

    range_sum = Decimal("0")
    count = 0
    for i in range(start, end_idx + 1):
        range_sum += bars[i].high - bars[i].low
        count += 1

    return range_sum / Decimal(count) if count > 0 else Decimal("0")
