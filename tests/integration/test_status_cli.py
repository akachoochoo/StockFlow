"""`trading status` CLI integration tests.

status 는 read-only 운영 조회 커맨드 — 네트워크/주문/lock zero. halt 상태
(env kill switch + 영속 sentinel) / DB 포지션 / grid 순보유 / PENDING 주문 /
마지막 snapshot 출력을 검증한다.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.cli import safety
from src.cli.main import main
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    SplitEntry,
    SplitSlot,
)
from src.infrastructure.db import connect
from src.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_sentinels(tmp_path, monkeypatch):
    """Redirect halt sentinel into tmp so tests never touch the real one."""
    monkeypatch.setattr(safety, "_HALT_PATH", tmp_path / "test.halt")
    monkeypatch.delenv("TRADING_HALT", raising=False)


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


def _position(code: str = "069500") -> Position:
    entry = SplitEntry(
        split_number=1,
        entry_date=date(2026, 6, 1),
        quantity=Decimal("10"),
        entry_price=Decimal("35000"),
        idempotency_key=f"k-{code}",
    )
    slots: list[SplitSlot] = [SplitSlot.filled(entry=entry)]
    slots.extend(SplitSlot.empty(slot_number=i) for i in range(2, 8))
    return Position(
        asset=_asset(code),
        quantity=Decimal("10"),
        avg_price=Decimal("35000"),
        split_level=1,
        last_buy_at=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        slots=slots,
    )


def _pending_order(key: str = "KRX:069500:2026-06-11:buy:1") -> Order:
    return Order(
        idempotency_key=key,
        asset=_asset(),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        target_price=Decimal("35000"),
        status=OrderStatus.PENDING,
        broker_order_id=None,
        filled_quantity=Decimal(0),
        filled_price=None,
        submitted_at=datetime(2026, 6, 11, 0, 30, tzinfo=UTC),
        filled_at=None,
    )


def _seed_db(
    db_path: Path,
    *,
    positions: list[Position] | None = None,
    orders: list[Order] | None = None,
) -> None:
    conn = connect(db_path)
    try:
        with SqliteUnitOfWork(conn) as uow:
            for p in positions or []:
                uow.positions.save(p)
            for o in orders or []:
                uow.orders.save(o)
            uow.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestStatusCli:
    def test_status_without_db_file_reports_and_exits_zero(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            main, ["status", "--db", str(tmp_path / "absent.db")]
        )
        assert result.exit_code == 0
        assert "DB 파일 없음" in result.output
        assert "sentinel: 없음" in result.output

    def test_status_shows_halt_sentinel_reason(self, tmp_path):
        safety.write_halt("reconciliation mismatch 조사 중")
        runner = CliRunner()
        result = runner.invoke(
            main, ["status", "--db", str(tmp_path / "absent.db")]
        )
        assert result.exit_code == 0
        assert "HALTED" in result.output
        assert "reconciliation mismatch 조사 중" in result.output
        assert "trading resume" in result.output

    def test_status_blocked_by_env_kill_switch_clean_exit(
        self, tmp_path, monkeypatch
    ):
        """TRADING_HALT=1 은 group 레벨에서 status 포함 모든 커맨드를 clean
        exit(0) 시킨다 (§11.1) — status 본문은 실행되지 않는다."""
        monkeypatch.setenv("TRADING_HALT", "1")
        runner = CliRunner()
        result = runner.invoke(
            main, ["status", "--db", str(tmp_path / "absent.db")]
        )
        assert result.exit_code == 0
        assert "=== halt ===" not in result.output

    def test_status_empty_db_shows_no_pending_no_snapshot(self, tmp_path):
        db = tmp_path / "trading.db"
        _seed_db(db)
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--db", str(db)])
        assert result.exit_code == 0
        assert "split 포지션: 0 종목" in result.output
        assert "PENDING 주문: 없음" in result.output
        assert "마지막 snapshot: 없음" in result.output

    def test_status_shows_positions_and_pending_orders(self, tmp_path):
        db = tmp_path / "trading.db"
        _seed_db(db, positions=[_position()], orders=[_pending_order()])
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--db", str(db)])
        assert result.exit_code == 0
        assert "split 포지션: 1 종목" in result.output
        assert "KRX:069500" in result.output
        assert "PENDING 주문: 1 건" in result.output
        assert "KRX:069500:2026-06-11:buy:1" in result.output
        # PENDING 안내 (CLAUDE.md §4.3 사람 확인 경로)
        assert "§4.3" in result.output

    def test_status_is_read_only(self, tmp_path):
        """status 실행이 DB 를 변경하지 않는다 (mtime 무관 — 내용 비교)."""
        db = tmp_path / "trading.db"
        _seed_db(db, positions=[_position()], orders=[_pending_order()])
        before = db.read_bytes()
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--db", str(db)])
        assert result.exit_code == 0
        assert db.read_bytes() == before
