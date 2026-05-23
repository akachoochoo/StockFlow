"""Telegram notifier configuration — Phase 1.1 Stage 3.4.

Loads the Telegram bot credentials from the environment (``.env`` via the
process env — this module reads a ``Mapping`` only, never a file). The
``bot_token`` is held in memory but **masked** in ``repr`` / ``str``
(ADR 0012 R10 / CLAUDE.md §8.3 민감 정보 로깅 금지) — an accidental
``log.info(config)`` cannot leak the token. ``chat_id`` is NOT a secret
(it only identifies the destination chat), so it is shown in full.

Telegram is **optional** at this stage (ADR 0012 D3): when either var is
absent, ``from_env`` returns ``None`` and the factory falls back to a
console-only notifier. Mandatory Telegram for 실거래 (Stage 8) is a later step.

출처: ADR 0012 D3 (텔레그램 + Console 이중) / ADR 0012 R10 (보안) /
CLAUDE.md §9.3 (비밀=환경변수).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


@dataclass(frozen=True)
class TelegramConfig:
    """Resolved Telegram credentials (bot token + destination chat id).

    ``bot_token`` is held in memory but masked in ``repr`` / ``str``
    (ADR 0012 R10) — no code path prints it in full. ``chat_id`` is not a
    secret and is shown verbatim.
    """

    bot_token: str
    chat_id: str

    def __repr__(self) -> str:
        # R10: never expose bot_token in repr. token -> 8-char prefix + ***.
        # chat_id is not a secret (CLAUDE.md §8.3).
        return (
            f"TelegramConfig(bot_token={self._masked_bot_token()!r}, "
            f"chat_id={self.chat_id!r})"
        )

    __str__ = __repr__

    def _masked_bot_token(self) -> str:
        """bot_token shown as ``<first 8>***`` (CLAUDE.md §8.3)."""
        return f"{self.bot_token[:8]}***" if self.bot_token else "***"

    @property
    def masked_bot_token(self) -> str:
        """Public masked bot token for log lines (``<first 8>***``)."""
        return self._masked_bot_token()

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> TelegramConfig | None:
        """Build a ``TelegramConfig`` from the environment, or ``None``.

        ``environ`` defaults to ``os.environ`` but may be injected (tests).
        Returns ``None`` when either ``TELEGRAM_BOT_TOKEN`` or
        ``TELEGRAM_CHAT_ID`` is absent / blank — the caller then falls back
        to console-only delivery (ADR 0012 D3, Telegram optional this stage).
        """
        env = os.environ if environ is None else environ
        bot_token = env.get(_BOT_TOKEN_ENV, "").strip()
        chat_id = env.get(_CHAT_ID_ENV, "").strip()
        if not bot_token or not chat_id:
            return None
        return cls(bot_token=bot_token, chat_id=chat_id)
