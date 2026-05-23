"""YAML asset-metadata loader — data-driven asset registry (Phase 1.1).

Reads ``config/assets.yaml`` and produces domain ``Asset`` value objects.
Phase 0 hardcoded asset metadata in ``composition._ASSET_FACTORIES``;
``composition.py`` itself predicted the graduation to a YAML lookup at
Phase 1 ("When Phase 1 adds multiple assets this graduates to a YAML
lookup"). This loader IS that graduation, and as of ADR 0021 §7.1 it is the
**single source of truth**: ``composition.asset_from_code`` resolves *every*
code (Phase 0 박제 9 종 포함) through this loader — the named accessors
(``kodex200()`` etc.) are thin convenience wrappers over it. A new asset is
declared as data, no code change required.

Strict, extra='forbid' pydantic — a typo in a YAML key surfaces as
``ValidationError`` rather than a silent default (CLAUDE.md §13.3). The
money-critical fields (``tick_size`` / ``listed_at``) pass through full
``Asset`` validation; the management script (``scripts/manage_strategies.py``)
additionally pykrx-cross-checks them on ``add`` to catch a wrong
code/name/market before it reaches this file.

YAML float → Decimal coerces via ``Decimal(str(value))`` (NOT the
``Decimal(float)`` path forbidden by CLAUDE.md §2.3).
"""
from __future__ import annotations

from datetime import date  # noqa: TC003 — pydantic resolves annotations at runtime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
)

# Default tick_size when omitted, by asset class. KR_ETF = 5 (KRX ETF 표준
# 최소 호가). KR_STOCK = 1 (placeholder — Asset.round_to_tick 가 가격대별
# helper 를 호출하므로 이 필드는 의미상 1원 placeholder, composition 의
# 하드코딩 팩토리와 동일한 ADR 0005 §3.3.1 근거).
_DEFAULT_TICK_BY_CLASS: dict[AssetClass, Decimal] = {
    AssetClass.KR_ETF: Decimal("5"),
    AssetClass.KR_STOCK: Decimal("1"),
}


class _StrictBase(BaseModel):
    """Strict, extra='forbid' base (mirrors yaml_strategy_config_loader)."""

    model_config = ConfigDict(extra="forbid", strict=False)


def _to_decimal(v: object) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("Cannot construct Decimal from bool")
    if isinstance(v, (int, str, float)):
        return Decimal(str(v))
    raise ValueError(f"Unsupported value type for Decimal: {type(v).__name__}")


class _AssetMetaEntry(_StrictBase):
    """Raw-YAML schema for one asset's metadata (validation only)."""

    name: str = Field(min_length=1, max_length=200)
    market: Market
    asset_class: AssetClass
    exchange: Exchange = Exchange.KRX
    currency: Currency = Currency.KRW
    # None → default by asset_class (see _DEFAULT_TICK_BY_CLASS).
    tick_size: Decimal | None = None
    lot_size: Decimal = Decimal("1")
    listed_at: date
    delisted_at: date | None = None

    @field_validator("tick_size", "lot_size", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> object:
        if v is None:
            return None
        return _to_decimal(v)


class _RootSchema(_StrictBase):
    version: Literal["1.0"]
    # Empty map allowed — a fresh assets.yaml has no user-added assets yet,
    # and composition falls back to it only on a hardcoded-registry miss.
    assets: dict[str, _AssetMetaEntry] = Field(default_factory=dict)


def load_asset_registry(path: Path | str) -> dict[str, Asset]:
    """Parse ``config/assets.yaml`` into ``{code: Asset}``.

    Returns an empty dict when the file does not exist or has no assets —
    this keeps ``asset_from_code`` regression-safe (a missing file behaves
    exactly like the Phase 0 hardcoded-only registry).

    Raises:
        ValueError: YAML root is not a mapping.
        ValidationError: schema violations (unknown keys, bad enum values,
            missing required fields, out-of-range sizes).
    """
    p = Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"YAML root must be a mapping, got {type(raw).__name__}"
        )
    schema = _RootSchema.model_validate(raw)
    return {code: _to_asset(code, entry) for code, entry in schema.assets.items()}


def _to_asset(code: str, entry: _AssetMetaEntry) -> Asset:
    tick = (
        entry.tick_size
        if entry.tick_size is not None
        else _DEFAULT_TICK_BY_CLASS[entry.asset_class]
    )
    return Asset(
        code=code,
        exchange=entry.exchange,
        market=entry.market,
        asset_class=entry.asset_class,
        currency=entry.currency,
        name=entry.name,
        tick_size=tick,
        lot_size=entry.lot_size,
        listed_at=entry.listed_at,
        delisted_at=entry.delisted_at,
    )
