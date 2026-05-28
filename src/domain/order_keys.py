"""Idempotency-key construction & parsing (Phase 1.1 Stage 8-2, ADR 0022 §12 D17).

Two key formats coexist (네임스페이스 분리, 충돌 zero):

**Split (분할매수 전략, 5세그먼트)** — `slot_number ∈ [1, 7]` 슬롯 인덱스:

    BUY:  "{asset_fqn}:{date}:buy:{slot_number}"
    SELL: "{asset_fqn}:{date}:sell:{slot_number}"

**Grid (DGT 그리드 전략, 6세그먼트)** — `level_idx ≥ 0` 격자 레벨 인덱스
(ADR 0022 §12 D17, Q7 해소):

    BUY:  "{asset_fqn}:{date}:buy:grid:{level_idx}"
    SELL: "{asset_fqn}:{date}:sell:grid:{level_idx}"

`asset_fqn = "{exchange}:{code}"` (exactly one colon — KRX codes are digit-only),
`date` 는 ISO date (no colons). 형식 판별 = segment 수 (5=split / 6=grid)
+ 4번째 segment 가 "grid" 토큰.

This module is the **single source of truth** for that format:
- 분할매수: orchestrator's :meth:`DailyOrchestrator._buy_idempotency_key` /
  ``_sell_idempotency_key`` build keys through :func:`build_order_key`, settle
  via :func:`parse_order_key`.
- DGT 그리드 (ADR 0022 §12): GridRunner / dry-run / paper / live 가
  :func:`build_grid_order_key` 로 build, PendingSettler 가 :func:`parse_any_order_key`
  로 형식 판별 후 :func:`parse_grid_order_key` 디스패치.

:func:`parse_order_key` / :func:`parse_grid_order_key` 둘 다 **strict**: 형식
이탈 = :class:`OrderKeyError` 즉시 raise → caller halt (CLAUDE.md §5 / §6.3
침묵의 실패 금지, Principle #3 불확실하면 멈춘다). 절대 추측 금지.

Pure domain (CLAUDE.md §1.1): stdlib + domain models only. No clock, no IO.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.models import OrderSide

_BUY_TOKEN = "buy"
_SELL_TOKEN = "sell"
_SIDE_TO_TOKEN: dict[OrderSide, str] = {
    OrderSide.BUY: _BUY_TOKEN,
    OrderSide.SELL: _SELL_TOKEN,
}
_TOKEN_TO_SIDE: dict[str, OrderSide] = {
    _BUY_TOKEN: OrderSide.BUY,
    _SELL_TOKEN: OrderSide.SELL,
}
_EXPECTED_SEGMENTS = 5
_MIN_SLOT = 1
_MAX_SLOT = 7

# Grid (ADR 0022 §12 D17): 6-segment with "grid" sentinel as 4th token.
# level_idx >= 0 (GridConfig.grid_count >= 2 → level_index ∈ [0, grid_count]).
_GRID_TOKEN = "grid"
_EXPECTED_GRID_SEGMENTS = 6
_MIN_GRID_LEVEL_IDX = 0


class OrderKeyError(ValueError):
    """An idempotency_key does not match the canonical format.

    Raised by :func:`parse_order_key`. A money-critical parse failure: the
    caller (``PendingSettler``) must halt rather than guess a slot
    (CLAUDE.md §6.3 — no silent failure).
    """


@dataclass(frozen=True)
class ParsedOrderKey:
    """The slot-bearing fields recovered from an idempotency_key."""

    asset_fqn: str
    trade_date: date
    side: OrderSide
    slot_number: int


def build_order_key(
    *,
    asset_fqn: str,
    date_iso: str,
    side: OrderSide,
    slot_number: int,
) -> str:
    """Build the canonical idempotency_key for an order.

    ``date_iso`` is the ISO trade date (``today.isoformat()``). Mirrors the
    orchestrator's historical format exactly so existing keys stay
    byte-identical.
    """
    if not _MIN_SLOT <= slot_number <= _MAX_SLOT:
        raise OrderKeyError(
            f"slot_number must be in [{_MIN_SLOT}, {_MAX_SLOT}], "
            f"got {slot_number}"
        )
    return f"{asset_fqn}:{date_iso}:{_SIDE_TO_TOKEN[side]}:{slot_number}"


def parse_order_key(key: str) -> ParsedOrderKey:
    """Recover (asset_fqn, trade_date, side, slot_number) from ``key``.

    Strict: raises :class:`OrderKeyError` on any deviation from the canonical
    five-segment format — never guesses a slot.
    """
    parts = key.split(":")
    if len(parts) != _EXPECTED_SEGMENTS:
        raise OrderKeyError(
            f"idempotency_key must have {_EXPECTED_SEGMENTS} ':'-segments "
            f"('{{exchange}}:{{code}}:{{date}}:{{side}}:{{slot}}'), "
            f"got {len(parts)} in {key!r}"
        )
    exchange, code, date_iso, side_token, slot_token = parts

    side = _TOKEN_TO_SIDE.get(side_token)
    if side is None:
        raise OrderKeyError(
            f"side segment must be one of {sorted(_TOKEN_TO_SIDE)}, "
            f"got {side_token!r} in {key!r}"
        )

    try:
        trade_date = date.fromisoformat(date_iso)
    except ValueError as exc:
        raise OrderKeyError(
            f"date segment {date_iso!r} is not an ISO date in {key!r}"
        ) from exc

    try:
        slot_number = int(slot_token)
    except ValueError as exc:
        raise OrderKeyError(
            f"slot segment {slot_token!r} is not an integer in {key!r}"
        ) from exc
    if not _MIN_SLOT <= slot_number <= _MAX_SLOT:
        raise OrderKeyError(
            f"slot_number must be in [{_MIN_SLOT}, {_MAX_SLOT}], "
            f"got {slot_number} in {key!r}"
        )

    return ParsedOrderKey(
        asset_fqn=f"{exchange}:{code}",
        trade_date=trade_date,
        side=side,
        slot_number=slot_number,
    )


@dataclass(frozen=True)
class ParsedGridOrderKey:
    """Recovered fields from a DGT grid idempotency_key (ADR 0022 §12 D17)."""

    asset_fqn: str
    trade_date: date
    side: OrderSide
    level_idx: int


def build_grid_order_key(
    *,
    asset_fqn: str,
    date_iso: str,
    side: OrderSide,
    level_idx: int,
) -> str:
    """Build a DGT grid idempotency_key (ADR 0022 §12 D17, Q7 해소).

    Format = ``{asset_fqn}:{date_iso}:{side}:grid:{level_idx}`` (6세그먼트).
    Split 키 (5세그먼트) 와 네임스페이스 분리 — 충돌 zero.

    ``level_idx`` 는 ``GridConfig.grid_count`` (n ≥ 2) 의 격자 레벨 인덱스
    (``GridStrategy.evaluate`` 의 ``level_index``). ge=0 만 검증 — 상한은
    runtime 의 grid_count 에 의존하므로 본 모듈에서 강제하지 않는다.
    """
    if level_idx < _MIN_GRID_LEVEL_IDX:
        raise OrderKeyError(
            f"level_idx must be ≥ {_MIN_GRID_LEVEL_IDX}, got {level_idx}"
        )
    return (
        f"{asset_fqn}:{date_iso}:{_SIDE_TO_TOKEN[side]}:"
        f"{_GRID_TOKEN}:{level_idx}"
    )


def parse_grid_order_key(key: str) -> ParsedGridOrderKey:
    """Recover (asset_fqn, trade_date, side, level_idx) from a grid ``key``.

    Strict: 6세그먼트 + 4번째 토큰 = "grid" 위반 시 :class:`OrderKeyError`.
    """
    parts = key.split(":")
    if len(parts) != _EXPECTED_GRID_SEGMENTS:
        raise OrderKeyError(
            f"grid idempotency_key must have {_EXPECTED_GRID_SEGMENTS} "
            f"':'-segments ('{{exchange}}:{{code}}:{{date}}:{{side}}:grid:"
            f"{{level_idx}}'), got {len(parts)} in {key!r}"
        )
    exchange, code, date_iso, side_token, grid_token, level_token = parts

    if grid_token != _GRID_TOKEN:
        raise OrderKeyError(
            f"grid sentinel segment must be {_GRID_TOKEN!r}, "
            f"got {grid_token!r} in {key!r}"
        )

    side = _TOKEN_TO_SIDE.get(side_token)
    if side is None:
        raise OrderKeyError(
            f"side segment must be one of {sorted(_TOKEN_TO_SIDE)}, "
            f"got {side_token!r} in {key!r}"
        )

    try:
        trade_date = date.fromisoformat(date_iso)
    except ValueError as exc:
        raise OrderKeyError(
            f"date segment {date_iso!r} is not an ISO date in {key!r}"
        ) from exc

    try:
        level_idx = int(level_token)
    except ValueError as exc:
        raise OrderKeyError(
            f"level_idx segment {level_token!r} is not an integer in {key!r}"
        ) from exc
    if level_idx < _MIN_GRID_LEVEL_IDX:
        raise OrderKeyError(
            f"level_idx must be ≥ {_MIN_GRID_LEVEL_IDX}, "
            f"got {level_idx} in {key!r}"
        )

    return ParsedGridOrderKey(
        asset_fqn=f"{exchange}:{code}",
        trade_date=trade_date,
        side=side,
        level_idx=level_idx,
    )


def is_grid_order_key(key: str) -> bool:
    """Quick format-detection: True if ``key`` looks like a 6-segment grid key.

    분기 helper — PendingSettler 가 :func:`parse_order_key` (split) vs
    :func:`parse_grid_order_key` 디스패치 결정에 사용. **파싱은 안 함** —
    형식 판별만 (parts 수 + grid 토큰 위치). 실제 검증은 각 parser 책임.
    """
    parts = key.split(":")
    return (
        len(parts) == _EXPECTED_GRID_SEGMENTS
        and parts[4] == _GRID_TOKEN
    )


__all__ = [
    "OrderKeyError",
    "ParsedOrderKey",
    "ParsedGridOrderKey",
    "build_order_key",
    "build_grid_order_key",
    "parse_order_key",
    "parse_grid_order_key",
    "is_grid_order_key",
]
