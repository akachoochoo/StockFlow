"""Tests for src.infrastructure.yaml_strategy_config_loader (ADR 0002 §6.2).

Each scenario writes a YAML temp file via pytest's ``tmp_path`` fixture
and asserts the loader's output (or its raised error). Strict / extra='forbid'
schema means a typo or unknown key surfaces here, not silently downstream.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from src.domain.models import Currency
from src.infrastructure.yaml_strategy_config_loader import (
    AssetStrategyBundle,
    load_strategy_config,
)


def _write(tmp_path: Path, body: str) -> Path:
    """Write a YAML file inside tmp_path and return its Path."""
    path = tmp_path / "strategies.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_HYBRID_KODEX = """\
version: "0.5"
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters:
      drop_threshold_pct: 5.0
      max_split_count: 7
      per_split_amount: 10000000
      max_split_per_day: 1
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: 10.0
      max_sells_per_day: 7
    reentry_strategy: "hybrid"
    reentry_parameters:
      cooldown_days: 60
"""

_MOVING_AVERAGE_KODEX = """\
version: "0.5"
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters:
      drop_threshold_pct: 7.0
      max_split_count: 7
      per_split_amount: 10000000
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: 10.0
    reentry_strategy: "moving_average"
    reentry_parameters:
      window: 20
      ma_type: "sma"
"""


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_load_kodex_hybrid(self, tmp_path: Path):
        result = load_strategy_config(_write(tmp_path, _HYBRID_KODEX))
        assert list(result.keys()) == ["069500"]
        bundle = result["069500"]
        assert isinstance(bundle, AssetStrategyBundle)
        assert bundle.code == "069500"
        assert bundle.name == "KODEX 200"
        assert bundle.enabled is True
        # Buy side
        assert bundle.buy_strategy_name == "price_drop"
        assert bundle.buy_config.drop_threshold_pct == Decimal("5.0")
        assert bundle.buy_config.max_split_count == 7
        assert bundle.buy_config.per_split_amount.amount == Decimal("10000000")
        assert bundle.buy_config.per_split_amount.currency is Currency.KRW
        assert bundle.buy_config.max_split_per_day == 1
        # Sell side
        assert bundle.sell_strategy_name == "profit_target"
        assert bundle.sell_config.profit_target_pct == Decimal("10.0")
        assert bundle.sell_config.max_sells_per_day == 7
        # Reentry side: only the hybrid-relevant key is preserved.
        assert bundle.reentry_strategy_name == "hybrid"
        assert bundle.reentry_parameters == {"cooldown_days": 60}

    def test_load_kodex_moving_average(self, tmp_path: Path):
        result = load_strategy_config(_write(tmp_path, _MOVING_AVERAGE_KODEX))
        bundle = result["069500"]
        assert bundle.reentry_strategy_name == "moving_average"
        # window + ma_type packed; no cooldown_days leaks in.
        assert bundle.reentry_parameters == {"window": 20, "ma_type": "sma"}
        # Defaults applied for omitted fields (max_split_per_day,
        # max_sells_per_day, ma_type would default to "sma" if absent).
        assert bundle.buy_config.max_split_per_day == 1
        assert bundle.sell_config.max_sells_per_day == 7

    def test_yaml_float_round_trips_to_decimal_via_str(self, tmp_path: Path):
        # YAML emits 10.5 as Python float; loader coerces via Decimal(str(..))
        # to avoid IEEE-754 leakage (CLAUDE.md §2.3).
        body = _HYBRID_KODEX.replace("profit_target_pct: 10.0", "profit_target_pct: 10.5")
        bundle = load_strategy_config(_write(tmp_path, body))["069500"]
        assert bundle.sell_config.profit_target_pct == Decimal("10.5")
        # Spot-check there's no float artefact (e.g. 10.499999999999998).
        assert str(bundle.sell_config.profit_target_pct) == "10.5"

    def test_max_loss_pct_optional(self, tmp_path: Path):
        # ``max_loss_pct`` is optional in buy_parameters (Phase 1+ tier);
        # absence yields ``None`` on the bundle.
        bundle = load_strategy_config(_write(tmp_path, _HYBRID_KODEX))["069500"]
        assert bundle.buy_config.max_loss_pct is None

    def test_multi_asset_returns_dict_with_all_entries(self, tmp_path: Path):
        # Phase 0.5 composition uses the first key only, but the loader
        # itself returns the whole dict so Phase 0.7 inherits a working
        # parse path without revisiting the schema.
        body = """\
version: "0.5"
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters: {drop_threshold_pct: 5.0, max_split_count: 7, per_split_amount: 10000000}
    sell_strategy: "profit_target"
    sell_parameters: {profit_target_pct: 10.0}
    reentry_strategy: "hybrid"
    reentry_parameters: {cooldown_days: 60}
  "229200":
    name: "KODEX KOSDAQ150"
    enabled: false
    buy_strategy: "price_drop"
    buy_parameters: {drop_threshold_pct: 7.0, max_split_count: 5, per_split_amount: 5000000}
    sell_strategy: "profit_target"
    sell_parameters: {profit_target_pct: 12.0}
    reentry_strategy: "moving_average"
    reentry_parameters: {window: 60}
"""
        result = load_strategy_config(_write(tmp_path, body))
        assert set(result.keys()) == {"069500", "229200"}
        assert result["069500"].enabled is True
        assert result["229200"].enabled is False
        assert result["229200"].reentry_strategy_name == "moving_average"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------
class TestValidationErrors:
    def test_missing_version_raises(self, tmp_path: Path):
        body = _HYBRID_KODEX.replace('version: "0.5"\n', "")
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_unsupported_version_raises(self, tmp_path: Path):
        body = _HYBRID_KODEX.replace('version: "0.5"', 'version: "0.4"')
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_empty_assets_raises(self, tmp_path: Path):
        body = 'version: "0.5"\nassets: {}\n'
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_missing_assets_raises(self, tmp_path: Path):
        body = 'version: "0.5"\n'
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_unknown_buy_strategy_raises(self, tmp_path: Path):
        body = _HYBRID_KODEX.replace(
            'buy_strategy: "price_drop"', 'buy_strategy: "magic_dip"'
        )
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_unknown_sell_strategy_raises(self, tmp_path: Path):
        body = _HYBRID_KODEX.replace(
            'sell_strategy: "profit_target"', 'sell_strategy: "ai_oracle"'
        )
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_unknown_reentry_strategy_raises(self, tmp_path: Path):
        body = _HYBRID_KODEX.replace(
            'reentry_strategy: "hybrid"', 'reentry_strategy: "current_market"'
        )
        # ADR §4.1.1 deprecated D ("current_market"); Literal rejects it.
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_profit_target_pct_out_of_range_raises(self, tmp_path: Path):
        # SellStrategyConfig field constraint: 0 < profit_target_pct < 100
        body = _HYBRID_KODEX.replace(
            "profit_target_pct: 10.0", "profit_target_pct: 150.0"
        )
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_drop_threshold_pct_must_be_positive(self, tmp_path: Path):
        body = _HYBRID_KODEX.replace(
            "drop_threshold_pct: 5.0", "drop_threshold_pct: 0"
        )
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_max_split_count_out_of_range_raises(self, tmp_path: Path):
        body = _HYBRID_KODEX.replace(
            "max_split_count: 7", "max_split_count: 8"
        )
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_hybrid_without_cooldown_days_raises(self, tmp_path: Path):
        # ADR §6.2 explicit consistency rule.
        body = """\
version: "0.5"
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters: {drop_threshold_pct: 5.0, max_split_count: 7, per_split_amount: 10000000}
    sell_strategy: "profit_target"
    sell_parameters: {profit_target_pct: 10.0}
    reentry_strategy: "hybrid"
    reentry_parameters: {window: 20}
"""
        with pytest.raises(ValidationError, match="cooldown_days"):
            load_strategy_config(_write(tmp_path, body))

    def test_moving_average_without_window_raises(self, tmp_path: Path):
        body = """\
version: "0.5"
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters: {drop_threshold_pct: 5.0, max_split_count: 7, per_split_amount: 10000000}
    sell_strategy: "profit_target"
    sell_parameters: {profit_target_pct: 10.0}
    reentry_strategy: "moving_average"
    reentry_parameters: {cooldown_days: 30}
"""
        with pytest.raises(ValidationError, match="window"):
            load_strategy_config(_write(tmp_path, body))

    def test_extra_top_level_key_raises(self, tmp_path: Path):
        body = _HYBRID_KODEX + "extra: true\n"
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_extra_buy_param_raises(self, tmp_path: Path):
        # ``mystery_param`` not declared on _BuyParams (extra='forbid').
        body = _HYBRID_KODEX.replace(
            "max_split_per_day: 1", "max_split_per_day: 1\n      mystery_param: 42"
        )
        with pytest.raises(ValidationError):
            load_strategy_config(_write(tmp_path, body))

    def test_empty_yaml_file_raises_value_error(self, tmp_path: Path):
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_strategy_config(path)

    def test_root_must_be_mapping(self, tmp_path: Path):
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="mapping"):
            load_strategy_config(path)


# ---------------------------------------------------------------------------
# Repo-checked-in config files (Phase 0.5 step 0.5.22)
# ---------------------------------------------------------------------------
class TestRepoConfigFiles:
    """Smoke tests for ``config/strategies-D.yaml`` / ``strategies-F.yaml``.

    These are the actual policy-D-2 vs policy-F config files used by the
    5-year KOSPI 200 D-vs-F comparison (ADR §8.4). Tests verify they
    load cleanly and carry the ADR §8.3 baseline parameters so a future
    schema change can't quietly invalidate them.
    """

    def _repo_root(self) -> Path:
        # tests/integration/infrastructure/test_*.py → repo root is 4 up.
        from pathlib import Path as _Path
        return _Path(__file__).resolve().parents[3]

    def test_strategies_d_yaml_loads(self):
        path = self._repo_root() / "config" / "strategies-D.yaml"
        bundles = load_strategy_config(path)
        assert "069500" in bundles
        bundle = bundles["069500"]
        # ADR §8.3 baseline parameters
        assert bundle.buy_config.drop_threshold_pct == Decimal("5.0")
        assert bundle.buy_config.max_split_count == 7
        assert bundle.buy_config.per_split_amount.amount == Decimal("10000000")
        assert bundle.buy_config.per_split_amount.currency is Currency.KRW
        assert bundle.sell_config.profit_target_pct == Decimal("10.0")
        # D-2 specific
        assert bundle.reentry_strategy_name == "moving_average"
        assert bundle.reentry_parameters == {"window": 20, "ma_type": "sma"}

    def test_strategies_f_yaml_loads(self):
        path = self._repo_root() / "config" / "strategies-F.yaml"
        bundles = load_strategy_config(path)
        bundle = bundles["069500"]
        # ADR §8.3 baseline parameters
        assert bundle.buy_config.drop_threshold_pct == Decimal("5.0")
        assert bundle.buy_config.max_split_count == 7
        assert bundle.buy_config.per_split_amount.amount == Decimal("10000000")
        assert bundle.sell_config.profit_target_pct == Decimal("10.0")
        # F specific
        assert bundle.reentry_strategy_name == "hybrid"
        assert bundle.reentry_parameters == {"cooldown_days": 60}

    def test_d_and_f_share_buy_and_sell_params(self):
        # Phase 0.5 D-vs-F comparison isolates the reentry variable per
        # ADR §1.3 — every other parameter must be identical.
        d = load_strategy_config(
            self._repo_root() / "config" / "strategies-D.yaml"
        )["069500"]
        f = load_strategy_config(
            self._repo_root() / "config" / "strategies-F.yaml"
        )["069500"]
        assert d.buy_config == f.buy_config
        assert d.sell_config == f.sell_config
        # Reentry side is the only intentional difference.
        assert d.reentry_strategy_name != f.reentry_strategy_name
