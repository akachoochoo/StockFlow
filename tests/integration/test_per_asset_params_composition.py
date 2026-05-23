"""Composition tests for per-asset parameters (Phase 1.1 Case A / Tier 2).

Verifies build_paper_components (and, in test_live_components-adjacent coverage,
build_live_components) thread per-asset buy/sell/reentry params into one
AssetContext per asset, while None preserves the broadcast.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

import pytest

from src.cli import composition
from src.domain.models import Currency, Money
from src.domain.strategies.price_drop import SplitStrategyConfig
from src.domain.strategies.profit_target import SellStrategyConfig
from src.use_cases.asset_context import AssetPolicyOverride

DAY = date(2026, 5, 22)


def _buy(*, drop: str, per_split: int) -> SplitStrategyConfig:
    return SplitStrategyConfig(
        drop_threshold_pct=Decimal(drop),
        max_split_count=7,
        per_split_amount=Money(amount=Decimal(per_split), currency=Currency.KRW),
        max_split_per_day=1,
    )


def _sell(profit: str) -> SellStrategyConfig:
    return SellStrategyConfig(
        profit_target_pct=Decimal(profit), max_sells_per_day=7
    )


def _overrides() -> dict[str, AssetPolicyOverride]:
    return {
        "069500": AssetPolicyOverride(
            buy_config=_buy(drop="5", per_split=3000000),
            sell_config=_sell("15"),
            reentry_parameters={"cooldown_days": 60},
        ),
        "132030": AssetPolicyOverride(
            buy_config=_buy(drop="7", per_split=1000000),
            sell_config=_sell("20"),
            reentry_parameters={"cooldown_days": 30},
        ),
    }


def test_paper_per_asset_overrides_applied(tmp_path) -> None:
    a = composition.asset_from_code("069500")
    b = composition.asset_from_code("132030")
    components = composition.build_paper_components(
        assets=[a, b],
        bars_by_asset={},
        db_path=tmp_path / "p.db",
        initial_capital=Money(amount=Decimal(10000000), currency=Currency.KRW),
        strategy_config=_buy(drop="5", per_split=2000000),
        initial_clock=composition.utc_for(DAY, time(9, 0)),
        per_asset_overrides=_overrides(),
    )
    try:
        ctx = {c.asset.code: c for c in components.orchestrator._asset_contexts}
        assert ctx["069500"].config.drop_threshold_pct == Decimal("5")
        assert ctx["132030"].config.drop_threshold_pct == Decimal("7")
        assert ctx["069500"].config.per_split_amount.amount == Decimal(3000000)
        assert ctx["132030"].config.per_split_amount.amount == Decimal(1000000)
        assert ctx["069500"].sell_config.profit_target_pct == Decimal("15")
        assert ctx["132030"].sell_config.profit_target_pct == Decimal("20")
        # distinct strategy instances (each carries its own reentry params)
        assert ctx["069500"].strategy is not ctx["132030"].strategy
    finally:
        components.close()


def test_paper_none_overrides_broadcasts(tmp_path) -> None:
    a = composition.asset_from_code("069500")
    b = composition.asset_from_code("132030")
    shared = _buy(drop="5", per_split=2000000)
    components = composition.build_paper_components(
        assets=[a, b],
        bars_by_asset={},
        db_path=tmp_path / "p.db",
        initial_capital=Money(amount=Decimal(10000000), currency=Currency.KRW),
        strategy_config=shared,
        initial_clock=composition.utc_for(DAY, time(9, 0)),
    )
    try:
        for c in components.orchestrator._asset_contexts:
            assert c.config is shared  # broadcast: same config object
    finally:
        components.close()


def _yaml_two(tmp_path, *, flag: bool, b_drop: str) -> object:
    from pathlib import Path

    flag_line = "allow_per_asset_params: true\n" if flag else ""
    body = f"""\
version: "0.5"
{flag_line}assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters: {{drop_threshold_pct: 5.0, max_split_count: 7, per_split_amount: 2000000, max_split_per_day: 1}}
    sell_strategy: "profit_target"
    sell_parameters: {{profit_target_pct: 15.0, max_sells_per_day: 7}}
    reentry_strategy: "hybrid"
    reentry_parameters: {{cooldown_days: 60}}
  "132030":
    name: "KODEX 골드선물(H)"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters: {{drop_threshold_pct: {b_drop}, max_split_count: 7, per_split_amount: 2000000, max_split_per_day: 1}}
    sell_strategy: "profit_target"
    sell_parameters: {{profit_target_pct: 15.0, max_sells_per_day: 7}}
    reentry_strategy: "hybrid"
    reentry_parameters: {{cooldown_days: 60}}
"""
    p = Path(tmp_path) / "s.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_resolve_per_asset_overrides_none_for_no_config() -> None:
    from src.cli.main import _resolve_per_asset_overrides

    assert _resolve_per_asset_overrides(None) is None


def test_resolve_per_asset_overrides_none_when_uniform(tmp_path) -> None:
    from src.cli.main import _resolve_per_asset_overrides

    # identical params (b_drop == a_drop) → broadcast (None).
    assert _resolve_per_asset_overrides(_yaml_two(tmp_path, flag=False, b_drop="5.0")) is None


def test_resolve_per_asset_overrides_dict_when_heterogeneous(tmp_path) -> None:
    from src.cli.main import _resolve_per_asset_overrides

    ov = _resolve_per_asset_overrides(_yaml_two(tmp_path, flag=True, b_drop="7.0"))
    assert ov is not None
    assert set(ov) == {"069500", "132030"}
    assert ov["069500"].buy_config.drop_threshold_pct == Decimal("5.0")
    assert ov["132030"].buy_config.drop_threshold_pct == Decimal("7.0")


def test_paper_overrides_key_mismatch_raises(tmp_path) -> None:
    a = composition.asset_from_code("069500")
    b = composition.asset_from_code("132030")
    bad = {"069500": _overrides()["069500"]}  # missing 132030
    with pytest.raises(ValueError, match="match asset codes"):
        composition.build_paper_components(
            assets=[a, b],
            bars_by_asset={},
            db_path=tmp_path / "p.db",
            initial_capital=Money(amount=Decimal(10000000), currency=Currency.KRW),
            strategy_config=_buy(drop="5", per_split=2000000),
            initial_clock=composition.utc_for(DAY, time(9, 0)),
            per_asset_overrides=bad,
        )
