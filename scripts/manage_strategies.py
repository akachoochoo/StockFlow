#!/usr/bin/env python
"""scripts/manage_strategies.py — strategies*.yaml + assets.yaml 관리 CLI.

종목(asset) 추가/관리를 코드 수정 없이 하기 위한 운영 도구. 두 데이터 파일을
함께 다룬다:

  - ``config/strategies*.yaml`` : 종목별 매수/매도/재진입 전략 + 파라미터.
  - ``config/assets.yaml``      : 종목 메타데이터(시장/호가/상장일 등). Phase
    1.1 data-driven 레지스트리 — ``composition.asset_from_code`` 가 하드코딩
    ``_ASSET_FACTORIES`` 미스 시 여기서 조회한다.

명령::

    uv run python scripts/manage_strategies.py list     <strategies.yaml>
    uv run python scripts/manage_strategies.py show     <strategies.yaml> [--code C]
    uv run python scripts/manage_strategies.py validate <strategies.yaml>
    uv run python scripts/manage_strategies.py add      <strategies.yaml> \
        --code C --market KOSPI --asset-class KR_STOCK --listed-at YYYY-MM-DD \
        [--name N] [--tick T] [--lot L] [--template CODE] \
        [--disabled] [--no-verify] [--assets-yaml PATH]
    uv run python scripts/manage_strategies.py remove   <strategies.yaml> --code C
    uv run python scripts/manage_strategies.py enable   <strategies.yaml> --code C
    uv run python scripts/manage_strategies.py disable  <strategies.yaml> --code C
    uv run python scripts/manage_strategies.py set      <strategies.yaml> \
        --param buy.drop_threshold_pct --value 6.0 [--code C | --all]
    uv run python scripts/manage_strategies.py new      <dest.yaml> --from <src.yaml>
    uv run python scripts/manage_strategies.py diff     <a.yaml> <b.yaml>

설계 노트:
  - 검증은 실제 로더(``load_strategy_config`` / ``load_asset_registry``)를
    재사용한다 — 스키마를 재구현하지 않으므로 drift 가 없다.
  - ``add`` 는 strategies + assets 양쪽을 갱신하기 **전에** 임시 파일로 검증해
    실패 시 어떤 파일도 건드리지 않는다 (부분 쓰기 방지).
  - ``add --verify`` (기본 ON) 는 pykrx 로 종목명/시장/데이터 가용성을 교차
    확인한다 (best-effort — 네트워크/미설치 시 경고 후 진행). ``listed_at`` 은
    pykrx 가 아니라 사용자 입력 + 경고로 다룬다(KRX/DART 공식 자료 확인 권장,
    verify_phase_0_9_assets.py 규율 정합).
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
from pathlib import Path
from typing import Any

import yaml

# Run-as-script: put repo root on sys.path so ``from src...`` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.cli.composition import _ASSET_FACTORIES  # noqa: E402
from src.infrastructure.yaml_asset_loader import (  # noqa: E402
    load_asset_registry,
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

    name = ""
    for getter in ("get_market_ticker_name", "get_etf_ticker_name"):
        try:
            candidate = getattr(stock, getter)(code) or ""
        except Exception:
            candidate = ""
        if candidate:
            name = candidate
            break

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
        found=bool(name), name=name, market=market, earliest_date=earliest
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
    if meta.code in _ASSET_FACTORIES:
        raise ValueError(
            f"종목 {meta.code!r} 은(는) 이미 하드코딩 레지스트리에 있습니다 "
            "(composition._ASSET_FACTORIES) — assets.yaml 추가 불필요."
        )
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


def available_codes(assets_data: dict[str, Any]) -> set[str]:
    """All resolvable codes: union of hardcoded registry and assets.yaml."""
    return set(_ASSET_FACTORIES) | set(assets_data.get("assets", {}))


def cross_check(
    strategies_data: dict[str, Any], assets_data: dict[str, Any]
) -> list[str]:
    """Every code in strategies must resolve to Asset metadata. Returns errors."""
    resolvable = available_codes(assets_data)
    errors: list[str] = []
    for code in _assets_map(strategies_data):
        if code not in resolvable:
            errors.append(
                f"종목 {code!r}: Asset 메타데이터 없음 — assets.yaml 에 add "
                "하거나 composition._ASSET_FACTORIES 에 등록 필요."
            )
    return errors


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _registry_tag(code: str, assets_data: dict[str, Any]) -> str:
    if code in _ASSET_FACTORIES:
        return "하드코딩"
    if code in assets_data.get("assets", {}):
        return "assets.yaml"
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


def cmd_add(args: argparse.Namespace) -> int:
    strategies_path = Path(args.strategies)
    assets_path = Path(args.assets_yaml)
    data = load_yaml(strategies_path)
    assets_data = load_assets_data(assets_path)

    meta = AssetMeta(
        code=args.code,
        market=args.market,
        asset_class=args.asset_class,
        listed_at=date.fromisoformat(args.listed_at),
        name=args.name or "",
        tick_size=args.tick,
        lot_size=args.lot,
    )

    # pykrx cross-verification (best-effort).
    if not args.no_verify:
        result = pykrx_lookup(meta.code)
        if result is not None and result.name and not meta.name:
            meta.name = result.name
            print(f"  pykrx: 종목명 자동 채움 → {meta.name!r}")
        for w in verify_asset_metadata(meta, result):
            print(f"  ⚠ {w}", file=sys.stderr)

    if not meta.name:
        print(
            "종목명을 확인할 수 없습니다 — --name 으로 지정하거나 검증을 "
            "켜고(--no-verify 제거) 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1

    template_code, template_entry = find_template_entry(data, args.template)
    add_strategy_entry(
        data, meta.code, meta.name, not args.disabled, template_entry
    )
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
        f"추가됨 ✓ {meta.code} ({meta.name}) — 전략은 {template_code!r} 정책 상속, "
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


def cmd_set(args: argparse.Namespace) -> int:
    strategies_path = Path(args.strategies)
    data = load_yaml(strategies_path)
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

    sp = sub.add_parser("add", help="종목 추가 (전략 + 메타데이터 + pykrx 검증)")
    sp.add_argument("strategies")
    sp.add_argument("--code", required=True)
    sp.add_argument("--market", required=True, choices=["KOSPI", "KOSDAQ"])
    sp.add_argument(
        "--asset-class", required=True, choices=["KR_ETF", "KR_STOCK"]
    )
    sp.add_argument("--listed-at", required=True, help="상장일 YYYY-MM-DD")
    sp.add_argument("--name", help="종목명 (생략 시 pykrx 자동 채움)")
    sp.add_argument("--tick", type=float, help="호가단위 (생략 시 클래스 기본값)")
    sp.add_argument("--lot", type=float, default=1, help="매매단위 (기본 1)")
    sp.add_argument("--template", help="정책을 상속할 기준 종목코드")
    sp.add_argument("--disabled", action="store_true", help="비활성 상태로 추가")
    sp.add_argument("--no-verify", action="store_true", help="pykrx 검증 생략")
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

    sp = sub.add_parser("set", help="파라미터 변경")
    sp.add_argument("strategies")
    sp.add_argument(
        "--param", required=True, help="buy.<k> / sell.<k> / reentry.<k>"
    )
    sp.add_argument("--value", required=True)
    grp = sp.add_mutually_exclusive_group(required=True)
    grp.add_argument("--code")
    grp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("new", help="새 전략 파일 생성 (복제)")
    sp.add_argument("dest")
    sp.add_argument("--from", dest="from_path", required=True, help="복제 원본")
    sp.set_defaults(func=cmd_new)

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
