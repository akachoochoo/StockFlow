"""CLI integration tests for ``trading kis-check`` (Phase 1.1 Stage 2.3).

Exercises the read-only KIS connectivity smoke command end-to-end through
Click's ``CliRunner`` with a **fake HttpClient** (returns canned KIS response
bodies) injected via ``composition.build_kis_read_components`` — **zero real
network**. Also covers the composition root directly (fake http + fixed clock
+ injected environ).

Real-money invariants verified here:
- read-only: KISBroker has NO ``place_order`` (structural — write surface
  absent until Stage 5).
- secret 미노출: appsecret / access_token never appear in stdout.

Function names carry ``kis_check`` (Stage gate selector).
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


def _paper_environ(
    *,
    appkey: str = _FAKE_APPKEY,
    appsecret: str = _FAKE_APPSECRET,
) -> dict[str, str]:
    """A complete paper-mode KIS env mapping (KISConfig.from_env happy path)."""
    return {
        "KIS_TRADING_MODE": "paper",
        "KIS_PAPER_APPKEY": appkey,
        "KIS_PAPER_APPSECRET": appsecret,
        "KIS_PAPER_ACCOUNT_CANO": "50012345",
        "KIS_PAPER_ACCOUNT_PRDT_CD": "01",
    }


# ---------------------------------------------------------------------------
# Canned KIS wire bodies (all numeric fields as strings — ADR 0020 §2.2)
# ---------------------------------------------------------------------------
def _token_body() -> dict[str, object]:
    return {
        "access_token": _FAKE_TOKEN,
        "access_token_token_expired": "2026-05-23 12:00:00",
        "token_type": "Bearer",
        "expires_in": "86400",
    }


def _balance_body(dnca_tot_amt: str = "5000000") -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": [
            {
                "pdno": "069500",
                "prdt_name": "KODEX 200",
                "hldg_qty": "10",
                "ord_psbl_qty": "10",
                "pchs_avg_pric": "35000",
                "prpr": "36000",
                "evlu_pfls_amt": "10000",
                "evlu_pfls_rt": "2.85",
                "pchs_amt": "350000",
                "evlu_amt": "360000",
            }
        ],
        "output2": [
            {
                "dnca_tot_amt": dnca_tot_amt,
                "tot_evlu_amt": "5360000",
                "nass_amt": "5360000",
                "scts_evlu_amt": "360000",
                "evlu_pfls_smtl_amt": "10000",
                "pchs_amt_smtl_amt": "350000",
                "thdt_tlex_amt": "0",
            }
        ],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


def _price_body(stck_prpr: str = "36000") -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output": {
            "stck_prpr": stck_prpr,
            "stck_oprc": "35500",
            "stck_hgpr": "36200",
            "stck_lwpr": "35400",
            "acml_vol": "1500000",
            "stck_sdpr": "35800",
            "prdy_vrss": "200",
            "prdy_ctrt": "0.56",
        },
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
    """HttpClient stand-in. Maps URL substrings → (status, body).

    ``token_status`` lets a test simulate an auth failure (non-2xx token POST);
    everything else returns the canned read body. Records every outbound call
    so a test can assert read-only (no order-cash POST ever issued).
    """

    def __init__(
        self,
        *,
        token_status: int = 200,
        balance_body: dict[str, object] | None = None,
        balance_status: int = 200,
        price_body: dict[str, object] | None = None,
        price_status: int = 200,
    ) -> None:
        self._token_status = token_status
        self._balance_body = balance_body if balance_body is not None else _balance_body()
        self._balance_status = balance_status
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
            if self._token_status != 200:
                return HttpResponse(
                    status_code=self._token_status,
                    body={"msg_cd": "EGW00133", "error_description": "auth failed"},
                )
            return HttpResponse(status_code=200, body=_token_body())
        # No other POST should occur in a read-only smoke test.
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
        if "inquire-price" in url:
            return HttpResponse(
                status_code=self._price_status, body=self._price_body
            )
        raise AssertionError(f"unexpected GET to {url}")


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 22, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path, monkeypatch):
    """Redirect the lock file into tmp so kis-check (lock-free) tests cannot
    collide with any real ~/.trading-system.lock — defensive even though
    kis-check itself acquires no lock.
    """
    monkeypatch.setattr(safety, "_DEFAULT_LOCK_PATH", tmp_path / "test.lock")


def _patch_build(monkeypatch, fake_http: _FakeHttp, environ: dict[str, str]) -> None:
    """Patch composition.build_kis_read_components to inject the fake http +
    fixed clock + the given environ (so the CLI command stays network-free).
    """
    real_build = composition.build_kis_read_components

    def _patched(*_args: object, **_kwargs: object) -> composition.KISReadComponents:
        return real_build(environ, http=fake_http, clock=_fixed_clock)

    monkeypatch.setattr(composition, "build_kis_read_components", _patched)


# ---------------------------------------------------------------------------
# build_kis_read_components — composition root (direct)
# ---------------------------------------------------------------------------
class TestBuildKisReadComponents:
    def test_kis_check_build_returns_broker_and_market_data(self) -> None:
        from src.adapters.kis.broker import KISBroker
        from src.adapters.kis.market_data import KISMarketData

        fake = _FakeHttp()
        components = composition.build_kis_read_components(
            _paper_environ(), http=fake, clock=_fixed_clock
        )
        assert isinstance(components.broker, KISBroker)
        assert isinstance(components.market_data, KISMarketData)

    def test_kis_check_build_get_balance_passes_through_fake(self) -> None:
        from decimal import Decimal

        fake = _FakeHttp(balance_body=_balance_body("7250000"))
        components = composition.build_kis_read_components(
            _paper_environ(), http=fake, clock=_fixed_clock
        )
        balance = components.broker.get_balance()
        assert balance.cash.amount == Decimal("7250000")

    def test_kis_check_build_config_exposes_paper_mode_and_masked_appkey(self) -> None:
        from src.adapters.kis.config import TradingMode

        fake = _FakeHttp()
        components = composition.build_kis_read_components(
            _paper_environ(), http=fake, clock=_fixed_clock
        )
        assert components.config.mode is TradingMode.PAPER
        # Masked appkey is the 4-char prefix + *** — never the full key.
        assert components.config.masked_appkey == "PKfa***"
        assert _FAKE_APPKEY not in components.config.masked_appkey

    def test_kis_check_build_missing_env_raises_configuration_error(self) -> None:
        from src.domain.exceptions import ConfigurationError

        incomplete = {"KIS_TRADING_MODE": "paper"}  # all keys missing
        with pytest.raises(ConfigurationError):
            composition.build_kis_read_components(incomplete, http=_FakeHttp())

    def test_kis_check_build_read_only_no_write_surface(self) -> None:
        """kis-check builds a read-only broker — orders structurally blocked.

        Option C transition (Stage 5): the write methods now EXIST on KISBroker
        but ``build_kis_read_components`` constructs it **without** an
        ``order_store``, so every write call raises ``RuntimeError`` — the
        kis-check / reconcile path cannot move money. The read-only guarantee is
        no longer "method absent" but "method present, structurally gated".
        """
        fake = _FakeHttp()
        components = composition.build_kis_read_components(
            _paper_environ(), http=fake, clock=_fixed_clock
        )
        # Methods exist (Stage 5 write surface)...
        assert hasattr(components.broker, "place_order")
        assert hasattr(components.broker, "cancel_order")
        assert hasattr(components.broker, "get_order_status")
        # ...but the read-only construction (no order_store) blocks every write.
        with pytest.raises(RuntimeError, match="requires order_store"):
            components.broker.get_order_status("any-key")
        with pytest.raises(RuntimeError, match="requires order_store"):
            components.broker.cancel_order("any-oid")


# ---------------------------------------------------------------------------
# trading kis-check — happy path
# ---------------------------------------------------------------------------
class TestKisCheckCommand:
    def test_kis_check_happy_path_prints_mode_host_balance_and_exits_zero(
        self, monkeypatch
    ) -> None:
        fake = _FakeHttp(balance_body=_balance_body("5000000"))
        _patch_build(monkeypatch, fake, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(main, ["kis-check"])
        assert result.exit_code == 0, result.output
        # mode + host (모의투자 VTS) printed so the operator can confirm.
        assert "mode=paper" in result.output
        assert "openapivts.koreainvestment.com" in result.output
        # 예수금 + 보유 + 현재가 all printed.
        assert "5000000" in result.output
        assert "보유 종목 수(holdings): 1" in result.output
        assert "36000" in result.output  # current price
        assert "✅ KIS read 연결 정상" in result.output

    def test_kis_check_custom_code_passed_to_get_price(self, monkeypatch) -> None:
        fake = _FakeHttp()
        _patch_build(monkeypatch, fake, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(main, ["kis-check", "--code", "005930"])
        assert result.exit_code == 0, result.output
        assert "현재가(005930)" in result.output

    def test_kis_check_does_not_leak_secret_in_output(self, monkeypatch) -> None:
        """appsecret / access_token must NEVER appear in stdout (CLAUDE.md §8.3)."""
        fake = _FakeHttp()
        _patch_build(monkeypatch, fake, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(main, ["kis-check"])
        assert result.exit_code == 0, result.output
        assert _FAKE_APPSECRET not in result.output
        assert _FAKE_TOKEN not in result.output
        # The full appkey is never printed either (only the masked prefix).
        assert _FAKE_APPKEY not in result.output

    def test_kis_check_is_read_only_no_order_post(self, monkeypatch) -> None:
        """Only the token POST + balance/price GETs occur — zero order POST."""
        fake = _FakeHttp()
        _patch_build(monkeypatch, fake, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(main, ["kis-check"])
        assert result.exit_code == 0, result.output
        posts = [url for method, url in fake.calls if method == "POST"]
        # The only POST is the OAuth token issue.
        assert all("/oauth2/tokenP" in url for url in posts)
        assert not any("order-cash" in url for url in posts)


# ---------------------------------------------------------------------------
# trading kis-check — error paths
# ---------------------------------------------------------------------------
class TestKisCheckErrors:
    def test_kis_check_missing_env_reports_clear_message(self, monkeypatch) -> None:
        # Inject an incomplete environ so KISConfig.from_env raises.
        incomplete = {"KIS_TRADING_MODE": "paper"}
        _patch_build(monkeypatch, _FakeHttp(), incomplete)
        runner = CliRunner()
        result = runner.invoke(main, ["kis-check"])
        assert result.exit_code != 0
        assert ".env" in result.output
        # No secret echoed (there is none, but assert the env-var name guidance).
        assert "KIS_PAPER_APPKEY" in result.output

    def test_kis_check_auth_failure_reports_and_hides_secret(
        self, monkeypatch
    ) -> None:
        fake = _FakeHttp(token_status=403)  # non-2xx token POST → KISAuthError
        _patch_build(monkeypatch, fake, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(main, ["kis-check"])
        assert result.exit_code != 0
        assert "auth failed" in result.output.lower()
        assert _FAKE_APPSECRET not in result.output
        assert _FAKE_TOKEN not in result.output

    def test_kis_check_balance_rt_cd_nonzero_reports_and_exits_nonzero(
        self, monkeypatch
    ) -> None:
        fake = _FakeHttp(balance_body=_error_envelope(rt_cd="1"))
        _patch_build(monkeypatch, fake, _paper_environ())
        runner = CliRunner()
        result = runner.invoke(main, ["kis-check"])
        assert result.exit_code != 0
        assert "balance/holdings query failed" in result.output
        assert _FAKE_APPSECRET not in result.output


# ---------------------------------------------------------------------------
# Top-level: kis-check registered + halt-blocked
# ---------------------------------------------------------------------------
def test_kis_check_listed_in_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "kis-check" in result.output


def test_kis_check_blocked_by_kill_switch_clean_exit(monkeypatch) -> None:
    fake = _FakeHttp()
    _patch_build(monkeypatch, fake, _paper_environ())
    monkeypatch.setenv("TRADING_HALT", "1")
    runner = CliRunner()
    result = runner.invoke(main, ["kis-check"])
    # Kill switch → clean exit(0), no KIS calls.
    assert result.exit_code == 0
    assert "KIS read 연결 정상" not in result.output
    assert fake.calls == []
