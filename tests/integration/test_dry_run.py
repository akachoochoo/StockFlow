"""CLI integration tests for ``trading dry-run`` (Phase 1.1 — paper-on-live).

Exercises the dry-run command end-to-end through Click's ``CliRunner`` with a
**fake KIS HttpClient** (returns canned market-data response bodies) injected
via ``composition.build_kis_market_data`` — **zero real network**. The broker is
a MockBroker (simulated fills against a local SQLite balance), so the live KIS
server is read ONLY for quotes; no real order, no real account access.

Real-money invariants verified here:
- **실주문 zero**: no ``order-cash`` POST is ever issued (fake http records all
  calls; the only POST is the OAuth token issue).
- **실계좌 미사용**: no ``inquire-balance`` GET (balance / holdings) is ever
  issued — only the quote endpoints (inquire-price / daily-itemchartprice).
- **다일 상태 누적**: a day-1 buy is reflected as a day-2 holding (MockBroker +
  SQLite state persists across runs).
- **회귀 zero**: ``build_paper_components(market_data=None)`` still builds a
  MockMarketData over ``bars_by_asset`` (default path unchanged).

Function names carry ``dry_run`` (Stage gate selector).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from src.adapters.kis._http import HttpResponse
from src.cli import composition, safety
from src.cli.main import main

if TYPE_CHECKING:
    from collections.abc import Mapping


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
# Canned KIS wire bodies (all numeric fields as strings — ADR 0020 §2.2)
# ---------------------------------------------------------------------------
def _token_body() -> dict[str, object]:
    return {
        "access_token": _FAKE_TOKEN,
        "access_token_token_expired": "2026-12-31 12:00:00",
        "token_type": "Bearer",
        "expires_in": "86400",
    }


def _price_body(
    *, stck_prpr: str = "30000", stck_sdpr: str = "35000"
) -> dict[str, object]:
    """Current-price body. Default = a -14.3% drop vs prev close (triggers a
    PriceDropStrategy first buy at the 7% threshold)."""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output": {
            "stck_prpr": stck_prpr,
            "stck_oprc": "30500",
            "stck_hgpr": "31000",
            "stck_lwpr": "29800",
            "acml_vol": "1500000",
            "stck_sdpr": stck_sdpr,
            "prdy_vrss": "-5000",
            "prdy_ctrt": "-14.28",
        },
    }


def _daily_body() -> dict[str, object]:
    """A small daily OHLCV page (used if reentry get_ohlcv is reached)."""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": {},
        "output2": [
            {
                "stck_bsop_date": "20260520",
                "stck_oprc": "35000",
                "stck_hgpr": "35500",
                "stck_lwpr": "34800",
                "stck_clpr": "35000",
                "acml_vol": "1000000",
            },
            {
                "stck_bsop_date": "20260519",
                "stck_oprc": "34800",
                "stck_hgpr": "35200",
                "stck_lwpr": "34500",
                "stck_clpr": "34900",
                "acml_vol": "900000",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Fake KIS HttpClient — routes by URL, records every call (zero network)
# ---------------------------------------------------------------------------
class _FakeHttp:
    """KIS ``HttpClient`` stand-in for market-data dry runs.

    Routes the token POST + quote GETs (inquire-price / daily-itemchartprice).
    Any other POST (e.g. order-cash) or the balance GET (inquire-balance) is an
    AssertionError — proving the dry run is read-only quotes + zero real
    account access. Records every outbound call for assertions.
    """

    def __init__(
        self,
        *,
        price_body: dict[str, object] | None = None,
        price_status: int = 200,
    ) -> None:
        self._price_body = price_body if price_body is not None else _price_body()
        self._price_status = price_status
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
            return HttpResponse(status_code=200, body=_token_body())
        # Any other POST (order-cash, etc.) must never occur in a dry run.
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
            # Real-account access — must never happen in a dry run.
            raise AssertionError(f"unexpected balance GET to {url}")
        if "inquire-price" in url:
            return HttpResponse(
                status_code=self._price_status, body=self._price_body
            )
        if "inquire-daily-itemchartprice" in url:
            return HttpResponse(status_code=200, body=_daily_body())
        raise AssertionError(f"unexpected GET to {url}")


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 22, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path, monkeypatch):
    """Redirect the lock file into tmp so dry-run tests cannot collide with a
    real ~/.trading-system.lock."""
    monkeypatch.setattr(safety, "_DEFAULT_LOCK_PATH", tmp_path / "test.lock")


def _patch_market_data(
    monkeypatch, fake_http: _FakeHttp, environ: dict[str, str]
) -> None:
    """Patch composition.build_kis_market_data to inject the fake http + fixed
    clock + the given environ (so the CLI command stays network-free)."""
    real_build = composition.build_kis_market_data

    def _patched(*_args: object, **_kwargs: object):
        return real_build(environ, http=fake_http, clock=_fixed_clock)

    monkeypatch.setattr(composition, "build_kis_market_data", _patched)


def _patch_config_env(monkeypatch, environ: dict[str, str]) -> None:
    """Patch KISConfig.from_env (called for the banner) to use the test env so
    no real OS env / .env is read."""
    from src.adapters.kis.config import KISConfig

    real_from_env = KISConfig.from_env.__func__  # type: ignore[attr-defined]

    def _patched(cls, _environ=None):
        return real_from_env(cls, environ)

    monkeypatch.setattr(KISConfig, "from_env", classmethod(_patched))


# ---------------------------------------------------------------------------
# trading dry-run — happy path (live quotes + simulated fill)
# ---------------------------------------------------------------------------
class TestDryRunCommand:
    def test_dry_run_live_quote_yields_decision_and_exits_zero(
        self, monkeypatch, tmp_path
    ) -> None:
        fake = _FakeHttp()
        _patch_market_data(monkeypatch, fake, _paper_environ())
        _patch_config_env(monkeypatch, _paper_environ())
        db = tmp_path / "dry.db"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "dry-run",
                "--code",
                "069500",
                "--db",
                str(db),
                "--date",
                "2026-05-22",
            ],
        )
        assert result.exit_code == 0, result.output
        # Banner + live-data source printed.
        assert "DRY-RUN — 실주문 없음, 실계좌 미사용" in result.output
        assert "paper-on-live" in result.output
        assert "openapivts.koreainvestment.com" in result.output
        # A decision was rendered (intended buy on the -14% drop) + sim balance.
        assert "069500" in result.output
        assert "intended" in result.output
        assert "Cash (simulated)" in result.output
        # A live current-price GET was issued.
        gets = [url for method, url in fake.calls if method == "GET"]
        assert any("inquire-price" in url for url in gets)

    def test_dry_run_no_real_order_post(self, monkeypatch, tmp_path) -> None:
        """실주문 zero: the only POST is the OAuth token issue — no order-cash."""
        fake = _FakeHttp()
        _patch_market_data(monkeypatch, fake, _paper_environ())
        _patch_config_env(monkeypatch, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dry-run", "--code", "069500", "--db", str(tmp_path / "d.db")],
        )
        assert result.exit_code == 0, result.output
        posts = [url for method, url in fake.calls if method == "POST"]
        assert all("/oauth2/tokenP" in url for url in posts)
        assert not any("order-cash" in url for url in posts)
        assert not any("order" in url for url in posts if "tokenP" not in url)

    def test_dry_run_no_real_account_access(
        self, monkeypatch, tmp_path
    ) -> None:
        """실계좌 미사용: no inquire-balance (balance / holdings) GET is issued —
        only the quote endpoints. (_FakeHttp asserts internally; here we also
        confirm explicitly from the recorded call list.)"""
        fake = _FakeHttp()
        _patch_market_data(monkeypatch, fake, _paper_environ())
        _patch_config_env(monkeypatch, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dry-run", "--code", "069500", "--db", str(tmp_path / "d.db")],
        )
        assert result.exit_code == 0, result.output
        gets = [url for method, url in fake.calls if method == "GET"]
        assert not any("inquire-balance" in url for url in gets)
        assert all(
            ("inquire-price" in url)
            or ("inquire-daily-itemchartprice" in url)
            for url in gets
        )

    def test_dry_run_does_not_leak_secret(self, monkeypatch, tmp_path) -> None:
        """appsecret / access_token must NEVER appear in stdout (CLAUDE.md §8.3)."""
        fake = _FakeHttp()
        _patch_market_data(monkeypatch, fake, _paper_environ())
        _patch_config_env(monkeypatch, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dry-run", "--code", "069500", "--db", str(tmp_path / "d.db")],
        )
        assert result.exit_code == 0, result.output
        assert _FAKE_APPSECRET not in result.output
        assert _FAKE_TOKEN not in result.output
        assert _FAKE_APPKEY not in result.output

    def test_dry_run_multi_day_state_accumulates(
        self, monkeypatch, tmp_path
    ) -> None:
        """Day-1 buy → day-2 holding (MockBroker + SQLite state persists)."""
        db = tmp_path / "multiday.db"
        runner = CliRunner()

        # Day 1: a -14% drop triggers a first buy → a position is opened.
        fake1 = _FakeHttp(price_body=_price_body(stck_prpr="30000"))
        _patch_market_data(monkeypatch, fake1, _paper_environ())
        _patch_config_env(monkeypatch, _paper_environ())
        r1 = runner.invoke(
            main,
            [
                "dry-run",
                "--code",
                "069500",
                "--db",
                str(db),
                "--date",
                "2026-05-22",
            ],
        )
        assert r1.exit_code == 0, r1.output

        # Day 2: a small further move; the day-1 holding must show up as a
        # simulated position carried over from the persisted SQLite state.
        fake2 = _FakeHttp(price_body=_price_body(stck_prpr="30500"))
        _patch_market_data(monkeypatch, fake2, _paper_environ())
        _patch_config_env(monkeypatch, _paper_environ())
        r2 = runner.invoke(
            main,
            [
                "dry-run",
                "--code",
                "069500",
                "--db",
                str(db),
                "--date",
                "2026-05-26",
            ],
        )
        assert r2.exit_code == 0, r2.output
        assert "Positions (simulated):" in r2.output
        assert "069500" in r2.output

    def test_dry_run_missing_env_reports_clear_message(
        self, monkeypatch, tmp_path
    ) -> None:
        """.env not configured → ConfigurationError, clear message, exit != 0."""
        incomplete = {"KIS_TRADING_MODE": "paper"}  # required keys missing
        _patch_market_data(monkeypatch, _FakeHttp(), incomplete)
        _patch_config_env(monkeypatch, incomplete)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["dry-run", "--code", "069500", "--db", str(tmp_path / "d.db")],
        )
        assert result.exit_code != 0
        assert ".env" in result.output


# ---------------------------------------------------------------------------
# build_paper_components — market_data injection (composition root, direct)
# ---------------------------------------------------------------------------
class TestBuildPaperComponentsMarketDataInjection:
    def test_dry_run_market_data_none_uses_mock_market_data(
        self, tmp_path
    ) -> None:
        """Default (market_data=None) builds a MockMarketData over bars — the
        existing paper path is unchanged (회귀 zero)."""
        from datetime import date
        from decimal import Decimal

        from src.adapters.mock.market_data import MockMarketData
        from src.domain.models import OHLCV, Currency, Money
        from src.domain.strategies.price_drop import SplitStrategyConfig

        asset = composition.asset_from_code("069500")
        bars = [
            OHLCV(
                asset=asset,
                trade_date=date(2026, 5, 22),
                open=Decimal("35000"),
                high=Decimal("35500"),
                low=Decimal("34800"),
                close=Decimal("35000"),
                volume=Decimal("1000000"),
            )
        ]
        components = composition.build_paper_components(
            assets=[asset],
            bars_by_asset={asset: bars},
            db_path=tmp_path / "paper.db",
            initial_capital=Money(
                amount=Decimal("10000000"), currency=Currency.KRW
            ),
            strategy_config=SplitStrategyConfig(
                drop_threshold_pct=Decimal("7.0"),
                max_split_count=7,
                per_split_amount=Money(
                    amount=Decimal("1000000"), currency=Currency.KRW
                ),
                max_split_per_day=1,
            ),
            initial_clock=composition.utc_for(
                date(2026, 5, 22), __import__("datetime").time(9, 0)
            ),
        )
        try:
            md = components.orchestrator._market_data
            assert isinstance(md, MockMarketData)
        finally:
            components.close()

    def test_dry_run_market_data_injected_is_used_verbatim(
        self, tmp_path
    ) -> None:
        """Injected market_data is wired into the orchestrator + snapshot builder
        verbatim; bars_by_asset is ignored (empty dict accepted)."""
        from datetime import date
        from decimal import Decimal

        from src.domain.models import Currency, Money
        from src.domain.strategies.price_drop import SplitStrategyConfig

        fake = _FakeHttp()
        injected = composition.build_kis_market_data(
            _paper_environ(), http=fake, clock=_fixed_clock
        )
        asset = composition.asset_from_code("069500")
        components = composition.build_paper_components(
            assets=[asset],
            bars_by_asset={},
            db_path=tmp_path / "inj.db",
            initial_capital=Money(
                amount=Decimal("10000000"), currency=Currency.KRW
            ),
            strategy_config=SplitStrategyConfig(
                drop_threshold_pct=Decimal("7.0"),
                max_split_count=7,
                per_split_amount=Money(
                    amount=Decimal("1000000"), currency=Currency.KRW
                ),
                max_split_per_day=1,
            ),
            initial_clock=composition.utc_for(
                date(2026, 5, 22), __import__("datetime").time(9, 0)
            ),
            market_data=injected,
        )
        try:
            assert components.orchestrator._market_data is injected
            assert (
                components.snapshot_builder._market_data is injected
            )
        finally:
            components.close()


# ---------------------------------------------------------------------------
# Top-level: dry-run registered + halt-blocked
# ---------------------------------------------------------------------------
def test_dry_run_listed_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "dry-run" in result.output


def test_dry_run_blocked_by_kill_switch_clean_exit(
    monkeypatch, tmp_path
) -> None:
    fake = _FakeHttp()
    _patch_market_data(monkeypatch, fake, _paper_environ())
    _patch_config_env(monkeypatch, _paper_environ())
    monkeypatch.setenv("TRADING_HALT", "1")
    runner = CliRunner()
    result = runner.invoke(
        main, ["dry-run", "--code", "069500", "--db", str(tmp_path / "d.db")]
    )
    # Kill switch → clean exit(0), no KIS calls.
    assert result.exit_code == 0
    assert "DRY-RUN" not in result.output
    assert fake.calls == []
