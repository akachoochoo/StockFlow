"""Unit tests for src.adapters.telegram.notifier (Phase 1.1 Stage 3.4).

Uses a fake ``HttpClient`` (records POST calls, returns canned status / raises
queued exc) — **zero real network**. Verifies dual delivery (Telegram +
Console), 100% delivery (N notify → N sends), send-failure swallowing (no raise,
loud Console fallback), level→log mapping, ConsoleNotifier (no network), and
(R10) that the bot token never appears in any log line / exception.

Function names carry ``telegram_console_dual_alert`` / ``telegram_100pct_delivery``
(Stage gate keyword selectors). No real network.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
import requests

from src.adapters.telegram.config import TelegramConfig
from src.adapters.telegram.notifier import (
    ConsoleNotifier,
    TelegramNotifier,
    build_notifier,
)
from src.ports.notifications import NotificationLevel

if TYPE_CHECKING:
    from collections.abc import Mapping

_SECRET_BOT_TOKEN = "123456789:AAabcdefghijklmnopqrstuvwxyz0123456789SECRET"
_CHAT_ID = "987654321"

_NOTIFIER_LOGGER = "src.adapters.telegram.notifier"


def _config() -> TelegramConfig:
    return TelegramConfig(bot_token=_SECRET_BOT_TOKEN, chat_id=_CHAT_ID)


class _FakeHttp:
    """Records POST calls; returns queued status codes or raises a queued exc."""

    def __init__(
        self,
        status_codes: list[int] | None = None,
        *,
        raise_exc: Exception | None = None,
        default_status: int = 200,
    ) -> None:
        self._status_codes = list(status_codes or [])
        self._raise_exc = raise_exc
        self._default_status = default_status
        self.post_calls: list[dict[str, object]] = []

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        timeout: float = 10.0,
    ) -> int:
        self.post_calls.append(
            {"url": url, "json": dict(json), "timeout": timeout}
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._status_codes:
            return self._status_codes.pop(0)
        return self._default_status


class TestTelegramNotifierDualDelivery:
    def test_telegram_console_dual_alert_sends_and_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        http = _FakeHttp([200])
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.INFO, logger=_NOTIFIER_LOGGER):
            notifier.notify(
                level=NotificationLevel.INFO,
                title="매수 의사결정",
                body="069500 split_level=2",
            )
        # Telegram send happened exactly once...
        assert len(http.post_calls) == 1
        call = http.post_calls[0]
        assert call["url"].endswith("/sendMessage")
        assert call["url"].startswith(
            f"https://api.telegram.org/bot{_SECRET_BOT_TOKEN}/"
        )
        assert call["json"]["chat_id"] == _CHAT_ID
        assert "매수 의사결정" in call["json"]["text"]
        assert "069500 split_level=2" in call["json"]["text"]
        # ...AND Console recorded the same alert (dual delivery).
        assert any("매수 의사결정" in r.getMessage() for r in caplog.records)

    def test_telegram_console_dual_alert_text_includes_level(self) -> None:
        http = _FakeHttp([200])
        notifier = TelegramNotifier(config=_config(), http=http)
        notifier.notify(
            level=NotificationLevel.CRITICAL,
            title="Kill switch",
            body="TRADING_HALT=1",
        )
        text = http.post_calls[0]["json"]["text"]
        assert "[CRITICAL]" in text
        assert "Kill switch" in text


class TestTelegramNotifier100PctDelivery:
    def test_telegram_100pct_delivery_each_notify_sends(self) -> None:
        # N notify -> N Telegram sends (ADR 0012 D6 (v) 100% 수신율).
        http = _FakeHttp([200, 200, 200, 200, 200])
        notifier = TelegramNotifier(config=_config(), http=http)
        for i in range(5):
            notifier.notify(
                level=NotificationLevel.INFO,
                title=f"alert {i}",
                body=f"body {i}",
            )
        assert len(http.post_calls) == 5

    def test_telegram_100pct_delivery_console_records_every_alert(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        http = _FakeHttp([200, 200, 200])
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.INFO, logger=_NOTIFIER_LOGGER):
            for i in range(3):
                notifier.notify(
                    level=NotificationLevel.INFO,
                    title=f"alert {i}",
                    body="x",
                )
        alert_records = [r for r in caplog.records if "ALERT" in r.getMessage()]
        assert len(alert_records) == 3


class TestTelegramNotifierFailureDoesNotKillTrading:
    def test_telegram_non_2xx_does_not_raise_and_logs_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        http = _FakeHttp([500])
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.INFO, logger=_NOTIFIER_LOGGER):
            # Must NOT raise — an alert outage cannot stop trading.
            notifier.notify(
                level=NotificationLevel.ERROR,
                title="KIS outage",
                body="token expired",
            )
        # Loud Console error logged (not silent — CLAUDE.md §6.3).
        error_records = [
            r for r in caplog.records if r.levelno == logging.ERROR
        ]
        assert any(
            "Telegram send failed" in r.getMessage() for r in error_records
        )

    def test_telegram_transport_exception_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        http = _FakeHttp(raise_exc=requests.ConnectionError("refused"))
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.INFO, logger=_NOTIFIER_LOGGER):
            # Transport failure swallowed — trading continues.
            notifier.notify(
                level=NotificationLevel.WARNING,
                title="손실한도",
                body="-20% reached",
            )
        assert any(
            "Telegram send failed" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.ERROR
        )

    def test_telegram_failure_still_records_console_alert(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Console alert is recorded BEFORE the Telegram attempt — present even
        # when the send fails (dual delivery degrades to console-only).
        http = _FakeHttp(raise_exc=requests.ConnectionError("refused"))
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.WARNING, logger=_NOTIFIER_LOGGER):
            notifier.notify(
                level=NotificationLevel.WARNING,
                title="손실한도",
                body="-20%",
            )
        assert any("손실한도" in r.getMessage() for r in caplog.records)


class TestTelegramNotifierSecretSafety:
    """R10 / CLAUDE.md §8.3 — bot token never in any log line / exception."""

    def test_telegram_bot_token_not_in_logs_on_success(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        http = _FakeHttp([200])
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.DEBUG, logger=_NOTIFIER_LOGGER):
            notifier.notify(
                level=NotificationLevel.INFO, title="t", body="b"
            )
        for record in caplog.records:
            assert _SECRET_BOT_TOKEN not in record.getMessage()

    def test_telegram_bot_token_not_in_logs_on_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The send URL embeds the token; the failure log must not echo the URL.
        http = _FakeHttp([403])
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.DEBUG, logger=_NOTIFIER_LOGGER):
            notifier.notify(
                level=NotificationLevel.ERROR, title="t", body="b"
            )
        for record in caplog.records:
            assert _SECRET_BOT_TOKEN not in record.getMessage()

    def test_telegram_bot_token_not_in_logs_on_transport_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        http = _FakeHttp(raise_exc=requests.ConnectionError("refused"))
        notifier = TelegramNotifier(config=_config(), http=http)
        with caplog.at_level(logging.DEBUG, logger=_NOTIFIER_LOGGER):
            notifier.notify(
                level=NotificationLevel.ERROR, title="t", body="b"
            )
        for record in caplog.records:
            assert _SECRET_BOT_TOKEN not in record.getMessage()


class TestConsoleNotifier:
    def test_console_notifier_logs_without_network(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        notifier = ConsoleNotifier()
        with caplog.at_level(logging.INFO, logger=_NOTIFIER_LOGGER):
            notifier.notify(
                level=NotificationLevel.INFO,
                title="일일 요약",
                body="PnL +1.2%",
            )
        assert any("일일 요약" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize(
        ("level", "expected_levelno"),
        [
            (NotificationLevel.INFO, logging.INFO),
            (NotificationLevel.WARNING, logging.WARNING),
            (NotificationLevel.ERROR, logging.ERROR),
            (NotificationLevel.CRITICAL, logging.CRITICAL),
        ],
    )
    def test_console_notifier_level_mapping(
        self,
        caplog: pytest.LogCaptureFixture,
        level: NotificationLevel,
        expected_levelno: int,
    ) -> None:
        notifier = ConsoleNotifier()
        with caplog.at_level(logging.DEBUG, logger=_NOTIFIER_LOGGER):
            notifier.notify(level=level, title="t", body="b")
        alert_records = [
            r for r in caplog.records if "ALERT" in r.getMessage()
        ]
        assert len(alert_records) == 1
        assert alert_records[0].levelno == expected_levelno


class TestBuildNotifier:
    def test_build_notifier_returns_telegram_when_configured(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": _SECRET_BOT_TOKEN,
            "TELEGRAM_CHAT_ID": _CHAT_ID,
        }
        http = _FakeHttp([200])
        notifier = build_notifier(env, http=http)
        assert isinstance(notifier, TelegramNotifier)
        notifier.notify(level=NotificationLevel.INFO, title="t", body="b")
        assert len(http.post_calls) == 1

    def test_build_notifier_returns_console_when_unconfigured(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_NOTIFIER_LOGGER):
            notifier = build_notifier({})
        assert isinstance(notifier, ConsoleNotifier)
        # One-time startup WARNING ("telegram 미설정 — console-only").
        assert any(
            "console-only" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
        )

    def test_build_notifier_console_when_only_token_present(self) -> None:
        env = {"TELEGRAM_BOT_TOKEN": _SECRET_BOT_TOKEN}
        notifier = build_notifier(env)
        assert isinstance(notifier, ConsoleNotifier)
