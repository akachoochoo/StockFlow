"""Loader tests for per-asset parameter differentiation (Phase 1.1 Case A).

``allow_per_asset_params`` relaxes the §7.3 uniformity gate to TYPE-only:
strategy *types* must stay uniform (single broker/settler slot_model), but
per-asset *parameters* (buy/sell/reentry) may differ.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.infrastructure.yaml_strategy_config_loader import load_strategy_config

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "strategies.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _two_assets(
    *,
    flag: bool,
    a_drop: str = "5.0",
    b_drop: str = "5.0",
    a_profit: str = "10.0",
    b_profit: str = "10.0",
    a_cooldown: int = 60,
    b_cooldown: int = 60,
    a_per_split: int = 5000000,
    b_per_split: int = 5000000,
    b_buy_strategy: str = "price_drop",
) -> str:
    flag_line = "allow_per_asset_params: true\n" if flag else ""
    return f"""\
version: "0.5"
{flag_line}assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters:
      drop_threshold_pct: {a_drop}
      max_split_count: 7
      per_split_amount: {a_per_split}
      max_split_per_day: 1
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: {a_profit}
      max_sells_per_day: 7
    reentry_strategy: "hybrid"
    reentry_parameters:
      cooldown_days: {a_cooldown}
  "132030":
    name: "KODEX 골드선물(H)"
    enabled: true
    buy_strategy: "{b_buy_strategy}"
    buy_parameters:
      drop_threshold_pct: {b_drop}
      max_split_count: 7
      per_split_amount: {b_per_split}
      max_split_per_day: 1
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: {b_profit}
      max_sells_per_day: 7
    reentry_strategy: "hybrid"
    reentry_parameters:
      cooldown_days: {b_cooldown}
"""


def test_param_diff_rejected_when_flag_off(tmp_path: Path) -> None:
    # Default strict — different drop → reject (Phase 0.7.1 regression invariant).
    body = _two_assets(flag=False, a_drop="5.0", b_drop="7.0")
    with pytest.raises(ValueError, match="differ"):
        load_strategy_config(_write(tmp_path, body))


def test_buy_param_diff_allowed_when_flag_on(tmp_path: Path) -> None:
    body = _two_assets(
        flag=True, a_drop="5.0", b_drop="7.0",
        a_per_split=5000000, b_per_split=2000000,
    )
    bundles = load_strategy_config(_write(tmp_path, body))
    assert bundles["069500"].buy_config.drop_threshold_pct == Decimal("5.0")
    assert bundles["132030"].buy_config.drop_threshold_pct == Decimal("7.0")
    assert bundles["069500"].buy_config.per_split_amount.amount == Decimal(5000000)
    assert bundles["132030"].buy_config.per_split_amount.amount == Decimal(2000000)


def test_sell_and_reentry_param_diff_allowed_when_flag_on(tmp_path: Path) -> None:
    body = _two_assets(
        flag=True, a_profit="15.0", b_profit="20.0", a_cooldown=60, b_cooldown=30,
    )
    bundles = load_strategy_config(_write(tmp_path, body))
    assert str(bundles["069500"].sell_config.profit_target_pct) == "15.0"
    assert str(bundles["132030"].sell_config.profit_target_pct) == "20.0"
    assert bundles["069500"].reentry_parameters["cooldown_days"] == 60
    assert bundles["132030"].reentry_parameters["cooldown_days"] == 30


def test_strategy_type_diff_rejected_even_with_flag(tmp_path: Path) -> None:
    # TYPE uniformity is structural (single slot_model) — always enforced.
    body = _two_assets(flag=True, b_buy_strategy="support_level")
    with pytest.raises(ValueError, match="TYPE"):
        load_strategy_config(_write(tmp_path, body))


def test_uniform_config_loads_regardless_of_flag(tmp_path: Path) -> None:
    # All-identical params load whether or not the flag is set (no diff).
    for flag in (False, True):
        bundles = load_strategy_config(_write(tmp_path, _two_assets(flag=flag)))
        assert len(bundles) == 2
