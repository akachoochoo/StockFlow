"""KIS OAuth2 authentication — Phase 1.1 Stage 2.2.

Issues + caches the KIS ``access_token`` (``POST /oauth2/tokenP``). Real-money
security is the top priority:

- ``appkey`` is masked (``<first 4>***``) anywhere it could surface; ``appsecret``
  and ``access_token`` are NEVER logged or placed in an exception message in
  plaintext (CLAUDE.md §8.3).
- **자동 재시도 zero** (ADR 0012 §1.6 #1) — a failed issue raises ``KISAuthError``
  and the caller decides whether to halt (D15 c). We never re-POST automatically.

Token storage (ADR 0012 R10 amendment, 2026-06-11):
- Default = in-memory only (`token_cache_path=None`) — preserves original
  invariant for live-trading callers that opted out of disk cache.
- Opt-in disk cache (`token_cache_path=Path(...)`) — survives process restarts,
  avoids KIS "1-issue-per-minute" rate limit during backfill / cron series.
  Guarded by 4 protections (ADR 0012 §1.5 R10 amendment):
  1. Path: caller-injected, recommended `.kis-token-cache.json` in repo root
     (gitignored).
  2. File perms: chmod **0600** enforced on save; load rejects + invalidates
     anything else (`_check_cache_perms`).
  3. Revoke command: `trading kis-revoke-token` unlinks the cache file.
  4. Logging: cache hit = silent / miss + issue = INFO + masked appkey /
     invalidate = WARNING + reason. Token contents never logged.

Expiry is **TTL-based** (UTC clock injected, CLAUDE.md §3.1): re-issue once
``clock() >= issued_at + 23h`` (the KIS token is valid 24h — we keep a 1h safety
buffer). KIS's own ``access_token_token_expired`` string is KST-ambiguous, so it
is kept only as a reference, not used to drive expiry.

출처: ADR 0020 §2.1 (tokenP) / ADR 0012 R10 amendment (disk cache 보호장치 4건)
+ §1.6 #1 + §1.10 시나리오 E.
"""
from __future__ import annotations

import json
import logging
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path  # noqa: TC003  -- runtime use in os.chmod / Path APIs
from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.adapters.kis.models import KISTokenResponse
from src.domain.exceptions import ExternalSystemError

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.adapters.kis._http import HttpClient
    from src.adapters.kis.config import KISConfig

logger = logging.getLogger(__name__)

# KIS access_token is valid 24h; re-issue with a 1h safety buffer (ADR 0020 §2.1).
_TOKEN_TTL = timedelta(hours=23)
# Per-request timeout for the token endpoint (seconds).
_TOKEN_TIMEOUT = 10.0
# Required permission bits for the disk cache file (owner read/write only).
_REQUIRED_CACHE_MODE = 0o600


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
        token_cache_path: Path | None = None,
    ) -> None:
        self._config = config
        self._http = http
        self._clock = clock
        # In-memory token cache.
        self._token: str | None = None
        self._issued_at: datetime | None = None
        # KIS wire expiry string ("YYYY-MM-DD HH:MM:SS", KST-ambiguous) kept
        # for reference / diagnostics only — NOT used to drive expiry.
        self._wire_expired: str | None = None
        # Disk cache (ADR 0012 R10 amendment, 2026-06-11). None = in-memory only
        # (회귀 zero). 명시 path 시만 활성 — 보호장치 4건 적용.
        self._token_cache_path = token_cache_path

    def get_token(self) -> str:
        """Return a valid access token, issuing one if the cache is empty/stale.

        Resolution order:
        1. In-memory cache (zero IO) — within TTL.
        2. Disk cache (if `token_cache_path` set) — permission verified + TTL
           checked. On any guard failure: invalidate + re-issue.
        3. POST /oauth2/tokenP — issue fresh token. Persist to disk if cache
           is enabled.

        Never retries automatically on failure (ADR 0012 §1.6 #1).
        """
        if self._token is not None and not self._is_expired():
            return self._token
        if self._token_cache_path is not None:
            loaded = self._load_cached_token()
            if loaded is not None:
                # Cache hit (disk) — silent log (ADR 0012 R10 amendment #4).
                return loaded
        return self._issue_token()

    def _is_expired(self) -> bool:
        """True when the cached token is past its TTL (clock is UTC)."""
        if self._issued_at is None:
            return True
        return self._clock() >= self._issued_at + _TOKEN_TTL

    # ------------------------------------------------------------------
    # Disk cache (ADR 0012 R10 amendment, 2026-06-11)
    # ------------------------------------------------------------------
    def _load_cached_token(self) -> str | None:
        """Disk cache load with 4-protection guards.

        Returns the cached token if every guard passes; otherwise invalidates
        + returns None so the caller falls back to a fresh issue.

        Guards (ADR 0012 R10 amendment 박제 순서):
        - Path exists (silent miss if not).
        - File permissions exactly 0600 — else invalidate (WARNING).
        - Schema valid + TTL not expired — else invalidate (WARNING).
        """
        assert self._token_cache_path is not None
        path = self._token_cache_path
        if not path.exists():
            return None

        # Permission check (보호장치 #2).
        try:
            file_mode = stat.S_IMODE(path.stat().st_mode)
        except OSError as exc:
            self._invalidate_cache(f"stat failed: {exc.strerror}")
            return None
        if file_mode != _REQUIRED_CACHE_MODE:
            self._invalidate_cache(
                f"file permission {file_mode:o} != required 600"
            )
            return None

        # Schema load.
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            token = str(raw["access_token"])
            issued_at = datetime.fromisoformat(str(raw["issued_at"]))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self._invalidate_cache(
                f"schema invalid: {type(exc).__name__}"
            )
            return None
        if issued_at.tzinfo is None:
            self._invalidate_cache("issued_at must be timezone-aware")
            return None

        # TTL check.
        if self._clock() >= issued_at + _TOKEN_TTL:
            self._invalidate_cache("ttl expired")
            return None

        # Hot reload into in-memory cache.
        self._token = token
        self._issued_at = issued_at
        self._wire_expired = raw.get("wire_expired")
        return token

    def _save_cached_token(self) -> None:
        """Atomic write (tmp + rename + chmod 0600). Token content not logged."""
        if self._token_cache_path is None:
            return
        assert self._token is not None
        assert self._issued_at is not None
        path = self._token_cache_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = {
            "access_token": self._token,
            "issued_at": self._issued_at.isoformat(),
            "wire_expired": self._wire_expired,
        }
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(tmp, _REQUIRED_CACHE_MODE)  # noqa: PTH101  -- explicit os.chmod
        tmp.replace(path)

    def _invalidate_cache(self, reason: str) -> None:
        """Unlink the cache + WARNING log. Token content never logged."""
        if self._token_cache_path is None:
            return
        path = self._token_cache_path
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning(
                    "KIS token cache unlink failed (%s): %s",
                    reason,
                    exc.strerror,
                )
                return
        logger.warning(
            "KIS token cache invalidated (appkey=%s): %s",
            self._config.masked_appkey,
            reason,
        )

    def revoke_cached_token(self) -> bool:
        """Public: revoke disk + in-memory cache. Returns True if anything removed.

        ADR 0012 R10 amendment 보호장치 #3 — `trading kis-revoke-token` 진입점.
        """
        removed = False
        if self._token is not None or self._issued_at is not None:
            removed = True
            self._token = None
            self._issued_at = None
            self._wire_expired = None
        if self._token_cache_path is not None and self._token_cache_path.exists():
            self._invalidate_cache("manual revoke")
            removed = True
        return removed

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

        # Cache in memory + (opt-in) disk per ADR 0012 R10 amendment.
        self._token = parsed.access_token
        self._issued_at = now
        self._wire_expired = parsed.access_token_token_expired
        logger.info("KIS token issued (appkey=%s)", self._config.masked_appkey)
        if self._token_cache_path is not None:
            self._save_cached_token()
        return self._token
