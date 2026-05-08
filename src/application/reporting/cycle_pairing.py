"""Trade cycle pairing — strategy-agnostic FIFO pairing of BUY↔SELL.

Phase 0.10.j (ADR 0006 §14.2 paraded). Application-layer pure function —
no view-model peer of ``TradeView``, no domain entity. ``Cycle`` is a
local-frozen dataclass for adapter rendering only.

Pairing rule (synth #4 + Critic patch C2):

- **Primary** = list-order FIFO over ``TradeView`` sequence (which already
  preserves ADR 0002 §5.4 sells-then-buys ordering — see
  ``trade_view.trades_from_decisions``)
- ``entry_price`` annotation in SELL records = **diagnostic only**, never a
  matching key. ``realized_pnl`` here is *display-derived FIFO match* — not
  strategy ground truth.

CLAUDE.md §8.1 + §13.3 정합 — 표시값 truthfulness 라벨링: 호출자(html_writer)
는 cycle table 컬럼 헤더에 ``(FIFO 표시)`` 표기. 정확한 strategy realized
P&L 은 Phase 1 KIS reconciliation (ADR 0007 trigger).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from src.application.reporting.trade_view import TradeView

_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Cycle:
    """단일 BUY → SELL 사이클 (open / orphan / closed 모두 표현 가능).

    ``entry_date`` / ``exit_date`` 둘 중 적어도 하나는 set:
    - 둘 다 set = 정상 매칭된 closed cycle. ``realized_pnl`` 계산 가능.
    - ``exit_date is None`` = open BUY (아직 매칭 SELL 없음).
    - ``entry_date is None`` = orphan SELL (매칭 BUY 없음 — episode 필터로
      잘림). ``realized_pnl`` 계산 불가.

    Fields:
        entry_date: BUY 일자 (orphan SELL 시 None)
        entry_price: BUY 단가 (orphan SELL 시 None)
        quantity: 매칭 수량 (closed = 전체 매칭, open = 잔여 BUY 수량,
            orphan = SELL 수량). Decimal > 0.
        exit_date: SELL 일자 (open BUY 시 None)
        exit_price: SELL 단가 (open BUY 시 None)
        realized_pnl: ``(exit_price - entry_price) * quantity``.
            entry_date / exit_date 둘 다 set 일 때만 산출. None = open / orphan.
        realized_pnl_pct: ``realized_pnl / (entry_price * quantity) * 100``.
            None = open / orphan / entry_price = 0.
    """

    entry_date: date | None
    entry_price: Decimal | None
    quantity: Decimal
    exit_date: date | None
    exit_price: Decimal | None
    realized_pnl: Decimal | None
    realized_pnl_pct: Decimal | None

    @property
    def hold_days(self) -> int | None:
        if self.entry_date is None or self.exit_date is None:
            return None
        return (self.exit_date - self.entry_date).days

    @property
    def is_open(self) -> bool:
        return self.exit_date is None and self.entry_date is not None

    @property
    def is_orphan_sell(self) -> bool:
        return self.entry_date is None


def pair_cycles(trades: Sequence[TradeView]) -> list[Cycle]:
    """``TradeView`` list 를 list-order FIFO 매칭으로 사이클로 분할.

    호출자 (html_writer) 가 종목별로 분리한 후 호출. 본 함수는 입력 시퀀스
    가 동일 종목 가정 — 다종목 mix 시에도 FIFO 로 매칭하지만 의미 없는
    페어가 생성될 수 있음.

    Args:
        trades: TradeView 시퀀스 (timestamp 순 가정). 호출자가 종목 기준
            필터링 후 전달.

    Returns:
        Cycle list — 발생 순. closed → open / orphan 순서가 아니라 SELL
        도착 시점에 closed cycle 가 emit 되고 모든 trades 처리 후 잔여
        open BUY 가 추가됨.
    """
    open_buys: list[_OpenBuy] = []
    cycles: list[Cycle] = []

    for t in trades:
        if t.side == "BUY":
            open_buys.append(
                _OpenBuy(
                    entry_date=t.timestamp.date(),
                    entry_price=t.price,
                    remaining=t.quantity,
                )
            )
            continue

        # SELL — match against open BUYs FIFO
        sell_remaining = t.quantity
        sell_date = t.timestamp.date()
        sell_price = t.price

        while sell_remaining > 0 and open_buys:
            head = open_buys[0]
            matched_qty = min(head.remaining, sell_remaining)
            cycles.append(
                _make_closed_cycle(
                    entry_date=head.entry_date,
                    entry_price=head.entry_price,
                    quantity=matched_qty,
                    exit_date=sell_date,
                    exit_price=sell_price,
                )
            )
            head.remaining -= matched_qty
            sell_remaining -= matched_qty
            if head.remaining == 0:
                open_buys.pop(0)

        if sell_remaining > 0:
            # No matching BUY (orphan SELL) — entry_date / price unknown
            cycles.append(
                Cycle(
                    entry_date=None,
                    entry_price=None,
                    quantity=sell_remaining,
                    exit_date=sell_date,
                    exit_price=sell_price,
                    realized_pnl=None,
                    realized_pnl_pct=None,
                )
            )

    # Remaining open BUYs at end of stream
    for ob in open_buys:
        cycles.append(
            Cycle(
                entry_date=ob.entry_date,
                entry_price=ob.entry_price,
                quantity=ob.remaining,
                exit_date=None,
                exit_price=None,
                realized_pnl=None,
                realized_pnl_pct=None,
            )
        )

    return cycles


def match_realized_pnl(trades: Sequence[TradeView]) -> Decimal | None:
    """Σ closed cycles' ``realized_pnl`` (FIFO 표시) — 표시값.

    ``pair_cycles`` 와 동일한 list-order FIFO 매칭 정책 사용. closed cycle
    이 하나도 없으면 None 반환 (synth #5 정신 — KPI strip 에는 deterministic
    한 값만 표시).

    Args:
        trades: TradeView 시퀀스 (호출자가 종목 / 윈도우 필터 후 전달)

    Returns:
        Decimal (closed cycles 합) 또는 None (closed cycle 없음 시).
    """
    cycles = pair_cycles(trades)
    closed = [c.realized_pnl for c in cycles if c.realized_pnl is not None]
    if not closed:
        return None
    total = Decimal(0)
    for v in closed:
        total += v
    return total


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


class _OpenBuy:
    """Mutable head of FIFO queue — 잔여 수량 차감 추적."""

    __slots__ = ("entry_date", "entry_price", "remaining")

    def __init__(
        self, *, entry_date: date, entry_price: Decimal, remaining: Decimal,
    ) -> None:
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.remaining = remaining


def _make_closed_cycle(
    *,
    entry_date: date,
    entry_price: Decimal,
    quantity: Decimal,
    exit_date: date,
    exit_price: Decimal,
) -> Cycle:
    realized_pnl = (exit_price - entry_price) * quantity
    cost_basis = entry_price * quantity
    realized_pnl_pct: Decimal | None
    if cost_basis == 0:
        realized_pnl_pct = None
    else:
        realized_pnl_pct = realized_pnl / cost_basis * _HUNDRED
    return Cycle(
        entry_date=entry_date,
        entry_price=entry_price,
        quantity=quantity,
        exit_date=exit_date,
        exit_price=exit_price,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
    )
