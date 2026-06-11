"""CLI integration tests for ``trading live`` (Phase 1.1 Stage 8-5).

Focus: the **실주문 zero** safety invariant + the arming/halt/NTP gates, driven
through Click's ``CliRunner`` with a fake HttpClient (zero real network). The
armed decision-phase logic (settle→decide order, stop-loss, G2(d)) is covered
by ``tests/unit/cli/test_live_runner.py``; here we prove the *command* refuses
to place any order unless armed and that the safety wrappers fire.

Real-money invariant verified: an unarmed ``trading live`` does settle +
reconcile then refuses — **no order-cash POST ever reaches the fake http**.
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

_FAKE_APPKEY = "PKfakeappkey0123456789"
_FAKE_APPSECRET = "FAKE_APPSECRET_must_never_be_printed=="
_FAKE_TOKEN = "FAKE_ACCESS_TOKEN_must_never_be_printed"


def _paper_environ() -> dict[str, str]:
    return {
        "KIS_TRADING_MODE": "paper",
        "KIS_PAPER_APPKEY": _FAKE_APPKEY,
        "KIS_PAPER_APPSECRET": _FAKE_APPSECRET,
        "KIS_PAPER_ACCOUNT_CANO": "50012345",
        "KIS_PAPER_ACCOUNT_PRDT_CD": "01",
    }


def _token_body() -> dict[str, object]:
    return {
        "access_token": _FAKE_TOKEN,
        "access_token_token_expired": "2026-05-23 12:00:00",
        "token_type": "Bearer",
        "expires_in": "86400",
    }


def _balance_body() -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": [],  # no holdings → recon matches an empty DB
        "output2": [
            {
                "dnca_tot_amt": "2000000",
                "tot_evlu_amt": "2000000",
                "nass_amt": "2000000",
                "scts_evlu_amt": "0",
                "evlu_pfls_smtl_amt": "0",
                "pchs_amt_smtl_amt": "0",
                "thdt_tlex_amt": "0",
            }
        ],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


class _FakeHttp:
    """token POST + inquire-balance GET only. Any order-cash POST is a leak."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

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
        # order-cash (or anything else) must NEVER be POSTed while unarmed.
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
            return HttpResponse(status_code=200, body=_balance_body())
        raise AssertionError(f"unexpected GET to {url}")


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 22, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated_safety(tmp_path, monkeypatch):
    """Redirect lock/halt sentinels to tmp + stub the NTP gate (no real shell)."""
    monkeypatch.setattr(safety, "_DEFAULT_LOCK_PATH", tmp_path / "test.lock")
    monkeypatch.setattr(safety, "_HALT_PATH", tmp_path / "test.halt")
    monkeypatch.setattr(safety, "verify_ntp_sync", lambda **_kw: None)


def _patch_build(monkeypatch, fake: _FakeHttp) -> None:
    monkeypatch.setenv("ALLOW_DAILY_LIVE", "1")  # pass daily-infra gate (ADR 0023 R6)
    real_build = composition.build_live_components

    def _patched(**kwargs: object):
        return real_build(
            environ=_paper_environ(),
            http=fake,
            clock=_fixed_clock,
            **kwargs,
        )

    monkeypatch.setattr(composition, "build_live_components", _patched)


# ---------------------------------------------------------------------------
# Unarmed → settle + reconcile, then refuse. 실주문 zero.
# ---------------------------------------------------------------------------
def test_live_unarmed_refuses_and_places_no_orders(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TRADING_ARM_LIVE", raising=False)
    fake = _FakeHttp()
    _patch_build(monkeypatch, fake)
    db = tmp_path / "trading.db"
    result = CliRunner().invoke(
        main, ["live", "--tier", "200", "--db", str(db), "--date", "2026-05-22"]
    )
    assert result.exit_code == 1, result.output
    assert "무장 안됨" in result.output
    # The ONLY POST is the OAuth token issue — no order-cash write ever.
    assert not any("order-cash" in url for _m, url in fake.calls)
    assert all(
        ("/oauth2/tokenP" in url) for m, url in fake.calls if m == "POST"
    )


def test_live_arm_flag_without_env_is_not_armed(tmp_path, monkeypatch) -> None:
    # --arm-live alone (no TRADING_ARM_LIVE env) must NOT arm (double-confirm).
    monkeypatch.delenv("TRADING_ARM_LIVE", raising=False)
    fake = _FakeHttp()
    _patch_build(monkeypatch, fake)
    db = tmp_path / "trading.db"
    result = CliRunner().invoke(
        main,
        ["live", "--tier", "200", "--arm-live", "200", "--db", str(db),
         "--date", "2026-05-22"],
    )
    assert result.exit_code == 1, result.output
    assert "무장 안됨" in result.output
    assert not any("order-cash" in url for _m, url in fake.calls)


def test_live_banner_shows_mode_and_not_armed(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TRADING_ARM_LIVE", raising=False)
    fake = _FakeHttp()
    _patch_build(monkeypatch, fake)
    db = tmp_path / "trading.db"
    result = CliRunner().invoke(
        main, ["live", "--tier", "200", "--db", str(db), "--date", "2026-05-22"]
    )
    assert "mode=paper" in result.output
    assert "armed=NO" in result.output
    # Secrets never printed.
    assert _FAKE_APPSECRET not in result.output
    assert _FAKE_TOKEN not in result.output


# ---------------------------------------------------------------------------
# Safety wrappers
# ---------------------------------------------------------------------------
def test_live_blocked_by_kill_switch_clean_exit(tmp_path, monkeypatch) -> None:
    fake = _FakeHttp()
    _patch_build(monkeypatch, fake)
    monkeypatch.setenv("TRADING_HALT", "1")
    db = tmp_path / "trading.db"
    result = CliRunner().invoke(main, ["live", "--tier", "200", "--db", str(db)])
    # Kill switch → clean exit(0), zero KIS calls.
    assert result.exit_code == 0
    assert fake.calls == []


def test_live_blocked_by_halt_sentinel(tmp_path, monkeypatch) -> None:
    fake = _FakeHttp()
    _patch_build(monkeypatch, fake)
    safety.write_halt("manual halt for test")
    db = tmp_path / "trading.db"
    result = CliRunner().invoke(main, ["live", "--tier", "200", "--db", str(db)])
    # Persistent halt → non-zero exit, zero KIS calls (blocked at the group).
    assert result.exit_code != 0
    assert fake.calls == []


def test_live_listed_in_help() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "live" in result.output


def test_live_requires_tier() -> None:
    # --tier is required (the intended capital tier must be explicit).
    result = CliRunner().invoke(main, ["live", "--db", "x.db"])
    assert result.exit_code != 0
    assert "tier" in result.output.lower()


def test_live_supervised_flag_registered() -> None:
    result = CliRunner().invoke(main, ["live", "--help"])
    assert result.exit_code == 0
    assert "--supervised-first-order" in result.output


def test_live_armed_over_exposure_refused_before_kis(tmp_path, monkeypatch) -> None:
    # Armed + default per_split (1,000,000 x 7 x 2 assets = 14M) > tier 200 (2M)
    # → capital cap refuses BEFORE any KIS call (D3 자본 과노출 방지).
    monkeypatch.setenv("TRADING_ARM_LIVE", "TIER_200")
    fake = _FakeHttp()
    _patch_build(monkeypatch, fake)
    db = tmp_path / "trading.db"
    result = CliRunner().invoke(
        main,
        ["live", "--tier", "200", "--arm-live", "200", "--db", str(db),
         "--date", "2026-05-22"],
    )
    assert result.exit_code == 1, result.output
    assert "자본 과노출" in result.output
    assert fake.calls == []  # refused before settle/recon → zero KIS calls
