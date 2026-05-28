"""Unit tests for src.domain.order_keys (Phase 1.1 Stage 8-2).

The idempotency_key is the single source that encodes the target slot; the
async-settlement use-case recovers slot_number from it, so the parser must be
strict (halt, never guess) and the builder must stay byte-identical to the
orchestrator's historical format.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.domain.models import OrderSide
from src.domain.order_keys import (
    OrderKeyError,
    build_grid_order_key,
    build_order_key,
    is_grid_order_key,
    parse_grid_order_key,
    parse_order_key,
)

_FQN = "KRX:069500"
_DAY = date(2026, 5, 22)


def test_build_order_key_matches_orchestrator_historical_format() -> None:
    # Byte-identical to DailyOrchestrator's legacy f-string (single source).
    assert build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, slot_number=3
    ) == f"{_FQN}:{_DAY.isoformat()}:buy:3"
    assert build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.SELL, slot_number=7
    ) == f"{_FQN}:{_DAY.isoformat()}:sell:7"


def test_build_rejects_out_of_range_slot() -> None:
    for bad in (0, 8, -1):
        with pytest.raises(OrderKeyError):
            build_order_key(
                asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, slot_number=bad
            )


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
@pytest.mark.parametrize("slot", [1, 4, 7])
def test_parse_round_trips_build(side: OrderSide, slot: int) -> None:
    key = build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=side, slot_number=slot
    )
    parsed = parse_order_key(key)
    assert parsed.asset_fqn == _FQN
    assert parsed.trade_date == _DAY
    assert parsed.side is side
    assert parsed.slot_number == slot


def test_parse_recovers_slot_from_orchestrator_format() -> None:
    # Exactly the orchestrator's emitted format (not via build_order_key).
    parsed = parse_order_key(f"{_FQN}:2026-05-22:sell:5")
    assert parsed.side is OrderSide.SELL
    assert parsed.slot_number == 5
    assert parsed.asset_fqn == _FQN


def test_parse_rejects_wrong_segment_count() -> None:
    for bad in ("KRX:069500:2026-05-22:buy", "KRX:069500:2026-05-22:buy:1:extra", "nope"):
        with pytest.raises(OrderKeyError):
            parse_order_key(bad)


def test_parse_rejects_unknown_side() -> None:
    with pytest.raises(OrderKeyError):
        parse_order_key(f"{_FQN}:2026-05-22:hold:1")


def test_parse_rejects_non_integer_slot() -> None:
    with pytest.raises(OrderKeyError):
        parse_order_key(f"{_FQN}:2026-05-22:buy:x")


def test_parse_rejects_out_of_range_slot() -> None:
    for bad in ("0", "8", "-1"):
        with pytest.raises(OrderKeyError):
            parse_order_key(f"{_FQN}:2026-05-22:buy:{bad}")


def test_parse_rejects_bad_date() -> None:
    with pytest.raises(OrderKeyError):
        parse_order_key(f"{_FQN}:not-a-date:buy:1")


# ───────── Grid key tests (ADR 0022 §12 D17) ─────────


def test_build_grid_order_key_format() -> None:
    """6세그먼트 `{fqn}:{date}:{side}:grid:{level_idx}` 정확히 일치."""
    assert build_grid_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, level_idx=5
    ) == f"{_FQN}:{_DAY.isoformat()}:buy:grid:5"
    assert build_grid_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.SELL, level_idx=0
    ) == f"{_FQN}:{_DAY.isoformat()}:sell:grid:0"


def test_build_grid_rejects_negative_level_idx() -> None:
    with pytest.raises(OrderKeyError):
        build_grid_order_key(
            asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, level_idx=-1
        )


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
@pytest.mark.parametrize("level_idx", [0, 1, 5, 11, 99])
def test_grid_parse_round_trips_build(side: OrderSide, level_idx: int) -> None:
    key = build_grid_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=side, level_idx=level_idx
    )
    parsed = parse_grid_order_key(key)
    assert parsed.asset_fqn == _FQN
    assert parsed.trade_date == _DAY
    assert parsed.side is side
    assert parsed.level_idx == level_idx


def test_grid_parse_rejects_wrong_segment_count() -> None:
    for bad in (
        f"{_FQN}:2026-05-22:buy:grid",  # 5 (slot 형식)
        f"{_FQN}:2026-05-22:buy:grid:1:extra",  # 7
        "nope",
    ):
        with pytest.raises(OrderKeyError):
            parse_grid_order_key(bad)


def test_grid_parse_rejects_missing_grid_sentinel() -> None:
    """6세그먼트지만 4번째 토큰이 'grid' 아닌 경우 거부."""
    with pytest.raises(OrderKeyError):
        parse_grid_order_key(f"{_FQN}:2026-05-22:buy:slot:1")


def test_grid_parse_rejects_unknown_side() -> None:
    with pytest.raises(OrderKeyError):
        parse_grid_order_key(f"{_FQN}:2026-05-22:hold:grid:1")


def test_grid_parse_rejects_non_integer_level_idx() -> None:
    with pytest.raises(OrderKeyError):
        parse_grid_order_key(f"{_FQN}:2026-05-22:buy:grid:x")


def test_grid_parse_rejects_negative_level_idx() -> None:
    with pytest.raises(OrderKeyError):
        parse_grid_order_key(f"{_FQN}:2026-05-22:buy:grid:-1")


def test_grid_parse_rejects_bad_date() -> None:
    with pytest.raises(OrderKeyError):
        parse_grid_order_key(f"{_FQN}:not-a-date:buy:grid:1")


# ───────── 네임스페이스 분리 (split vs grid 교차 파싱 차단) ─────────


def test_split_and_grid_keys_are_disjoint() -> None:
    """split 키를 grid 파서가, grid 키를 split 파서가 거부."""
    split_key = build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, slot_number=3
    )
    grid_key = build_grid_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, level_idx=3
    )
    # grid parser rejects split key (5-segment vs expected 6)
    with pytest.raises(OrderKeyError):
        parse_grid_order_key(split_key)
    # split parser rejects grid key (6-segment vs expected 5)
    with pytest.raises(OrderKeyError):
        parse_order_key(grid_key)


def test_is_grid_order_key_format_detection() -> None:
    """is_grid_order_key 는 형식 판별만 (실제 파싱 안 함)."""
    split_key = build_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, slot_number=3
    )
    grid_key = build_grid_order_key(
        asset_fqn=_FQN, date_iso=_DAY.isoformat(), side=OrderSide.BUY, level_idx=3
    )
    assert not is_grid_order_key(split_key)
    assert is_grid_order_key(grid_key)
    # 6세그먼트지만 grid 토큰 자리가 다른 경우 → False (형식만 보고 판별 — 실제 파싱은
    # parse_grid_order_key 가 책임지므로 거짓 양성 없음)
    assert not is_grid_order_key(f"{_FQN}:2026-05-22:buy:notgrid:1")
    assert not is_grid_order_key("nope")
    assert not is_grid_order_key("a:b:c:d:e:f:g")  # 7 segments
