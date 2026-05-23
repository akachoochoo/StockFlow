"""Tests for scripts/manage_strategies.py (Phase 1.1 asset management CLI).

Pure helpers (dict ops, pykrx verification with an injected lookup) are
unit-tested directly; the ``main()`` glue is exercised end-to-end against
temp YAML files. pykrx is never hit — verification uses a fake lookup or
``--no-verify`` (CLAUDE.md §7.3: mock external systems).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.manage_strategies import (  # noqa: E402
    AssetMeta,
    LookupResult,
    _coerce_scalar,
    add_asset_meta,
    add_strategy_entry,
    available_codes,
    cross_check,
    find_template_entry,
    format_diff,
    format_list,
    load_assets_data,
    load_yaml,
    main,
    remove_entry,
    set_enabled,
    set_param,
    verify_asset_metadata,
)

_BASE_STRATEGIES = """\
version: "0.5"
allocation_policy: EQUAL
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters:
      drop_threshold_pct: 5.0
      max_split_count: 7
      per_split_amount: 5000000
      max_split_per_day: 1
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: 10.0
      max_sells_per_day: 7
    reentry_strategy: "hybrid"
    reentry_parameters:
      cooldown_days: 60
  "132030":
    name: "KODEX 골드선물(H)"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters:
      drop_threshold_pct: 5.0
      max_split_count: 7
      per_split_amount: 5000000
      max_split_per_day: 1
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: 10.0
      max_sells_per_day: 7
    reentry_strategy: "hybrid"
    reentry_parameters:
      cooldown_days: 60
"""


@pytest.fixture
def strat_path(tmp_path: Path) -> Path:
    p = tmp_path / "strategies.yaml"
    p.write_text(_BASE_STRATEGIES, encoding="utf-8")
    return p


@pytest.fixture
def assets_path(tmp_path: Path) -> Path:
    return tmp_path / "assets.yaml"


def _meta(**kw) -> AssetMeta:
    base = {
        "code": "035720",
        "market": "KOSPI",
        "asset_class": "KR_STOCK",
        "listed_at": date(2017, 7, 10),
        "name": "카카오",
    }
    base.update(kw)
    return AssetMeta(**base)


# ---------------------------------------------------------------------------
# _coerce_scalar
# ---------------------------------------------------------------------------
class TestCoerceScalar:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("6", 6),
            ("6.0", 6.0),
            ("true", True),
            ("false", False),
            ("sma", "sma"),
            ("KOSPI", "KOSPI"),
        ],
    )
    def test_coerce(self, raw: str, expected: object):
        assert _coerce_scalar(raw) == expected
        assert type(_coerce_scalar(raw)) is type(expected)


# ---------------------------------------------------------------------------
# verify_asset_metadata (injected lookup — no network)
# ---------------------------------------------------------------------------
class TestVerify:
    def test_unavailable_lookup_warns(self):
        w = verify_asset_metadata(_meta(), None)
        assert len(w) == 1 and "검증 불가" in w[0]

    def test_all_match_no_warning(self):
        r = LookupResult(found=True, name="카카오", market="KOSPI", earliest_date=date(2017, 7, 10))
        assert verify_asset_metadata(_meta(), r) == []

    def test_name_mismatch(self):
        r = LookupResult(found=True, name="다른이름", market="KOSPI")
        w = verify_asset_metadata(_meta(), r)
        assert any("종목명 불일치" in x for x in w)

    def test_market_mismatch(self):
        r = LookupResult(found=True, name="카카오", market="KOSDAQ")
        w = verify_asset_metadata(_meta(), r)
        assert any("시장 불일치" in x for x in w)

    def test_listed_at_gap(self):
        r = LookupResult(found=True, name="카카오", market="KOSPI", earliest_date=date(2010, 1, 1))
        w = verify_asset_metadata(_meta(), r)
        assert any("상장일 확인 필요" in x for x in w)

    def test_code_not_found(self):
        r = LookupResult(found=False, name="", market=None)
        w = verify_asset_metadata(_meta(name=""), r)
        assert any("찾지 못함" in x for x in w)


# ---------------------------------------------------------------------------
# strategies.yaml pure ops
# ---------------------------------------------------------------------------
class TestStrategyOps:
    def test_find_template_explicit(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        code, entry = find_template_entry(data, "132030")
        assert code == "132030"
        assert entry["name"] == "KODEX 골드선물(H)"

    def test_find_template_first_enabled(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        data["assets"]["069500"]["enabled"] = False
        code, _ = find_template_entry(data)
        assert code == "132030"

    def test_find_template_empty_raises(self):
        with pytest.raises(ValueError):
            find_template_entry({"assets": {}})

    def test_add_inherits_policy(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        _, tmpl = find_template_entry(data)
        add_strategy_entry(data, "035720", "카카오", True, tmpl)
        new = data["assets"]["035720"]
        assert new["name"] == "카카오"
        assert new["enabled"] is True
        assert new["buy_parameters"] == data["assets"]["069500"]["buy_parameters"]
        # deep copy — mutating the new entry must not touch the template
        new["buy_parameters"]["drop_threshold_pct"] = 99
        assert data["assets"]["069500"]["buy_parameters"]["drop_threshold_pct"] == 5.0

    def test_add_duplicate_raises(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        _, tmpl = find_template_entry(data)
        with pytest.raises(ValueError):
            add_strategy_entry(data, "069500", "x", True, tmpl)

    def test_remove_missing_raises(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        with pytest.raises(ValueError):
            remove_entry(data, "999999")

    def test_set_enabled(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        set_enabled(data, "069500", False)
        assert data["assets"]["069500"]["enabled"] is False


class TestSetParam:
    def test_set_all(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        targets = set_param(data, "buy.drop_threshold_pct", "6.0", None, True)
        assert set(targets) == {"069500", "132030"}
        assert data["assets"]["069500"]["buy_parameters"]["drop_threshold_pct"] == 6.0

    def test_set_one_code(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        set_param(data, "sell.profit_target_pct", "15.0", "069500", False)
        assert data["assets"]["069500"]["sell_parameters"]["profit_target_pct"] == 15.0
        assert data["assets"]["132030"]["sell_parameters"]["profit_target_pct"] == 10.0

    def test_bad_param_format(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        with pytest.raises(ValueError):
            set_param(data, "nope", "1", "069500", False)

    def test_requires_exactly_one_target(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        with pytest.raises(ValueError):
            set_param(data, "buy.x", "1", None, False)  # neither
        with pytest.raises(ValueError):
            set_param(data, "buy.x", "1", "069500", True)  # both


# ---------------------------------------------------------------------------
# assets.yaml ops + cross-check
# ---------------------------------------------------------------------------
class TestAssetOps:
    def test_add_asset_meta_omits_defaults(self):
        data = {"version": "1.0", "assets": {}}
        add_asset_meta(data, _meta())
        entry = data["assets"]["035720"]
        assert entry == {
            "name": "카카오",
            "market": "KOSPI",
            "asset_class": "KR_STOCK",
            "listed_at": date(2017, 7, 10),
        }  # tick/lot/exchange/currency at defaults → omitted

    def test_add_asset_meta_keeps_overrides(self):
        data = {"version": "1.0", "assets": {}}
        add_asset_meta(data, _meta(tick_size=5, lot_size=10))
        entry = data["assets"]["035720"]
        assert entry["tick_size"] == 5
        assert entry["lot_size"] == 10

    def test_add_hardcoded_code_rejected(self):
        data = {"version": "1.0", "assets": {}}
        with pytest.raises(ValueError):
            add_asset_meta(data, _meta(code="069500"))  # in _ASSET_FACTORIES

    def test_add_duplicate_rejected(self):
        data = {"version": "1.0", "assets": {}}
        add_asset_meta(data, _meta())
        with pytest.raises(ValueError):
            add_asset_meta(data, _meta())

    def test_available_codes_union(self):
        data = {"version": "1.0", "assets": {"035720": {}}}
        codes = available_codes(data)
        assert "069500" in codes  # hardcoded
        assert "035720" in codes  # yaml

    def test_cross_check_flags_missing(self):
        strat = yaml.safe_load(_BASE_STRATEGIES)
        strat["assets"]["035720"] = {"name": "x", "enabled": True}
        errors = cross_check(strat, {"version": "1.0", "assets": {}})
        assert any("035720" in e for e in errors)

    def test_cross_check_passes_when_present(self):
        strat = yaml.safe_load(_BASE_STRATEGIES)
        assert cross_check(strat, {"version": "1.0", "assets": {}}) == []


# ---------------------------------------------------------------------------
# formatting smoke
# ---------------------------------------------------------------------------
class TestFormatting:
    def test_format_list(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        out = format_list(data, {"version": "1.0", "assets": {}})
        assert "069500" in out and "KODEX 200" in out and "하드코딩" in out

    def test_format_diff(self):
        a = yaml.safe_load(_BASE_STRATEGIES)
        b = yaml.safe_load(_BASE_STRATEGIES)
        b["assets"]["069500"]["enabled"] = False
        del b["assets"]["132030"]
        out = format_diff(a, b)
        assert "132030" in out and "enabled" in out

    def test_format_diff_identical(self):
        a = yaml.safe_load(_BASE_STRATEGIES)
        assert "차이 없음" in format_diff(a, dict(a))


# ---------------------------------------------------------------------------
# main() end-to-end (temp files; pykrx faked / disabled)
# ---------------------------------------------------------------------------
class TestMainAdd:
    def test_add_no_verify_writes_both_files(self, strat_path: Path, assets_path: Path):
        rc = main(
            [
                "add", str(strat_path),
                "--code", "035720", "--name", "카카오",
                "--market", "KOSPI", "--asset-class", "KR_STOCK",
                "--listed-at", "2017-07-10", "--no-verify",
                "--assets-yaml", str(assets_path),
            ]
        )
        assert rc == 0
        strat = load_yaml(strat_path)
        assert "035720" in strat["assets"]
        assert strat["assets"]["035720"]["buy_strategy"] == "price_drop"
        assets = load_assets_data(assets_path)
        assert assets["assets"]["035720"]["name"] == "카카오"
        # validate command on the result passes
        assert main(["validate", str(strat_path), "--assets-yaml", str(assets_path)]) == 0

    def test_add_autofills_name_from_lookup(
        self, strat_path: Path, assets_path: Path, monkeypatch
    ):
        import scripts.manage_strategies as m

        monkeypatch.setattr(
            m, "pykrx_lookup",
            lambda code: LookupResult(found=True, name="카카오", market="KOSPI", earliest_date=date(2017, 7, 10)),
        )
        rc = main(
            [
                "add", str(strat_path),
                "--code", "035720",  # no --name → autofilled
                "--market", "KOSPI", "--asset-class", "KR_STOCK",
                "--listed-at", "2017-07-10",
                "--assets-yaml", str(assets_path),
            ]
        )
        assert rc == 0
        assert load_assets_data(assets_path)["assets"]["035720"]["name"] == "카카오"

    def test_add_no_name_no_verify_fails(self, strat_path: Path, assets_path: Path):
        rc = main(
            [
                "add", str(strat_path),
                "--code", "035720",
                "--market", "KOSPI", "--asset-class", "KR_STOCK",
                "--listed-at", "2017-07-10", "--no-verify",
                "--assets-yaml", str(assets_path),
            ]
        )
        assert rc == 1  # no name available → refuse, no write
        assert "035720" not in load_yaml(strat_path)["assets"]

    def test_add_hardcoded_code_fails_without_writing(
        self, strat_path: Path, assets_path: Path
    ):
        before = strat_path.read_text(encoding="utf-8")
        rc = main(
            [
                "add", str(strat_path),
                "--code", "005930", "--name", "삼성전자",
                "--market", "KOSPI", "--asset-class", "KR_STOCK",
                "--listed-at", "1975-06-11", "--no-verify",
                "--assets-yaml", str(assets_path),
            ]
        )
        assert rc == 1  # 005930 already hardcoded
        assert strat_path.read_text(encoding="utf-8") == before  # untouched


class TestMainToggleAndValidate:
    def test_disable_then_validate(self, strat_path: Path, assets_path: Path):
        assert main(["disable", str(strat_path), "--code", "132030"]) == 0
        assert load_yaml(strat_path)["assets"]["132030"]["enabled"] is False
        assert main(["validate", str(strat_path), "--assets-yaml", str(assets_path)]) == 0

    def test_set_code_uniformity_violation_rejected(self, strat_path: Path):
        before = strat_path.read_text(encoding="utf-8")
        # changing one asset's param breaks strict uniformity → loader rejects,
        # file left untouched.
        rc = main(
            ["set", str(strat_path), "--param", "sell.profit_target_pct",
             "--value", "15.0", "--code", "069500"]
        )
        assert rc == 1
        assert strat_path.read_text(encoding="utf-8") == before
