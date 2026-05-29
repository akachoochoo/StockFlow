"""Reconciler — DB positions vs broker holdings 대조 (Phase 1.1 Stage 3.3).

Reconciliation 은 Phase 1.1 Stage 3 의 capstone (CLAUDE.md §11.2 / ADR 0012 D14).
매 거래일 시작 (일 2회, 08:30 + 15:50 KST — ADR 0012 D14) 에 DB 가 기록한
포지션과 브로커가 실제로 보고하는 보유를 종목별 수량으로 정확 대조한다.

**안전-크리티컬 (CLAUDE.md §11.2)**: 불일치 발견 시 **자동 수정 절대 금지**.
대신:

1. ``notifier.notify(CRITICAL, ...)`` — 사람에게 즉시 알림 (ADR 0012 D3 알림 #3).
2. ``halt(reason)`` — 영구 halt sentinel 기록 (composition 이 ``safety.write_halt``
   를 callback 으로 주입; use_case 는 cli 를 import 하지 않음 — ring 정합).
3. ``raise StateMismatchError`` — IntegrityError 전파 → 모든 거래 정지 + 사람
   개입 대기.

어떤 ``save`` / ``place_order`` 도 호출하지 않는다 (자동 수정 zero). 일치하면
부수효과 없이 ``ReconciliationResult(matched=True, [])`` 를 반환한다.

Ring 정합 (CLAUDE.md §1.1): reconciliation 은 ports (broker / repo / notifier /
uow) + domain (exceptions / models) + 주입 callback (halt / clock) 만 의존한다.
``from src.cli.*`` / ``from src.adapters.*`` import 금지 — 구체 어댑터는
composition 이 주입한다 (check_namespace 통과).

수량 대조 기준 (정수 주식): DB 와 broker 의 종목별 quantity 가 **정확히 일치**해야
한다. ``avg_price`` 는 detail 로 비교 (broker 반올림 차이 가능) 하되 halt trigger
는 **quantity** 기준이다. cash 대조는 본 단계 scope 외 — expected cash 도출이
복잡 (체결 / 수수료 / 세금 누적). Phase 1.x follow-up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.exceptions import StateMismatchError
from src.ports.notifications import NotificationLevel

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from src.ports.broker import HoldingsReaderPort
    from src.ports.notifications import NotifierPort
    from src.ports.unit_of_work import UnitOfWorkPort


__all__ = ["Reconciler", "ReconciliationMismatch", "ReconciliationResult"]


@dataclass(frozen=True)
class ReconciliationMismatch:
    """One per-asset reconciliation discrepancy.

    ``db_quantity`` is None when the asset exists only at the broker;
    ``broker_quantity`` is None when it exists only in the DB. When both are
    present they differ (a quantity mismatch). ``db_avg_price`` /
    ``broker_avg_price`` are carried for the alert detail only — they do NOT
    drive the halt decision (broker rounding may differ; quantity is the
    authoritative trigger).
    """

    asset_code: str
    db_quantity: Decimal | None
    broker_quantity: Decimal | None
    db_avg_price: Decimal | None = None
    broker_avg_price: Decimal | None = None


@dataclass(frozen=True)
class ReconciliationResult:
    """Outcome of a reconciliation pass.

    ``matched`` is True iff every held asset's quantity agrees between the DB
    and the broker (``mismatches`` empty). A matched result has **no side
    effects** — no alert, no halt, no raise.
    """

    matched: bool
    mismatches: list[ReconciliationMismatch] = field(default_factory=list)


class Reconciler:
    """Reconcile DB positions against broker holdings (CLAUDE.md §11.2).

    DI per CLAUDE.md §1.2 — every dependency is injected:

    - ``uow_factory`` : opens a UnitOfWork to read ``positions.list_all()``.
    - ``broker``      : :meth:`HoldingsReaderPort.get_holdings` (aggregated holdings).
    - ``notifier``    : CRITICAL alert on mismatch (ADR 0012 D3 알림 #3).
    - ``halt``        : ``Callable[[str], None]`` — composition injects
      ``safety.write_halt`` so the use_case never imports cli (ring 정합).
    - ``clock``       : injected UTC clock (CLAUDE.md §3.2 — no datetime.now()).
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWorkPort],
        broker: HoldingsReaderPort,
        notifier: NotifierPort,
        halt: Callable[[str], None],
        clock: Callable[[], datetime],
    ) -> None:
        self._uow_factory = uow_factory
        self._broker = broker
        self._notifier = notifier
        self._halt = halt
        self._clock = clock

    def reconcile(self) -> ReconciliationResult:
        """Compare DB positions vs broker holdings; halt on any mismatch.

        On a perfect quantity match returns ``ReconciliationResult(True, [])``
        with no side effects. On ANY mismatch (DB-only / broker-only / quantity
        differs) it alerts CRITICAL, writes the halt sentinel, and raises
        :class:`StateMismatchError` — **never** auto-corrects (CLAUDE.md §11.2).
        """
        db_quantities, db_avg_prices = self._read_db_positions()
        broker_quantities, broker_avg_prices = self._read_broker_holdings()

        mismatches = self._diff(
            db_quantities=db_quantities,
            db_avg_prices=db_avg_prices,
            broker_quantities=broker_quantities,
            broker_avg_prices=broker_avg_prices,
        )
        if not mismatches:
            return ReconciliationResult(matched=True, mismatches=[])

        # Mismatch — DO NOT auto-correct (CLAUDE.md §11.2). Alert + halt + raise.
        detail = self._format_detail(mismatches)
        as_of = self._clock()
        reason = (
            f"Reconciliation mismatch at {as_of.isoformat()}: {detail}"
        )
        self._notifier.notify(
            level=NotificationLevel.CRITICAL,
            title="Reconciliation 불일치",
            body=reason,
        )
        self._halt(reason)
        raise StateMismatchError(reason)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _read_db_positions(
        self,
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """Return ({asset_code: quantity}, {asset_code: avg_price}) for qty > 0.

        ADR 0022 §13 D26 — Reconciliation grid 인식: split Position quantity 와
        grid net quantity (BUY−SELL, ``grid_decisions.list_net_quantities``)
        를 같은 asset_code 키로 합산. 한 종목에 split + grid 동시 보유 시
        양쪽 합산 (방어적). grid 만 보유한 종목은 avg_price 가 None 으로 유지
        (mismatch struct 의 ``db_avg_price`` 가 Optional — quantity 가 halt
        trigger 라 avg_price 결손은 halt 결정에 영향 없음).
        """
        quantities: dict[str, Decimal] = {}
        avg_prices: dict[str, Decimal] = {}
        with self._uow_factory() as uow:
            # Split positions (기존 경로, 0 변경).
            for position in uow.positions.list_all():
                if position.quantity > 0:
                    code = position.asset.code
                    quantities[code] = position.quantity
                    avg_prices[code] = position.avg_price
            # Grid 보유 합산 (D26): asset_fqn 의 마지막 세그먼트 = asset_code.
            grid_net = uow.grid_decisions.list_net_quantities()
            for asset_fqn, net_qty in grid_net.items():
                code = asset_fqn.split(":")[-1]
                quantities[code] = quantities.get(code, Decimal("0")) + net_qty
                # avg_price: grid 만이면 결손, split + grid 합산 시 split avg
                # 유지 (혼합 시 detail 비교 무의미 — quantity 만 halt trigger).
        return quantities, avg_prices

    def _read_broker_holdings(
        self,
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """Return ({asset_code: quantity}, {asset_code: avg_price}) from broker."""
        quantities: dict[str, Decimal] = {}
        avg_prices: dict[str, Decimal] = {}
        for holding in self._broker.get_holdings():
            quantities[holding.asset_code] = holding.quantity
            avg_prices[holding.asset_code] = holding.avg_price
        return quantities, avg_prices

    @staticmethod
    def _diff(
        *,
        db_quantities: dict[str, Decimal],
        db_avg_prices: dict[str, Decimal],
        broker_quantities: dict[str, Decimal],
        broker_avg_prices: dict[str, Decimal],
    ) -> list[ReconciliationMismatch]:
        """Per-asset quantity diff. Returns mismatches in sorted code order.

        A mismatch is any of: DB-only asset, broker-only asset, or a quantity
        difference. ``avg_price`` is carried as detail only (not a trigger).
        """
        mismatches: list[ReconciliationMismatch] = []
        for code in sorted(set(db_quantities) | set(broker_quantities)):
            db_qty = db_quantities.get(code)
            broker_qty = broker_quantities.get(code)
            if db_qty == broker_qty:
                continue
            mismatches.append(
                ReconciliationMismatch(
                    asset_code=code,
                    db_quantity=db_qty,
                    broker_quantity=broker_qty,
                    db_avg_price=db_avg_prices.get(code),
                    broker_avg_price=broker_avg_prices.get(code),
                )
            )
        return mismatches

    @staticmethod
    def _format_detail(mismatches: list[ReconciliationMismatch]) -> str:
        """Render mismatches into a human-readable alert / halt detail string."""
        parts = [
            f"{m.asset_code} (DB qty={m.db_quantity}, "
            f"broker qty={m.broker_quantity})"
            for m in mismatches
        ]
        return "; ".join(parts)
