"""Unit tests for src.cli.live_runner.run_live_pipeline (Phase 1.1 Stage 8-5).

Pins the safety-critical sequencing: settle → reconcile → arm → decide, with
real orders structurally unreachable until the arming gate returns. Pipeline
order + gating use lightweight fakes; the post-settle G2(d) equivalence uses a
REAL PendingSettler; gap (e) close-persistence uses a real paper orchestrator.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.cli.live_gate import CapitalTier, LiveArmingError, LiveArmingToken
from src.cli.live_runner import run_live_pipeline
from src.domain.models import (
    Asset,
    AssetClass,
    BuyActionRecord,
    Currency,
    Decision,
    Exchange,
    Market,
    Money,
    Order,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    SplitEntry,
    SplitSlot,
)
from src.domain.order_keys import build_order_key
from src.ports.notifications import NotificationLevel
from src.use_cases.decision_equivalence import decisions_equivalent
from src.use_cases.pending_settler import SettleEvent, SettleOutcome
from src.use_cases.reconciliation import ReconciliationResult

if TYPE_CHECKING:
    from collections.abc import Sequence

DATE = date(2026, 5, 22)
ARMED = LiveArmingToken(tier_cap=CapitalTier.TIER_200, env_confirmed=True)


def _asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _decision(asset: Asset, *, current_price: str) -> Decision:
    # A valid skip Decision carrying the run's close price in reasoning (the
    # stop-loss check only reads reasoning['current_price']).
    from src.domain.models import SkipReason

    return Decision(
        timestamp=datetime(2026, 5, 22, 6, 0, tzinfo=UTC),
        asset=asset,
        skip_reason=SkipReason.STRATEGY_NO_BUY,
        reasoning={"current_price": current_price},
    )


def _held_position(asset: Asset, *, avg: str, qty: str = "10") -> Position:
    entry = SplitEntry(
        split_number=1,
        entry_date=DATE,
        quantity=Decimal(qty),
        entry_price=Decimal(avg),
        idempotency_key="seed",
    )
    slots: list[SplitSlot] = [SplitSlot.filled(entry=entry)]
    slots.extend(SplitSlot.empty(slot_number=i) for i in range(2, 8))
    return Position(
        asset=asset, quantity=Decimal(qty), avg_price=Decimal(avg),
        split_level=1, last_buy_at=datetime(2026, 5, 1, tzinfo=UTC), slots=slots,
    )


# Decision invariant 1 forbids a skip with no actions only if everything empty;
# a "skip" decision needs a skip_reason. Use a no-action skip for orchestrator
# fakes where the content is irrelevant.
def _skip(asset: Asset) -> Decision:
    from src.domain.models import SkipReason
    return Decision(
        timestamp=datetime(2026, 5, 22, 6, 0, tzinfo=UTC),
        asset=asset, skip_reason=SkipReason.STRATEGY_NO_BUY, reasoning={},
    )


class _FakeSettler:
    def __init__(self, log: list[str], *, events: Sequence[SettleEvent] = ()) -> None:
        self._log = log
        self._events = list(events)

    def settle(self, today: date) -> SettleOutcome:
        self._log.append("settle")
        return SettleOutcome(events=list(self._events))


class _FakeReconciler:
    def __init__(self, log: list[str], *, matched: bool = True) -> None:
        self._log = log
        self._matched = matched

    def reconcile(self) -> ReconciliationResult:
        self._log.append("recon")
        return ReconciliationResult(matched=self._matched, mismatches=[])


class _FakeOrchestrator:
    def __init__(self, log: list[str], *, decisions: Sequence[Decision] = ()) -> None:
        self._log = log
        self._decisions = list(decisions)

    def run_for_date(self, today: date) -> list[Decision]:
        self._log.append("decide")
        return list(self._decisions)


class _FakePositionSource:
    def __init__(self, positions: Sequence[Position] = ()) -> None:
        self._positions = list(positions)

    def get_positions(self) -> list[Position]:
        return list(self._positions)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[NotificationLevel, str, str]] = []

    def notify(self, *, level: NotificationLevel, title: str, body: str) -> None:
        self.calls.append((level, title, body))


def _run(
    *,
    log: list[str],
    matched: bool = True,
    arm_token: LiveArmingToken | None = ARMED,
    settle_events: Sequence[SettleEvent] = (),
    decisions: Sequence[Decision] = (),
    positions: Sequence[Position] = (),
    notifier: _RecordingNotifier | None = None,
    max_loss_pct: str = "20",
    halt_active: bool = False,
    ntp_synced: bool = True,
    supervised_first_order: bool = False,
    orders_today_count=None,
    halt_writer=None,
):
    notif = notifier or _RecordingNotifier()
    return run_live_pipeline(
        settler=_FakeSettler(log, events=settle_events),  # type: ignore[arg-type]
        reconciler=_FakeReconciler(log, matched=matched),  # type: ignore[arg-type]
        orchestrator=_FakeOrchestrator(log, decisions=decisions),  # type: ignore[arg-type]
        position_source=_FakePositionSource(positions),  # type: ignore[arg-type]
        notifier=notif,  # type: ignore[arg-type]
        today=DATE,
        intended_tier=CapitalTier.TIER_200,
        arm_token=arm_token,
        halt_active=halt_active,
        ntp_synced=ntp_synced,
        max_loss_pct=Decimal(max_loss_pct),
        supervised_first_order=supervised_first_order,
        orders_today_count=orders_today_count,
        halt_writer=halt_writer,
    )


# ---------------------------------------------------------------------------
# Pipeline order + gating
# ---------------------------------------------------------------------------
def test_live_runner_settle_then_decide_pipeline() -> None:
    log: list[str] = []
    a = _asset()
    result = _run(log=log, decisions=[_skip(a)])
    assert log == ["settle", "recon", "decide"]
    assert len(result.decisions) == 1


def test_recon_runs_before_decision_in_live() -> None:
    log: list[str] = []
    _run(log=log, decisions=[_skip(_asset())])
    assert log.index("recon") < log.index("decide")


def test_arming_refused_blocks_decision() -> None:
    log: list[str] = []
    with pytest.raises(LiveArmingError):
        _run(log=log, arm_token=None, decisions=[_skip(_asset())])
    # settle + recon ran; decision NEVER reached (no orders).
    assert log == ["settle", "recon"]


def test_arming_uses_in_process_recon_result() -> None:
    # A non-matched in-process recon result refuses arming → no decision.
    log: list[str] = []
    with pytest.raises(LiveArmingError):
        _run(log=log, matched=False, decisions=[_skip(_asset())])
    assert "decide" not in log


def test_settle_events_forwarded_to_notifier() -> None:
    log: list[str] = []
    notifier = _RecordingNotifier()
    event = SettleEvent(
        level=NotificationLevel.WARNING, kind="sell_pending_buy_skip",
        title="t", body="b",
    )
    _run(log=log, settle_events=[event], decisions=[], notifier=notifier)
    assert (NotificationLevel.WARNING, "t", "b") in notifier.calls


# ---------------------------------------------------------------------------
# Stop-loss breach alert (ADR 0012 D2(b') — alert only)
# ---------------------------------------------------------------------------
def test_stop_loss_breach_emits_warning() -> None:
    a = _asset()
    notifier = _RecordingNotifier()
    pos = _held_position(a, avg="35000")  # current 26000 → ~-25.7% ≤ -20%
    result = _run(
        log=[], decisions=[_decision(a, current_price="26000")],
        positions=[pos], notifier=notifier, max_loss_pct="20",
    )
    assert len(result.stop_loss_breaches) == 1
    assert result.stop_loss_breaches[0][0] == a.fqn
    warnings = [c for c in notifier.calls if c[0] is NotificationLevel.WARNING]
    assert any("손절" in title for _lvl, title, _body in warnings)


def test_stop_loss_within_limit_no_warning() -> None:
    a = _asset()
    notifier = _RecordingNotifier()
    pos = _held_position(a, avg="35000")  # current 33000 → ~-5.7% > -20%
    result = _run(
        log=[], decisions=[_decision(a, current_price="33000")],
        positions=[pos], notifier=notifier, max_loss_pct="20",
    )
    assert result.stop_loss_breaches == []


def test_stop_loss_skipped_when_no_priced_decision() -> None:
    # A held position whose asset had no priced decision this run is not
    # evaluated (cannot fabricate a price).
    a = _asset()
    pos = _held_position(a, avg="35000")
    result = _run(log=[], decisions=[_skip(a)], positions=[pos])
    assert result.stop_loss_breaches == []


# ---------------------------------------------------------------------------
# Supervised first-order (Stage 8-6 / ADR 0012 §2.5(b)/(i))
# ---------------------------------------------------------------------------
class _HaltSpy:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    def __call__(self, reason: str) -> None:
        self.reasons.append(reason)


def test_supervised_hold_writes_halt_when_order_placed() -> None:
    spy = _HaltSpy()
    result = _run(
        log=[], supervised_first_order=True,
        orders_today_count=lambda: 1, halt_writer=spy,
    )
    assert result.supervised_hold is True
    assert len(spy.reasons) == 1
    assert "supervised first-order" in spy.reasons[0]


def test_supervised_no_hold_when_no_order_placed() -> None:
    spy = _HaltSpy()
    result = _run(
        log=[], supervised_first_order=True,
        orders_today_count=lambda: 0, halt_writer=spy,
    )
    assert result.supervised_hold is False
    assert spy.reasons == []


def test_supervised_flag_off_never_holds() -> None:
    spy = _HaltSpy()
    result = _run(
        log=[], supervised_first_order=False,
        orders_today_count=lambda: 5, halt_writer=spy,
    )
    assert result.supervised_hold is False
    assert spy.reasons == []


# ---------------------------------------------------------------------------
# G2(d) — post-settle equivalence via a REAL PendingSettler
# ---------------------------------------------------------------------------
def test_g2d_equivalent_after_settle_true() -> None:
    from src.adapters.mock.in_memory_unit_of_work import InMemoryUnitOfWork
    from src.use_cases.pending_settler import PendingSettler

    a = _asset()
    uow = InMemoryUnitOfWork()
    key = build_order_key(
        asset_fqn=a.fqn, date_iso=DATE.isoformat(), side=OrderSide.BUY, slot_number=1
    )
    submitted = datetime(2026, 5, 21, 6, 0, tzinfo=UTC)
    uow.orders.save(
        Order(
            idempotency_key=key, asset=a, side=OrderSide.BUY,
            order_type=OrderType.LIMIT, quantity=Decimal("10"),
            target_price=Decimal("35000"), status=OrderStatus.PENDING,
            broker_order_id="ODNO-1", filled_quantity=Decimal(0),
            filled_price=None, submitted_at=submitted, filled_at=None,
        )
    )

    class _StatusBroker:
        def get_order_status(self, idempotency_key: str) -> OrderResult | None:
            return OrderResult(
                idempotency_key=idempotency_key, asset=a, broker_order_id="ODNO-1",
                status=OrderStatus.FILLED, filled_quantity=Decimal("10"),
                filled_price=Decimal("35000"), submitted_at=submitted,
                filled_at=datetime(2026, 5, 21, 6, 30, tzinfo=UTC),
            )

    settler = PendingSettler(uow_factory=lambda: uow, broker=_StatusBroker())  # type: ignore[arg-type]
    log: list[str] = []

    class _RealSettleAdapter:
        def settle(self, today: date) -> SettleOutcome:
            log.append("settle")
            return settler.settle(today)

    result = run_live_pipeline(
        settler=_RealSettleAdapter(),  # type: ignore[arg-type]
        reconciler=_FakeReconciler(log),  # type: ignore[arg-type]
        orchestrator=_FakeOrchestrator(log),  # type: ignore[arg-type]
        position_source=_FakePositionSource(),  # type: ignore[arg-type]
        notifier=_RecordingNotifier(),  # type: ignore[arg-type]
        today=DATE, intended_tier=CapitalTier.TIER_200, arm_token=ARMED,
        halt_active=False, ntp_synced=True, max_loss_pct=Decimal("20"),
    )
    settled = result.settle.settled_buys[0]
    backtest = Decision(
        timestamp=datetime(2026, 5, 21, 7, 0, tzinfo=UTC), asset=a,
        buy_action=BuyActionRecord(
            slot_number=1, split_level_after=1, filled_quantity=Decimal("10"),
            filled_price=Decimal("35000"), target_price=Decimal("35000"),
            idempotency_key="backtest", reasoning={},
        ),
        reasoning={},
    )
    assert decisions_equivalent(settled, backtest)


# ---------------------------------------------------------------------------
# gap (e) — live close persisted in decision.reasoning (replay determinism)
# ---------------------------------------------------------------------------
def test_live_close_persisted_for_replay(tmp_path) -> None:
    from src.cli import composition
    from src.domain.models import OHLCV
    from src.domain.strategies.price_drop import SplitStrategyConfig

    a = composition.asset_from_code("069500")
    # Decision at 09:00 KST sees the PRIOR close (ADR §9.3) → bar dated DATE-1.
    bar = OHLCV(
        asset=a, trade_date=date(2026, 5, 21),
        open=Decimal("35000"), high=Decimal("35500"), low=Decimal("34500"),
        close=Decimal("35000"), volume=Decimal("1000"),
    )
    components = composition.build_paper_components(
        assets=[a],
        bars_by_asset={a: [bar]},
        db_path=tmp_path / "paper.db",
        initial_capital=Money(amount=Decimal("2000000"), currency=Currency.KRW),
        strategy_config=SplitStrategyConfig(
            drop_threshold_pct=Decimal("5"), max_split_count=7,
            per_split_amount=Money(amount=Decimal("280000"), currency=Currency.KRW),
            max_split_per_day=1,
        ),
        initial_clock=composition.utc_for(DATE, time(9, 0)),
    )
    try:
        decisions = components.orchestrator.run_for_date(DATE)
    finally:
        components.close()
    # The live runner drives this same orchestrator; the close it used is
    # persisted in reasoning → backtest replay determinism (gap e).
    assert decisions[0].reasoning.get("current_price") == "35000"
