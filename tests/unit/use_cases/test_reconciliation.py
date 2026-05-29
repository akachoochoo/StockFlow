"""Unit tests for src.use_cases.reconciliation.reconciler.Reconciler.

Phase 1.1 Stage 3.3 — DB positions vs broker holdings 대조 (CLAUDE.md §11.2).

**안전-크리티컬**: mismatch → notify(CRITICAL) + halt callback + StateMismatchError,
**자동 수정 zero** (어떤 save / place_order 도 호출 안 됨). 일치 → matched True +
side-effect zero.

Fakes (zero real network / DB):
- _FakeBroker      : get_holdings() returns canned BrokerHolding list; records
                     whether any forbidden write (place_order) was attempted.
- _FakePositionRepo: list_all() returns canned Positions; records save() calls.
- _FakeUoW         : context-manager wrapping the repo; records commit / save.
- _RecordingNotifier: records every notify() call.
- halt spy         : Callable[[str], None] recording reasons.
- fixed clock      : deterministic UTC datetime.

Function names carry ``reconciliation`` (gate keyword); the halt-on-mismatch
test is named ``reconciliation_mismatch_halts`` per the task spec.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.domain.exceptions import StateMismatchError
from src.domain.models import (
    Asset,
    AssetClass,
    BrokerHolding,
    Currency,
    Exchange,
    Market,
    Position,
    SplitEntry,
    SplitSlot,
)
from src.ports.notifications import NotificationLevel
from src.use_cases.reconciliation import (
    Reconciler,
    ReconciliationMismatch,
    ReconciliationResult,
)

UTC_NOW = datetime(2026, 5, 22, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Domain builders
# ---------------------------------------------------------------------------
def _asset(code: str = "069500", name: str = "KODEX 200") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name=name,
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _position(
    code: str = "069500",
    *,
    quantity: str = "10",
    avg_price: str = "35000",
) -> Position:
    """A single-slot FILLED Position for the given code."""
    a = _asset(code=code)
    entry = SplitEntry(
        split_number=1,
        entry_date=UTC_NOW.date(),
        quantity=Decimal(quantity),
        entry_price=Decimal(avg_price),
        idempotency_key=f"k-{code}",
    )
    slots: list[SplitSlot] = [SplitSlot.filled(entry=entry)]
    slots.extend(SplitSlot.empty(slot_number=i) for i in range(2, 8))
    return Position(
        asset=a,
        quantity=Decimal(quantity),
        avg_price=Decimal(avg_price),
        split_level=1,
        last_buy_at=UTC_NOW,
        slots=slots,
    )


def _holding(
    code: str = "069500",
    *,
    quantity: str = "10",
    avg_price: str = "35000",
) -> BrokerHolding:
    return BrokerHolding(
        asset_code=code,
        quantity=Decimal(quantity),
        avg_price=Decimal(avg_price),
    )


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeBroker:
    """Returns canned holdings; flags any forbidden write attempt."""

    def __init__(self, holdings: list[BrokerHolding]) -> None:
        self._holdings = list(holdings)
        self.place_order_calls = 0

    def get_holdings(self) -> list[BrokerHolding]:
        return list(self._holdings)

    def place_order(self, *args: object, **kwargs: object) -> None:
        # Reconciliation must NEVER auto-correct via the broker.
        self.place_order_calls += 1
        raise AssertionError("reconciliation must not call place_order")


class _FakePositionRepo:
    """list_all() returns canned Positions; records save() calls (must be 0)."""

    def __init__(self, positions: list[Position]) -> None:
        self._positions = list(positions)
        self.save_calls = 0

    def list_all(self) -> list[Position]:
        return list(self._positions)

    def save(self, position: Position) -> None:
        self.save_calls += 1
        raise AssertionError("reconciliation must not save positions")


class _FakeGridDecisionRepo:
    """ADR 0022 §13 D26 — minimal stand-in for GridDecisionRepoPort.

    Only ``list_net_quantities`` 가 reconciler 에서 호출됨. 다른 메서드는
    AssertionError 로 reconciliation 이 의도치 않은 호출을 못 하도록 보호.
    """

    def __init__(self, net: dict[str, Decimal] | None = None) -> None:
        self._net = dict(net) if net else {}

    def list_net_quantities(self) -> dict[str, Decimal]:
        return dict(self._net)

    def save(self, *args, **kwargs) -> None:  # noqa: ARG002
        raise AssertionError("reconciliation must not save grid_decisions")

    def list_for_date(self, *args, **kwargs):  # noqa: ARG002
        raise AssertionError("reconciliation must not query grid_decisions by date")

    def list_by_date_range(self, *args, **kwargs):  # noqa: ARG002
        raise AssertionError("reconciliation must not query grid_decisions by date range")


class _FakeUoW:
    """Minimal UnitOfWork stand-in exposing ``positions`` + ``grid_decisions``."""

    def __init__(
        self,
        repo: _FakePositionRepo,
        grid_repo: _FakeGridDecisionRepo | None = None,
    ) -> None:
        self.positions = repo
        self.grid_decisions = grid_repo or _FakeGridDecisionRepo()
        self.commit_calls = 0
        self.entered = False

    def __enter__(self) -> _FakeUoW:
        self.entered = True
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_calls += 1


class _RecordingNotifier:
    """Records every notify() call (level, title, body)."""

    def __init__(self) -> None:
        self.calls: list[tuple[NotificationLevel, str, str]] = []

    def notify(
        self, *, level: NotificationLevel, title: str, body: str
    ) -> None:
        self.calls.append((level, title, body))


class _HaltSpy:
    """Records halt reasons (composition injects safety.write_halt here)."""

    def __init__(self) -> None:
        self.reasons: list[str] = []

    def __call__(self, reason: str) -> None:
        self.reasons.append(reason)


def _build(
    *,
    positions: list[Position],
    holdings: list[BrokerHolding],
    grid_net: dict[str, Decimal] | None = None,
) -> tuple[Reconciler, _FakeBroker, _FakePositionRepo, _RecordingNotifier, _HaltSpy]:
    repo = _FakePositionRepo(positions)
    uow = _FakeUoW(repo, _FakeGridDecisionRepo(grid_net))
    broker = _FakeBroker(holdings)
    notifier = _RecordingNotifier()
    halt = _HaltSpy()
    reconciler = Reconciler(
        # Structural fakes — only the methods the Reconciler actually calls are
        # implemented (positions.list_all / get_holdings / notify); mypy can't
        # see the duck-typed match against the full Ports.
        uow_factory=lambda: uow,  # type: ignore[arg-type, return-value]
        broker=broker,  # type: ignore[arg-type]
        notifier=notifier,
        halt=halt,
        clock=lambda: UTC_NOW,
    )
    return reconciler, broker, repo, notifier, halt


# ---------------------------------------------------------------------------
# Matched — no side effects
# ---------------------------------------------------------------------------
class TestReconciliationMatched:
    def test_reconciliation_matched_returns_matched_result(self) -> None:
        reconciler, _, _, _, _ = _build(
            positions=[_position("069500", quantity="10")],
            holdings=[_holding("069500", quantity="10")],
        )
        result = reconciler.reconcile()
        assert isinstance(result, ReconciliationResult)
        assert result.matched is True
        assert result.mismatches == []

    def test_reconciliation_matched_has_zero_side_effects(self) -> None:
        reconciler, broker, repo, notifier, halt = _build(
            positions=[_position("069500", quantity="10")],
            holdings=[_holding("069500", quantity="10")],
        )
        reconciler.reconcile()
        assert notifier.calls == []
        assert halt.reasons == []
        assert repo.save_calls == 0
        assert broker.place_order_calls == 0

    def test_reconciliation_matched_empty_both_sides(self) -> None:
        """No DB positions and no broker holdings → matched, no side effects."""
        reconciler, _, _, notifier, halt = _build(positions=[], holdings=[])
        result = reconciler.reconcile()
        assert result.matched is True
        assert notifier.calls == []
        assert halt.reasons == []

    def test_reconciliation_matched_ignores_avg_price_difference(self) -> None:
        """avg_price差 (broker rounding) is detail-only — quantity matches → OK."""
        reconciler, _, _, notifier, halt = _build(
            positions=[_position("069500", quantity="10", avg_price="35000")],
            holdings=[_holding("069500", quantity="10", avg_price="35001")],
        )
        result = reconciler.reconcile()
        assert result.matched is True
        assert notifier.calls == []
        assert halt.reasons == []

    def test_reconciliation_matched_multiple_symbols(self) -> None:
        reconciler, _, _, notifier, halt = _build(
            positions=[
                _position("069500", quantity="10"),
                _position("005930", quantity="7"),
            ],
            holdings=[
                _holding("069500", quantity="10"),
                _holding("005930", quantity="7"),
            ],
        )
        assert reconciler.reconcile().matched is True
        assert notifier.calls == []
        assert halt.reasons == []


# ---------------------------------------------------------------------------
# Mismatch — halt + alert + raise, zero auto-correction
# ---------------------------------------------------------------------------
class TestReconciliationMismatch:
    def test_reconciliation_mismatch_halts_on_quantity_difference(self) -> None:
        """Quantity differs → CRITICAL alert + halt callback + StateMismatchError."""
        reconciler, broker, repo, notifier, halt = _build(
            positions=[_position("069500", quantity="10")],
            holdings=[_holding("069500", quantity="8")],
        )
        with pytest.raises(StateMismatchError, match="069500"):
            reconciler.reconcile()
        # Alert: exactly one CRITICAL notification.
        assert len(notifier.calls) == 1
        level, title, body = notifier.calls[0]
        assert level is NotificationLevel.CRITICAL
        assert "069500" in body
        assert title  # non-empty
        # Halt callback fired with a detailed reason.
        assert len(halt.reasons) == 1
        assert "069500" in halt.reasons[0]
        # Zero auto-correction.
        assert repo.save_calls == 0
        assert broker.place_order_calls == 0

    def test_reconciliation_mismatch_db_only_symbol(self) -> None:
        """Asset in DB but absent at broker → mismatch (broker_quantity None)."""
        reconciler, _, _, notifier, halt = _build(
            positions=[_position("069500", quantity="10")],
            holdings=[],
        )
        with pytest.raises(StateMismatchError, match="069500"):
            reconciler.reconcile()
        assert len(notifier.calls) == 1
        assert len(halt.reasons) == 1

    def test_reconciliation_mismatch_broker_only_symbol(self) -> None:
        """Asset at broker but absent in DB → mismatch (db_quantity None)."""
        reconciler, _, _, notifier, halt = _build(
            positions=[],
            holdings=[_holding("005930", quantity="5")],
        )
        with pytest.raises(StateMismatchError, match="005930"):
            reconciler.reconcile()
        assert len(notifier.calls) == 1
        assert len(halt.reasons) == 1

    def test_reconciliation_mismatch_partial_overlap(self) -> None:
        """One matching + one mismatching symbol → still halts."""
        reconciler, _, _, notifier, halt = _build(
            positions=[
                _position("069500", quantity="10"),
                _position("005930", quantity="7"),
            ],
            holdings=[
                _holding("069500", quantity="10"),  # match
                _holding("005930", quantity="3"),  # mismatch
            ],
        )
        with pytest.raises(StateMismatchError, match="005930"):
            reconciler.reconcile()
        assert len(notifier.calls) == 1
        assert len(halt.reasons) == 1

    def test_reconciliation_mismatch_alert_before_raise(self) -> None:
        """Alert + halt must both fire before the exception propagates."""
        reconciler, _, _, notifier, halt = _build(
            positions=[_position("069500", quantity="10")],
            holdings=[_holding("069500", quantity="9")],
        )
        with pytest.raises(StateMismatchError):
            reconciler.reconcile()
        # Both side effects recorded despite the raise.
        assert notifier.calls
        assert halt.reasons

    def test_reconciliation_mismatch_zero_position_filtered(self) -> None:
        """A DB Position with quantity 0 is not held → not a mismatch source.

        Empty (sold-out) positions report quantity 0; get_holdings excludes
        them too, so an empty-DB / empty-broker pair stays matched.
        """
        empty = Position.empty(_asset("069500"))
        reconciler, _, _, notifier, halt = _build(
            positions=[empty],
            holdings=[],
        )
        result = reconciler.reconcile()
        assert result.matched is True
        assert notifier.calls == []
        assert halt.reasons == []


# ---------------------------------------------------------------------------
# Mismatch DTO
# ---------------------------------------------------------------------------
class TestReconciliationMismatchDto:
    def test_mismatch_dto_carries_both_quantities(self) -> None:
        m = ReconciliationMismatch(
            asset_code="069500",
            db_quantity=Decimal("10"),
            broker_quantity=Decimal("8"),
            db_avg_price=Decimal("35000"),
            broker_avg_price=Decimal("34000"),
        )
        assert m.asset_code == "069500"
        assert m.db_quantity == Decimal("10")
        assert m.broker_quantity == Decimal("8")

    def test_mismatch_dto_none_for_missing_side(self) -> None:
        m = ReconciliationMismatch(
            asset_code="005930",
            db_quantity=None,
            broker_quantity=Decimal("5"),
        )
        assert m.db_quantity is None
        assert m.broker_quantity == Decimal("5")


# ===========================================================================
# ADR 0022 §13 D26 — Grid 보유 인식
# ===========================================================================


class TestGridReconciliation:
    """Reconciler 가 grid 보유를 split Position 과 같은 asset_code 키로 합산."""

    def test_grid_only_asset_matches_broker(self) -> None:
        """split Position zero + grid net 12 + broker 12 → match."""
        reconciler, broker, _repo, notifier, halt = _build(
            positions=[],
            holdings=[
                BrokerHolding(
                    asset_code="095660",
                    quantity=Decimal("12"),
                    avg_price=Decimal("30000"),
                )
            ],
            grid_net={"KRX:095660": Decimal("12")},
        )
        result = reconciler.reconcile()
        assert result.matched is True
        assert result.mismatches == []
        assert notifier.calls == []
        assert halt.reasons == []

    def test_grid_only_asset_mismatch_halts(self) -> None:
        """grid net 12 + broker 0 → mismatch + halt."""
        reconciler, broker, _repo, notifier, halt = _build(
            positions=[],
            holdings=[],  # broker 빈 보유
            grid_net={"KRX:095660": Decimal("12")},
        )
        with pytest.raises(StateMismatchError):
            reconciler.reconcile()
        assert len(notifier.calls) == 1
        assert notifier.calls[0][0] is NotificationLevel.CRITICAL
        assert "095660" in notifier.calls[0][2]
        assert len(halt.reasons) == 1

    def test_split_plus_grid_sum_matches_broker(self) -> None:
        """같은 종목에 split 5 + grid 7 = 12, broker 12 → match (방어적 합산)."""
        asset = _asset("069500")
        positions = [
            Position(
                asset=asset,
                quantity=Decimal("5"),
                avg_price=Decimal("28000"),
                split_level=1,
                last_buy_at=datetime(2026, 5, 22, 6, 0, 0, tzinfo=UTC),
                slots=[
                    SplitSlot(
                        slot_number=1,
                        state=__import__(
                            "src.domain.models", fromlist=["SlotState"]
                        ).SlotState.FILLED,
                        entry=SplitEntry(
                            split_number=1,
                            entry_date=date(2026, 5, 22),
                            quantity=Decimal("5"),
                            entry_price=Decimal("28000"),
                            idempotency_key="k1",
                        ),
                    ),
                    *[
                        SplitSlot(
                            slot_number=i,
                            state=__import__(
                                "src.domain.models", fromlist=["SlotState"]
                            ).SlotState.EMPTY,
                        )
                        for i in range(2, 8)
                    ],
                ],
            )
        ]
        reconciler, _broker, _repo, _notifier, _halt = _build(
            positions=positions,
            holdings=[
                BrokerHolding(
                    asset_code="069500",
                    quantity=Decimal("12"),
                    avg_price=Decimal("28500"),
                )
            ],
            grid_net={"KRX:069500": Decimal("7")},
        )
        result = reconciler.reconcile()
        assert result.matched is True

    def test_grid_zero_net_excluded_from_db_positions(self) -> None:
        """grid net 0 (완전 매도) 자산은 DB 보유 0 으로 취급 — broker 0 이면 match."""
        reconciler, _broker, _repo, _notifier, _halt = _build(
            positions=[],
            holdings=[],
            grid_net={},  # list_net_quantities 가 qty>0 만 반환
        )
        result = reconciler.reconcile()
        assert result.matched is True

    def test_grid_decision_asset_fqn_decomposed_to_code(self) -> None:
        """asset_fqn 의 마지막 세그먼트가 asset_code 로 사용됨."""
        reconciler, _broker, _repo, notifier, halt = _build(
            positions=[],
            holdings=[
                BrokerHolding(
                    asset_code="069500",  # KRX:069500 의 코드
                    quantity=Decimal("5"),
                    avg_price=Decimal("30000"),
                )
            ],
            grid_net={"KRX:069500": Decimal("5")},
        )
        result = reconciler.reconcile()
        assert result.matched is True
        # 다른 fqn 형식 (e.g., 가상 NASDAQ:AAPL) 도 마지막 세그먼트 사용 가능
        reconciler2, _b2, _r2, n2, h2 = _build(
            positions=[],
            holdings=[
                BrokerHolding(
                    asset_code="AAPL",
                    quantity=Decimal("10"),
                    avg_price=Decimal("180"),
                )
            ],
            grid_net={"NASDAQ:AAPL": Decimal("10")},
        )
        assert reconciler2.reconcile().matched is True
