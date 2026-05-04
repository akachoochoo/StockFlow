"""YAML strategy config loader — multi-asset (Phase 0.7.1 박제).

Reads ``config/strategies-*.yaml`` and produces ``AssetStrategyBundle``
instances ready for composition. Phase 0.7.1 박제 — 모든 자산 동일 정책
강제 (ADR 0003 §7.3). Composition root 가 모든 enabled bundle 사용.

The loader validates with strict, extra='forbid' pydantic schemas — typos
in YAML keys surface as ``ValidationError`` rather than silent defaults
(CLAUDE.md §13.3 "친절한 추가 금지" applies to config too).

YAML float → Decimal: pyyaml returns ``float`` for unquoted decimals
(e.g. ``profit_target_pct: 10.0``). We coerce via ``Decimal(str(value))``
— NOT the direct ``Decimal(float)`` path forbidden by CLAUDE.md §2.3 —
because the str round-trip preserves the human-readable representation
(``Decimal("10.0")``) without IEEE-754 precision artefacts.

Asset metadata note: YAML carries asset code + name + strategy parameters
only. The full ``Asset`` value object (exchange / asset_class / currency /
tick / lot) is built by the composition root, where these KRX-specific
fields stay hardcoded until Phase 1+ multi-exchange arrives.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.domain.models import AllocationPolicy, Currency, DomainModel, Money
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.domain.strategies.profit_target import SellStrategyConfig


# ---------------------------------------------------------------------------
# Internal raw-YAML pydantic schemas (validation only; never returned)
# ---------------------------------------------------------------------------
class _StrictBase(BaseModel):
    """Strict, extra='forbid' base for raw YAML schema models.

    Disabling ``strict`` mode (the field-level coerce-from-int default) is
    intentional — YAML often emits ``int`` for whole numbers and ``float``
    for decimals, and we want a human-readable config to load even when
    the user wrote ``max_split_count: 7`` (int) where pydantic strict=True
    would otherwise insist on ``Decimal`` literals.
    """

    model_config = ConfigDict(extra="forbid", strict=False)


def _to_decimal(v: object) -> Decimal:
    """YAML-safe Decimal coerce.

    Accepts: ``Decimal``, ``int``, ``str``, ``float``. Floats round-trip
    via ``str(...)`` to avoid IEEE-754 surprises (CLAUDE.md §2.3). Bools
    are rejected.
    """
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("Cannot construct Decimal from bool")
    if isinstance(v, (int, str, float)):
        return Decimal(str(v))
    raise ValueError(
        f"Unsupported value type for Decimal: {type(v).__name__}"
    )


class _BuyParams(_StrictBase):
    drop_threshold_pct: Decimal = Field(gt=Decimal(0))
    max_split_count: int = Field(ge=1, le=7)
    # Phase 0.5 single-currency: per_split_amount is a KRW integer.
    per_split_amount: int = Field(gt=0)
    max_split_per_day: int = Field(default=1, ge=1)
    max_loss_pct: Decimal | None = None

    @field_validator("drop_threshold_pct", "max_loss_pct", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> object:
        if v is None:
            return None
        return _to_decimal(v)


class _SellParams(_StrictBase):
    profit_target_pct: Decimal = Field(gt=Decimal(0), lt=Decimal(100))
    max_sells_per_day: int = Field(default=7, ge=1, le=7)

    @field_validator("profit_target_pct", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _to_decimal(v)


class _ReentryParams(_StrictBase):
    """Union of parameters across reentry policies.

    Phase 0.5 ships two policies (ADR §4): ``moving_average`` (window /
    ma_type) and ``hybrid`` (cooldown_days). Only the relevant fields for
    the chosen policy are populated downstream — the schema accepts both
    sets but the consistency validator on ``_AssetEntry`` rejects misaligned
    combinations (e.g. hybrid without cooldown_days).
    """

    cooldown_days: int | None = Field(default=None, ge=0, le=365)
    window: int | None = Field(default=None, ge=1, le=500)
    ma_type: str = "sma"


class _AssetEntry(_StrictBase):
    name: str = Field(min_length=1)
    enabled: bool = True
    buy_strategy: Literal["price_drop"]
    buy_parameters: _BuyParams
    sell_strategy: Literal["profit_target"]
    sell_parameters: _SellParams
    reentry_strategy: Literal["moving_average", "hybrid"]
    reentry_parameters: _ReentryParams

    @model_validator(mode="after")
    def _check_reentry_consistency(self) -> _AssetEntry:
        # ADR §6.2: required parameters must match the chosen policy.
        if (
            self.reentry_strategy == "hybrid"
            and self.reentry_parameters.cooldown_days is None
        ):
            raise ValueError(
                "reentry_strategy 'hybrid' requires "
                "reentry_parameters.cooldown_days"
            )
        if (
            self.reentry_strategy == "moving_average"
            and self.reentry_parameters.window is None
        ):
            raise ValueError(
                "reentry_strategy 'moving_average' requires "
                "reentry_parameters.window"
            )
        return self


class _RootSchema(_StrictBase):
    version: Literal["0.5"]
    # ADR 0003 §16.1 — Phase 0.7.2 자본 배분 정책. default EQUAL 시 Phase
    # 0.7.1 동작 그대로 (회귀 invariant). 기존 yaml 들 명시 없이 호환.
    allocation_policy: AllocationPolicy = AllocationPolicy.EQUAL
    assets: dict[str, _AssetEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_policy_uniformity(self) -> _RootSchema:
        """Phase 0.7.1 strict: all enabled assets must share the same policy.

        ADR 0003 §7.3 — 정책 동일성 강제. ``name`` and ``enabled`` may differ
        per asset; every other field must be identical across all enabled
        assets. Comparison uses ``model_dump()`` dict equality so Decimal /
        int / str all compare correctly.

        Raises ValueError naming the first mismatch asset and differing field
        to aid debugging (e.g. "asset '214980' differs from '069500':
        buy_parameters differ").
        Skips validation when ≤ 1 enabled asset exists (no pair to compare).
        """
        enabled_items = [
            (code, entry)
            for code, entry in self.assets.items()
            if entry.enabled
        ]
        if len(enabled_items) <= 1:
            return self

        ref_code, ref_entry = enabled_items[0]
        ref_dump = ref_entry.model_dump()

        policy_fields = (
            "buy_strategy",
            "buy_parameters",
            "sell_strategy",
            "sell_parameters",
            "reentry_strategy",
            "reentry_parameters",
        )

        for code, entry in enabled_items[1:]:
            entry_dump = entry.model_dump()
            for field_name in policy_fields:
                if entry_dump[field_name] != ref_dump[field_name]:
                    raise ValueError(
                        f"Phase 0.7.1 strict (ADR 0003 §7.3): asset "
                        f"{code!r} differs from {ref_code!r}: "
                        f"{field_name} differ. "
                        f"All enabled assets must share the same policy."
                    )

        return self


# ---------------------------------------------------------------------------
# Public output model
# ---------------------------------------------------------------------------
class AssetStrategyBundle(DomainModel):
    """Phase 0.5 strategy bundle for one asset (ADR §6.2).

    Holds the asset code/name plus concrete domain config models. The
    composition root pairs this with a full ``Asset`` value object (carrying
    exchange / asset_class / currency / tick / lot metadata that Phase 0.5
    hardcodes in code rather than YAML) and constructs the actual strategy
    instances by passing ``reentry_parameters`` to ``create_reentry_strategy``.
    """

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool
    buy_strategy_name: str
    buy_config: SplitStrategyConfig
    sell_strategy_name: str
    sell_config: SellStrategyConfig
    reentry_strategy_name: str
    reentry_parameters: dict[str, Any]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def load_strategy_config(path: Path | str) -> dict[str, AssetStrategyBundle]:
    """Parse a strategies YAML file (ADR 0002 §6.2 / ADR 0003 §7.3).

    Returns a dict keyed by asset code. Phase 0.7.1 — composition root 가
    모든 enabled bundle 사용. 정책 동일성은 _RootSchema 가 검증.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ValueError: YAML is empty or otherwise unparseable at the root.
        ValidationError: schema violations (missing keys, wrong types,
            unknown strategy names, out-of-range parameters, misaligned
            reentry params, extra keys, or policy non-uniformity across
            enabled assets — ADR 0003 §7.3).
    """
    schema = _parse_root_schema(path)
    return {
        code: _to_bundle(code, entry)
        for code, entry in schema.assets.items()
    }


def load_allocation_policy(path: Path | str) -> AllocationPolicy:
    """Parse only the root-level ``allocation_policy`` (ADR 0003 §16.1).

    Phase 0.7.2 박제 — Composition root 가 자본 배분 정책에 따라 per-asset
    budget 산정. ``load_strategy_config`` 와 별도 함수로 노출 (시그니처
    보존, callers regression zero).

    Default: ``AllocationPolicy.EQUAL`` (yaml 에 명시 없을 시) — Phase
    0.7.1 회귀 invariant 보존.

    Raises:
        FileNotFoundError / ValueError / ValidationError: ``load_strategy_config``
            과 동일.
    """
    return _parse_root_schema(path).allocation_policy


def _parse_root_schema(path: Path | str) -> _RootSchema:
    """Shared YAML parse + ``_RootSchema`` validation."""
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if raw is None:
        raise ValueError(f"YAML file {path} is empty")
    if not isinstance(raw, dict):
        raise ValueError(
            f"YAML root must be a mapping, got {type(raw).__name__}"
        )
    return _RootSchema.model_validate(raw)


def _to_bundle(code: str, entry: _AssetEntry) -> AssetStrategyBundle:
    bp = entry.buy_parameters
    sp = entry.sell_parameters
    rp = entry.reentry_parameters

    buy_config = SplitStrategyConfig(
        drop_threshold_pct=bp.drop_threshold_pct,
        max_split_count=bp.max_split_count,
        per_split_amount=Money(
            amount=Decimal(bp.per_split_amount),
            currency=Currency.KRW,
        ),
        max_split_per_day=bp.max_split_per_day,
        max_loss_pct=bp.max_loss_pct,
    )

    sell_config = SellStrategyConfig(
        profit_target_pct=sp.profit_target_pct,
        max_sells_per_day=sp.max_sells_per_day,
    )

    # Pack only the relevant params for the chosen reentry strategy. The
    # consistency validator on _AssetEntry guarantees the required fields
    # are present, so the assertions below never fire in practice.
    reentry_parameters: dict[str, Any] = {}
    if entry.reentry_strategy == "hybrid":
        assert rp.cooldown_days is not None
        reentry_parameters["cooldown_days"] = rp.cooldown_days
    else:  # "moving_average"
        assert rp.window is not None
        reentry_parameters["window"] = rp.window
        reentry_parameters["ma_type"] = rp.ma_type

    return AssetStrategyBundle(
        code=code,
        name=entry.name,
        enabled=entry.enabled,
        buy_strategy_name=entry.buy_strategy,
        buy_config=buy_config,
        sell_strategy_name=entry.sell_strategy,
        sell_config=sell_config,
        reentry_strategy_name=entry.reentry_strategy,
        reentry_parameters=reentry_parameters,
    )
