"""KIS OAuth2 authentication — Phase 1.1 Stage 2.2.

Issues + caches the KIS ``access_token`` (``POST /oauth2/tokenP``). Real-money
security is the top priority:

- The token lives **in memory only** (``self._token`` / ``self._issued_at``) —
  never written to a file / DB / log (ADR 0012 R10 / §1.10 시나리오 E).
- ``appkey`` is masked (``<first 4>***``) anywhere it could surface; ``appsecret``
  and ``access_token`` are NEVER logged or placed in an exception message in
  plaintext (CLAUDE.md §8.3).
- **자동 재시도 zero** (ADR 0012 §1.6 #1) — a failed issue raises ``KISAuthError``
  and the caller decides whether to halt (D15 c). We never re-POST automatically.

Expiry is **TTL-based** (UTC clock injected, CLAUDE.md §3.1): re-issue once
``clock() >= issued_at + 23h`` (the KIS token is valid 24h — we keep a 1h safety
buffer). KIS's own ``access_token_token_expired`` string is KST-ambiguous, so it
is kept only as a reference, not used to drive expiry.

출처: ADR 0020 §2.1 (tokenP) / ADR 0012 R10 + §1.6 #1 + §1.10 시나리오 E.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.adapters.kis.models import KISTokenResponse
from src.domain.exceptions import ExternalSystemError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from src.adapters.kis._http import HttpClient
    from src.adapters.kis.config import KISConfig

logger = logging.getLogger(__name__)

# KIS access_token is valid 24h; re-issue with a 1h safety buffer (ADR 0020 §2.1).
_TOKEN_TTL = timedelta(hours=23)
# Per-request timeout for the token endpoint (seconds).
_TOKEN_TIMEOUT = 10.0


class KISAuthError(ExternalSystemError):
    """KIS authentication (token issue) failed.

    Adapter-local subclass of ``ExternalSystemError`` (adapter→domain import is
    allowed). Messages NEVER contain appsecret / access_token in plaintext
    (ADR 0012 R10)."""


class KISAuth:
    """KIS OAuth2 token issuer + in-memory cache.

    DI per CLAUDE.md §1.2: ``config`` / ``http`` / ``clock`` are all injected.
    ``clock`` returns UTC (CLAUDE.md §3.1) — no ``datetime.now()`` here.
    """

    def __init__(
        self,
        *,
        config: KISConfig,
        http: HttpClient,
        clock: Callable[[], datetime],
    ) -> None:
        self._config = config
        self._http = http
        self._clock = clock
        # In-memory token cache only (never persisted — ADR 0012 R10).
        self._token: str | None = None
        self._issued_at: datetime | None = None
        # KIS wire expiry string ("YYYY-MM-DD HH:MM:SS", KST-ambiguous) kept
        # for reference / diagnostics only — NOT used to drive expiry.
        self._wire_expired: str | None = None

    def get_token(self) -> str:
        """Return a valid access token, issuing one if the cache is empty/stale.

        Returns the cached token (zero HTTP) while within TTL; otherwise issues
        a fresh token. Never retries automatically on failure (ADR 0012 §1.6 #1).
        """
        if self._token is not None and not self._is_expired():
            return self._token
        return self._issue_token()

    def _is_expired(self) -> bool:
        """True when the cached token is past its TTL (clock is UTC)."""
        if self._issued_at is None:
            return True
        return self._clock() >= self._issued_at + _TOKEN_TTL

    def _issue_token(self) -> str:
        """POST /oauth2/tokenP and cache the resulting token (in memory only)."""
        url = f"{self._config.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self._config.appkey,
            "appsecret": self._config.appsecret,
        }
        headers = {"Content-Type": "application/json"}

        # appkey masked; appsecret NEVER logged (CLAUDE.md §8.3 / R10).
        logger.info("KIS token issue request (appkey=%s)", self._config.masked_appkey)

        now = self._clock()
        resp = self._http.post(
            url, json=body, headers=headers, timeout=_TOKEN_TIMEOUT
        )

        if not (200 <= resp.status_code < 300):
            # No retry (ADR 0012 §1.6 #1). The token endpoint is OAuth2, so its
            # error body uses error_code / error_description (NOT the KIS trading
            # envelope msg_cd / msg1). Surface whichever is present so a 403
            # (unregistered IP / wrong-env key / bad appsecret) is diagnosable.
            err = resp.json()
            detail = str(
                err.get("error_description")
                or err.get("msg1")
                or err.get("error_code")
                or err.get("msg_cd")
                or ""
            )[:200]
            # R10 defense: never let appkey/appsecret echo through an error body.
            for secret in (self._config.appkey, self._config.appsecret):
                if secret and secret in detail:
                    detail = detail.replace(secret, "***")
            raise KISAuthError(
                f"KIS token issue failed: HTTP {resp.status_code} "
                f"detail={detail!r} (no automatic retry; ADR 0012 §1.6 #1)"
            )

        try:
            parsed = KISTokenResponse.model_validate(resp.json())
        except ValidationError as exc:
            # Missing access_token (or malformed response). Do not echo the body
            # (could carry the token) — only the error code count.
            raise KISAuthError(
                f"KIS token response missing/invalid access_token "
                f"({len(exc.errors())} field error(s))"
            ) from exc

        # Cache in memory only — never persist (ADR 0012 R10).
        self._token = parsed.access_token
        self._issued_at = now
        self._wire_expired = parsed.access_token_token_expired
        logger.info("KIS token issued (appkey=%s)", self._config.masked_appkey)
        return self._token
