"""Notifier port — operational alerts (Telegram + Console dual delivery).

CLAUDE.md §1.3: domain / use cases depend only on this Protocol; concrete
notifiers (ConsoleNotifier, TelegramNotifier, ...) live in src/adapters/.

This is a **new external system** integration (Telegram), approved by
ADR 0012 D3 (텔레그램 + Console 이중 알림). It is a brand-new port — no
existing port is changed.

The 7 alert kinds (ADR 0012 D3) — (1) 매수 의사결정 INFO, (2) 매도 체결 INFO,
(3) Reconciliation 불일치 CRITICAL, (4) Kill switch 발화 CRITICAL,
(5) 손실한도 -20% 도달 WARNING, (6) KIS outage / token 만료 ERROR,
(7) 일일 요약 INFO — map to the :class:`NotificationLevel` values below.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class NotificationLevel(StrEnum):
    """Severity of an operational alert.

    ``StrEnum`` mirrors the domain enum convention (``src/domain/models.py``
    SignalLevel / OrderStatus / ...) — str-valued, ruff-clean.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NotifierPort(Protocol):
    """Send an operational alert.

    Implementations MUST:
    - **Dual-deliver** — every alert is recorded to the Console (logger) AND,
      when Telegram is configured, pushed to Telegram (ADR 0012 D3 이중 알림).
      The Console record happens regardless of Telegram success.
    - **Never kill trading on a delivery failure** — a Telegram send failure
      must NOT raise into the trading path (an alert outage must not stop the
      account). It is, however, NOT a silent failure: the failure is logged
      loudly on the Console (CLAUDE.md §6.3 침묵의 실패 금지).
    - Be synchronous (CLAUDE.md §10.1 disallows asyncio).
    """

    def notify(
        self, *, level: NotificationLevel, title: str, body: str
    ) -> None:
        """Emit an alert at ``level`` with a short ``title`` and ``body``."""
        ...
