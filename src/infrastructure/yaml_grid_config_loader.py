"""Grid (DGT) config loader — ``config/grid-*.yaml`` → per-asset ``GridConfig``.

ADR 0022 §11 D11/D12. DGT 는 strategies.yaml(``_AssetEntry``)와 **물리적으로
분리된 전용 config** 로 운용한다(별도 파일 채택 — split 로더 0변경 + live 가
grid config 를 애초에 받지 않아 G5 차단이 구조적). ``grid-backtest --config`` 가
이 로더를 쓴다(증분 ③).

핵심 설계 (D12): ``grid_parameters`` → ``GridConfig`` 매핑은 ``GridConfig`` 자체를
single source of truth 로 재사용한다 — 필드/제약을 **재선언하지 않고**
``GridConfig.model_fields`` 를 introspect 해 (a) 미지 키 거부, (b) Decimal 필드
str-coerce(CLAUDE.md §2.3), (c) 나머지는 ``GridConfig(...)`` 의 pydantic 검증
(ge/gt/Literal/required)에 위임. 스키마 drift zero (strategies 로더가 실제
로더를 재사용하는 규율과 동형).

YAML 형식::

    version: "1.0"
    assets:
      "069500":
        name: "KODEX 200"
        enabled: true
        grid_parameters:
          grid_count: 11
          fallback_k: 0.05
          volatility_measure: adr   # optional (GridConfig default 적용)
          ...
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.domain.strategies.grid import GridConfig


# ---------------------------------------------------------------------------
# Raw YAML structure (strict — entry-level typo protection)
# ---------------------------------------------------------------------------
class _GridAssetRaw(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    name: str = Field(min_length=1)
    enabled: bool = True
    grid_parameters: dict[str, Any]


class _GridRootRaw(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)

    version: str
    assets: dict[str, _GridAssetRaw] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Public output model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GridAssetConfig:
    """One asset's validated DGT config (code/name/enabled + ``GridConfig``)."""

    code: str
    name: str
    enabled: bool
    config: GridConfig


# ---------------------------------------------------------------------------
# grid_parameters → GridConfig (introspection-driven, zero re-declaration)
# ---------------------------------------------------------------------------
def _decimal_fields() -> frozenset[str]:
    """GridConfig fields whose annotation is ``Decimal`` (need str-coerce)."""
    return frozenset(
        name
        for name, field in GridConfig.model_fields.items()
        if field.annotation is Decimal
    )


def _to_decimal(value: object) -> Decimal:
    """YAML-safe Decimal coerce (str round-trip; bool rejected) — §2.3."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("Cannot construct Decimal from bool")
    if isinstance(value, (int, str, float)):
        return Decimal(str(value))
    raise ValueError(f"Unsupported value type for Decimal: {type(value).__name__}")


def _build_grid_config(code: str, params: dict[str, Any]) -> GridConfig:
    """Map a raw ``grid_parameters`` dict to a validated ``GridConfig``.

    Unknown keys are rejected here (GridConfig is strict/extra=forbid but its
    error would not name the asset); Decimal fields are str-coerced; everything
    else is validated by ``GridConfig`` itself (range/Literal/required).
    """
    allowed = set(GridConfig.model_fields)
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(
            f"grid_parameters[{code!r}] 미지 키: {sorted(unknown)} "
            f"(허용: {sorted(allowed)})"
        )
    decimals = _decimal_fields()
    coerced = {
        key: (_to_decimal(val) if key in decimals else val)
        for key, val in params.items()
    }
    return GridConfig(**coerced)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def load_grid_config(path: Path | str) -> dict[str, GridAssetConfig]:
    """Parse a grid config YAML → ``{code: GridAssetConfig}`` (ADR 0022 §11 D12).

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ValueError: empty/non-mapping YAML, or unknown ``grid_parameters`` key.
        ValidationError: structural (missing name/grid_parameters, extra entry
            key) or GridConfig violations (missing grid_count/fallback_k,
            out-of-range, bad Literal).
    """
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if raw is None:
        raise ValueError(f"YAML file {path} is empty")
    if not isinstance(raw, dict):
        raise ValueError(
            f"YAML root must be a mapping, got {type(raw).__name__}"
        )
    root = _GridRootRaw.model_validate(raw)
    return {
        code: GridAssetConfig(
            code=code,
            name=entry.name,
            enabled=entry.enabled,
            config=_build_grid_config(code, entry.grid_parameters),
        )
        for code, entry in root.assets.items()
    }
