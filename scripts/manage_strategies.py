#!/usr/bin/env python
"""scripts/manage_strategies.py — strategies*.yaml + assets.yaml 관리 CLI.

종목(asset) 추가/관리를 코드 수정 없이 하기 위한 운영 도구. 두 데이터 파일을
함께 다룬다:

  - ``config/strategies*.yaml`` : 종목별 매수/매도/재진입 전략 + 파라미터.
  - ``config/assets.yaml``      : 종목 메타데이터(시장/호가/상장일 등). Phase
    1.1 data-driven 레지스트리 — ``composition.asset_from_code`` 의 단일 정본
    (ADR 0021 §7.1 — Phase 0 박제 9 종 포함 전 종목).

명령::

    uv run python scripts/manage_strategies.py list     <strategies.yaml>
    uv run python scripts/manage_strategies.py show     <strategies.yaml> [--code C]
    uv run python scripts/manage_strategies.py validate <strategies.yaml>
    # 종목 추가 — 메타데이터(종목명/시장/자산구분/상장일)는 pykrx 로 자동 조회.
    # TTY 에서는 일괄 확인 프롬프트가 뜨고, 비대화식(CI)/`--yes` 는 건너뛴다.
    # 플래그를 주면 자동값을 덮어쓴다(자동 조회 실패 시에만 필요). 파일이 없거나
    # 비어 있으면(=cold start) 첫 종목의 전략 정책을 대화식으로 입력받아 생성한다.
    uv run python scripts/manage_strategies.py add      <strategies.yaml> \
        --code C [--market KOSPI] [--asset-class KR_STOCK] [--listed-at YYYY-MM-DD] \
        [--name N] [--tick T] [--lot L] [--template CODE] \
        [--disabled] [--no-verify] [--yes] [--assets-yaml PATH]
    uv run python scripts/manage_strategies.py remove   <strategies.yaml> --code C
    uv run python scripts/manage_strategies.py enable   <strategies.yaml> --code C
    uv run python scripts/manage_strategies.py disable  <strategies.yaml> --code C
    uv run python scripts/manage_strategies.py set      <strategies.yaml> \
        --param buy.drop_threshold_pct --value 6.0 [--code C | --all]
    # 대화식 편집 — 각 파라미터의 기본값·허용 범위를 안내하며 입력받는다.
    uv run python scripts/manage_strategies.py set      <strategies.yaml> \
        --interactive [--code C | --all]
    uv run python scripts/manage_strategies.py new      <dest.yaml> --from <src.yaml>
    # 새 config 를 대화식 생성 — 전략 종류(분할매수/DGT)를 먼저 고르고 분기.
    #   분할매수 → strategies.yaml (trading backtest --config 로 구동)
    #   DGT      → grid.yaml       (trading grid-backtest --config 로 구동)
    uv run python scripts/manage_strategies.py wizard   <dest.yaml> [--assets-yaml PATH]
    # grid-wizard = wizard 의 DGT 분기 직행 단축 (아는 사람용).
    uv run python scripts/manage_strategies.py grid-wizard <dest.yaml> [--assets-yaml PATH]
    uv run python scripts/manage_strategies.py diff     <a.yaml> <b.yaml>

설계 노트:
  - 검증은 실제 로더(``load_strategy_config`` / ``load_asset_registry``)를
    재사용한다 — 스키마를 재구현하지 않으므로 drift 가 없다. 마찬가지로
    ``wizard`` / ``set --interactive`` 의 기본값·허용 범위는 로더의 raw 스키마
    (`_BuyParams` 등)를 introspect 해 얻는다 (하드코딩 zero → drift zero).
  - ``add`` 는 strategies + assets 양쪽을 갱신하기 **전에** 임시 파일로 검증해
    실패 시 어떤 파일도 건드리지 않는다 (부분 쓰기 방지). ``wizard`` 도 동일.
  - ``add`` 메타데이터는 pykrx 로 종목명/시장/자산구분/데이터 시작일을 자동
    조회한다 (best-effort — 네트워크/미설치 시 경고 후 수동 입력). ``listed_at``
    은 pykrx 데이터 시작일을 *제안*하되 money-critical 이므로 확인 프롬프트에서
    KRX/DART 공식 상장일 확인을 권고한다 (CLAUDE.md §5.1 / verify_phase_0_9 규율).
  - 균일성: ``wizard`` 는 선택한 모든 종목에 동일 파라미터를 적용한다 — 종목별
    차등은 로더 균일성 규칙(§7.3)상 ``allow_per_asset_params: true`` 필요.
  - Cold start: 상속할 기존 종목이 없으면(파일 없음/빈 assets) ``add`` 는 첫
    종목의 전략 TYPE·파라미터를 ``wizard`` 와 동일한 프롬프트로 입력받아 파일을
    생성한다. 정책 입력이 필요하므로 이 경우는 대화식(TTY) 전용 — 비대화식/
    ``--yes`` 는 거부한다. 둘째 종목부터는 기존처럼 템플릿 상속.
  - YAML 쓰기는 pyyaml — 기존 주석은 제거되고 헤더는 자동 생성된다(사용자
    승인된 trade-off).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import yaml

# Run-as-script: put repo root on sys.path so ``from src...`` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.domain.strategies.grid import GridConfig  # noqa: E402
from src.infrastructure.yaml_asset_loader import (  # noqa: E402
    load_asset_registry,
)
from src.infrastructure.yaml_grid_config_loader import (  # noqa: E402
    load_grid_config,
)

# Private raw-YAML schemas reused for parameter introspection (default / range).
# Importing them — rather than re-listing constraints here — keeps the wizard's
# defaults/ranges in lock-step with the loader (zero drift, same discipline as
# `validate` reusing the real loaders).
from src.infrastructure.yaml_strategy_config_loader import (  # noqa: E402
    _AssetEntry as _LoaderAssetEntry,
)
from src.infrastructure.yaml_strategy_config_loader import (  # noqa: E402
    _BuyParams as _LoaderBuyParams,
)
from src.infrastructure.yaml_strategy_config_loader import (  # noqa: E402
    _ReentryParams as _LoaderReentryParams,
)
from src.infrastructure.yaml_strategy_config_loader import (  # noqa: E402
    _SellParams as _LoaderSellParams,
)
from src.infrastructure.yaml_strategy_config_loader import (  # noqa: E402
    load_strategy_config,
)

_DEFAULT_ASSETS_YAML = _REPO_ROOT / "config" / "assets.yaml"

# CLI param prefix → strategies.yaml section key (for the `set` command).
_SECTION_BY_PREFIX = {
    "buy": "buy_parameters",
    "sell": "sell_parameters",
    "reentry": "reentry_parameters",
}


# ---------------------------------------------------------------------------
# YAML read / write (pyyaml — comments are not preserved)
# ---------------------------------------------------------------------------
def load_yaml(path: Path | str) -> dict[str, Any]:
    """Load a YAML file into a plain dict (raises on missing/non-mapping)."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if raw is None:
        raise ValueError(f"YAML file {p} is empty")
    if not isinstance(raw, dict):
        raise ValueError(f"YAML root must be a mapping, got {type(raw).__name__}")
    return raw


def _dump_yaml(path: Path | str, data: dict[str, Any], header: str) -> None:
    """Write ``data`` to ``path`` with a generated header comment block."""
    body = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    Path(path).write_text(header + body, encoding="utf-8")


_STRATEGIES_HEADER = (
    "# 전략 설정 — scripts/manage_strategies.py 로 갱신됨 (pyyaml 재작성,\n"
    "# 원본 주석 제거). 종목 추가는 `add`, 검증은 `validate` 사용.\n"
)
_ASSETS_HEADER = (
    "# config/assets.yaml — 데이터 주도 자산 메타데이터 레지스트리.\n"
    "# scripts/manage_strategies.py 로 갱신됨 (pyyaml 재작성, 원본 주석 제거).\n"
    "# money-critical 필드(tick_size / listed_at)는 KRX/DART 공식 자료 확인.\n"
)
_GRID_HEADER = (
    "# DGT grid config — scripts/manage_strategies.py grid-wizard 로 생성 (ADR 0022\n"
    "# §11). 'trading grid-backtest --config <이파일> --csv CODE=path' 로 구동.\n"
    "# grid_parameters = GridConfig 필드 (생략 시 기본값). backtest/paper 전용.\n"
)


def _file_has_comments(path: Path | str) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    return any(
        line.lstrip().startswith("#") for line in p.read_text(encoding="utf-8").splitlines()
    )


# ---------------------------------------------------------------------------
# Asset metadata model + pykrx cross-verification
# ---------------------------------------------------------------------------
@dataclass
class AssetMeta:
    """User-supplied asset metadata for the `add` command."""

    code: str
    market: str
    asset_class: str
    listed_at: date
    name: str = ""
    tick_size: int | float | None = None
    lot_size: int | float = 1
    exchange: str = "KRX"
    currency: str = "KRW"


@dataclass
class LookupResult:
    """Best-effort result of a pykrx cross-check for one code."""

    found: bool = False
    name: str = ""
    market: str | None = None
    earliest_date: date | None = None
    asset_class: str | None = None  # "KR_ETF" | "KR_STOCK" (inferred)


# A lookup callable: code -> LookupResult or None (None = totally unavailable).
AssetLookup = Callable[[str], "LookupResult | None"]


def verify_asset_metadata(
    meta: AssetMeta, result: LookupResult | None
) -> list[str]:
    """Compare user metadata against a pykrx lookup; return warning strings.

    Pure / no I/O — ``result`` is injected, so this is unit-testable with a
    fake lookup. ``listed_at`` is treated as a soft check (KRX data start as a
    proxy) because the legal listing date should be confirmed against official
    sources, not auto-trusted from pykrx (verify_phase_0_9_assets.py 규율).
    """
    if result is None:
        return [
            "pykrx 검증 불가 (네트워크 단절 또는 미설치) — 종목명·시장·"
            "상장일을 KRX/DART 로 수동 확인하세요."
        ]
    warnings: list[str] = []
    if not result.found and not result.name:
        warnings.append(
            f"KRX 에서 코드 {meta.code!r} 종목명을 찾지 못함 — 코드 오타 가능성."
        )
    if result.name and meta.name and result.name != meta.name:
        warnings.append(
            f"종목명 불일치: 입력 {meta.name!r} ≠ KRX {result.name!r}."
        )
    if result.market and meta.market and result.market != meta.market:
        warnings.append(
            f"시장 불일치: 입력 {meta.market} ≠ KRX {result.market}."
        )
    if (
        result.asset_class
        and meta.asset_class
        and result.asset_class != meta.asset_class
    ):
        warnings.append(
            f"자산구분 불일치: 입력 {meta.asset_class} ≠ KRX {result.asset_class}."
        )
    if result.earliest_date is not None:
        gap = abs((meta.listed_at - result.earliest_date).days)
        if gap > 7:
            warnings.append(
                f"상장일 확인 필요: 입력 {meta.listed_at} vs KRX 데이터 시작 "
                f"{result.earliest_date} ({gap}일 차)."
            )
    return warnings


def pykrx_lookup(code: str) -> LookupResult | None:
    """Real pykrx cross-check (best-effort, graceful on any failure).

    Returns ``None`` when pykrx is unavailable or every probe fails so the
    caller can warn rather than crash. Never raises.
    """
    try:
        from pykrx import stock
    except Exception:
        return None

    import datetime as _dt

    today = _dt.date.today().strftime("%Y%m%d")

    # Probe the ETF name first: a non-empty result both names the asset *and*
    # classifies it as KR_ETF (stocks return "" here). Falling back to the
    # equity getter classifies it as KR_STOCK. This lets asset_class be
    # auto-filled instead of typed.
    name = ""
    asset_class: str | None = None
    try:
        etf_name = stock.get_etf_ticker_name(code) or ""
    except Exception:
        etf_name = ""
    if etf_name:
        name, asset_class = etf_name, "KR_ETF"
    else:
        try:
            stk_name = stock.get_market_ticker_name(code) or ""
        except Exception:
            stk_name = ""
        if stk_name:
            name, asset_class = stk_name, "KR_STOCK"

    market: str | None = None
    for mk in ("KOSPI", "KOSDAQ"):
        try:
            if code in stock.get_market_ticker_list(today, market=mk):
                market = mk
                break
        except Exception:
            continue

    earliest: date | None = None
    try:
        df = stock.get_market_ohlcv_by_date("19900101", today, code)
        if df is not None and len(df) > 0:
            earliest = df.index.min().date()
    except Exception:
        earliest = None

    if not name and market is None and earliest is None:
        return None
    return LookupResult(
        found=bool(name),
        name=name,
        market=market,
        earliest_date=earliest,
        asset_class=asset_class,
    )


# ---------------------------------------------------------------------------
# strategies.yaml pure operations
# ---------------------------------------------------------------------------
def _assets_map(data: dict[str, Any]) -> dict[str, Any]:
    assets = data.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("strategies YAML has no 'assets' mapping")
    return assets


def find_template_entry(
    data: dict[str, Any], template_code: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Pick a strategy entry to inherit policy from (uniformity 보장).

    With ``template_code`` returns that asset; otherwise the first enabled
    asset, else the first asset. Raises if the file has no assets.
    """
    assets = _assets_map(data)
    if not assets:
        raise ValueError(
            "전략 파일에 종목이 없습니다 — 먼저 `new --from <기존.yaml>` 으로 "
            "복제하거나 기준 종목이 있는 파일을 지정하세요."
        )
    if template_code is not None:
        if template_code not in assets:
            raise ValueError(f"--template {template_code!r} 가 파일에 없습니다.")
        return template_code, assets[template_code]
    for code, entry in assets.items():
        if entry.get("enabled", True):
            return code, entry
    code = next(iter(assets))
    return code, assets[code]


def add_strategy_entry(
    data: dict[str, Any],
    code: str,
    name: str,
    enabled: bool,
    template_entry: dict[str, Any],
) -> None:
    """Insert a new asset into strategies data, inheriting policy from template.

    Strategy TYPE + parameters are copied so the default (strict uniformity)
    loader passes. Edit afterwards with `set` (and `allow_per_asset_params:
    true` for per-asset parameters).
    """
    assets = _assets_map(data)
    if code in assets:
        raise ValueError(f"종목 {code!r} 이(가) 이미 전략 파일에 있습니다.")
    import copy

    entry = copy.deepcopy(template_entry)
    entry["name"] = name
    entry["enabled"] = enabled
    assets[code] = entry


def remove_entry(data: dict[str, Any], code: str) -> None:
    assets = _assets_map(data)
    if code not in assets:
        raise ValueError(f"종목 {code!r} 이(가) 전략 파일에 없습니다.")
    del assets[code]


def set_enabled(data: dict[str, Any], code: str, enabled: bool) -> None:
    assets = _assets_map(data)
    if code not in assets:
        raise ValueError(f"종목 {code!r} 이(가) 전략 파일에 없습니다.")
    assets[code]["enabled"] = enabled


def _coerce_scalar(value: str) -> Any:
    """Parse a CLI string into int/float/bool, else leave as string."""
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            continue
    return value


def set_param(
    data: dict[str, Any],
    param: str,
    value: str,
    code: str | None,
    apply_all: bool,
) -> list[str]:
    """Set ``<section>.<key>`` for one asset or all. Returns affected codes.

    ``param`` is ``buy.<k>`` / ``sell.<k>`` / ``reentry.<k>``.
    """
    if (code is None) == (not apply_all):
        raise ValueError("--code <C> 또는 --all 중 정확히 하나를 지정하세요.")
    prefix, _, key = param.partition(".")
    section = _SECTION_BY_PREFIX.get(prefix)
    if section is None or not key:
        raise ValueError(
            f"--param 형식 오류 {param!r} — buy.<k> / sell.<k> / reentry.<k>."
        )
    assets = _assets_map(data)
    targets = list(assets) if apply_all else [code]
    coerced = _coerce_scalar(value)
    for c in targets:
        if c not in assets:
            raise ValueError(f"종목 {c!r} 이(가) 전략 파일에 없습니다.")
        assets[c].setdefault(section, {})[key] = coerced
    return targets


# ---------------------------------------------------------------------------
# assets.yaml pure operations
# ---------------------------------------------------------------------------
def load_assets_data(path: Path | str) -> dict[str, Any]:
    """Load assets.yaml as raw dict; tolerate a missing file."""
    p = Path(path)
    if not p.exists():
        return {"version": "1.0", "assets": {}}
    data = load_yaml(p)
    data.setdefault("assets", {})
    return data


def add_asset_meta(assets_data: dict[str, Any], meta: AssetMeta) -> None:
    """Insert metadata for ``meta.code`` into assets.yaml data."""
    assets = assets_data.setdefault("assets", {})
    if meta.code in assets:
        raise ValueError(f"종목 {meta.code!r} 이(가) 이미 assets.yaml 에 있습니다.")
    entry: dict[str, Any] = {
        "name": meta.name,
        "market": meta.market,
        "asset_class": meta.asset_class,
        "listed_at": meta.listed_at,
    }
    if meta.tick_size is not None:
        entry["tick_size"] = meta.tick_size
    if meta.lot_size != 1:
        entry["lot_size"] = meta.lot_size
    if meta.exchange != "KRX":
        entry["exchange"] = meta.exchange
    if meta.currency != "KRW":
        entry["currency"] = meta.currency
    assets[meta.code] = entry


# ---------------------------------------------------------------------------
# Validation (reuses the real loaders via temp files — zero schema reimpl)
# ---------------------------------------------------------------------------
def _validate_strategies(data: dict[str, Any]) -> None:
    """Run the real strategy loader on ``data`` (raises on invalid)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "strategies.yaml"
        _dump_yaml(p, data, "")
        load_strategy_config(p)


def _validate_assets(data: dict[str, Any]) -> None:
    """Run the real asset loader on ``data`` (raises on invalid)."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "assets.yaml"
        _dump_yaml(p, data, "")
        load_asset_registry(p)


def _validate_grid(data: dict[str, Any]) -> None:
    """Run the real grid loader on ``data`` (raises on invalid) — drift-free."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "grid.yaml"
        _dump_yaml(p, data, "")
        load_grid_config(p)


def available_codes(assets_data: dict[str, Any]) -> set[str]:
    """All resolvable codes (assets.yaml = 단일 정본, ADR 0021 §7.1)."""
    return set(assets_data.get("assets", {}))


def cross_check(
    strategies_data: dict[str, Any], assets_data: dict[str, Any]
) -> list[str]:
    """Every code in strategies must resolve to Asset metadata. Returns errors."""
    resolvable = available_codes(assets_data)
    errors: list[str] = []
    for code in _assets_map(strategies_data):
        if code not in resolvable:
            errors.append(
                f"종목 {code!r}: Asset 메타데이터 없음 — assets.yaml 에 "
                "add 하거나 직접 추가 필요."
            )
    return errors


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _registry_tag(code: str, assets_data: dict[str, Any]) -> str:
    if code in assets_data.get("assets", {}):
        return "등록"
    return "✗ 없음"


def format_list(data: dict[str, Any], assets_data: dict[str, Any]) -> str:
    """Render a one-line-per-asset summary table."""
    assets = _assets_map(data)
    rows = [
        (
            "코드",
            "종목명",
            "사용",
            "매수",
            "drop%",
            "분할",
            "1회금액",
            "익절%",
            "재진입",
            "레지스트리",
        )
    ]
    for code, e in assets.items():
        bp = e.get("buy_parameters", {})
        sp = e.get("sell_parameters", {})
        rows.append(
            (
                code,
                str(e.get("name", "")),
                "Y" if e.get("enabled", True) else "n",
                str(e.get("buy_strategy", "")),
                str(bp.get("drop_threshold_pct", "")),
                str(bp.get("max_split_count", "")),
                str(bp.get("per_split_amount", "")),
                str(sp.get("profit_target_pct", "")),
                str(e.get("reentry_strategy", "")),
                _registry_tag(code, assets_data),
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for ri, r in enumerate(rows):
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))
        if ri == 0:
            lines.append("  ".join("-" * w for w in widths))
    policy = data.get("allocation_policy", "EQUAL")
    per_asset = data.get("allow_per_asset_params", False)
    head = (
        f"allocation_policy={policy}  allow_per_asset_params={per_asset}  "
        f"종목={len(assets)}"
    )
    return head + "\n" + "\n".join(lines)


def format_diff(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Structured diff of two strategies files (codes + per-code params)."""
    aa, ba = _assets_map(a), _assets_map(b)
    lines: list[str] = []
    only_a = [c for c in aa if c not in ba]
    only_b = [c for c in ba if c not in aa]
    if only_a:
        lines.append(f"A 에만: {only_a}")
    if only_b:
        lines.append(f"B 에만: {only_b}")
    for code in [c for c in aa if c in ba]:
        diffs = []
        for fld in (
            "enabled",
            "buy_strategy",
            "sell_strategy",
            "reentry_strategy",
            "buy_parameters",
            "sell_parameters",
            "reentry_parameters",
        ):
            if aa[code].get(fld) != ba[code].get(fld):
                diffs.append(f"    {fld}: A={aa[code].get(fld)} | B={ba[code].get(fld)}")
        if diffs:
            lines.append(f"  {code}:")
            lines.extend(diffs)
    for fld in ("version", "allocation_policy", "allow_per_asset_params"):
        if a.get(fld) != b.get(fld):
            lines.append(f"  {fld}: A={a.get(fld)} | B={b.get(fld)}")
    return "\n".join(lines) if lines else "차이 없음 (종목/정책 동일)."


# ---------------------------------------------------------------------------
# Strategy parameter introspection (single source of truth = loader schemas)
# ---------------------------------------------------------------------------
def _literal_choices(field: str) -> list[str]:
    """Strategy TYPE choices straight from the loader's Literal[...] (zero drift)."""
    return list(get_args(_LoaderAssetEntry.model_fields[field].annotation))


BUY_STRATEGIES = _literal_choices("buy_strategy")
SELL_STRATEGIES = _literal_choices("sell_strategy")
REENTRY_STRATEGIES = _literal_choices("reentry_strategy")
ALLOCATION_POLICIES = ["EQUAL", "INV_VOL", "VOL"]


@dataclass
class ParamSpec:
    """One configurable parameter: its YAML key, kind, default, and bounds.

    Built by introspecting the loader's raw pydantic schemas so defaults and
    valid ranges never drift from the validator that ultimately accepts them.
    """

    key: str
    kind: str  # "int" | "decimal" | "bool" | "str"
    default: Any | None  # None when the field is required (no usable default)
    required: bool
    bounds: dict[str, Any]  # subset of {"gt","ge","lt","le"}
    choices: list[str] | None = None  # Literal[...] options (e.g. atr/adr)


# Phase 1+/structural fields excluded from interactive entry.
_BUY_SKIP = frozenset({"max_loss_pct"})


def _kind_of(annotation: Any) -> str:
    """Map a (possibly Optional) annotation to 'int'/'decimal'/'bool'/'str'."""
    if get_origin(annotation) is Literal:
        return "str"  # choices carried separately (see _choices_of)
    base = annotation
    args = [a for a in get_args(annotation) if a is not type(None)]
    if args:
        base = args[0]
    if base is bool:  # before int — bool is an int subclass
        return "bool"
    if base is Decimal:
        return "decimal"
    if base is int:
        return "int"
    return "str"


def _choices_of(annotation: Any) -> list[str] | None:
    """Literal[...] members as strings, else None (for choice prompts)."""
    if get_origin(annotation) is Literal:
        return [str(a) for a in get_args(annotation)]
    return None


def _bounds_of(field_info: Any) -> dict[str, Any]:
    """Extract gt/ge/lt/le constraints from a pydantic FieldInfo."""
    bounds: dict[str, Any] = {}
    for meta in field_info.metadata:
        for op in ("gt", "ge", "lt", "le"):
            value = getattr(meta, op, None)
            if value is not None:
                bounds[op] = value
    return bounds


def _specs_from(model: Any, skip: frozenset[str] = frozenset()) -> list[ParamSpec]:
    specs: list[ParamSpec] = []
    for name, field_info in model.model_fields.items():
        if name in skip:
            continue
        specs.append(
            ParamSpec(
                key=name,
                kind=_kind_of(field_info.annotation),
                default=None if field_info.is_required() else field_info.default,
                required=field_info.is_required(),
                bounds=_bounds_of(field_info),
                choices=_choices_of(field_info.annotation),
            )
        )
    return specs


def grid_param_specs() -> list[ParamSpec]:
    """DGT GridConfig fields (single source of truth — ADR 0022 §11 D15)."""
    return _specs_from(GridConfig)


def buy_param_specs() -> list[ParamSpec]:
    return _specs_from(_LoaderBuyParams, _BUY_SKIP)


def sell_param_specs() -> list[ParamSpec]:
    return _specs_from(_LoaderSellParams)


def reentry_param_specs(strategy: str) -> list[ParamSpec]:
    """Reentry params relevant to ``strategy`` (the chosen policy decides which).

    The loader schema lists both policies' fields as Optional; the
    ``_check_reentry_consistency`` validator then *requires* the matching one,
    so we mark the relevant field required here too.
    """
    by_key = {s.key: s for s in _specs_from(_LoaderReentryParams)}
    if strategy == "hybrid":
        spec = by_key["cooldown_days"]
        spec.required = True
        return [spec]
    if strategy == "moving_average":
        window = by_key["window"]
        window.required = True
        return [window, by_key["ma_type"]]
    raise ValueError(f"알 수 없는 reentry 전략: {strategy!r}")


def range_str(spec: ParamSpec) -> str:
    """Human-readable bound hint, e.g. '>0, <100' or '≥1, ≤7'."""
    sym = {"gt": ">", "ge": "≥", "lt": "<", "le": "≤"}
    parts = [f"{sym[op]}{spec.bounds[op]}" for op in ("gt", "ge", "lt", "le") if op in spec.bounds]
    return ", ".join(parts) if parts else "제약 없음"


def _check_bounds(spec: ParamSpec, value: Any) -> None:
    b = spec.bounds
    if (
        ("gt" in b and not value > b["gt"])
        or ("ge" in b and not value >= b["ge"])
        or ("lt" in b and not value < b["lt"])
        or ("le" in b and not value <= b["le"])
    ):
        raise ValueError(f"{spec.key}={value}: 허용 범위 {range_str(spec)} 위반")


def parse_param_value(spec: ParamSpec, raw: str) -> Any:
    """Parse a raw string into the storage type (int/float/str), bounds-checked.

    Decimal params are stored as ``float`` to match existing config files and
    the ``set`` command; the loader re-coerces via ``Decimal(str(...))``.
    """
    raw = raw.strip()
    if spec.kind == "int":
        try:
            value: Any = int(raw)
        except ValueError as exc:
            raise ValueError(f"{spec.key}: 정수가 필요합니다 ({raw!r}).") from exc
        _check_bounds(spec, value)
        return value
    if spec.kind == "decimal":
        try:
            dval = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{spec.key}: 숫자가 필요합니다 ({raw!r}).") from exc
        _check_bounds(spec, dval)
        return float(dval)
    if spec.kind == "bool":
        low = raw.lower()
        if low in ("true", "yes", "y", "1"):
            return True
        if low in ("false", "no", "n", "0"):
            return False
        raise ValueError(f"{spec.key}: true/false 가 필요합니다 ({raw!r}).")
    return raw


# ---------------------------------------------------------------------------
# Interactive prompt helpers (stdlib input(); tests monkeypatch builtins.input)
# ---------------------------------------------------------------------------
_MAX_RETRY = 5


def _ask(prompt: str) -> str:
    return input(prompt)


# 파라미터 의미 + 영향도 (wizard UX 소유 — 범위/기본값은 introspect, 설명은 prose).
# 새 파라미터 추가 시 여기도 채울 것 (test_param_help_covers_all_specs 가 강제).
_PARAM_HELP: dict[str, str] = {
    # 선택지(전략 TYPE)
    "paradigm": "split=하락 분할매수+익절(추세장 유리) / dgt=그리드 자동매매"
    "(횡보 수확·MDD 방어, 강세장은 B&H 미달이 설계상 trade-off).",
    "allocation_policy": "종목 간 자본 배분. EQUAL=균등 / VOL=변동성 비례 / "
    "INV_VOL=역변동성(변동 큰 종목에 덜).",
    "buy_strategy": "매수 전략. price_drop=하락률 기준 분할매수 / "
    "support_level=지지선 기반 매수.",
    "sell_strategy": "매도 전략 (현재 profit_target=차수별 목표수익 익절만).",
    "reentry_strategy": "전량 매도 후 재진입 정책. hybrid=쿨다운 기반 / "
    "moving_average=이동평균 기반.",
    # 분할매수 파라미터
    "drop_threshold_pct": "전일 종가 대비 하락률 임계치(%). 이 값 이상 떨어진 날 "
    "분할 매수. 낮을수록 자주·일찍 매수(거래·분산↑), 높을수록 큰 하락에만.",
    "max_split_count": "최대 분할 횟수(1~7). 한 종목을 몇 번에 나눠 살지. 클수록 "
    "더 깊은 하락까지 대응(자본 분산), 작을수록 빨리 소진.",
    "per_split_amount": "1회 분할 매수 금액(KRW). 클수록 회당 비중↑(자본 빨리 소진), "
    "작을수록 잘게 분산.",
    "max_split_per_day": "하루 최대 분할 체결 수(기본 1=하루 한 번).",
    "profit_target_pct": "차수별 익절 목표 수익률(%). 각 매수분이 +이 % 도달 시 매도. "
    "낮을수록 자주 익절(회전↑·추세 못 먹음), 높을수록 길게 보유.",
    "max_sells_per_day": "하루 최대 매도 차수(기본 7=상한, 보통 그대로).",
    "cooldown_days": "전량 매도 후 재매수까지 대기일(0~365). 길수록 과매매 억제.",
    "window": "이동평균 재진입 판단 기간(일). moving_average 전용.",
    "ma_type": "이동평균 종류(sma 등). moving_average 전용.",
    # DGT 그리드 파라미터
    "grid_count": "그리드 레벨 수 n(≥2, 보통 11). 클수록 촘촘히 매매"
    "(회당 소량·거래 잦음), 작을수록 듬성.",
    "fallback_k": "변동성 산출 불가 시 격자 간격 비율(예 0.05=5%). 격자 한 칸 폭.",
    "rebalance_mode": "격자 재중심 방식. daily=매일 현재가 기준 재중심 / "
    "on_breach=격자 이탈 시에만.",
    "volatility_measure": "격자 폭 산출 지표. adr=일중 범위(갭 무시, 상승장 거래↑) / "
    "atr=갭 포함 변동성.",
    "atr_period": "변동성(ADR/ATR) 산출 기간(일, 기본 14). 길수록 격자 폭이 천천히 변함.",
    "multiplier": "변동성 x 이 배수 = 격자 간격 k. 클수록 넓어짐(거래 뜸·큰 변동만), "
    "작을수록 촘촘.",
    "k_min": "격자 간격 하한(예 0.005=0.5%). 너무 촘촘한 과매매 방지.",
    "k_max": "격자 간격 상한(예 0.05=5%). 너무 넓어 기회 놓침 방지.",
    "slope_gate": "추세 게이트 on/off. on이면 급등 시 매도·급락 시 매수 스킵(역행 억제).",
    "slope_gate_period": "추세 게이트 기울기 산출 기간(일).",
    "slope_gate_threshold": "추세 게이트 발동 기울기 임계치.",
    "volume_gate": "거래량 게이트 on/off. on이면 거래량 급증+상승 시 매도 스킵"
    "(수익 보유 연장), 급증+하락 시 매수 스킵.",
    "volume_gate_period": "거래량 평균 산출 기간(일, 기본 10/20).",
    "volume_gate_multiplier": "평균 거래량 x 이 배수 초과 시 '급증' 판정(예 1.5).",
    "profit_guard": "평단 이상에서만 매도. on이면 체결가가 가중평균 매수가 이하인 "
    "매도를 스킵(손실 실현 방지) — 가격이 평단 위로 회복할 때까지 보유.",
    "sell_cooldown_bars": "매도 후 N 거래일 매수 금지(0=off). 하락 재매수 연쇄·"
    "whipsaw 억제 → MDD 방어(권고 5). 강세장 상단은 일부 양보.",
    "price_based_reentry": "매도 후 *가격* 기준 재진입(on/off). on이면 직전 매도가 "
    "이상에선 매수 차단, 그 아래로 떨어지면 즉시 재진입. sell_cooldown_bars 와 "
    "AND 결합 시 둘 다 통과해야 매수.",
}


def _print_help(key: str) -> None:
    """프롬프트 직전, 해당 파라미터의 의미+영향 한 줄 안내 (있을 때만)."""
    desc = _PARAM_HELP.get(key)
    if desc:
        print(f"  ↳ {desc}")


def prompt_param(spec: ParamSpec, current: Any | None = None) -> Any:
    """Prompt for one parameter. Empty input keeps ``current`` (edit flow) or
    the schema default (wizard flow); required fields with neither re-ask.

    Bool fields → yes/no prompt; Literal fields → choice prompt (Enter=keep).
    각 파라미터 의미/영향은 입력 직전에 ``_PARAM_HELP`` 로 안내한다.
    """
    keep = current if current is not None else spec.default
    _print_help(spec.key)
    if spec.kind == "bool":
        return confirm(f"  {spec.key}", default=bool(keep))
    if spec.choices:
        default_choice = str(keep) if keep is not None else spec.choices[0]
        return prompt_choice(f"  {spec.key}", spec.choices, default_choice)
    keep_txt = f"현재 {current}" if current is not None else (
        f"기본 {spec.default}" if spec.default is not None else "필수"
    )
    label = f"  {spec.key} ({spec.kind} {range_str(spec)}) [{keep_txt}]: "
    for _ in range(_MAX_RETRY):
        raw = _ask(label).strip()
        if raw == "":
            if keep is not None:
                return keep
            print("    값이 필요합니다 (기본값 없음).", file=sys.stderr)
            continue
        try:
            return parse_param_value(spec, raw)
        except ValueError as exc:
            print(f"    ⚠ {exc} — 다시 입력하세요.", file=sys.stderr)
    raise ValueError(f"{spec.key}: 유효한 값 입력 실패 ({_MAX_RETRY}회 초과).")


def prompt_choice(label: str, choices: list[str], default: str) -> str:
    opts = "/".join(f"{c}*" if c == default else c for c in choices)
    for _ in range(_MAX_RETRY):
        raw = _ask(f"{label} ({opts}) [{default}]: ").strip()
        if raw == "":
            return default
        if raw in choices:
            return raw
        print(f"    ⚠ {choices} 중 선택하세요.", file=sys.stderr)
    raise ValueError(f"{label}: 유효한 선택 실패 ({_MAX_RETRY}회 초과).")


def confirm(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = _ask(f"{label} [{hint}]: ").strip().lower()
    if raw == "":
        return default
    return raw in ("y", "yes")


def collect_strategy_params(
    reentry_strategy: str,
    current: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Interactively gather buy/sell/reentry parameter dicts.

    ``current`` pre-fills prompts (the ``set`` edit flow); ``None`` = fresh
    wizard. The same uniform values are applied to every asset by the caller —
    per-asset divergence is blocked by the loader's uniformity rule.
    """
    cur = current or {}
    out: dict[str, dict[str, Any]] = {
        "buy_parameters": {},
        "sell_parameters": {},
        "reentry_parameters": {},
    }
    print("매수 파라미터:")
    for spec in buy_param_specs():
        out["buy_parameters"][spec.key] = prompt_param(
            spec, cur.get("buy_parameters", {}).get(spec.key)
        )
    print("매도 파라미터:")
    for spec in sell_param_specs():
        out["sell_parameters"][spec.key] = prompt_param(
            spec, cur.get("sell_parameters", {}).get(spec.key)
        )
    print(f"재진입 파라미터 ({reentry_strategy}):")
    for spec in reentry_param_specs(reentry_strategy):
        out["reentry_parameters"][spec.key] = prompt_param(
            spec, cur.get("reentry_parameters", {}).get(spec.key)
        )
    return out


def collect_grid_params() -> dict[str, Any]:
    """Interactively gather a DGT ``GridConfig`` as a grid_parameters dict.

    Required fields (grid_count / fallback_k) are always emitted; optional
    fields only when changed from the GridConfig default → minimal YAML.
    """
    print("그리드 파라미터 (Enter=기본값):")
    out: dict[str, Any] = {}
    for spec in grid_param_specs():
        value = prompt_param(spec)
        if spec.required or value != spec.default:
            out[spec.key] = value
    return out


# ---------------------------------------------------------------------------
# Command handlers (I/O glue)
# ---------------------------------------------------------------------------
def _warn_comment_loss(path: Path) -> None:
    if _file_has_comments(path):
        print(
            f"  참고: {path.name} 의 기존 주석은 pyyaml 재작성으로 제거됩니다.",
            file=sys.stderr,
        )


def cmd_list(args: argparse.Namespace) -> int:
    data = load_yaml(args.strategies)
    assets_data = load_assets_data(args.assets_yaml)
    print(format_list(data, assets_data))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    data = load_yaml(args.strategies)
    assets = _assets_map(data)
    if args.code:
        if args.code not in assets:
            print(f"종목 {args.code!r} 없음.", file=sys.stderr)
            return 1
        print(yaml.safe_dump({args.code: assets[args.code]}, allow_unicode=True, sort_keys=False))
    else:
        print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    data = load_yaml(args.strategies)
    assets_data = load_assets_data(args.assets_yaml)
    errors: list[str] = []
    try:
        load_strategy_config(args.strategies)
    except Exception as e:
        errors.append(f"strategies 스키마: {e}")
    try:
        load_asset_registry(args.assets_yaml)
    except Exception as e:
        errors.append(f"assets 스키마: {e}")
    errors.extend(cross_check(data, assets_data))
    if errors:
        print("검증 실패:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"검증 통과 ✓ ({args.strategies} + {args.assets_yaml})")
    return 0


def _print_meta_summary(meta: AssetMeta, lookup: LookupResult | None) -> None:
    """Show the resolved metadata before the write confirmation (batch check)."""
    print("─ 추가할 종목 ─", file=sys.stderr)
    print(f"  코드      : {meta.code}", file=sys.stderr)
    print(f"  종목명    : {meta.name}", file=sys.stderr)
    print(f"  시장      : {meta.market}", file=sys.stderr)
    print(f"  자산구분  : {meta.asset_class}", file=sys.stderr)
    note = ""
    if lookup is not None and lookup.earliest_date == meta.listed_at:
        # listed_at came from pykrx's data-start proxy — money-critical (§5.1).
        note = " (⚠ pykrx 데이터 시작일 — KRX/DART 공식 상장일 확인 권장)"
    print(f"  상장일    : {meta.listed_at}{note}", file=sys.stderr)
    if meta.tick_size is not None:
        print(f"  호가단위  : {meta.tick_size}", file=sys.stderr)


def _prompt_missing_meta(
    code: str,
    name: str,
    market: str | None,
    asset_class: str | None,
    listed_at: date | None,
) -> tuple[str, str, str, date]:
    """Fill any field pykrx could not auto-resolve, interactively."""
    if not name:
        name = _ask(f"  종목명 [{code}]: ").strip() or code
    if not market:
        market = prompt_choice("  시장", ["KOSPI", "KOSDAQ"], "KOSPI")
    if not asset_class:
        asset_class = prompt_choice("  자산구분", ["KR_ETF", "KR_STOCK"], "KR_STOCK")
    if not listed_at:
        for _ in range(_MAX_RETRY):
            raw = _ask("  상장일 YYYY-MM-DD (KRX/DART 확인): ").strip()
            try:
                listed_at = date.fromisoformat(raw)
                break
            except ValueError:
                print("    ⚠ YYYY-MM-DD 형식이 필요합니다.", file=sys.stderr)
        else:
            raise ValueError("상장일 입력 실패.")
    return name, market, asset_class, listed_at


def _make_asset_entry(
    name: str,
    enabled: bool,
    buy_strategy: str,
    sell_strategy: str,
    reentry_strategy: str,
    params: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Assemble one strategies.yaml asset entry from a TYPE + parameter set."""
    return {
        "name": name,
        "enabled": enabled,
        "buy_strategy": buy_strategy,
        "buy_parameters": dict(params["buy_parameters"]),
        "sell_strategy": sell_strategy,
        "sell_parameters": dict(params["sell_parameters"]),
        "reentry_strategy": reentry_strategy,
        "reentry_parameters": dict(params["reentry_parameters"]),
    }


def _prompt_first_entry(meta: AssetMeta, enabled: bool) -> dict[str, Any]:
    """Collect strategy TYPE + params for the first asset (no template to inherit).

    Reuses the same wizard prompts so a cold-start ``add`` and ``wizard`` stay
    behaviourally identical for the policy itself.
    """
    print("첫 종목 — 상속할 기존 종목이 없어 전략 정책을 입력받습니다:")
    buy_strategy = prompt_choice("매수 전략", BUY_STRATEGIES, BUY_STRATEGIES[0])
    sell_strategy = SELL_STRATEGIES[0]
    if len(SELL_STRATEGIES) > 1:  # pragma: no cover - single sell strategy today
        sell_strategy = prompt_choice("매도 전략", SELL_STRATEGIES, SELL_STRATEGIES[0])
    else:
        print(f"  매도 전략: {sell_strategy} (현재 유일)")
    reentry_strategy = prompt_choice("재진입 전략", REENTRY_STRATEGIES, "hybrid")
    params = collect_strategy_params(reentry_strategy)
    return _make_asset_entry(
        meta.name, enabled, buy_strategy, sell_strategy, reentry_strategy, params
    )


def cmd_add(args: argparse.Namespace) -> int:
    strategies_path = Path(args.strategies)
    assets_path = Path(args.assets_yaml)
    # Bootstrap-safe: a missing strategies file (cold start — no template to
    # inherit) is not an error here; the first asset's policy is collected
    # interactively below (data_missing → True).
    data_missing = not strategies_path.exists()
    data = {} if data_missing else load_yaml(strategies_path)
    assets_data = load_assets_data(assets_path)

    # 1) pykrx auto-fill (best-effort). Explicit flags always override.
    lookup = None if args.no_verify else pykrx_lookup(args.code)
    name = args.name or (lookup.name if lookup else "") or ""
    market = args.market or (lookup.market if lookup else None)
    asset_class = args.asset_class or (lookup.asset_class if lookup else None)
    if args.listed_at:
        listed_at: date | None = date.fromisoformat(args.listed_at)
    elif lookup is not None and lookup.earliest_date is not None:
        listed_at = lookup.earliest_date
    else:
        listed_at = None

    interactive = sys.stdin.isatty() and not args.yes

    # 2) Fill any remaining gaps: prompt when interactive, else require flags.
    if interactive:
        name, market, asset_class, listed_at = _prompt_missing_meta(
            args.code, name, market, asset_class, listed_at
        )
    missing = [
        flag
        for flag, value in (
            ("--name", name),
            ("--market", market),
            ("--asset-class", asset_class),
            ("--listed-at", listed_at),
        )
        if not value
    ]
    if missing:
        print(
            f"메타데이터 부족: {missing} — pykrx 자동 조회 실패 시 해당 플래그를 "
            "지정하거나 TTY 에서 대화식으로 입력하세요.",
            file=sys.stderr,
        )
        return 1

    meta = AssetMeta(
        code=args.code,
        market=market,
        asset_class=asset_class,
        listed_at=listed_at,
        name=name,
        tick_size=args.tick,
        lot_size=args.lot,
    )

    # 3) Cross-verification warnings (best-effort).
    if lookup is not None:
        for w in verify_asset_metadata(meta, lookup):
            print(f"  ⚠ {w}", file=sys.stderr)
    elif not args.no_verify:
        print(
            "  ⚠ pykrx 검증 불가 (네트워크 단절/미설치) — 종목명·시장·상장일을 "
            "KRX/DART 로 확인하세요.",
            file=sys.stderr,
        )

    # 4) Bootstrap detection: no asset exists yet to inherit a policy from
    #    (missing file OR a file with an empty assets map → cold start).
    existing_assets = data.get("assets") or {}
    bootstrap = not existing_assets
    if bootstrap and args.template is not None:
        print(
            f"--template {args.template!r} 를 상속할 수 없습니다 — 전략 파일에 "
            "종목이 없습니다 (첫 종목은 정책을 직접 입력).",
            file=sys.stderr,
        )
        return 1
    if bootstrap and not interactive:
        print(
            "첫 종목(상속할 기존 종목 없음)은 전략 정책 입력이 필요합니다 — "
            "TTY 에서 대화식으로 실행하거나 `wizard` 를 사용하세요 "
            "(--yes/비대화식 불가).",
            file=sys.stderr,
        )
        return 1

    # 5) Batch confirmation gate (interactive only; non-TTY/--yes skip → keeps
    #    CI and existing flag-driven invocations non-blocking).
    if interactive:
        _print_meta_summary(meta, lookup)
        if not confirm("이대로 추가할까요?", default=True):
            print("취소됨 — 파일 변경 없음.")
            return 0

    # 6) Build the strategy entry: inherit from a template, or — when this is
    #    the very first asset — collect the policy interactively.
    if bootstrap:
        if data_missing:
            allocation = prompt_choice("자본 배분 정책", ALLOCATION_POLICIES, "EQUAL")
            data = {"version": "0.5", "allocation_policy": allocation, "assets": {}}
        data.setdefault("assets", {})[meta.code] = _prompt_first_entry(
            meta, not args.disabled
        )
        policy_note = "전략 정책 신규 입력 (첫 종목)"
    else:
        template_code, template_entry = find_template_entry(data, args.template)
        add_strategy_entry(
            data, meta.code, meta.name, not args.disabled, template_entry
        )
        policy_note = f"전략은 {template_code!r} 정책 상속"
    add_asset_meta(assets_data, meta)

    # Validate the proposed result BEFORE writing anything (no partial writes).
    try:
        _validate_strategies(data)
        _validate_assets(assets_data)
    except Exception as e:
        print(f"검증 실패 — 파일을 변경하지 않았습니다: {e}", file=sys.stderr)
        return 1
    errors = cross_check(data, assets_data)
    if errors:
        print("교차검증 실패 — 파일을 변경하지 않았습니다:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    _warn_comment_loss(strategies_path)
    _warn_comment_loss(assets_path)
    _dump_yaml(strategies_path, data, _STRATEGIES_HEADER)
    _dump_yaml(assets_path, assets_data, _ASSETS_HEADER)
    print(
        f"추가됨 ✓ {meta.code} ({meta.name}) — {policy_note}, "
        f"메타데이터는 assets.yaml 기록. enabled={not args.disabled}."
    )
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    strategies_path = Path(args.strategies)
    data = load_yaml(strategies_path)
    remove_entry(data, args.code)
    try:
        _validate_strategies(data)
    except Exception as e:
        print(f"검증 실패 — 변경하지 않았습니다: {e}", file=sys.stderr)
        return 1
    _warn_comment_loss(strategies_path)
    _dump_yaml(strategies_path, data, _STRATEGIES_HEADER)
    print(f"제거됨 ✓ {args.code} (assets.yaml 메타데이터는 유지 — 필요 시 수동 정리).")
    return 0


def _toggle(args: argparse.Namespace, enabled: bool) -> int:
    strategies_path = Path(args.strategies)
    data = load_yaml(strategies_path)
    set_enabled(data, args.code, enabled)
    try:
        _validate_strategies(data)
    except Exception as e:
        print(f"검증 실패 — 변경하지 않았습니다: {e}", file=sys.stderr)
        return 1
    _warn_comment_loss(strategies_path)
    _dump_yaml(strategies_path, data, _STRATEGIES_HEADER)
    print(f"{'활성화' if enabled else '비활성화'} ✓ {args.code}.")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    return _toggle(args, True)


def cmd_disable(args: argparse.Namespace) -> int:
    return _toggle(args, False)


def _cmd_set_interactive(
    args: argparse.Namespace, data: dict[str, Any], strategies_path: Path
) -> int:
    """Interactively retune the uniform policy (Enter keeps the current value)."""
    assets = _assets_map(data)
    if args.all:
        targets = list(assets)
    elif args.code:
        if args.code not in assets:
            print(f"종목 {args.code!r} 이(가) 전략 파일에 없습니다.", file=sys.stderr)
            return 1
        targets = [args.code]
    else:
        print("오류: --all 또는 --code 를 지정하세요.", file=sys.stderr)
        return 1

    ref = assets[targets[0]]
    reentry_strategy = ref.get("reentry_strategy", "hybrid")
    current = {
        "buy_parameters": ref.get("buy_parameters", {}),
        "sell_parameters": ref.get("sell_parameters", {}),
        "reentry_parameters": ref.get("reentry_parameters", {}),
    }
    print(f"대화식 파라미터 편집 — 대상 {targets} (Enter = 현재값 유지)")
    params = collect_strategy_params(reentry_strategy, current)

    for code in targets:
        for section, values in params.items():
            assets[code].setdefault(section, {})
            for key, value in values.items():
                assets[code][section][key] = value

    try:
        _validate_strategies(data)
    except Exception as e:
        print(
            f"검증 실패 — 변경하지 않았습니다 (종목별 차등은 "
            f"allow_per_asset_params: true 필요): {e}",
            file=sys.stderr,
        )
        return 1
    _warn_comment_loss(strategies_path)
    _dump_yaml(strategies_path, data, _STRATEGIES_HEADER)
    print(f"설정됨 ✓ {targets} 파라미터 갱신.")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    strategies_path = Path(args.strategies)
    data = load_yaml(strategies_path)
    if getattr(args, "interactive", False):
        return _cmd_set_interactive(args, data, strategies_path)
    if not args.param or args.value is None:
        print(
            "오류: --param 과 --value 가 필요합니다 (또는 --interactive).",
            file=sys.stderr,
        )
        return 1
    targets = set_param(data, args.param, args.value, args.code, args.all)
    try:
        _validate_strategies(data)
    except Exception as e:
        print(
            f"검증 실패 — 변경하지 않았습니다 (균일성 위반 시 "
            f"allow_per_asset_params: true 필요): {e}",
            file=sys.stderr,
        )
        return 1
    _warn_comment_loss(strategies_path)
    _dump_yaml(strategies_path, data, _STRATEGIES_HEADER)
    print(f"설정됨 ✓ {args.param}={args.value} → {targets}.")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    dest = Path(args.dest)
    if dest.exists():
        print(f"대상 파일이 이미 존재합니다: {dest}", file=sys.stderr)
        return 1
    data = load_yaml(args.from_path)
    try:
        _validate_strategies(data)
    except Exception as e:
        print(f"원본 검증 실패 — 생성하지 않았습니다: {e}", file=sys.stderr)
        return 1
    _dump_yaml(dest, data, _STRATEGIES_HEADER)
    print(f"생성됨 ✓ {dest} ({args.from_path} 복제).")
    return 0


def _prompt_asset_codes(codes: list[str]) -> list[str]:
    """Pick which registered codes to include ('all' or a comma list)."""
    for _ in range(_MAX_RETRY):
        raw = _ask("포함할 종목 (쉼표 구분, 'all'=전체) [all]: ").strip()
        if raw == "" or raw.lower() == "all":
            return list(codes)
        picked = [c.strip() for c in raw.split(",") if c.strip()]
        unknown = [c for c in picked if c not in codes]
        if unknown:
            print(
                f"    ⚠ assets.yaml 미등록 종목: {unknown} — 먼저 add 로 등록하세요.",
                file=sys.stderr,
            )
            continue
        if picked:
            return picked
    return []


def _wizard_setup(
    args: argparse.Namespace,
) -> tuple[Path, dict[str, Any], list[str]] | int:
    """Shared wizard preamble: validate dest + load registered codes.

    Returns ``(dest, assets_data, codes)`` or an ``int`` exit code on failure.
    """
    dest = Path(args.dest)
    if dest.exists():
        print(f"대상 파일이 이미 존재합니다: {dest}", file=sys.stderr)
        return 1
    assets_data = load_assets_data(args.assets_yaml)
    codes = sorted(available_codes(assets_data))
    if not codes:
        print(
            f"assets.yaml 에 등록된 종목이 없습니다 ({args.assets_yaml}) — "
            "먼저 add 로 종목을 등록하세요.",
            file=sys.stderr,
        )
        return 1
    return dest, assets_data, codes


def _wizard_split(
    dest: Path, assets_data: dict[str, Any], codes: list[str]
) -> int:
    """분할매수(PriceDrop/SupportLevel) strategies.yaml 대화식 생성.

    Defaults/ranges are introspected from the loader schemas (drift zero).
    Per-asset divergence is unsupported (loader uniformity §7.3) — use `set`
    + ``allow_per_asset_params: true`` for that.
    """
    print(f"등록된 종목: {', '.join(codes)}")
    _print_help("allocation_policy")
    allocation = prompt_choice("자본 배분 정책", ALLOCATION_POLICIES, "EQUAL")
    _print_help("buy_strategy")
    buy_strategy = prompt_choice("매수 전략", BUY_STRATEGIES, BUY_STRATEGIES[0])
    sell_strategy = SELL_STRATEGIES[0]
    if len(SELL_STRATEGIES) == 1:
        print(f"  매도 전략: {sell_strategy} (현재 유일)")
    else:  # pragma: no cover - single sell strategy today
        sell_strategy = prompt_choice("매도 전략", SELL_STRATEGIES, SELL_STRATEGIES[0])
    _print_help("reentry_strategy")
    reentry_strategy = prompt_choice("재진입 전략", REENTRY_STRATEGIES, "hybrid")

    params = collect_strategy_params(reentry_strategy)

    chosen = _prompt_asset_codes(codes)
    if not chosen:
        print("종목을 하나 이상 선택해야 합니다 — 생성하지 않았습니다.", file=sys.stderr)
        return 1

    data: dict[str, Any] = {
        "version": "0.5",
        "allocation_policy": allocation,
        "assets": {},
    }
    for code in chosen:
        data["assets"][code] = _make_asset_entry(
            assets_data["assets"][code].get("name", code),
            True,
            buy_strategy,
            sell_strategy,
            reentry_strategy,
            params,
        )

    try:
        _validate_strategies(data)
    except Exception as e:
        print(f"검증 실패 — 생성하지 않았습니다: {e}", file=sys.stderr)
        return 1
    errors = cross_check(data, assets_data)
    if errors:
        print("교차검증 실패 — 생성하지 않았습니다:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    _dump_yaml(dest, data, _STRATEGIES_HEADER)
    print(
        f"생성됨 ✓ {dest} — {len(chosen)} 종목 (분할매수), "
        f"{buy_strategy}/{sell_strategy}/{reentry_strategy}, allocation={allocation}. "
        f"'trading backtest --config {dest} --csv CODE=path' 로 구동."
    )
    return 0


def _wizard_grid(
    dest: Path, assets_data: dict[str, Any], codes: list[str]
) -> int:
    """DGT grid config 대화식 생성 (ADR 0022 §11 D15).

    strategies.yaml 과 분리된 grid 전용 config. GridConfig 를 introspect 해
    기본값·범위·Literal·bool 을 안내(drift zero). 선택 종목에 동일 GridConfig
    적용(종목별 차등은 파일 직접 편집 — grid 로더는 균일성 강제 없음).
    """
    print(f"등록된 종목: {', '.join(codes)}")
    grid_params = collect_grid_params()
    chosen = _prompt_asset_codes(codes)
    if not chosen:
        print("종목을 하나 이상 선택해야 합니다 — 생성하지 않았습니다.", file=sys.stderr)
        return 1

    data: dict[str, Any] = {"version": "1.0", "assets": {}}
    for code in chosen:
        data["assets"][code] = {
            "name": assets_data["assets"][code].get("name", code),
            "enabled": True,
            "grid_parameters": dict(grid_params),
        }

    try:
        _validate_grid(data)
    except Exception as e:
        print(f"검증 실패 — 생성하지 않았습니다: {e}", file=sys.stderr)
        return 1

    _dump_yaml(dest, data, _GRID_HEADER)
    print(
        f"생성됨 ✓ {dest} — {len(chosen)} 종목 (DGT grid). "
        f"'trading grid-backtest --config {dest} --csv CODE=path' 로 구동."
    )
    return 0


def cmd_wizard(args: argparse.Namespace) -> int:
    """새 config 를 대화식 생성 — 전략 종류(분할매수/DGT)를 먼저 고르고 분기.

    DGT 는 매수/매도가 한 엔진이라 분할매수와 다른 파일(grid)·명령(grid-backtest)
    을 쓴다(ADR 0022 §11). 이 입구에서 분기해 알맞은 config 를 생성한다 —
    사용자가 grid-wizard 존재를 몰라도 wizard 한 번으로 DGT 까지 도달한다.
    """
    setup = _wizard_setup(args)
    if isinstance(setup, int):
        return setup
    dest, assets_data, codes = setup
    print(f"새 config 생성: {dest}")
    _print_help("paradigm")
    paradigm = prompt_choice(
        "전략 종류 (split=분할매수 PriceDrop / dgt=그리드 DGT)",
        ["split", "dgt"],
        "split",
    )
    if paradigm == "dgt":
        return _wizard_grid(dest, assets_data, codes)
    return _wizard_split(dest, assets_data, codes)


def cmd_grid_wizard(args: argparse.Namespace) -> int:
    """grid-wizard = wizard 의 DGT 분기 직행 단축 명령 (ADR 0022 §11 D15)."""
    setup = _wizard_setup(args)
    if isinstance(setup, int):
        return setup
    dest, assets_data, codes = setup
    print(f"새 DGT grid config 생성: {dest}")
    return _wizard_grid(dest, assets_data, codes)


def cmd_diff(args: argparse.Namespace) -> int:
    print(format_diff(load_yaml(args.file_a), load_yaml(args.file_b)))
    return 0


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="manage_strategies",
        description="strategies*.yaml + assets.yaml 관리 도구",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_assets_yaml(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--assets-yaml",
            default=str(_DEFAULT_ASSETS_YAML),
            help="assets.yaml 경로 (기본 config/assets.yaml)",
        )

    sp = sub.add_parser("list", help="종목 요약 표")
    sp.add_argument("strategies")
    add_assets_yaml(sp)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="전체/단일 종목 상세")
    sp.add_argument("strategies")
    sp.add_argument("--code")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("validate", help="로더 검증 + 레지스트리 정합성")
    sp.add_argument("strategies")
    add_assets_yaml(sp)
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser(
        "add",
        help="종목 추가 (메타데이터 pykrx 자동 조회 + 일괄 확인 + 전략 상속)",
    )
    sp.add_argument("strategies")
    sp.add_argument("--code", required=True)
    # market/asset-class/listed-at/name 은 pykrx 로 자동 채움 → 모두 선택적.
    # 플래그를 주면 자동값을 덮어쓰고, 자동 조회 실패 시에만 필요해진다.
    sp.add_argument("--market", choices=["KOSPI", "KOSDAQ"], help="생략 시 pykrx 자동")
    sp.add_argument(
        "--asset-class", choices=["KR_ETF", "KR_STOCK"], help="생략 시 pykrx 자동"
    )
    sp.add_argument("--listed-at", help="상장일 YYYY-MM-DD (생략 시 pykrx 데이터 시작일 제안)")
    sp.add_argument("--name", help="종목명 (생략 시 pykrx 자동 채움)")
    sp.add_argument("--tick", type=float, help="호가단위 (생략 시 클래스 기본값)")
    sp.add_argument("--lot", type=float, default=1, help="매매단위 (기본 1)")
    sp.add_argument("--template", help="정책을 상속할 기준 종목코드")
    sp.add_argument("--disabled", action="store_true", help="비활성 상태로 추가")
    sp.add_argument("--no-verify", action="store_true", help="pykrx 검증/자동조회 생략")
    sp.add_argument(
        "--yes", action="store_true", help="TTY 일괄 확인 프롬프트 생략 (비대화식/CI)"
    )
    add_assets_yaml(sp)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("remove", help="종목 제거")
    sp.add_argument("strategies")
    sp.add_argument("--code", required=True)
    sp.set_defaults(func=cmd_remove)

    sp = sub.add_parser("enable", help="종목 활성화")
    sp.add_argument("strategies")
    sp.add_argument("--code", required=True)
    sp.set_defaults(func=cmd_enable)

    sp = sub.add_parser("disable", help="종목 비활성화")
    sp.add_argument("strategies")
    sp.add_argument("--code", required=True)
    sp.set_defaults(func=cmd_disable)

    sp = sub.add_parser("set", help="파라미터 변경 (--param/--value 또는 --interactive)")
    sp.add_argument("strategies")
    sp.add_argument("--param", help="buy.<k> / sell.<k> / reentry.<k>")
    sp.add_argument("--value")
    sp.add_argument(
        "--interactive",
        action="store_true",
        help="범위·기본값 안내와 함께 파라미터를 대화식으로 편집",
    )
    grp = sp.add_mutually_exclusive_group(required=True)
    grp.add_argument("--code")
    grp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("new", help="새 전략 파일 생성 (복제)")
    sp.add_argument("dest")
    sp.add_argument("--from", dest="from_path", required=True, help="복제 원본")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser(
        "wizard",
        help="새 config 대화식 생성 — 전략 종류(분할매수/DGT) 분기 + 범위 안내",
    )
    sp.add_argument("dest")
    add_assets_yaml(sp)
    sp.set_defaults(func=cmd_wizard)

    sp = sub.add_parser(
        "grid-wizard",
        help="DGT grid config 직행 생성 (= wizard 의 dgt 분기 단축)",
    )
    sp.add_argument("dest")
    add_assets_yaml(sp)
    sp.set_defaults(func=cmd_grid_wizard)

    sp = sub.add_parser("diff", help="두 전략 파일 비교")
    sp.add_argument("file_a")
    sp.add_argument("file_b")
    sp.set_defaults(func=cmd_diff)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
