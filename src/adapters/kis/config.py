"""KIS API configuration + trading-mode resolution — Phase 1.1 Stage 2.2.

Loads KIS credentials from the environment (``.env`` via the shell / process
env — this module does NOT read a file, only ``Mapping``). Holds appkey /
appsecret as in-memory fields but **never** exposes them via ``repr`` / ``str``
(ADR 0012 R10 / CLAUDE.md §8.3 민감 정보 로깅 금지) — both magic methods mask
the secrets so an accidental ``log.info(config)`` cannot leak credentials.

Default mode is **paper** (모의투자 / VTS) — ``real`` requires an explicit
``KIS_TRADING_MODE=real`` (Stage 8 실거래 ON only). Missing required env vars
raise ``ConfigurationError`` (no silent fallback — CLAUDE.md §6.3).

출처: ADR 0020 §2.1 (도메인 URL) / ADR 0012 R10 (보안) / CLAUDE.md §9.3 (비밀=환경변수).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from src.domain.exceptions import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Mapping


# ADR 0020 §2.1 — KIS base URLs (real vs 모의투자/VTS).
_PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"

# Env var prefixes per mode (see .env.example).
_PREFIX_BY_MODE = {
    "paper": "KIS_PAPER_",
    "real": "KIS_REAL_",
}


class TradingMode(StrEnum):
    """KIS trading mode. PAPER (모의투자/VTS) is the development/verification
    default; REAL (실계좌) is only enabled at Stage 8 실거래 ON.

    ``StrEnum`` (str-valued enum) mirrors the domain enum convention
    (``src/domain/models.py`` Currency/OrderSide/...) — equivalent to the
    classic ``(str, Enum)`` form, ruff-clean (RUF / pyupgrade)."""

    PAPER = "paper"
    REAL = "real"


@dataclass(frozen=True)
class KISConfig:
    """Resolved KIS API configuration (mode + base URL + credentials + account).

    ``appkey`` / ``appsecret`` are held in memory but masked in ``repr`` / ``str``
    (ADR 0012 R10) — there is no code path that prints them in full.
    """

    mode: TradingMode
    base_url: str
    appkey: str
    appsecret: str
    cano: str
    acnt_prdt_cd: str

    def __repr__(self) -> str:
        # R10: never expose appkey/appsecret in repr. appkey -> 4-char prefix
        # + ***, appsecret -> fully masked. (CLAUDE.md §8.3.)
        return (
            f"KISConfig(mode={self.mode.value!r}, base_url={self.base_url!r}, "
            f"appkey={self._masked_appkey()!r}, appsecret='***', "
            f"cano={self.cano!r}, acnt_prdt_cd={self.acnt_prdt_cd!r})"
        )

    __str__ = __repr__

    def _masked_appkey(self) -> str:
        """appkey shown as ``<first 4>***`` (CLAUDE.md §8.3)."""
        return f"{self.appkey[:4]}***" if self.appkey else "***"

    @property
    def masked_appkey(self) -> str:
        """Public masked appkey for log lines (``<first 4>***``)."""
        return self._masked_appkey()

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> KISConfig:
        """Build a ``KISConfig`` from the environment.

        ``environ`` defaults to ``os.environ`` but may be injected (tests).
        ``KIS_TRADING_MODE`` defaults to ``paper``; ``real`` requires the
        explicit value (Stage 8). Missing required vars raise
        ``ConfigurationError`` (no silent fallback — CLAUDE.md §6.3).
        """
        env = os.environ if environ is None else environ

        raw_mode = env.get("KIS_TRADING_MODE", "paper").strip().lower()
        if raw_mode not in _PREFIX_BY_MODE:
            valid = "/".join(sorted(_PREFIX_BY_MODE))
            raise ConfigurationError(
                f"KIS_TRADING_MODE must be one of {valid}, got {raw_mode!r}"
            )
        mode = TradingMode(raw_mode)
        base_url = _REAL_BASE_URL if mode is TradingMode.REAL else _PAPER_BASE_URL

        prefix = _PREFIX_BY_MODE[raw_mode]
        appkey = cls._require(env, f"{prefix}APPKEY")
        appsecret = cls._require(env, f"{prefix}APPSECRET")
        cano = cls._require(env, f"{prefix}ACCOUNT_CANO")
        acnt_prdt_cd = cls._require(env, f"{prefix}ACCOUNT_PRDT_CD")

        return cls(
            mode=mode,
            base_url=base_url,
            appkey=appkey,
            appsecret=appsecret,
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
        )

    @staticmethod
    def _require(env: Mapping[str, str], key: str) -> str:
        """Return a required env var or raise ``ConfigurationError``.

        Treats an empty / whitespace-only value as missing — a blank key in
        ``.env`` would otherwise pass silently then fail at auth time
        (CLAUDE.md §6.3 침묵의 실패 금지). The error message never echoes the
        value, only the key name.
        """
        value = env.get(key, "")
        if value.strip() == "":
            raise ConfigurationError(
                f"Missing required KIS env var: {key} (set it in .env; "
                "see .env.example)"
            )
        return value
