"""Display formatters for backtest reports (Phase 0.10.h — ADR 0006 §14).

표시 ≠ 모델: Decimal 정밀도와 UTC ISO timestamp 는 모델 진실 그대로
유지하고, 본 모듈에서만 표시 정밀도 / 통화 표기 / KST 변환을 적용한다.
CLAUDE.md §2.1 (계산은 Decimal) + §3.1 (저장은 UTC) 정합 — 본 helper
들은 표시 전용.

float 미경유: 모든 정밀도 절단은 ``Decimal.quantize(..., ROUND_HALF_UP)``
사용.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")
_KOREAN_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def format_money(amount: Decimal, currency: str = "KRW") -> str:
    """금액 표시 — ``₩`` prefix + 천단위 콤마.

    KRW 는 정수, 그 외 통화는 소수 2자리. 음수는 ``-`` 부호 prefix.

    Args:
        amount: Decimal 금액 (음수 가능)
        currency: ``"KRW"`` (default) 또는 ISO 4217 코드

    Returns:
        ``"₩102,506,200"`` (KRW), ``"USD 1,234.56"`` (그 외).
    """
    sign = "-" if amount < 0 else ""
    abs_amount = abs(amount)
    if currency == "KRW":
        whole = int(abs_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return f"{sign}₩{whole:,}"
    quantized = abs_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{sign}{currency} {quantized:,.2f}"


def format_pct(
    value: Decimal, *, places: int = 2, signed: bool = True,
) -> str:
    """퍼센트 표시 — Decimal 을 ``places`` 자리 + 부호 옵션.

    Args:
        value: Decimal (이미 percent 단위. 예: ``-37.6516`` = -37.65%)
        places: 소수점 자리 (default 2)
        signed: True 면 양수에도 ``+`` 부호 prefix

    Returns:
        ``"+11.11%"``, ``"-37.65%"``, ``"15.50%"`` (signed=False)
    """
    if places <= 0:
        quant = Decimal("1")
    else:
        quant = Decimal("0." + ("0" * (places - 1)) + "1")
    quantized = value.quantize(quant, rounding=ROUND_HALF_UP)
    if signed:
        return f"{quantized:+,.{places}f}%"
    return f"{quantized:,.{places}f}%"


def format_price(value: Decimal, currency: str = "KRW") -> str:
    """가격 표시 — KRW 정수, 그 외 통화 소수 2자리.

    Returns:
        ``"₩37,900"`` (KRW), ``"USD 37.95"`` (그 외).
    """
    if currency == "KRW":
        whole = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return f"₩{whole:,}"
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{currency} {quantized:,.2f}"


def format_quantity(value: Decimal) -> str:
    """수량 표시 — 정수면 ``"131"``, 소수면 2자리.

    천단위 콤마 적용. 음수는 부호 prefix.
    """
    if value == value.to_integral_value():
        return f"{int(value):,}"
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:,.2f}"


def format_date(d: date) -> str:
    """ISO 날짜 — ``"2020-02-12"``."""
    return d.isoformat()


def format_datetime_kst(dt: datetime) -> str:
    """일봉 datetime 표시.

    BacktestRunner 가 만드는 일봉 timestamp 는 UTC midnight
    (예: ``2020-02-12T00:00:00+00:00``) — 시계열상 "그 날짜" 의미.
    UTC midnight 이면 시간 / 타임존을 숨기고 ``"2020-02-12 (목)"`` 만 표시.

    시간 ≠ 0 인 경우 (실거래 / intraday) 는 KST 변환:
    ``"2020-02-12 09:30 KST (목)"``.

    Args:
        dt: datetime — naive 입력은 UTC 로 간주 (CLAUDE.md §3.1).
    """
    norm = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    utc = norm.astimezone(timezone.utc)

    if (
        utc.hour == 0
        and utc.minute == 0
        and utc.second == 0
        and utc.microsecond == 0
    ):
        d = utc.date()
        return f"{format_date(d)} ({_KOREAN_WEEKDAYS[d.weekday()]})"

    kst = utc.astimezone(_KST)
    weekday = _KOREAN_WEEKDAYS[kst.weekday()]
    return (
        f"{format_date(kst.date())} {kst.hour:02d}:{kst.minute:02d}"
        f" KST ({weekday})"
    )
