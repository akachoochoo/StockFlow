"""Unit tests for src.adapters.telegram.config (Phase 1.1 Stage 3.4).

Verifies from_env loading (both vars present), None when either var
absent/blank, and (R10 / CLAUDE.md §8.3) that bot_token never appears in
plaintext in repr/str. ``chat_id`` is NOT a secret — exposure is allowed.

No real network.
"""
from __future__ import annotations

from src.adapters.telegram.config import TelegramConfig

# Sentinel secret — this exact string must never leak into repr/str.
_SECRET_BOT_TOKEN = "123456789:AAabcdefghijklmnopqrstuvwxyz0123456789SECRET"
_CHAT_ID = "987654321"


def _env() -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": _SECRET_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": _CHAT_ID,
    }


class TestTelegramConfigFromEnv:
    def test_telegram_config_from_env_loads_token_and_chat_id(self) -> None:
        cfg = TelegramConfig.from_env(_env())
        assert cfg is not None
        assert cfg.bot_token == _SECRET_BOT_TOKEN
        assert cfg.chat_id == _CHAT_ID

    def test_telegram_config_from_env_strips_whitespace(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": f"  {_SECRET_BOT_TOKEN}  ",
            "TELEGRAM_CHAT_ID": f" {_CHAT_ID} ",
        }
        cfg = TelegramConfig.from_env(env)
        assert cfg is not None
        assert cfg.bot_token == _SECRET_BOT_TOKEN
        assert cfg.chat_id == _CHAT_ID

    def test_telegram_config_none_when_token_absent(self) -> None:
        env = _env()
        del env["TELEGRAM_BOT_TOKEN"]
        assert TelegramConfig.from_env(env) is None

    def test_telegram_config_none_when_chat_id_absent(self) -> None:
        env = _env()
        del env["TELEGRAM_CHAT_ID"]
        assert TelegramConfig.from_env(env) is None

    def test_telegram_config_none_when_token_blank(self) -> None:
        env = _env()
        env["TELEGRAM_BOT_TOKEN"] = "   "
        assert TelegramConfig.from_env(env) is None

    def test_telegram_config_none_when_chat_id_blank(self) -> None:
        env = _env()
        env["TELEGRAM_CHAT_ID"] = ""
        assert TelegramConfig.from_env(env) is None


class TestTelegramConfigSecretMasking:
    """R10 / CLAUDE.md §8.3 — bot_token never in plaintext repr/str."""

    def test_telegram_config_repr_does_not_expose_bot_token(self) -> None:
        cfg = TelegramConfig.from_env(_env())
        assert cfg is not None
        rendered = repr(cfg)
        assert _SECRET_BOT_TOKEN not in rendered
        assert f"{_SECRET_BOT_TOKEN[:8]}***" in rendered

    def test_telegram_config_str_does_not_expose_bot_token(self) -> None:
        cfg = TelegramConfig.from_env(_env())
        assert cfg is not None
        assert _SECRET_BOT_TOKEN not in str(cfg)

    def test_telegram_config_chat_id_not_masked(self) -> None:
        # chat_id is not a secret — exposure in repr is allowed.
        cfg = TelegramConfig.from_env(_env())
        assert cfg is not None
        assert _CHAT_ID in repr(cfg)

    def test_telegram_config_masked_bot_token_property(self) -> None:
        cfg = TelegramConfig.from_env(_env())
        assert cfg is not None
        assert cfg.masked_bot_token == f"{_SECRET_BOT_TOKEN[:8]}***"
        assert _SECRET_BOT_TOKEN not in cfg.masked_bot_token
