"""Unit tests for src.adapters.kis.auth (Phase 1.1 Stage 2.2).

Uses a fake ``HttpClient`` (records calls, returns canned responses) — **zero
real network**. ``clock`` is an injected mutable fixture so TTL transitions are
deterministic. Verifies: issue+cache, TTL reuse, TTL re-issue, non-2xx →
KISAuthError (no retry), missing access_token → KISAuthError, network exception
→ BrokerConnectionError wrap, and (R10) that no secret appears in any error.

Function names carry ``kis_auth_`` (Stage gate selector).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from src.adapters.kis._http import HttpResponse
from src.adapters.kis.auth import KISAuth, KISAuthError
from src.adapters.kis.config import KISConfig, TradingMode
from src.domain.exceptions import BrokerConnectionError

if TYPE_CHECKING:
    from collections.abc import Mapping

_SECRET_APPKEY = "PKabcdefghijklmnop1234567890"
_SECRET_APPSECRET = "SECRETsupersecretappsecretvalue=="
_SECRET_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.SECRETTOKEN.sig"

_T0 = datetime(2026, 5, 22, 0, 0, 0, tzinfo=UTC)


def _config() -> KISConfig:
    return KISConfig(
        mode=TradingMode.PAPER,
        base_url="https://openapivts.koreainvestment.com:29443",
        appkey=_SECRET_APPKEY,
        appsecret=_SECRET_APPSECRET,
        cano="50012345",
        acnt_prdt_cd="01",
    )


def _token_body() -> dict[str, object]:
    return {
        "access_token": _SECRET_ACCESS_TOKEN,
        "access_token_token_expired": "2026-05-23 09:00:00",
        "token_type": "Bearer",
        "expires_in": "86400",
    }


class _MutableClock:
    """Injected UTC clock; advance via ``+=``."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class _FakeHttp:
    """Records POST/GET calls; returns queued responses or raises queued exc."""

    def __init__(
        self,
        responses: list[HttpResponse] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise_exc = raise_exc
        self.post_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float = 10.0,
    ) -> HttpResponse:
        self.post_calls.append(
            {"url": url, "json": dict(json), "headers": dict(headers), "timeout": timeout}
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._responses.pop(0)

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float = 10.0,
    ) -> HttpResponse:
        self.get_calls.append(
            {"url": url, "params": dict(params), "headers": dict(headers)}
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._responses.pop(0)


def _ok_token_response() -> HttpResponse:
    return HttpResponse(status_code=200, body=_token_body())


class TestKisAuthIssueAndCache:
    def test_kis_auth_first_get_token_issues_via_http(self) -> None:
        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        token = auth.get_token()
        assert token == _SECRET_ACCESS_TOKEN
        assert len(http.post_calls) == 1
        call = http.post_calls[0]
        assert call["url"].endswith("/oauth2/tokenP")
        assert call["json"]["grant_type"] == "client_credentials"

    def test_kis_auth_cached_token_reused_within_ttl(self) -> None:
        http = _FakeHttp([_ok_token_response()])
        clock = _MutableClock(_T0)
        auth = KISAuth(config=_config(), http=http, clock=clock)
        first = auth.get_token()
        # Advance 22h — still inside the 23h TTL.
        clock.advance(timedelta(hours=22))
        second = auth.get_token()
        assert first == second
        assert len(http.post_calls) == 1  # no second HTTP call

    def test_kis_auth_reissues_after_ttl_expiry(self) -> None:
        http = _FakeHttp([_ok_token_response(), _ok_token_response()])
        clock = _MutableClock(_T0)
        auth = KISAuth(config=_config(), http=http, clock=clock)
        auth.get_token()
        # Advance 23h — at/over TTL → re-issue.
        clock.advance(timedelta(hours=23))
        auth.get_token()
        assert len(http.post_calls) == 2


class TestKisAuthErrors:
    def test_kis_auth_non_2xx_raises_auth_error_without_retry(self) -> None:
        http = _FakeHttp(
            [HttpResponse(status_code=403, body={"rt_cd": "1", "msg_cd": "EGW00133"})]
        )
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        with pytest.raises(KISAuthError):
            auth.get_token()
        # No automatic retry — exactly one HTTP call (ADR 0012 §1.6 #1).
        assert len(http.post_calls) == 1

    def test_kis_auth_403_surfaces_oauth_error_description(self) -> None:
        # The OAuth2 token endpoint returns error_code/error_description (not the
        # KIS envelope msg_cd). The message must surface it so a 403 is diagnosable.
        http = _FakeHttp(
            [
                HttpResponse(
                    status_code=403,
                    body={
                        "error_code": "EGW00133",
                        "error_description": "등록되지 않은 IP 입니다.",
                    },
                )
            ]
        )
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        with pytest.raises(KISAuthError) as exc_info:
            auth.get_token()
        assert "등록되지 않은 IP" in str(exc_info.value)

    def test_kis_auth_missing_access_token_raises_auth_error(self) -> None:
        http = _FakeHttp(
            [
                HttpResponse(
                    status_code=200,
                    body={"token_type": "Bearer", "access_token_token_expired": "x"},
                )
            ]
        )
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        with pytest.raises(KISAuthError):
            auth.get_token()

    def test_kis_auth_network_exception_wrapped_as_broker_connection_error(
        self,
    ) -> None:
        http = _FakeHttp(raise_exc=BrokerConnectionError("connection refused"))
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        with pytest.raises(BrokerConnectionError):
            auth.get_token()


class TestKisAuthSecretSafety:
    """R10 — appsecret / access_token never appear in error text."""

    def test_kis_auth_error_message_excludes_secrets_on_non_2xx(self) -> None:
        http = _FakeHttp(
            [HttpResponse(status_code=403, body={"rt_cd": "1", "msg_cd": "EGW00133"})]
        )
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        with pytest.raises(KISAuthError) as exc_info:
            auth.get_token()
        text = str(exc_info.value)
        assert _SECRET_APPSECRET not in text
        assert _SECRET_ACCESS_TOKEN not in text

    def test_kis_auth_error_redacts_appkey_if_echoed_in_body(self) -> None:
        # R10 defense: even if KIS echoed the appkey into an error_description,
        # the raised message must mask it.
        http = _FakeHttp(
            [
                HttpResponse(
                    status_code=403,
                    body={"error_description": f"invalid appkey {_SECRET_APPKEY}"},
                )
            ]
        )
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        with pytest.raises(KISAuthError) as exc_info:
            auth.get_token()
        text = str(exc_info.value)
        assert _SECRET_APPKEY not in text
        assert "***" in text

    def test_kis_auth_validation_error_excludes_token_body(self) -> None:
        # A 200 body that carries a token but fails validation must not echo it.
        http = _FakeHttp(
            [
                HttpResponse(
                    status_code=200,
                    body={
                        "access_token": _SECRET_ACCESS_TOKEN,
                        # missing required access_token_token_expired + token_type
                    },
                )
            ]
        )
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        with pytest.raises(KISAuthError) as exc_info:
            auth.get_token()
        assert _SECRET_ACCESS_TOKEN not in str(exc_info.value)
