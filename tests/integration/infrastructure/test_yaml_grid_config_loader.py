"""Tests for src/infrastructure/yaml_grid_config_loader.py (ADR 0022 §11 D12).

Grid config = strategies.yaml 와 분리된 DGT 전용 config. grid_parameters →
GridConfig 매핑이 GridConfig 를 single source of truth 로 재사용하는지(미지 키
거부 / Decimal str-coerce / 범위·Literal·required 위임) 잠근다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from src.domain.strategies.grid import GridConfig
from src.infrastructure.yaml_grid_config_loader import (
    GridAssetConfig,
    load_grid_config,
)

if TYPE_CHECKING:
    from pathlib import Path

_MINIMAL = """\
version: "1.0"
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    grid_parameters:
      grid_count: 11
      fallback_k: 0.05
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "grid.yaml"
    p.write_text(body, encoding="utf-8")
    return p


class TestLoadHappyPath:
    def test_minimal_loads_with_defaults(self, tmp_path):
        result = load_grid_config(_write(tmp_path, _MINIMAL))
        assert set(result) == {"069500"}
        ac = result["069500"]
        assert isinstance(ac, GridAssetConfig)
        assert ac.name == "KODEX 200"
        assert ac.enabled is True
        assert ac.config.grid_count == 11
        assert ac.config.fallback_k == Decimal("0.05")
        # optional fields fall back to GridConfig defaults (drift-free)
        assert ac.config.volatility_measure == "adr"
        assert ac.config.k_min == GridConfig.model_fields["k_min"].default

    def test_decimal_fields_str_coerced_exact(self, tmp_path):
        body = _MINIMAL + """      k_min: 0.005
      k_max: 0.05
      multiplier: 1.0
      volume_gate_multiplier: 1.5
"""
        ac = load_grid_config(_write(tmp_path, body))["069500"]
        assert ac.config.k_min == Decimal("0.005")
        assert ac.config.k_max == Decimal("0.05")
        assert ac.config.multiplier == Decimal("1.0")
        # no IEEE-754 drift (string round-trip)
        assert str(ac.config.k_min) == "0.005"

    def test_literals_and_bools(self, tmp_path):
        body = _MINIMAL + """      volatility_measure: atr
      rebalance_mode: on_breach
      volume_gate: true
"""
        ac = load_grid_config(_write(tmp_path, body))["069500"]
        assert ac.config.volatility_measure == "atr"
        assert ac.config.rebalance_mode == "on_breach"
        assert ac.config.volume_gate is True

    def test_multi_asset_order_preserved(self, tmp_path):
        body = """\
version: "1.0"
assets:
  "069500":
    name: "KODEX 200"
    grid_parameters: {grid_count: 11, fallback_k: 0.05}
  "132030":
    name: "KODEX 골드"
    enabled: false
    grid_parameters: {grid_count: 9, fallback_k: 0.04}
"""
        result = load_grid_config(_write(tmp_path, body))
        assert list(result) == ["069500", "132030"]
        assert result["069500"].enabled is True  # default
        assert result["132030"].enabled is False
        assert result["132030"].config.grid_count == 9


class TestValidation:
    def test_unknown_grid_parameter_rejected(self, tmp_path):
        body = _MINIMAL + "      bogus: 1\n"
        with pytest.raises(ValueError, match="미지 키"):
            load_grid_config(_write(tmp_path, body))

    def test_missing_required_grid_count(self, tmp_path):
        body = """\
version: "1.0"
assets:
  "069500":
    name: "KODEX 200"
    grid_parameters: {fallback_k: 0.05}
"""
        with pytest.raises(ValidationError):
            load_grid_config(_write(tmp_path, body))

    def test_out_of_range_grid_count(self, tmp_path):
        body = """\
version: "1.0"
assets:
  "069500":
    name: "KODEX 200"
    grid_parameters: {grid_count: 1, fallback_k: 0.05}
"""
        with pytest.raises(ValidationError):
            load_grid_config(_write(tmp_path, body))

    def test_bad_literal_rejected(self, tmp_path):
        body = _MINIMAL + "      volatility_measure: xyz\n"
        with pytest.raises(ValidationError):
            load_grid_config(_write(tmp_path, body))

    def test_extra_entry_key_rejected(self, tmp_path):
        body = """\
version: "1.0"
assets:
  "069500":
    name: "KODEX 200"
    bogus_field: 1
    grid_parameters: {grid_count: 11, fallback_k: 0.05}
"""
        with pytest.raises(ValidationError):
            load_grid_config(_write(tmp_path, body))

    def test_empty_assets_rejected(self, tmp_path):
        with pytest.raises(ValidationError):
            load_grid_config(_write(tmp_path, 'version: "1.0"\nassets: {}\n'))

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_grid_config(tmp_path / "nope.yaml")

    def test_empty_yaml_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="empty"):
            load_grid_config(_write(tmp_path, ""))
