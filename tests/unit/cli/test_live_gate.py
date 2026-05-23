"""Unit tests for src.cli.live_gate (Phase 1.1 Stage 8-3 / M4 arming gate).

The arming gate is the last guard before a real-money order. These tests pin
the five per-run AND conditions, the capital-tier cap, and that the
reconciliation condition uses the in-process result (not ambient state).
"""
from __future__ import annotations

from typing import Any

import pytest

from src.cli.live_gate import (
    ARM_LIVE_ENV,
    CapitalTier,
    LiveArmingError,
    LiveArmingToken,
    assert_armed_for_live,
    build_arming_token,
)
from src.domain.exceptions import ClockSkewError
from src.use_cases.reconciliation import ReconciliationResult


def _matched() -> ReconciliationResult:
    return ReconciliationResult(matched=True, mismatches=[])


def _armed_kwargs(**overrides: Any) -> dict[str, Any]:
    """All-valid arming inputs; override one to test a single unmet condition."""
    base: dict[str, Any] = {
        "intended_tier": CapitalTier.TIER_200,
        "token": LiveArmingToken(tier_cap=CapitalTier.TIER_200, env_confirmed=True),
        "recon": _matched(),
        "halt_active": False,
        "ntp_synced": True,
    }
    base.update(overrides)
    return base


def test_arming_passes_when_all_conditions_met() -> None:
    # Returns None (no raise) when fully armed.
    assert assert_armed_for_live(**_armed_kwargs()) is None


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"halt_active": True}, LiveArmingError),
        ({"ntp_synced": False}, ClockSkewError),
        ({"recon": ReconciliationResult(matched=False, mismatches=[])}, LiveArmingError),
        ({"token": None}, LiveArmingError),
        (
            {"token": LiveArmingToken(tier_cap=CapitalTier.TIER_200, env_confirmed=False)},
            LiveArmingError,
        ),
        ({"intended_tier": CapitalTier.TIER_300}, LiveArmingError),  # 300 > cap 200
    ],
)
def test_arming_refuses_when_d16_condition_unmet(
    override: dict[str, Any], expected: type[Exception]
) -> None:
    with pytest.raises(expected):
        assert_armed_for_live(**_armed_kwargs(**override))


def test_capital_tier_cap_enforced() -> None:
    # intended within cap → armed; intended above cap → refused.
    assert (
        assert_armed_for_live(
            **_armed_kwargs(
                intended_tier=CapitalTier.TIER_200,
                token=LiveArmingToken(tier_cap=CapitalTier.TIER_300, env_confirmed=True),
            )
        )
        is None
    )
    with pytest.raises(LiveArmingError):
        assert_armed_for_live(
            **_armed_kwargs(
                intended_tier=CapitalTier.TIER_500,
                token=LiveArmingToken(tier_cap=CapitalTier.TIER_300, env_confirmed=True),
            )
        )


def test_arming_recon_condition_uses_in_process_result() -> None:
    # The matched=True in-process result arms; matched=False refuses. The gate
    # reads only the passed ReconciliationResult — no filesystem/sentinel.
    assert assert_armed_for_live(**_armed_kwargs(recon=_matched())) is None
    with pytest.raises(LiveArmingError):
        assert_armed_for_live(
            **_armed_kwargs(recon=ReconciliationResult(matched=False, mismatches=[]))
        )


def test_ntp_unsynced_raises_clock_skew() -> None:
    with pytest.raises(ClockSkewError):
        assert_armed_for_live(**_armed_kwargs(ntp_synced=False))


def test_build_arming_token_none_when_no_cli_flag() -> None:
    assert build_arming_token(None, env={ARM_LIVE_ENV: "TIER_200"}) is None


def test_build_arming_token_requires_env_double_confirm() -> None:
    # CLI flag + matching env → confirmed.
    tok = build_arming_token(CapitalTier.TIER_200, env={ARM_LIVE_ENV: "TIER_200"})
    assert tok is not None and tok.env_confirmed is True
    assert tok.tier_cap is CapitalTier.TIER_200

    # CLI flag but env missing → not confirmed (stray flag cannot arm).
    tok_missing = build_arming_token(CapitalTier.TIER_200, env={})
    assert tok_missing is not None and tok_missing.env_confirmed is False

    # CLI flag but env names a different tier → not confirmed.
    tok_mismatch = build_arming_token(
        CapitalTier.TIER_200, env={ARM_LIVE_ENV: "TIER_500"}
    )
    assert tok_mismatch is not None and tok_mismatch.env_confirmed is False


def test_build_token_then_gate_end_to_end_refuses_without_env() -> None:
    # A --arm-live flag with NO env confirm must not arm (double-gate).
    token = build_arming_token(CapitalTier.TIER_200, env={})
    with pytest.raises(LiveArmingError):
        assert_armed_for_live(**_armed_kwargs(token=token))


def test_capital_tier_krw_values() -> None:
    from decimal import Decimal

    assert CapitalTier.TIER_200.krw == Decimal("2000000")
    assert CapitalTier.TIER_300.krw == Decimal("3000000")
    assert CapitalTier.TIER_500.krw == Decimal("5000000")
