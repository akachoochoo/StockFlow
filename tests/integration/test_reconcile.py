"""CLI integration tests for ``trading reconcile`` (Phase 1.1 Stage 4).

Exercises the reconciliation command end-to-end through Click's ``CliRunner``
with a **fake HttpClient** (canned KIS ``inquire-balance`` bodies) injected via
``composition.build_reconciler`` — **zero real network**. DB positions are
seeded into a ``tmp_path`` SQLite file; the halt sentinel is redirected to
``tmp_path`` (spy) so no real ``~/.trading-system.halt`` is touched; the
notifier is a recording spy.

Real-money invariants verified here (안전-크리티컬, CLAUDE.md §11.2):
- 실주문 zero — only the OAuth token POST + ``inquire-balance`` GET occur; no
  ``order-cash`` POST is ever issued (asserted on the fake http call log).
- 실계좌 read만 — KISBroker exposes only ``get_holdings`` (read); reconciliation
  never saves / places orders (자동 수정 zero — structural Reconciler guarantee).
- 불일치 → notify(CRITICAL) + 영속 halt sentinel + StateMismatchError → exit≠0.

Function names carry ``reconcile`` (Stage gate selector).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from src.adapters.kis._http import HttpResponse
from src.cli import composition, safety
from src.cli.main import main
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Position,
    SplitEntry,
    SplitSlot,
)
from src.infrastructure.db import connect
from src.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork
from src.ports.notifications import NotificationLevel

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


# ---------------------------------------------------------------------------
# Test secrets (clearly fake — never real credentials)
# ---------------------------------------------------------------------------
_FAKE_APPKEY = "PKfakeappkey0123456789"
_FAKE_APPSECRET = "FAKE_APPSECRET_must_never_be_printed=="
_FAKE_TOKEN = "FAKE_ACCESS_TOKEN_must_never_be_printed"


def _paper_environ() -> dict[str, str]:
    """A complete paper-mode KIS env mapping (KISConfig.from_env happy path)."""
    return {
        "KIS_TRADING_MODE": "paper",
        "KIS_PAPER_APPKEY": _FAKE_APPKEY,
        "KIS_PAPER_APPSECRET": _FAKE_APPSECRET,
        "KIS_PAPER_ACCOUNT_CANO": "50012345",
        "KIS_PAPER_ACCOUNT_PRDT_CD": "01",
    }


# ---------------------------------------------------------------------------
# Canned KIS wire bodies (numeric fields as strings — ADR 0020 §2.2)
# ---------------------------------------------------------------------------
def _token_body() -> dict[str, object]:
    return {
        "access_token": _FAKE_TOKEN,
        "access_token_token_expired": "2026-05-23 12:00:00",
        "token_type": "Bearer",
        "expires_in": "86400",
    }


def _holding_row(
    *, pdno: str = "069500", hldg_qty: str = "10", avg: str = "35000"
) -> dict[str, object]:
    return {
        "pdno": pdno,
        "prdt_name": "ETF",
        "hldg_qty": hldg_qty,
        "ord_psbl_qty": hldg_qty,
        "pchs_avg_pric": avg,
        "prpr": "36000",
        "evlu_pfls_amt": "0",
        "evlu_pfls_rt": "0",
        "pchs_amt": "0",
        "evlu_amt": "0",
    }


def _balance_body(
    output1: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """inquire-balance envelope. ``output1`` = holdings rows (default: empty)."""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": output1 if output1 is not None else [],
        "output2": [
            {
                "dnca_tot_amt": "5000000",
                "tot_evlu_amt": "5000000",
                "nass_amt": "5000000",
                "scts_evlu_amt": "0",
                "evlu_pfls_smtl_amt": "0",
                "pchs_amt_smtl_amt": "0",
                "thdt_tlex_amt": "0",
            }
        ],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


def _error_envelope(rt_cd: str = "1", msg_cd: str = "EGW00123") -> dict[str, object]:
    return {
        "rt_cd": rt_cd,
        "msg_cd": msg_cd,
        "msg1": "오류",
        "output1": [],
        "output2": [],
    }


# ---------------------------------------------------------------------------
# Fake HttpClient — routes by URL, returns canned HttpResponse (zero network)
# ---------------------------------------------------------------------------
class _FakeHttp:
    """HttpClient stand-in. token POST + inquire-balance GET only.

    Records every outbound call so a test can assert read-only (no order-cash
    POST). Any other POST/GET raises (would mean a write surface leaked in).
    """

    def __init__(
        self,
        *,
        token_status: int = 200,
        balance_body: dict[str, object] | None = None,
        balance_status: int = 200,
    ) -> None:
        self._token_status = token_status
        self._balance_body = (
            balance_body if balance_body is not None else _balance_body()
        )
        self._balance_status = balance_status
        self.calls: list[tuple[str, str]] = []  # (method, url)

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float = 10.0,
    ) -> HttpResponse:
        self.calls.append(("POST", url))
        if "/oauth2/tokenP" in url:
            if self._token_status != 200:
                return HttpResponse(
                    status_code=self._token_status,
                    body={"msg_cd": "EGW00133", "error_description": "auth failed"},
                )
            return HttpResponse(status_code=200, body=_token_body())
        # No other POST should occur in a read-only reconcile.
        raise AssertionError(f"unexpected POST to {url}")

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float = 10.0,
    ) -> HttpResponse:
        self.calls.append(("GET", url))
        if "inquire-balance" in url:
            return HttpResponse(
                status_code=self._balance_status, body=self._balance_body
            )
        raise AssertionError(f"unexpected GET to {url}")


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 22, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Recording fakes (notifier + halt spy)
# ---------------------------------------------------------------------------
class _RecordingNotifier:
    """Records every notify() call (level, title, body)."""

    def __init__(self) -> None:
        self.calls: list[tuple[NotificationLevel, str, str]] = []

    def notify(
        self, *, level: NotificationLevel, title: str, body: str
    ) -> None:
        self.calls.append((level, title, body))


class _HaltSpy:
    """Records halt reasons (stands in for safety.write_halt — sentinel-free)."""

    def __init__(self) -> None:
        self.reasons: list[str] = []

    def __call__(self, reason: str) -> None:
        self.reasons.append(reason)


# ---------------------------------------------------------------------------
# DB seeding
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
    code: str = "069500", *, quantity: str = "10", avg_price: str = "35000"
) -> Position:
    a = _asset(code=code)
    entry = SplitEntry(
        split_number=1,
        entry_date=date(2026, 5, 1),
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
        last_buy_at=datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
        slots=slots,
    )


def _seed_db(db_path: Path, positions: list[Position]) -> None:
    """Persist the given positions into a fresh SQLite DB at ``db_path``."""
    conn = connect(db_path)
    try:
        with SqliteUnitOfWork(conn) as uow:
            for position in positions:
                uow.positions.save(position)
            uow.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path, monkeypatch):
    """Redirect the lock + halt files into tmp so reconcile tests never touch
    the real ~/.trading-system.lock / ~/.trading-system.halt sentinels.
    """
    monkeypatch.setattr(safety, "_DEFAULT_LOCK_PATH", tmp_path / "test.lock")
    monkeypatch.setattr(safety, "_HALT_PATH", tmp_path / "test.halt")


def _patch_build(
    monkeypatch,
    fake_http: _FakeHttp,
    *,
    notifier: _RecordingNotifier,
    halt: _HaltSpy,
    environ: dict[str, str] | None = None,
) -> None:
    """Patch composition.build_reconciler to inject the fake http + fixed clock
    + recording notifier + halt spy + the given environ (network/sentinel-free).
    The CLI passes only ``db_path`` positionally; we forward it verbatim.
    """
    real_build = composition.build_reconciler
    env = environ if environ is not None else _paper_environ()

    def _patched(db_path, *_args: object, **_kwargs: object):
        return real_build(
            db_path,
            env,
            http=fake_http,
            clock=_fixed_clock,
            notifier=notifier,
            halt=halt,
        )

    monkeypatch.setattr(composition, "build_reconciler", _patched)


# ---------------------------------------------------------------------------
# build_reconciler — composition root (direct)
# ---------------------------------------------------------------------------
class TestBuildReconciler:
    def test_reconcile_build_returns_reconciler_close_config(
        self, tmp_path
    ) -> None:
        from src.adapters.kis.config import TradingMode
        from src.use_cases.reconciliation import Reconciler

        db = tmp_path / "trading.db"
        _seed_db(db, [])
        fake = _FakeHttp()
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        reconciler, close, config = composition.build_reconciler(
            db,
            _paper_environ(),
            http=fake,
            clock=_fixed_clock,
            notifier=notifier,
            halt=halt,
        )
        try:
            assert isinstance(reconciler, Reconciler)
            assert config.mode is TradingMode.PAPER
        finally:
            close()

    def test_reconcile_build_reconcile_matches_empty(self, tmp_path) -> None:
        db = tmp_path / "trading.db"
        _seed_db(db, [])
        fake = _FakeHttp()  # broker holdings empty (default)
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        reconciler, close, _ = composition.build_reconciler(
            db,
            _paper_environ(),
            http=fake,
            clock=_fixed_clock,
            notifier=notifier,
            halt=halt,
        )
        try:
            result = reconciler.reconcile()
        finally:
            close()
        assert result.matched is True
        assert notifier.calls == []
        assert halt.reasons == []

    def test_reconcile_build_halt_spy_invoked_on_mismatch(self, tmp_path) -> None:
        from src.domain.exceptions import StateMismatchError

        db = tmp_path / "trading.db"
        _seed_db(db, [])  # DB empty
        fake = _FakeHttp(
            balance_body=_balance_body([_holding_row(hldg_qty="5")])
        )  # broker has 5
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        reconciler, close, _ = composition.build_reconciler(
            db,
            _paper_environ(),
            http=fake,
            clock=_fixed_clock,
            notifier=notifier,
            halt=halt,
        )
        try:
            with pytest.raises(StateMismatchError):
                reconciler.reconcile()
        finally:
            close()
        assert len(halt.reasons) == 1
        assert "069500" in halt.reasons[0]


# ---------------------------------------------------------------------------
# trading reconcile — matched
# ---------------------------------------------------------------------------
class TestReconcileMatched:
    def test_reconcile_matched_empty_both_sides_exits_zero(
        self, tmp_path, monkeypatch
    ) -> None:
        db = tmp_path / "trading.db"
        _seed_db(db, [])
        fake = _FakeHttp()  # broker holdings empty
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code == 0, result.output
        assert "reconciliation matched" in result.output
        assert "mode=paper" in result.output
        assert notifier.calls == []
        assert halt.reasons == []

    def test_reconcile_matched_nonempty_exits_zero(
        self, tmp_path, monkeypatch
    ) -> None:
        db = tmp_path / "trading.db"
        _seed_db(db, [_position("069500", quantity="10")])
        fake = _FakeHttp(
            balance_body=_balance_body(
                [_holding_row(pdno="069500", hldg_qty="10")]
            )
        )
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code == 0, result.output
        assert "reconciliation matched" in result.output
        assert notifier.calls == []
        assert halt.reasons == []

    def test_reconcile_is_read_only_no_order_post(
        self, tmp_path, monkeypatch
    ) -> None:
        """Only the token POST + inquire-balance GET occur — zero order POST."""
        db = tmp_path / "trading.db"
        _seed_db(db, [_position("069500", quantity="10")])
        fake = _FakeHttp(
            balance_body=_balance_body(
                [_holding_row(pdno="069500", hldg_qty="10")]
            )
        )
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code == 0, result.output
        posts = [url for method, url in fake.calls if method == "POST"]
        gets = [url for method, url in fake.calls if method == "GET"]
        # The only POST is the OAuth token issue (no order-cash write).
        assert all("/oauth2/tokenP" in url for url in posts)
        assert not any("order-cash" in url for _m, url in fake.calls)
        # The read path is inquire-balance only.
        assert all("inquire-balance" in url for url in gets)


# ---------------------------------------------------------------------------
# trading reconcile — mismatch (halt + alert + exit≠0)
# ---------------------------------------------------------------------------
class TestReconcileMismatch:
    def test_reconcile_mismatch_broker_only_halts(
        self, tmp_path, monkeypatch
    ) -> None:
        """DB 0 positions + broker holds 069500 qty 5 → halt + alert + exit≠0."""
        db = tmp_path / "trading.db"
        _seed_db(db, [])
        fake = _FakeHttp(
            balance_body=_balance_body(
                [_holding_row(pdno="069500", hldg_qty="5")]
            )
        )
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code != 0
        assert "불일치" in result.output
        # CRITICAL alert fired exactly once.
        assert len(notifier.calls) == 1
        level, _title, body = notifier.calls[0]
        assert level is NotificationLevel.CRITICAL
        assert "069500" in body
        # Persistent halt sentinel recorded.
        assert len(halt.reasons) == 1
        assert "069500" in halt.reasons[0]

    def test_reconcile_mismatch_quantity_diff_halts(
        self, tmp_path, monkeypatch
    ) -> None:
        """DB 069500 qty 10 + broker qty 7 → halt + alert + exit≠0."""
        db = tmp_path / "trading.db"
        _seed_db(db, [_position("069500", quantity="10")])
        fake = _FakeHttp(
            balance_body=_balance_body(
                [_holding_row(pdno="069500", hldg_qty="7")]
            )
        )
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code != 0
        assert len(notifier.calls) == 1
        assert notifier.calls[0][0] is NotificationLevel.CRITICAL
        assert len(halt.reasons) == 1

    def test_reconcile_mismatch_does_not_leak_secret(
        self, tmp_path, monkeypatch
    ) -> None:
        """appsecret / token must NEVER appear in stdout, even on mismatch."""
        db = tmp_path / "trading.db"
        _seed_db(db, [])
        fake = _FakeHttp(
            balance_body=_balance_body(
                [_holding_row(pdno="069500", hldg_qty="5")]
            )
        )
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code != 0
        assert _FAKE_APPSECRET not in result.output
        assert _FAKE_TOKEN not in result.output
        assert _FAKE_APPKEY not in result.output


# ---------------------------------------------------------------------------
# trading reconcile — error paths
# ---------------------------------------------------------------------------
class TestReconcileErrors:
    def test_reconcile_missing_env_reports_clear_message(
        self, tmp_path, monkeypatch
    ) -> None:
        db = tmp_path / "trading.db"
        _seed_db(db, [])
        incomplete = {"KIS_TRADING_MODE": "paper"}  # required keys missing
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(
            monkeypatch,
            _FakeHttp(),
            notifier=notifier,
            halt=halt,
            environ=incomplete,
        )
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code != 0
        assert ".env" in result.output
        assert "KIS_PAPER_APPKEY" in result.output

    def test_reconcile_balance_rt_cd_nonzero_reports_and_exits_nonzero(
        self, tmp_path, monkeypatch
    ) -> None:
        db = tmp_path / "trading.db"
        _seed_db(db, [])
        fake = _FakeHttp(balance_body=_error_envelope(rt_cd="1"))
        notifier = _RecordingNotifier()
        halt = _HaltSpy()
        _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
        runner = CliRunner()
        result = runner.invoke(main, ["reconcile", "--db", str(db)])
        assert result.exit_code != 0
        assert "holdings query failed" in result.output
        assert _FAKE_APPSECRET not in result.output
        # No auto-correction: a query failure must NOT halt nor alert.
        assert halt.reasons == []
        assert notifier.calls == []


# ---------------------------------------------------------------------------
# Top-level: reconcile registered + default --db is trading.db (not dry-run.db)
# ---------------------------------------------------------------------------
def test_reconcile_listed_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "reconcile" in result.output


def test_reconcile_db_default_is_trading_db_not_dry_run() -> None:
    """--db default must be the 실거래 상태 DB (trading.db), NOT dry-run.db.

    The help text MENTIONS dry-run.db only inside the warning ("dry-run.db 를
    가리키지 말 것"); the asserted invariant is that the click *default* shown by
    --help is ``trading.db`` (Click renders ``[default: trading.db]``).
    """
    runner = CliRunner()
    result = runner.invoke(main, ["reconcile", "--help"])
    assert result.exit_code == 0
    # Click renders "[default: trading.db]" (may line-wrap); normalise whitespace.
    normalised = " ".join(result.output.split())
    assert "[default: trading.db]" in normalised
    assert "[default: dry-run.db]" not in normalised


def test_reconcile_blocked_by_kill_switch_clean_exit(
    tmp_path, monkeypatch
) -> None:
    db = tmp_path / "trading.db"
    _seed_db(db, [])
    fake = _FakeHttp()
    notifier = _RecordingNotifier()
    halt = _HaltSpy()
    _patch_build(monkeypatch, fake, notifier=notifier, halt=halt)
    monkeypatch.setenv("TRADING_HALT", "1")
    runner = CliRunner()
    result = runner.invoke(main, ["reconcile", "--db", str(db)])
    # Kill switch → clean exit(0), zero KIS calls.
    assert result.exit_code == 0
    assert "reconciliation matched" not in result.output
    assert fake.calls == []
