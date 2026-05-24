"""Tests for scripts/manage_strategies.py (Phase 1.1 asset management CLI).

Pure helpers (dict ops, pykrx verification with an injected lookup) are
unit-tested directly; the ``main()`` glue is exercised end-to-end against
temp YAML files. pykrx is never hit — verification uses a fake lookup or
``--no-verify`` (CLAUDE.md §7.3: mock external systems).
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.manage_strategies import (  # noqa: E402
    BUY_STRATEGIES,
    REENTRY_STRATEGIES,
    SELL_STRATEGIES,
    AssetMeta,
    LookupResult,
    ParamSpec,
    _coerce_scalar,
    add_asset_meta,
    add_strategy_entry,
    available_codes,
    buy_param_specs,
    collect_grid_params,
    collect_strategy_params,
    confirm,
    cross_check,
    find_template_entry,
    format_diff,
    format_list,
    grid_param_specs,
    load_assets_data,
    load_yaml,
    main,
    parse_param_value,
    prompt_choice,
    prompt_param,
    range_str,
    reentry_param_specs,
    remove_entry,
    sell_param_specs,
    set_enabled,
    set_param,
    verify_asset_metadata,
)


def _feed(monkeypatch, answers: list[str]) -> None:
    """Drive interactive prompts: builtins.input returns each answer in turn."""
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))

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


# assets.yaml metadata for the two assets in _BASE_STRATEGIES (ADR 0021 §7.1:
# assets.yaml = 단일 정본, so cross_check needs every strategy code present).
_BASE_ASSETS = """\
version: "1.0"
assets:
  "069500":
    name: "KODEX 200"
    market: KOSPI
    asset_class: KR_ETF
    listed_at: 2002-10-14
  "132030":
    name: "KODEX 골드선물(H)"
    market: KOSPI
    asset_class: KR_ETF
    listed_at: 2010-10-01
"""


@pytest.fixture
def assets_path(tmp_path: Path) -> Path:
    p = tmp_path / "assets.yaml"
    p.write_text(_BASE_ASSETS, encoding="utf-8")
    return p


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

    def test_add_duplicate_rejected(self):
        data = {"version": "1.0", "assets": {}}
        add_asset_meta(data, _meta())
        with pytest.raises(ValueError):
            add_asset_meta(data, _meta())

    def test_available_codes(self):
        # ADR 0021 §7.1: assets.yaml = 단일 정본 (하드코딩 union 제거).
        data = {"version": "1.0", "assets": {"035720": {}, "069500": {}}}
        codes = available_codes(data)
        assert codes == {"035720", "069500"}

    def test_cross_check_flags_missing(self):
        strat = yaml.safe_load(_BASE_STRATEGIES)
        strat["assets"]["035720"] = {"name": "x", "enabled": True}
        # 069500/132030 present; only the unregistered 035720 is flagged.
        assets = {"version": "1.0", "assets": {"069500": {}, "132030": {}}}
        errors = cross_check(strat, assets)
        assert any("035720" in e for e in errors)

    def test_cross_check_passes_when_present(self):
        strat = yaml.safe_load(_BASE_STRATEGIES)
        assets = {"version": "1.0", "assets": {"069500": {}, "132030": {}}}
        assert cross_check(strat, assets) == []


# ---------------------------------------------------------------------------
# formatting smoke
# ---------------------------------------------------------------------------
class TestFormatting:
    def test_format_list(self):
        data = yaml.safe_load(_BASE_STRATEGIES)
        assets = {"version": "1.0", "assets": {"069500": {}, "132030": {}}}
        out = format_list(data, assets)
        assert "069500" in out and "KODEX 200" in out and "등록" in out

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

    def test_add_existing_code_fails_without_writing(
        self, strat_path: Path, assets_path: Path
    ):
        before = strat_path.read_text(encoding="utf-8")
        rc = main(
            [
                "add", str(strat_path),
                "--code", "069500", "--name", "KODEX 200",
                "--market", "KOSPI", "--asset-class", "KR_ETF",
                "--listed-at", "2002-10-14", "--no-verify",
                "--assets-yaml", str(assets_path),
            ]
        )
        assert rc == 1  # 069500 already in strategies file → duplicate
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


# ---------------------------------------------------------------------------
# Parameter introspection (defaults/ranges from loader schemas — zero drift)
# ---------------------------------------------------------------------------
class TestParamSpecs:
    def test_buy_specs_keys_and_skip(self):
        keys = [s.key for s in buy_param_specs()]
        assert keys == [
            "drop_threshold_pct",
            "max_split_count",
            "per_split_amount",
            "max_split_per_day",
        ]
        assert "max_loss_pct" not in keys  # Phase 1+ field excluded

    def test_buy_specs_bounds_and_defaults(self):
        by_key = {s.key: s for s in buy_param_specs()}
        assert by_key["drop_threshold_pct"].kind == "decimal"
        assert by_key["drop_threshold_pct"].required is True
        assert by_key["drop_threshold_pct"].bounds == {"gt": 0}
        assert by_key["max_split_count"].bounds == {"ge": 1, "le": 7}
        assert by_key["max_split_per_day"].required is False
        assert by_key["max_split_per_day"].default == 1

    def test_sell_specs(self):
        by_key = {s.key: s for s in sell_param_specs()}
        assert by_key["profit_target_pct"].bounds == {"gt": 0, "lt": 100}
        assert by_key["max_sells_per_day"].default == 7

    def test_reentry_hybrid_requires_cooldown(self):
        specs = reentry_param_specs("hybrid")
        assert [s.key for s in specs] == ["cooldown_days"]
        assert specs[0].required is True
        assert specs[0].bounds == {"ge": 0, "le": 365}

    def test_reentry_moving_average(self):
        keys = [s.key for s in reentry_param_specs("moving_average")]
        assert keys == ["window", "ma_type"]

    def test_reentry_unknown_raises(self):
        with pytest.raises(ValueError):
            reentry_param_specs("nope")

    def test_strategy_choices_mirror_loader(self):
        assert BUY_STRATEGIES == ["price_drop", "support_level"]
        assert SELL_STRATEGIES == ["profit_target"]
        assert set(REENTRY_STRATEGIES) == {"moving_average", "hybrid"}


class TestParseAndRange:
    def test_range_str(self):
        spec = ParamSpec("x", "int", None, True, {"ge": 1, "le": 7})
        assert range_str(spec) == "≥1, ≤7"

    def test_parse_decimal_returns_float(self):
        spec = ParamSpec("drop", "decimal", None, True, {"gt": 0})
        assert parse_param_value(spec, "5.0") == 5.0
        assert isinstance(parse_param_value(spec, "5.0"), float)

    def test_parse_int(self):
        spec = ParamSpec("n", "int", None, True, {"ge": 1, "le": 7})
        assert parse_param_value(spec, "7") == 7

    def test_parse_bounds_violation(self):
        spec = ParamSpec("n", "int", None, True, {"ge": 1, "le": 7})
        with pytest.raises(ValueError):
            parse_param_value(spec, "8")

    def test_parse_type_error(self):
        spec = ParamSpec("n", "int", None, True, {})
        with pytest.raises(ValueError):
            parse_param_value(spec, "abc")

    def test_parse_str_passthrough(self):
        spec = ParamSpec("ma_type", "str", "sma", False, {})
        assert parse_param_value(spec, "ema") == "ema"


# ---------------------------------------------------------------------------
# Interactive prompt helpers (builtins.input monkeypatched)
# ---------------------------------------------------------------------------
class TestPrompts:
    def test_prompt_param_keeps_current_on_empty(self, monkeypatch):
        _feed(monkeypatch, [""])
        spec = ParamSpec("drop", "decimal", None, True, {"gt": 0})
        assert prompt_param(spec, current=5.0) == 5.0

    def test_prompt_param_uses_default_on_empty(self, monkeypatch):
        _feed(monkeypatch, [""])
        spec = ParamSpec("m", "int", 1, False, {"ge": 1})
        assert prompt_param(spec) == 1

    def test_prompt_param_parses_value(self, monkeypatch):
        _feed(monkeypatch, ["6.5"])
        spec = ParamSpec("drop", "decimal", None, True, {"gt": 0})
        assert prompt_param(spec) == 6.5

    def test_prompt_param_retries_on_invalid(self, monkeypatch):
        _feed(monkeypatch, ["abc", "99", "7"])  # type err, bounds err, ok
        spec = ParamSpec("n", "int", None, True, {"ge": 1, "le": 7})
        assert prompt_param(spec) == 7

    def test_prompt_param_required_empty_then_value(self, monkeypatch):
        _feed(monkeypatch, ["", "3"])  # required no default: empty re-asks
        spec = ParamSpec("n", "int", None, True, {"ge": 1, "le": 7})
        assert prompt_param(spec) == 3

    def test_prompt_choice_default_and_pick(self, monkeypatch):
        _feed(monkeypatch, [""])
        assert prompt_choice("x", ["a", "b"], "a") == "a"
        _feed(monkeypatch, ["bad", "b"])
        assert prompt_choice("x", ["a", "b"], "a") == "b"

    @pytest.mark.parametrize(
        "raw,default,expected",
        [("y", False, True), ("n", True, False), ("", True, True), ("", False, False)],
    )
    def test_confirm(self, monkeypatch, raw, default, expected):
        _feed(monkeypatch, [raw])
        assert confirm("ok?", default=default) is expected

    def test_collect_params_hybrid(self, monkeypatch):
        # drop, max_split, per_split, max_split_per_day(keep), profit, sells(keep), cooldown
        _feed(monkeypatch, ["5.0", "7", "5000000", "", "10.0", "", "60"])
        out = collect_strategy_params("hybrid")
        assert out["buy_parameters"]["drop_threshold_pct"] == 5.0
        assert out["buy_parameters"]["max_split_per_day"] == 1  # default kept
        assert out["sell_parameters"]["max_sells_per_day"] == 7  # default kept
        assert out["reentry_parameters"]["cooldown_days"] == 60


# ---------------------------------------------------------------------------
# wizard (interactive new-file creation)
# ---------------------------------------------------------------------------
class TestWizard:
    def test_wizard_creates_valid_file(
        self, tmp_path: Path, assets_path: Path, monkeypatch
    ):
        dest = tmp_path / "new_strategies.yaml"
        _feed(
            monkeypatch,
            [
                "split",     # 패러다임 → 분할매수
                "",          # allocation → EQUAL
                "",          # buy_strategy → price_drop
                "",          # reentry → hybrid
                "5.0", "7", "5000000", "",   # buy params (max_split_per_day default)
                "10.0", "",  # sell params (max_sells default)
                "60",        # cooldown_days
                "all",       # include all registered assets
            ],
        )
        rc = main(["wizard", str(dest), "--assets-yaml", str(assets_path)])
        assert rc == 0
        data = load_yaml(dest)
        assert set(data["assets"]) == {"069500", "132030"}
        assert data["assets"]["069500"]["buy_parameters"]["drop_threshold_pct"] == 5.0
        # the produced file passes the real loader + registry cross-check
        assert main(["validate", str(dest), "--assets-yaml", str(assets_path)]) == 0

    def test_wizard_refuses_existing_dest(self, strat_path: Path, assets_path: Path):
        rc = main(["wizard", str(strat_path), "--assets-yaml", str(assets_path)])
        assert rc == 1  # dest already exists → no overwrite

    def test_wizard_subset_of_assets(
        self, tmp_path: Path, assets_path: Path, monkeypatch
    ):
        dest = tmp_path / "subset.yaml"
        _feed(
            monkeypatch,
            ["split", "", "", "", "5.0", "7", "5000000", "", "10.0", "", "60",
             "069500"],
        )
        rc = main(["wizard", str(dest), "--assets-yaml", str(assets_path)])
        assert rc == 0
        assert set(load_yaml(dest)["assets"]) == {"069500"}

    def test_wizard_dgt_branch_creates_grid_config(
        self, tmp_path: Path, assets_path: Path, monkeypatch
    ):
        from src.infrastructure.yaml_grid_config_loader import load_grid_config

        dest = tmp_path / "via_wizard_grid.yaml"
        n = len(grid_param_specs())
        # 패러다임=dgt → grid 분기 (grid_count/fallback_k + 나머지 기본 + 종목)
        _feed(monkeypatch, ["dgt", "11", "0.05", *[""] * (n - 2), "069500"])
        rc = main(["wizard", str(dest), "--assets-yaml", str(assets_path)])
        assert rc == 0
        loaded = load_grid_config(dest)
        assert set(loaded) == {"069500"}
        assert loaded["069500"].config.grid_count == 11


# ---------------------------------------------------------------------------
# set --interactive
# ---------------------------------------------------------------------------
class TestSetInteractive:
    def test_set_interactive_all_uniform(
        self, strat_path: Path, assets_path: Path, monkeypatch
    ):
        # change drop→6.0 and profit→15.0, keep the rest (Enter)
        _feed(monkeypatch, ["6.0", "", "", "", "15.0", "", ""])
        rc = main(["set", str(strat_path), "--interactive", "--all"])
        assert rc == 0
        data = load_yaml(strat_path)
        for code in ("069500", "132030"):
            assert data["assets"][code]["buy_parameters"]["drop_threshold_pct"] == 6.0
            assert data["assets"][code]["sell_parameters"]["profit_target_pct"] == 15.0
        assert main(["validate", str(strat_path), "--assets-yaml", str(assets_path)]) == 0

    def test_set_requires_param_or_interactive(self, strat_path: Path):
        rc = main(["set", str(strat_path), "--all"])  # neither --param nor -i
        assert rc == 1


# ---------------------------------------------------------------------------
# add: full pykrx auto-fill + batch confirmation
# ---------------------------------------------------------------------------
def _full_lookup(_code: str) -> LookupResult:
    return LookupResult(
        found=True,
        name="카카오",
        market="KOSPI",
        earliest_date=date(2017, 7, 10),
        asset_class="KR_STOCK",
    )


class TestAddAutofill:
    def test_add_autofills_all_metadata_non_tty(
        self, strat_path: Path, assets_path: Path, monkeypatch
    ):
        import scripts.manage_strategies as m

        monkeypatch.setattr(m, "pykrx_lookup", _full_lookup)
        # non-TTY (pytest): no confirmation prompt; only --code given.
        rc = main(
            ["add", str(strat_path), "--code", "035720",
             "--assets-yaml", str(assets_path)]
        )
        assert rc == 0
        entry = load_assets_data(assets_path)["assets"]["035720"]
        assert entry["market"] == "KOSPI"
        assert entry["asset_class"] == "KR_STOCK"
        assert entry["listed_at"] == date(2017, 7, 10)

    def test_add_interactive_confirm_yes(
        self, strat_path: Path, assets_path: Path, monkeypatch
    ):
        import scripts.manage_strategies as m

        monkeypatch.setattr(m, "pykrx_lookup", _full_lookup)
        monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
        _feed(monkeypatch, ["y"])  # confirm
        rc = main(
            ["add", str(strat_path), "--code", "035720",
             "--assets-yaml", str(assets_path)]
        )
        assert rc == 0
        assert "035720" in load_assets_data(assets_path)["assets"]

    def test_add_interactive_cancel(
        self, strat_path: Path, assets_path: Path, monkeypatch
    ):
        import scripts.manage_strategies as m

        before = strat_path.read_text(encoding="utf-8")
        monkeypatch.setattr(m, "pykrx_lookup", _full_lookup)
        monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)
        _feed(monkeypatch, ["n"])  # decline
        rc = main(
            ["add", str(strat_path), "--code", "035720",
             "--assets-yaml", str(assets_path)]
        )
        assert rc == 0  # clean cancel
        assert strat_path.read_text(encoding="utf-8") == before  # untouched
        assert "035720" not in load_assets_data(assets_path)["assets"]

    def test_add_missing_metadata_no_verify_errors(
        self, strat_path: Path, assets_path: Path
    ):
        # --no-verify (no lookup), no metadata flags, non-TTY → cannot resolve.
        rc = main(
            ["add", str(strat_path), "--code", "035720", "--no-verify",
             "--assets-yaml", str(assets_path)]
        )
        assert rc == 1
        assert "035720" not in load_yaml(strat_path)["assets"]


class TestVerifyAssetClass:
    def test_asset_class_mismatch_warns(self):
        r = LookupResult(
            found=True, name="카카오", market="KOSPI", asset_class="KR_ETF"
        )
        # _meta() default asset_class is KR_STOCK
        w = verify_asset_metadata(_meta(), r)
        assert any("자산구분 불일치" in x for x in w)


# ---------------------------------------------------------------------------
# add bootstrap (cold start — first asset, no template to inherit)
# ---------------------------------------------------------------------------
def _interactive(monkeypatch) -> None:
    import scripts.manage_strategies as m

    monkeypatch.setattr(m, "pykrx_lookup", _full_lookup)
    monkeypatch.setattr(m.sys.stdin, "isatty", lambda: True)


# confirm → allocation → buy_strategy → reentry_strategy → 7 params
_COLD_START_INPUTS = [
    "y", "", "", "", "5.0", "7", "5000000", "", "10.0", "", "60",
]


class TestAddBootstrap:
    def test_cold_start_creates_both_files(self, tmp_path: Path, monkeypatch):
        strat = tmp_path / "strategies-new.yaml"
        assets = tmp_path / "assets-new.yaml"  # neither file exists yet
        _interactive(monkeypatch)
        _feed(monkeypatch, _COLD_START_INPUTS)
        rc = main(
            ["add", str(strat), "--code", "035720", "--assets-yaml", str(assets)]
        )
        assert rc == 0
        data = load_yaml(strat)
        assert data["version"] == "0.5"
        assert data["allocation_policy"] == "EQUAL"
        assert set(data["assets"]) == {"035720"}
        entry = data["assets"]["035720"]
        assert entry["buy_strategy"] == "price_drop"
        assert entry["buy_parameters"]["drop_threshold_pct"] == 5.0
        assert entry["reentry_parameters"]["cooldown_days"] == 60
        # registry written + whole thing passes the real loader/cross-check
        assert load_assets_data(assets)["assets"]["035720"]["market"] == "KOSPI"
        assert main(["validate", str(strat), "--assets-yaml", str(assets)]) == 0

    def test_cold_start_then_second_add_inherits(
        self, tmp_path: Path, monkeypatch
    ):
        strat = tmp_path / "s.yaml"
        assets = tmp_path / "a.yaml"
        _interactive(monkeypatch)
        _feed(monkeypatch, _COLD_START_INPUTS)
        assert main(
            ["add", str(strat), "--code", "035720", "--assets-yaml", str(assets)]
        ) == 0
        # second add: a template now exists → inherits, no policy prompts
        import scripts.manage_strategies as m

        monkeypatch.setattr(
            m, "pykrx_lookup",
            lambda code: LookupResult(
                found=True, name="네이버", market="KOSPI",
                earliest_date=date(2008, 11, 28), asset_class="KR_STOCK",
            ),
        )
        _feed(monkeypatch, ["y"])  # only the confirmation, no policy prompts
        assert main(
            ["add", str(strat), "--code", "035420", "--assets-yaml", str(assets)]
        ) == 0
        data = load_yaml(strat)
        assert set(data["assets"]) == {"035720", "035420"}
        # inherited policy is identical (uniformity holds)
        assert (
            data["assets"]["035420"]["buy_parameters"]
            == data["assets"]["035720"]["buy_parameters"]
        )
        assert main(["validate", str(strat), "--assets-yaml", str(assets)]) == 0

    def test_bootstrap_empty_assets_file_keeps_allocation(
        self, tmp_path: Path, monkeypatch
    ):
        strat = tmp_path / "empty.yaml"
        strat.write_text(
            'version: "0.5"\nallocation_policy: VOL\nassets: {}\n', encoding="utf-8"
        )
        assets = tmp_path / "a.yaml"
        _interactive(monkeypatch)
        # file exists → no allocation prompt; drop the leading allocation input
        _feed(monkeypatch, ["y", "", "", "5.0", "7", "5000000", "", "10.0", "", "60"])
        rc = main(
            ["add", str(strat), "--code", "035720", "--assets-yaml", str(assets)]
        )
        assert rc == 0
        data = load_yaml(strat)
        assert data["allocation_policy"] == "VOL"  # preserved, not re-prompted
        assert set(data["assets"]) == {"035720"}

    def test_bootstrap_non_interactive_refused(self, tmp_path: Path, monkeypatch):
        strat = tmp_path / "s.yaml"
        assets = tmp_path / "a.yaml"
        import scripts.manage_strategies as m

        monkeypatch.setattr(m, "pykrx_lookup", _full_lookup)
        # non-TTY (pytest default): cannot prompt for the first policy.
        rc = main(
            ["add", str(strat), "--code", "035720", "--assets-yaml", str(assets)]
        )
        assert rc == 1
        assert not strat.exists()
        assert not assets.exists()

    def test_bootstrap_template_flag_refused(self, tmp_path: Path, monkeypatch):
        strat = tmp_path / "s.yaml"
        assets = tmp_path / "a.yaml"
        _interactive(monkeypatch)
        _feed(monkeypatch, [])  # error fires before any prompt
        rc = main(
            ["add", str(strat), "--code", "035720",
             "--template", "069500", "--assets-yaml", str(assets)]
        )
        assert rc == 1
        assert not strat.exists()

    def test_bootstrap_cancel_at_confirm(self, tmp_path: Path, monkeypatch):
        strat = tmp_path / "s.yaml"
        assets = tmp_path / "a.yaml"
        _interactive(monkeypatch)
        _feed(monkeypatch, ["n"])  # decline before policy prompts
        rc = main(
            ["add", str(strat), "--code", "035720", "--assets-yaml", str(assets)]
        )
        assert rc == 0  # clean cancel
        assert not strat.exists()


# ---------------------------------------------------------------------------
# grid config introspection + grid-wizard (ADR 0022 §11 D15)
# ---------------------------------------------------------------------------
class TestGridParamSpecs:
    def test_includes_bool_and_literal(self):
        by = {s.key: s for s in grid_param_specs()}
        assert by["grid_count"].required and by["grid_count"].kind == "int"
        assert by["fallback_k"].required and by["fallback_k"].kind == "decimal"
        assert by["volume_gate"].kind == "bool"
        assert by["rebalance_mode"].choices == ["on_breach", "daily"]
        assert by["volatility_measure"].choices == ["atr", "adr"]

    def test_parse_bool(self):
        spec = ParamSpec("x", "bool", False, False, {})
        assert parse_param_value(spec, "true") is True
        assert parse_param_value(spec, "n") is False
        with pytest.raises(ValueError):
            parse_param_value(spec, "maybe")


class TestCollectGridParams:
    def test_defaults_only_emit_required(self, monkeypatch):
        n = len(grid_param_specs())
        _feed(monkeypatch, ["11", "0.05", *[""] * (n - 2)])
        assert collect_grid_params() == {"grid_count": 11, "fallback_k": 0.05}

    def test_changed_optional_emitted(self, monkeypatch):
        answers = []
        for s in grid_param_specs():
            answers.append(
                {"grid_count": "11", "fallback_k": "0.05",
                 "volatility_measure": "atr", "volume_gate": "y"}.get(s.key, "")
            )
        _feed(monkeypatch, answers)
        out = collect_grid_params()
        assert out["volatility_measure"] == "atr"
        assert out["volume_gate"] is True
        assert "atr_period" not in out  # unchanged default → skipped


class TestGridWizard:
    def test_creates_valid_grid_config(self, tmp_path, assets_path, monkeypatch):
        from src.infrastructure.yaml_grid_config_loader import load_grid_config

        dest = tmp_path / "grid.yaml"
        n = len(grid_param_specs())
        _feed(monkeypatch, ["11", "0.05", *[""] * (n - 2), "069500"])
        rc = main(["grid-wizard", str(dest), "--assets-yaml", str(assets_path)])
        assert rc == 0
        loaded = load_grid_config(dest)
        assert set(loaded) == {"069500"}
        assert loaded["069500"].config.grid_count == 11
        assert loaded["069500"].config.fallback_k == Decimal("0.05")

    def test_refuses_existing_dest(self, strat_path, assets_path):
        rc = main(
            ["grid-wizard", str(strat_path), "--assets-yaml", str(assets_path)]
        )
        assert rc == 1
