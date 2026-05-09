"""Unit tests for src.application.reporting.strategy_info (Phase 0.10.y §15.5)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.reporting.strategy_info import (
    StrategyInfo,
    from_strategy_bundle,
)
from src.domain.models import Currency, Money
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.domain.strategies.profit_target import SellStrategyConfig
from src.infrastructure.yaml_strategy_config_loader import AssetStrategyBundle


def _bundle(
    *,
    code: str = "005930",
    name: str = "삼성전자",
    drop_pct: str = "5.0",
    max_split: int = 7,
    per_split: int = 5_000_000,
    max_split_per_day: int = 1,
    target_pct: str = "10.0",
    max_sells_per_day: int = 7,
    reentry_strategy: str = "hybrid",
    reentry_parameters: dict | None = None,
) -> AssetStrategyBundle:
    return AssetStrategyBundle(
        code=code,
        name=name,
        enabled=True,
        buy_strategy_name="price_drop",
        buy_config=SplitStrategyConfig(
            drop_threshold_pct=Decimal(drop_pct),
            max_split_count=max_split,
            per_split_amount=Money(
                amount=Decimal(per_split), currency=Currency.KRW,
            ),
            max_split_per_day=max_split_per_day,
        ),
        sell_strategy_name="profit_target",
        sell_config=SellStrategyConfig(
            profit_target_pct=Decimal(target_pct),
            max_sells_per_day=max_sells_per_day,
        ),
        reentry_strategy_name=reentry_strategy,
        reentry_parameters=reentry_parameters or {"cooldown_days": 60},
    )


class TestFromBundle:
    def test_emits_six_field_groups(self):
        info = from_strategy_bundle(
            _bundle(), "config/strategies-0.9.2.yaml",
        )
        assert info.buy_strategy_name == "price_drop"
        assert "drop_threshold_pct" in info.buy_parameters
        assert info.sell_strategy_name == "profit_target"
        assert "profit_target_pct" in info.sell_parameters
        assert info.reentry_strategy_name == "hybrid"
        assert "cooldown_days" in info.reentry_parameters
        assert info.config_source == "config/strategies-0.9.2.yaml"

    def test_buy_parameters_decimal_formatted(self):
        # AC: drop_threshold_pct=5.0 → "5.00%" (places=2, signed=False)
        info = from_strategy_bundle(_bundle(drop_pct="5.0"), "x.yaml")
        assert info.buy_parameters["drop_threshold_pct"] == "5.00%"
        # NOT Decimal repr
        assert "Decimal" not in info.buy_parameters["drop_threshold_pct"]

    def test_buy_parameters_money_formatted_krw(self):
        # AC: per_split_amount=5_000_000 KRW → "₩5,000,000"
        info = from_strategy_bundle(_bundle(), "x.yaml")
        assert info.buy_parameters["per_split_amount"] == "₩5,000,000"

    def test_sell_parameters_pct_formatted(self):
        info = from_strategy_bundle(
            _bundle(target_pct="10.0"), "x.yaml",
        )
        assert info.sell_parameters["profit_target_pct"] == "10.00%"
        assert info.sell_parameters["max_sells_per_day"] == "7"

    def test_reentry_hybrid_cooldown(self):
        info = from_strategy_bundle(
            _bundle(reentry_parameters={"cooldown_days": 60}), "x.yaml",
        )
        assert info.reentry_parameters == {"cooldown_days": "60"}

    def test_reentry_moving_average(self):
        info = from_strategy_bundle(
            _bundle(
                reentry_strategy="moving_average",
                reentry_parameters={"window": 20, "ma_type": "sma"},
            ),
            "x.yaml",
        )
        assert info.reentry_strategy_name == "moving_average"
        assert info.reentry_parameters["window"] == "20"
        assert info.reentry_parameters["ma_type"] == "sma"

    def test_factory_deterministic_equal(self):
        b = _bundle()
        a = from_strategy_bundle(b, "x.yaml")
        b2 = from_strategy_bundle(b, "x.yaml")
        assert a == b2

    def test_asset_codes_default_single(self):
        info = from_strategy_bundle(_bundle(code="005930"), "x.yaml")
        assert info.asset_codes == ("005930",)

    def test_asset_codes_from_mapping_sorted(self):
        info = from_strategy_bundle(
            _bundle(code="005930"),
            "x.yaml",
            asset_codes={
                "005930": object(),
                "005380": object(),
                "055550": object(),
            },
        )
        assert info.asset_codes == ("005380", "005930", "055550")

    def test_no_asset_uniformity_field(self):
        # Patch 1 — field NOT present (premature optionality avoided)
        info = from_strategy_bundle(_bundle(), "x.yaml")
        with pytest.raises(AttributeError):
            _ = info.asset_uniformity  # type: ignore[attr-defined]

    def test_pathlib_config_source_str(self):
        from pathlib import Path
        info = from_strategy_bundle(
            _bundle(), Path("config/strategies-0.9.2.yaml"),
        )
        assert info.config_source == "config/strategies-0.9.2.yaml"


class TestFactoryReadsDocumentedFieldSet:
    """Patch S2 — factory's bundle read-set is the frozen contract surface.

    Asserts the factory only reads the documented bundle attributes. If a
    Phase 1+ bundle field gets added (e.g. tax_config), this test fails
    until the docstring is consciously updated.
    """

    def test_only_six_documented_fields_read(self):
        from unittest.mock import MagicMock

        bundle = _bundle()
        # Wrap with a tracking proxy that records attribute access
        class _AttrTracker:
            def __init__(self, target):
                object.__setattr__(self, "_target", target)
                object.__setattr__(self, "_accessed", set())

            def __getattribute__(self, name):
                if name in ("_target", "_accessed"):
                    return object.__getattribute__(self, name)
                self._accessed.add(name)
                return getattr(self._target, name)

        tracker = _AttrTracker(bundle)
        from_strategy_bundle(tracker, "x.yaml")  # type: ignore[arg-type]
        # Documented contract surface (S2)
        documented = {
            "buy_strategy_name",
            "buy_config",
            "sell_strategy_name",
            "sell_config",
            "reentry_strategy_name",
            "reentry_parameters",
        }
        # Permitted extras for asset_codes default: bundle.code
        permitted = documented | {"code"}
        accessed = tracker._accessed
        unexpected = accessed - permitted
        assert not unexpected, (
            f"factory accessed undocumented bundle fields: {unexpected}. "
            f"Update docstring + this test if the new fields belong on the "
            f"frozen contract surface."
        )


class TestStrategyInfoFrozen:
    def test_frozen_dataclass(self):
        info = from_strategy_bundle(_bundle(), "x.yaml")
        with pytest.raises(Exception):  # noqa: B017
            info.buy_strategy_name = "other"  # type: ignore[misc]

    def test_layer_placement(self):
        # AC10 — StrategyInfo lives in application layer, NOT domain
        import src.application.reporting.strategy_info as mod
        assert mod.__name__ == "src.application.reporting.strategy_info"
        # Class import via factory result confirms accessibility
        info = from_strategy_bundle(_bundle(), "x.yaml")
        assert isinstance(info, StrategyInfo)
