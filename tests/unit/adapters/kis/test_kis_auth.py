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


# ============================================================================
# ADR 0012 R10 amendment (2026-06-11) — disk cache 보호장치 4건
# ============================================================================
import json
import stat


class TestKisAuthDiskCache:
    """Disk cache opt-in (token_cache_path 인자). ADR 0012 R10 amendment 박제.

    회귀 보호: cache path None 시 disk 동작 zero / in-memory 만.
    """

    @staticmethod
    def _cache_path(tmp_path) -> object:  # noqa: ANN001  -- pytest fixture
        return tmp_path / ".kis-token-cache.json"

    def test_kis_cache_default_none_in_memory_only(self, tmp_path) -> None:  # noqa: ANN001
        """token_cache_path 미지정 → 디스크 미사용 + 회귀 보장."""
        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(config=_config(), http=http, clock=_MutableClock(_T0))
        auth.get_token()
        # cwd / tmp 어디에도 disk cache zero.
        assert not (tmp_path / ".kis-token-cache.json").exists()

    def test_kis_cache_save_on_issue_with_chmod_0600(self, tmp_path) -> None:  # noqa: ANN001
        cache = self._cache_path(tmp_path)
        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(
            config=_config(),
            http=http,
            clock=_MutableClock(_T0),
            token_cache_path=cache,
        )
        auth.get_token()
        assert cache.exists()
        mode = stat.S_IMODE(cache.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {mode:o}"
        # 파일 내용 schema 검증.
        payload = json.loads(cache.read_text(encoding="utf-8"))
        assert "access_token" in payload
        assert "issued_at" in payload

    def test_kis_cache_hit_zero_http(self, tmp_path) -> None:  # noqa: ANN001
        """기존 cache 파일 → HTTP 호출 zero."""
        cache = self._cache_path(tmp_path)
        # First call: 발급 + write
        http1 = _FakeHttp([_ok_token_response()])
        auth1 = KISAuth(
            config=_config(),
            http=http1,
            clock=_MutableClock(_T0),
            token_cache_path=cache,
        )
        auth1.get_token()
        assert len(http1.post_calls) == 1

        # Second instance (process restart 시뮬) — 새 KISAuth, 같은 cache path.
        http2 = _FakeHttp([])  # 응답 zero — HTTP 호출되면 IndexError
        auth2 = KISAuth(
            config=_config(),
            http=http2,
            clock=_MutableClock(_T0 + timedelta(minutes=5)),
            token_cache_path=cache,
        )
        token = auth2.get_token()
        assert token == _SECRET_ACCESS_TOKEN
        assert len(http2.post_calls) == 0

    def test_kis_cache_perm_enforced(self, tmp_path) -> None:  # noqa: ANN001
        """0600 외 권한 → invalidate + 새 발급."""
        cache = self._cache_path(tmp_path)
        # 권한 0644 로 cache 위조.
        payload = {
            "access_token": "stolen",
            "issued_at": _T0.isoformat(),
            "wire_expired": None,
        }
        cache.write_text(json.dumps(payload), encoding="utf-8")
        import os as _os
        _os.chmod(cache, 0o644)

        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(
            config=_config(),
            http=http,
            clock=_MutableClock(_T0 + timedelta(minutes=5)),
            token_cache_path=cache,
        )
        token = auth.get_token()
        # stolen 토큰 거부 → 새 발급.
        assert token == _SECRET_ACCESS_TOKEN
        # 파일 invalidate (unlink) 됐을 것 → 새 발급 시 재생성 + 0600.
        assert cache.exists()
        assert stat.S_IMODE(cache.stat().st_mode) == 0o600

    def test_kis_cache_ttl_expired_invalidates(self, tmp_path) -> None:  # noqa: ANN001
        """TTL 만료된 cache → invalidate + 새 발급."""
        cache = self._cache_path(tmp_path)
        # cache 직접 작성 — TTL 초과 시점.
        payload = {
            "access_token": "expired_token",
            "issued_at": _T0.isoformat(),
            "wire_expired": None,
        }
        cache.write_text(json.dumps(payload), encoding="utf-8")
        import os as _os
        _os.chmod(cache, 0o600)

        # Clock = _T0 + 23h+5min (TTL 초과)
        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(
            config=_config(),
            http=http,
            clock=_MutableClock(_T0 + timedelta(hours=23, minutes=5)),
            token_cache_path=cache,
        )
        token = auth.get_token()
        assert token == _SECRET_ACCESS_TOKEN
        assert len(http.post_calls) == 1

    def test_kis_cache_corrupt_json_invalidates(self, tmp_path) -> None:  # noqa: ANN001
        """JSON 깨진 cache → invalidate + 새 발급."""
        cache = self._cache_path(tmp_path)
        cache.write_text("{not valid json", encoding="utf-8")
        import os as _os
        _os.chmod(cache, 0o600)

        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(
            config=_config(),
            http=http,
            clock=_MutableClock(_T0),
            token_cache_path=cache,
        )
        token = auth.get_token()
        assert token == _SECRET_ACCESS_TOKEN

    def test_kis_cache_missing_field_invalidates(self, tmp_path) -> None:  # noqa: ANN001
        """필수 필드 누락 → invalidate + 새 발급."""
        cache = self._cache_path(tmp_path)
        cache.write_text(json.dumps({"only": "this"}), encoding="utf-8")
        import os as _os
        _os.chmod(cache, 0o600)

        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(
            config=_config(),
            http=http,
            clock=_MutableClock(_T0),
            token_cache_path=cache,
        )
        token = auth.get_token()
        assert token == _SECRET_ACCESS_TOKEN

    def test_kis_cache_naive_datetime_invalidates(self, tmp_path) -> None:  # noqa: ANN001
        """timezone-aware 아닌 issued_at → invalidate."""
        cache = self._cache_path(tmp_path)
        payload = {
            "access_token": "tok",
            "issued_at": "2026-05-22T00:00:00",  # naive
            "wire_expired": None,
        }
        cache.write_text(json.dumps(payload), encoding="utf-8")
        import os as _os
        _os.chmod(cache, 0o600)

        http = _FakeHttp([_ok_token_response()])
        auth = KISAuth(
            config=_config(),
            http=http,
            clock=_MutableClock(_T0),
            token_cache_path=cache,
        )
        token = auth.get_token()
        assert token == _SECRET_ACCESS_TOKEN

    def test_kis_revoke_unlinks_cache_and_forces_reissue(self, tmp_path) -> None:  # noqa: ANN001
        """revoke_cached_token → 파일 unlink + 다음 발급 강제."""
        cache = self._cache_path(tmp_path)
        # 1) 발급 + cache write
        http1 = _FakeHttp([_ok_token_response()])
        auth = KISAuth(
            config=_config(),
            http=http1,
            clock=_MutableClock(_T0),
            token_cache_path=cache,
        )
        auth.get_token()
        assert cache.exists()

        # 2) revoke
        removed = auth.revoke_cached_token()
        assert removed is True
        assert not cache.exists()

        # 3) 다음 get_token → 새 발급.
        auth._http = _FakeHttp([_ok_token_response()])  # 새 응답 주입
        token = auth.get_token()
        assert token == _SECRET_ACCESS_TOKEN
        assert cache.exists()

    def test_kis_revoke_returns_false_when_nothing_cached(self, tmp_path) -> None:  # noqa: ANN001
        cache = self._cache_path(tmp_path)
        auth = KISAuth(
            config=_config(),
            http=_FakeHttp([]),
            clock=_MutableClock(_T0),
            token_cache_path=cache,
        )
        # 발급 zero, cache zero
        assert auth.revoke_cached_token() is False


class TestKisCachePathInGitignore:
    """`.gitignore` 가 `.kis-token-cache*` 박제 (ADR 0012 R10 amendment 보호장치 #1)."""

    def test_kis_cache_path_in_gitignore(self) -> None:
        from pathlib import Path
        gitignore = Path(__file__).resolve().parents[4] / ".gitignore"
        assert gitignore.exists(), f".gitignore not found at {gitignore}"
        text = gitignore.read_text(encoding="utf-8")
        assert ".kis-token-cache" in text, (
            ".gitignore must include .kis-token-cache* "
            "(ADR 0012 R10 amendment 보호장치 #1)"
        )
