"""HTTP seam for the KIS adapter — Phase 1.1 Stage 2.2.

A thin synchronous (``requests``) HTTP boundary behind a ``Protocol`` so the
auth / read / write adapters can be unit-tested with a fake client and **zero
real network** (CLAUDE.md §10.1 동기 / async 금지; §7.3 adapter test = mock
외부 라이브러리만).

Policy invariants:
- **timeout 필수** (default 10s) — no unbounded waits against KIS.
- **자동 retry zero** (ADR 0012 §1.6 #1 — 자동 재시도/복구 절대 금지). requests
  does not retry by default; we keep it that way and never add a retry adapter.
- Non-2xx responses are returned (not raised) as ``HttpResponse`` — the KIS
  ``rt_cd`` envelope is the authoritative success signal (ADR 0020 §2.3), so the
  caller decides. Transport-level failures (connection / timeout) are wrapped in
  ``BrokerConnectionError`` (ExternalSystemError — caller halts, never retries).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import requests

from src.domain.exceptions import BrokerConnectionError

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class HttpResponse:
    """Transport-agnostic HTTP response (status + parsed JSON body)."""

    status_code: int
    body: dict[str, object] = field(default_factory=dict)

    def json(self) -> dict[str, object]:
        """Return the parsed JSON body."""
        return self.body

    @property
    def is_success(self) -> bool:
        """True for a 2xx HTTP status (transport-level only — NOT KIS rt_cd)."""
        return 200 <= self.status_code < 300


class HttpClient(Protocol):
    """Minimal synchronous HTTP client seam (POST / GET)."""

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> HttpResponse: ...

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> HttpResponse: ...


class RequestsHttpClient:
    """``requests.Session``-backed ``HttpClient``.

    Wraps every transport-level failure (``requests.RequestException``) in
    ``BrokerConnectionError`` (ExternalSystemError) so callers treat it as an
    external outage → halt (ADR 0012 D15 c). No automatic retry is performed
    (ADR 0012 §1.6 #1).
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        default_timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session if session is not None else requests.Session()
        self._default_timeout = default_timeout

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> HttpResponse:
        return self._request("POST", url, json=json, headers=headers, timeout=timeout)

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> HttpResponse:
        return self._request(
            "GET", url, params=params, headers=headers, timeout=timeout
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        try:
            resp = self._session.request(
                method,
                url,
                json=dict(json) if json is not None else None,
                params=dict(params) if params is not None else None,
                headers=dict(headers),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            # Transport-level failure (connection / timeout / DNS). Wrap as an
            # external-system error — caller halts (ADR 0012 §1.6 #1, no retry).
            # The exception message carries no credentials (url + method only).
            raise BrokerConnectionError(
                f"KIS HTTP {method} {url} failed: {exc.__class__.__name__}"
            ) from exc

        try:
            parsed = resp.json()
        except ValueError:
            parsed = {}
        body = parsed if isinstance(parsed, dict) else {"_raw": parsed}
        return HttpResponse(status_code=resp.status_code, body=body)
