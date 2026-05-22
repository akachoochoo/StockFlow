"""Telegram + Console notifiers — Phase 1.1 Stage 3.4.

Implements :class:`~src.ports.notifications.NotifierPort` (ADR 0012 D3 텔레그램 +
Console 이중 알림). Two concrete notifiers:

- :class:`ConsoleNotifier` — Console (logger) only. Always works, no network.
- :class:`TelegramNotifier` — Telegram ``sendMessage`` **AND** Console (dual).
  A Telegram send failure NEVER raises into the trading path (an alert outage
  must not stop the account) but is logged loudly on the Console — not silent
  (CLAUDE.md §6.3 침묵의 실패 금지).

The notifier owns a **thin, telegram-local** HTTP seam (``HttpClient`` Protocol +
``RequestsHttpClient``) rather than reusing the KIS adapter's client: a Telegram
outage must be swallowed here, whereas the KIS client wraps transport failures in
``BrokerConnectionError`` (caller halts) — opposite semantics. Keeping a local
client avoids adapter→adapter coupling and keeps the right error policy local.

Security (ADR 0012 R10 / CLAUDE.md §8.3): the bot token is masked in every log
line. The ``sendMessage`` URL embeds the token, so the URL itself is NEVER logged
or placed in an exception message.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

import requests

from src.adapters.telegram.config import TelegramConfig
from src.ports.notifications import NotificationLevel, NotifierPort

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

_SEND_TIMEOUT = 10.0
_TELEGRAM_API_BASE = "https://api.telegram.org"

# NotificationLevel -> logger method (CRITICAL -> logger.critical, etc.).
_LEVEL_TO_LOG = {
    NotificationLevel.INFO: logging.INFO,
    NotificationLevel.WARNING: logging.WARNING,
    NotificationLevel.ERROR: logging.ERROR,
    NotificationLevel.CRITICAL: logging.CRITICAL,
}


def _log_console(level: NotificationLevel, title: str, body: str) -> None:
    """Record an alert on the Console at the mapped log level."""
    log_level = _LEVEL_TO_LOG[level]
    logger.log(log_level, "ALERT [%s] %s — %s", level.value, title, body)


class HttpClient(Protocol):
    """Minimal synchronous HTTP POST seam for Telegram (telegram-local).

    Deliberately separate from the KIS ``HttpClient`` — the notifier swallows
    transport failures (alert outage must not halt trading), so it must not
    share the KIS client's halt-on-failure wrapping.
    """

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        timeout: float = _SEND_TIMEOUT,
    ) -> int:
        """POST ``json`` to ``url``; return the HTTP status code."""
        ...


class RequestsHttpClient:
    """``requests``-backed Telegram ``HttpClient``.

    Returns the HTTP status code. Raises ``requests.RequestException`` on a
    transport-level failure — :class:`TelegramNotifier` catches it (the alert
    path must never raise into trading). No automatic retry.
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        default_timeout: float = _SEND_TIMEOUT,
    ) -> None:
        self._session = session if session is not None else requests.Session()
        self._default_timeout = default_timeout

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        timeout: float = _SEND_TIMEOUT,
    ) -> int:
        resp = self._session.post(url, json=dict(json), timeout=timeout)
        return resp.status_code


class ConsoleNotifier(NotifierPort):
    """Console-only notifier (logger). Always available, no network."""

    def notify(
        self, *, level: NotificationLevel, title: str, body: str
    ) -> None:
        _log_console(level, title, body)


class TelegramNotifier(NotifierPort):
    """Telegram ``sendMessage`` + Console (dual delivery, ADR 0012 D3).

    DI per CLAUDE.md §1.2: ``config`` + ``http`` injected. Every ``notify``
    records to the Console (always) and pushes to Telegram. A Telegram failure
    (non-2xx or exception) is logged loudly on the Console and swallowed — it
    NEVER raises into the trading path (alert outage must not stop the account),
    and it is NOT silent (CLAUDE.md §6.3).
    """

    def __init__(self, *, config: TelegramConfig, http: HttpClient) -> None:
        self._config = config
        self._http = http
        # URL embeds the bot token — built once, NEVER logged (ADR 0012 R10).
        self._send_url = (
            f"{_TELEGRAM_API_BASE}/bot{config.bot_token}/sendMessage"
        )

    def notify(
        self, *, level: NotificationLevel, title: str, body: str
    ) -> None:
        # Console first — recorded regardless of Telegram outcome (dual).
        _log_console(level, title, body)
        self._send_telegram(level, title, body)

    def _send_telegram(
        self, level: NotificationLevel, title: str, body: str
    ) -> None:
        """Push the alert to Telegram; swallow failures (loud Console log)."""
        text = f"[{level.value}] {title}\n{body}"
        payload = {"chat_id": self._config.chat_id, "text": text}
        try:
            status_code = self._http.post(
                self._send_url, json=payload, timeout=_SEND_TIMEOUT
            )
        except requests.RequestException as exc:
            # Transport failure — do NOT raise into trading (ADR 0012 D3 /
            # CLAUDE.md §6.3). Loud Console error; URL omitted (carries token).
            logger.error(
                "Telegram send failed (transport, bot=%s): %s — alert kept on "
                "Console only; trading continues.",
                self._config.masked_bot_token,
                exc.__class__.__name__,
            )
            return
        if not (200 <= status_code < 300):
            # Non-2xx — also swallowed but logged loudly (not silent). The
            # request URL is NOT logged (it embeds the bot token).
            logger.error(
                "Telegram send failed (HTTP %d, bot=%s) — alert kept on "
                "Console only; trading continues.",
                status_code,
                self._config.masked_bot_token,
            )


def build_notifier(
    environ: Mapping[str, str] | None = None,
    *,
    http: HttpClient | None = None,
) -> NotifierPort:
    """Build a notifier from the environment (ADR 0012 D3).

    Returns a :class:`TelegramNotifier` when both ``TELEGRAM_BOT_TOKEN`` and
    ``TELEGRAM_CHAT_ID`` are present, else a :class:`ConsoleNotifier` with a
    one-time startup WARNING ("telegram 미설정 — console-only"). Mandatory
    Telegram for 실거래 (Stage 8) is a later step.

    ``http`` is injectable (tests); defaults to a ``requests``-backed client.
    """
    config = TelegramConfig.from_env(environ)
    if config is None:
        logger.warning(
            "Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
            "absent) — console-only notifications. Set both in .env to enable "
            "Telegram (ADR 0012 D3)."
        )
        return ConsoleNotifier()
    client = http if http is not None else RequestsHttpClient()
    return TelegramNotifier(config=config, http=client)
