"""Shared KIS request layer — auth + throttle + error envelope (Stage 2.3).

A single ``request`` seam every KIS read adapter (broker / market_data) routes
through, so the auth-header construction, rate-limit throttle (ADR 0020 §2.3),
TR_ID paper conversion, and ``rt_cd`` error handling live in exactly one place.

Real-money invariants (CLAUDE.md / ADR 0012):
- **자동 재시도 zero** (ADR 0012 §1.6 #1) — a non-2xx HTTP status or a non-"0"
  ``rt_cd`` raises ``KISApiError`` immediately. We never re-call automatically.
- **secret zero in errors / logs** (ADR 0012 R10 / CLAUDE.md §8.3) —
  ``KISApiError`` carries only the non-sensitive KIS envelope codes
  (``rt_cd`` / ``msg_cd`` / HTTP status), never appkey / appsecret / token.
- **throttle** (ADR 0020 §2.3) — KIS rejects bursts with ``EGW00201`` (유량
  초과): 실 20/s, 모의 2/s. We enforce a per-mode minimum interval between
  outbound calls using the injected UTC ``clock`` + injected ``sleep`` (DI so
  tests stay network-free and instant).

DI per CLAUDE.md §1.2: ``config`` / ``http`` / ``auth`` / ``sleep`` / ``clock``
are all injected. ``clock`` returns UTC (CLAUDE.md §3.1) — no ``datetime.now()``.

출처: ADR 0020 §2.1 (TR_ID 변환) / §2.3 (rate limit, rt_cd) / ADR 0012 §1.6 #1
+ R10 / CLAUDE.md §8.3.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

from src.adapters.kis.config import TradingMode
from src.domain.exceptions import ExternalSystemError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from src.adapters.kis._http import HttpClient, HttpResponse
    from src.adapters.kis.auth import KISAuth
    from src.adapters.kis.config import KISConfig

logger = logging.getLogger(__name__)

# Per-request HTTP timeout (seconds). No unbounded waits against KIS.
_REQUEST_TIMEOUT = 10.0

# Per-mode minimum interval between outbound calls (ADR 0020 §2.3).
# 모의 2/s → 0.5s; 실 20/s → 0.05s. EGW00201 (유량 초과) 회피.
_MIN_INTERVAL_BY_MODE = {
    TradingMode.PAPER: 0.5,
    TradingMode.REAL: 0.05,
}


class KISApiError(ExternalSystemError):
    """KIS API call failed (non-2xx HTTP or non-"0" ``rt_cd``).

    Adapter-local subclass of ``ExternalSystemError`` (adapter→domain import is
    allowed). Carries the non-sensitive KIS envelope codes
    (``rt_cd`` / ``msg_cd`` / HTTP status) only — NEVER appkey / appsecret /
    access_token in plaintext (ADR 0012 R10 / CLAUDE.md §8.3).
    """


class KISClient:
    """Shared KIS request executor (auth header + throttle + error envelope).

    One instance per ``KISConfig`` (mode-aware). Read adapters call
    ``request`` and receive the parsed JSON body; envelope-level success
    (``rt_cd == "0"``) is enforced here so callers only see valid bodies.
    """

    def __init__(
        self,
        *,
        config: KISConfig,
        http: HttpClient,
        auth: KISAuth,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._http = http
        self._auth = auth
        self._clock = clock
        self._sleep = sleep
        self._min_interval = _MIN_INTERVAL_BY_MODE[config.mode]
        # UTC timestamp of the previous outbound call (None until the first).
        self._last_call_at: datetime | None = None

    @property
    def config(self) -> KISConfig:
        """The resolved KIS config (mode + account, secrets masked in repr)."""
        return self._config

    def request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        *,
        tr_id: str,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        tr_cont: str = "",
    ) -> dict[str, object]:
        """Execute a KIS API call and return the parsed JSON body.

        - ``tr_id`` is paper-converted (T/J/C → V) when ``config.mode`` is
          PAPER (ADR 0020 §2.1); ``F...`` (시세) stays unchanged.
        - The caller passes ``tr_cont`` (continuation flag) for paginated
          queries; ``request`` forwards it as a header (default "").
        - Throttles to the per-mode minimum interval before the call
          (ADR 0020 §2.3, EGW00201 회피).
        - Non-2xx → ``KISApiError``. ``rt_cd != "0"`` → ``KISApiError``.
          **자동 재시도 zero** (ADR 0012 §1.6 #1).
        """
        effective_tr_id = self._resolve_tr_id(tr_id)
        headers = self._build_headers(effective_tr_id, tr_cont)
        url = f"{self._config.base_url}{path}"

        self._throttle()

        if method == "GET":
            resp = self._http.get(
                url,
                params=params or {},
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )
        else:  # POST
            resp = self._http.post(
                url,
                json=json or {},
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )

        self._last_call_at = self._clock()
        return self._validate(resp, effective_tr_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_tr_id(self, tr_id: str) -> str:
        """Convert a real-mode TR_ID to its paper (모의) form when in PAPER.

        ADR 0020 §2.1: 첫 글자 T/J/C → V (예 ``TTTC8434R`` → ``VTTC8434R``).
        ``F...`` (시세) = 실/모의 동일 (left unchanged). In REAL mode every
        TR_ID is left unchanged.
        """
        if self._config.mode is TradingMode.PAPER and tr_id and tr_id[0] in "TJC":
            return "V" + tr_id[1:]
        return tr_id

    def _build_headers(self, tr_id: str, tr_cont: str) -> dict[str, str]:
        """Build the KIS common headers.

        ``appkey`` / ``appsecret`` are sent in the header (required by KIS) but
        NEVER logged (CLAUDE.md §8.3 / R10). The bearer token comes from the
        injected ``KISAuth`` (in-memory cache, no persistence).
        """
        return {
            "authorization": f"Bearer {self._auth.get_token()}",
            "appkey": self._config.appkey,
            "appsecret": self._config.appsecret,
            "tr_id": tr_id,
            "custtype": "P",
            "content-type": "application/json",
            "tr_cont": tr_cont,
        }

    def _throttle(self) -> None:
        """Sleep just enough to honour the per-mode minimum call interval.

        Uses the injected UTC ``clock`` to measure elapsed time since the last
        outbound call; if less than ``_min_interval`` has passed, sleep the
        remainder (ADR 0020 §2.3, EGW00201 회피). No-op on the first call.
        """
        if self._last_call_at is None:
            return
        elapsed = (self._clock() - self._last_call_at).total_seconds()
        remaining = self._min_interval - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _validate(self, resp: HttpResponse, tr_id: str) -> dict[str, object]:
        """Enforce HTTP-2xx + KIS ``rt_cd == "0"``; return the body or raise.

        No secret appears in any raised message — only ``tr_id`` (non-secret),
        HTTP status, and the KIS envelope codes (``rt_cd`` / ``msg_cd``).
        **자동 재시도 zero** (ADR 0012 §1.6 #1) — the caller decides.
        """
        body = resp.json()
        if not (200 <= resp.status_code < 300):
            msg_cd = body.get("msg_cd", "")
            raise KISApiError(
                f"KIS {tr_id} HTTP {resp.status_code} msg_cd={msg_cd!r} "
                f"(no automatic retry; ADR 0012 §1.6 #1)"
            )
        rt_cd = body.get("rt_cd")
        if rt_cd != "0":
            msg_cd = body.get("msg_cd", "")
            raise KISApiError(
                f"KIS {tr_id} rt_cd={rt_cd!r} msg_cd={msg_cd!r} "
                f"(no automatic retry; ADR 0012 §1.6 #1)"
            )
        return body
