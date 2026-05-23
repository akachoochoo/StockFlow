"""Unit tests for src.adapters.kis.config (Phase 1.1 Stage 2.2).

Verifies mode→base_url mapping, env-var prefix selection per mode, default=paper,
required-var-missing → ConfigurationError, and (R10 / CLAUDE.md §8.3) that
appkey/appsecret never appear in plaintext in repr/str.

Function names carry ``kis_config_`` (Stage gate selector). No real network.
"""
from __future__ import annotations

import pytest

from src.adapters.kis.config import (
    _PAPER_BASE_URL,
    _REAL_BASE_URL,
    KISConfig,
    TradingMode,
)
from src.domain.exceptions import ConfigurationError

# Sentinel secrets — these exact strings must never leak into repr/str.
_SECRET_APPKEY = "PKabcdefghijklmnop1234567890"
_SECRET_APPSECRET = "SECRETsupersecretappsecretvalue=="


def _paper_env() -> dict[str, str]:
    return {
        "KIS_TRADING_MODE": "paper",
        "KIS_PAPER_APPKEY": _SECRET_APPKEY,
        "KIS_PAPER_APPSECRET": _SECRET_APPSECRET,
        "KIS_PAPER_ACCOUNT_CANO": "50012345",
        "KIS_PAPER_ACCOUNT_PRDT_CD": "01",
    }


def _real_env() -> dict[str, str]:
    return {
        "KIS_TRADING_MODE": "real",
        "KIS_REAL_APPKEY": _SECRET_APPKEY,
        "KIS_REAL_APPSECRET": _SECRET_APPSECRET,
        "KIS_REAL_ACCOUNT_CANO": "12345678",
        "KIS_REAL_ACCOUNT_PRDT_CD": "01",
    }


class TestKisConfigMode:
    def test_kis_config_paper_mode_maps_to_vts_base_url(self) -> None:
        cfg = KISConfig.from_env(_paper_env())
        assert cfg.mode is TradingMode.PAPER
        assert cfg.base_url == _PAPER_BASE_URL
        assert cfg.base_url == "https://openapivts.koreainvestment.com:29443"

    def test_kis_config_real_mode_maps_to_real_base_url(self) -> None:
        cfg = KISConfig.from_env(_real_env())
        assert cfg.mode is TradingMode.REAL
        assert cfg.base_url == _REAL_BASE_URL
        assert cfg.base_url == "https://openapi.koreainvestment.com:9443"

    def test_kis_config_default_mode_is_paper(self) -> None:
        # KIS_TRADING_MODE unset → default paper (real requires explicit value).
        env = _paper_env()
        del env["KIS_TRADING_MODE"]
        cfg = KISConfig.from_env(env)
        assert cfg.mode is TradingMode.PAPER
        assert cfg.base_url == _PAPER_BASE_URL

    def test_kis_config_invalid_mode_raises_configuration_error(self) -> None:
        env = _paper_env()
        env["KIS_TRADING_MODE"] = "live"
        with pytest.raises(ConfigurationError, match="KIS_TRADING_MODE"):
            KISConfig.from_env(env)


class TestKisConfigEnvSelection:
    def test_kis_config_paper_selects_paper_prefix_vars(self) -> None:
        cfg = KISConfig.from_env(_paper_env())
        assert cfg.appkey == _SECRET_APPKEY
        assert cfg.appsecret == _SECRET_APPSECRET
        assert cfg.cano == "50012345"
        assert cfg.acnt_prdt_cd == "01"

    def test_kis_config_real_selects_real_prefix_vars(self) -> None:
        cfg = KISConfig.from_env(_real_env())
        assert cfg.appkey == _SECRET_APPKEY
        assert cfg.cano == "12345678"

    def test_kis_config_real_ignores_paper_vars(self) -> None:
        # real mode with only paper vars present → missing real vars → error.
        env = {"KIS_TRADING_MODE": "real", **_paper_env()}
        del env["KIS_TRADING_MODE"]
        env["KIS_TRADING_MODE"] = "real"
        with pytest.raises(ConfigurationError, match="KIS_REAL_APPKEY"):
            KISConfig.from_env(env)


class TestKisConfigMissingVars:
    @pytest.mark.parametrize(
        "missing_key",
        [
            "KIS_PAPER_APPKEY",
            "KIS_PAPER_APPSECRET",
            "KIS_PAPER_ACCOUNT_CANO",
            "KIS_PAPER_ACCOUNT_PRDT_CD",
        ],
    )
    def test_kis_config_missing_required_var_raises(self, missing_key: str) -> None:
        env = _paper_env()
        del env[missing_key]
        with pytest.raises(ConfigurationError, match=missing_key):
            KISConfig.from_env(env)

    def test_kis_config_blank_var_treated_as_missing(self) -> None:
        env = _paper_env()
        env["KIS_PAPER_APPKEY"] = "   "  # whitespace-only → missing
        with pytest.raises(ConfigurationError, match="KIS_PAPER_APPKEY"):
            KISConfig.from_env(env)


class TestKisConfigSecretMasking:
    """R10 / CLAUDE.md §8.3 — appkey/appsecret never in plaintext repr/str."""

    def test_kis_config_repr_does_not_expose_appsecret(self) -> None:
        cfg = KISConfig.from_env(_paper_env())
        rendered = repr(cfg)
        assert _SECRET_APPSECRET not in rendered

    def test_kis_config_str_does_not_expose_appsecret(self) -> None:
        cfg = KISConfig.from_env(_paper_env())
        assert _SECRET_APPSECRET not in str(cfg)

    def test_kis_config_repr_does_not_expose_full_appkey(self) -> None:
        cfg = KISConfig.from_env(_paper_env())
        rendered = repr(cfg)
        # Full appkey absent; only the masked 4-char prefix form is allowed.
        assert _SECRET_APPKEY not in rendered
        assert f"{_SECRET_APPKEY[:4]}***" in rendered

    def test_kis_config_repr_masks_appsecret_as_stars(self) -> None:
        cfg = KISConfig.from_env(_paper_env())
        assert "appsecret='***'" in repr(cfg)

    def test_kis_config_masked_appkey_property(self) -> None:
        cfg = KISConfig.from_env(_paper_env())
        assert cfg.masked_appkey == f"{_SECRET_APPKEY[:4]}***"
        assert _SECRET_APPKEY not in cfg.masked_appkey
