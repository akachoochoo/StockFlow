"""Tests for SqlitePositionRepo (round-trip + cascade + asset_json).

Phase 0.5 (ADR 0002 §3): the schema persists ``split_slots`` rows that
carry ``state``, the optional ``entry_*`` columns when FILLED, and the
optional ``last_exit_*`` history regardless of state.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Position,
    SlotState,
    SplitEntry,
    SplitSlot,
)
from src.infrastructure.repositories.sqlite_position_repo import (
    SqlitePositionRepo,
)

UTC_NOW = datetime(2026, 4, 30, 6, 0, 0, tzinfo=UTC)
TRADE_DATE = date(2026, 4, 29)
EXIT_DATE = date(2026, 4, 27)


def _asset(code: str = "069500", name: str = "KODEX 200") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name=name,
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
    )


def _split_entry(
    n: int, qty: str = "10", price: str = "35000", key_suffix: str = ""
) -> SplitEntry:
    return SplitEntry(
        split_number=n,
        entry_date=TRADE_DATE,
        quantity=Decimal(qty),
        entry_price=Decimal(price),
        idempotency_key=f"k{n}{key_suffix}",
    )


def _build_position(
    asset: Asset,
    *entries: SplitEntry,
    quantity: Decimal,
    avg_price: Decimal,
    last_buy_at: datetime | None = UTC_NOW,
    extra_empty_slots: list[SplitSlot] | None = None,
    max_split_count: int = 7,
) -> Position:
    """Build a Position from a sparse list of FILLED entries.

    `entries` may have any slot_numbers in [1, max_split_count] without
    needing to be sequential. Slots not covered by entries default to
    EMPTY (no exit history); pass `extra_empty_slots` to override
    individual EMPTY slots with last_exit_* metadata.
    """
    extras = {s.slot_number: s for s in (extra_empty_slots or [])}
    filled_by_num = {e.split_number: SplitSlot.filled(entry=e) for e in entries}
    slots: list[SplitSlot] = []
    for i in range(1, max_split_count + 1):
        if i in filled_by_num:
            slots.append(filled_by_num[i])
        elif i in extras:
            slots.append(extras[i])
        else:
            slots.append(SplitSlot.empty(slot_number=i))
    return Position(
        asset=asset,
        quantity=quantity,
        avg_price=avg_price,
        split_level=len(entries),
        last_buy_at=last_buy_at,
        slots=slots,
    )


class TestSqlitePositionRepoRoundTrip:
    def test_save_then_get_returns_equal_position(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        original = _build_position(
            a,
            _split_entry(1, qty="14"),
            _split_entry(2, qty="14", price="35000"),
            quantity=Decimal("28"),
            avg_price=Decimal("35000"),
        )
        repo.save(original)
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.asset == a
        assert loaded.quantity == Decimal("28")
        assert loaded.avg_price == Decimal("35000")
        assert loaded.split_level == 2
        assert loaded.last_buy_at == UTC_NOW
        assert [s.slot_number for s in loaded.filled_slots] == [1, 2]
        slot1 = loaded.get_slot(1)
        assert slot1 is not None and slot1.entry is not None
        assert slot1.entry.entry_date == TRADE_DATE
        # All seven slots round-trip (sequence 1..7)
        assert [s.slot_number for s in loaded.slots] == [1, 2, 3, 4, 5, 6, 7]

    def test_get_returns_none_for_unknown_fqn(self, conn):
        repo = SqlitePositionRepo(conn)
        assert repo.get("KRX:000000") is None

    def test_save_empty_position(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        empty = Position.empty(a)
        repo.save(empty)
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.quantity == Decimal(0)
        assert loaded.split_level == 0
        assert loaded.filled_slots == []
        assert loaded.last_buy_at is None

    def test_round_trip_preserves_last_exit_history_on_empty_slots(
        self, conn
    ):
        # Phase 0.5 (ADR 0002 §3.1): EMPTY slots may carry last_exit_*
        # so the HybridTimeBasedReentry policy can decide a reentry trigger.
        repo = SqlitePositionRepo(conn)
        a = _asset()
        original = _build_position(
            a,
            _split_entry(1, qty="10"),
            quantity=Decimal("10"),
            avg_price=Decimal("35000"),
            extra_empty_slots=[
                SplitSlot.empty(
                    slot_number=2,
                    last_exit_price=Decimal("33000"),
                    last_exit_date=EXIT_DATE,
                ),
            ],
        )
        repo.save(original)
        loaded = repo.get(a.fqn)
        assert loaded is not None
        slot2 = loaded.get_slot(2)
        assert slot2 is not None
        assert slot2.state is SlotState.EMPTY
        assert slot2.last_exit_price == Decimal("33000")
        assert slot2.last_exit_date == EXIT_DATE


class TestSqlitePositionRepoUpsert:
    def test_save_existing_position_replaces_slots(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        # Initial save: split_level 1
        repo.save(
            _build_position(
                a,
                _split_entry(1, qty="10"),
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
            )
        )
        # Upsert: split_level 2 (slots replaced wholesale)
        repo.save(
            _build_position(
                a,
                _split_entry(1, qty="10", price="35000"),
                _split_entry(2, qty="10", price="31000", key_suffix="b"),
                quantity=Decimal("20"),
                avg_price=Decimal("33000"),
            )
        )
        loaded = repo.get(a.fqn)
        assert loaded is not None
        assert loaded.split_level == 2
        assert [s.slot_number for s in loaded.filled_slots] == [1, 2]
        slot2 = loaded.get_slot(2)
        assert slot2 is not None and slot2.entry is not None
        assert slot2.entry.idempotency_key == "k2b"

    def test_asset_json_preserved_on_update(self, conn):
        # ADR §8.3: asset_json is point-in-time. Updates do NOT overwrite it.
        repo = SqlitePositionRepo(conn)
        a_old = _asset(name="KODEX 200")
        repo.save(Position.empty(a_old))
        # Caller now passes a renamed Asset (mimicking metadata change)
        a_new = _asset(name="KODEX 200 (renamed)")
        repo.save(Position.empty(a_new))
        loaded = repo.get(a_old.fqn)
        assert loaded is not None
        # The stored asset is the original — point-in-time integrity intact.
        assert loaded.asset.name == "KODEX 200"


class TestSqlitePositionRepoListAndDelete:
    def test_list_all_returns_every_position(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset(code="069500", name="KODEX 200")
        b = _asset(code="105190", name="KODEX 코스닥")
        repo.save(Position.empty(a))
        repo.save(Position.empty(b))
        positions = repo.list_all()
        fqns = {p.asset.fqn for p in positions}
        assert fqns == {"KRX:069500", "KRX:105190"}

    def test_list_all_empty(self, conn):
        repo = SqlitePositionRepo(conn)
        assert repo.list_all() == []

    def test_delete_returns_true_when_present(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        repo.save(Position.empty(a))
        assert repo.delete(a.fqn) is True
        assert repo.get(a.fqn) is None

    def test_delete_returns_false_when_missing(self, conn):
        repo = SqlitePositionRepo(conn)
        assert repo.delete("KRX:999999") is False

    def test_delete_cascades_split_slots(self, conn):
        repo = SqlitePositionRepo(conn)
        a = _asset()
        repo.save(
            _build_position(
                a,
                _split_entry(1, qty="10"),
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
            )
        )
        # Sanity: rows exist (one per slot, all 7 of them)
        count = conn.execute(
            "SELECT COUNT(*) FROM split_slots"
        ).fetchone()[0]
        assert count == 7
        repo.delete(a.fqn)
        count = conn.execute(
            "SELECT COUNT(*) FROM split_slots"
        ).fetchone()[0]
        assert count == 0
