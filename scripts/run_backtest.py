#!/usr/bin/env python
"""scripts/run_backtest.py — 데이터 자동 확보 + 백테스트 파이프라인.

한 줄로: config 의 종목들 데이터를 (없으면) 받아서 백테스트까지 실행한다.

    uv run python scripts/run_backtest.py --config config/my.yaml \
        --start 2025-12-02 --end 2026-05-20 --capital 10000000

동작:
  1. config(분할매수/DGT 무관)에서 enabled 종목코드를 읽는다.
  2. 각 종목의 ``[start,end]`` CSV 가 없으면 pykrx 로 다운로드한다(있으면 스킵).
  3. ``trading backtest --config ... --csv CODE=path ...`` 로 위임 — config 종류에
     따라 분할매수/DGT 로 자동 라우팅(ADR 0022 §11.7)된다.

설계 (CLAUDE.md §0.3 / §1.1): 네트워크(pykrx)는 본 CLI(``trading``)가 아니라
**scripts/ 오케스트레이션**에만 둔다. 본 스크립트는 기존 `download_kr_assets`
(다운로드)와 `trading` CLI(백테스트) 두 도구를 잇는 얇은 파이프라인일 뿐이며,
도메인/앱 코드는 건드리지 않는다. 다운로드·실행 단계는 주입 가능(테스트는
네트워크 없이 fake 주입).
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import yaml

# Run-as-script: repo root on sys.path so ``from src...`` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.infrastructure.asset_csv import derive_csv_path  # noqa: E402

# Injection seams (tests override; defaults touch network / run the real CLI).
Downloader = Callable[[str, date, date, Path], None]
Runner = Callable[[list[str]], int]
Reporter = Callable[..., None]


def _krw(amount: int) -> Any:
    from src.domain.models import Currency, Money

    return Money(amount=__import__("decimal").Decimal(amount), currency=Currency.KRW)


class _MarkerView:
    """Adapt a domain GridTrade to the duck-type _serialize_markers expects
    (``trade_date`` / ``side`` / ``grid_level_price``)."""

    def __init__(self, trade: Any) -> None:
        self.trade_date = trade.trade_date
        self.side = "BUY" if str(trade.side) in ("BUY", "OrderSide.BUY") else (
            trade.side.value if hasattr(trade.side, "value") else str(trade.side)
        )
        self.grid_level_price = trade.level_price


def build_dgt_chart_html(asset: Any, bars: list[Any], config: Any, result: Any) -> str:
    """도메인 GridRunResult → lightweight-charts 인터랙티브 HTML.

    캔들 + 거래량 + 매수/매도 마커 + 초기 그리드 라인. 시변(time-varying) 그리드
    엔벨로프는 research 결과 shape 의존이라 본 버전에서는 제외(초기 그리드만).
    """
    from html import escape

    from src.domain.strategies.grid_math import adaptive_k, grid_levels
    from src.research.dgt._interactive_chart import (
        _serialize_grid_levels,
        _serialize_markers,
        _serialize_ohlcv,
        _serialize_volume,
        build_interactive_chart_html,
    )

    date_set = {b.trade_date.strftime("%Y-%m-%d") for b in bars}
    markers = _serialize_markers([_MarkerView(t) for t in result.trades], date_set)

    reference = bars[0].close
    k0 = adaptive_k(
        bars, 0, reference,
        period=config.atr_period, multiplier=config.multiplier,
        k_min=config.k_min, k_max=config.k_max, fallback_k=config.fallback_k,
        measure=config.volatility_measure,
    )
    levels = grid_levels(config.grid_count, reference, k0, config.levels_above)
    # _serialize_grid_levels is duck-typed (dict or object) — use a dict.
    grid_artifact = {"grid_levels": list(levels), "reference_price": reference}

    return build_interactive_chart_html(
        title=f"{escape(asset.name)} ({escape(asset.code)}) — DGT 백테스트",
        ohlcv=_serialize_ohlcv(bars),
        volume=_serialize_volume(bars),
        marker_groups=[{"label": asset.code, "markers": markers}],
        grid_levels=_serialize_grid_levels(grid_artifact),
    )


def _report_grid(
    config_path: Path, csv_map: dict[str, Path], start: date, end: date,
    capital: int, report_dir: Path,
) -> None:
    """DGT config → 종목별 인터랙티브 차트 HTML 생성."""
    from src.application.grid_portfolio_backtest import (
        GridAssetInput,
        run_grid_portfolio,
    )
    from src.cli import composition
    from src.infrastructure.csv_market_data_loader import load_ohlcv_csv
    from src.infrastructure.yaml_grid_config_loader import load_grid_config

    enabled = [
        (c, b) for c, b in load_grid_config(config_path).items() if b.enabled
    ]
    inputs: list[Any] = []
    metas: list[tuple] = []
    for code, bundle in enabled:
        asset = composition.asset_from_code(code)
        bars = [
            bar
            for bar in load_ohlcv_csv(csv_map[code], asset)
            if start <= bar.trade_date <= end
        ]
        if not bars:
            print(f"  [{code}] 기간 데이터 없음 — 차트 스킵", file=sys.stderr)
            continue
        inputs.append(GridAssetInput(asset=asset, bars=bars, config=bundle.config))
        metas.append((asset, bars, bundle.config))
    if not inputs:
        return
    port = run_grid_portfolio(inputs, initial_capital=_krw(capital))
    report_dir.mkdir(parents=True, exist_ok=True)
    for (asset, bars, cfg), run in zip(metas, port.per_asset, strict=True):
        html = build_dgt_chart_html(asset, bars, cfg, run.result)
        out = report_dir / f"{asset.code}.html"
        out.write_text(html, encoding="utf-8")
        print(f"  인터랙티브 차트: {out}")


def _report_split(
    config_path: Path, csv_map: dict[str, Path], start: date, end: date,
    capital: int, report_dir: Path,
) -> None:
    """분할매수 config → drawdown episode HTML 리포트 생성."""
    import click

    from src.application.backtest_runner import BacktestRunner
    from src.application.reporting.report import generate_episode_report
    from src.cli.main import (
        _resolve_assets_and_bars,
        _resolve_per_asset_overrides,
        _resolve_strategy_configs,
    )
    from src.cli.main import (
        main as _trading_main,
    )

    codes, buy_config, sell_config, reentry_name, reentry_params, buy_name = (
        _resolve_strategy_configs(
            click.Context(_trading_main), config_path,
            drop_pct="5.0", max_split=7, per_split_amount=500000,
            max_split_per_day=1, profit_target_pct="10.0", max_sells_per_day=7,
            reentry_strategy="hybrid", cooldown_days=60,
        )
    )
    assets, ohlcv_by_asset = _resolve_assets_and_bars(
        codes, {code: csv_map[code] for code in codes}
    )
    result = BacktestRunner(
        assets=assets,
        strategy_config=buy_config,
        buy_strategy_name=buy_name,
        sell_strategy_config=sell_config,
        reentry_strategy_name=reentry_name,
        reentry_parameters=reentry_params,
        initial_capital=_krw(capital),
        ohlcv_by_asset=ohlcv_by_asset,
        per_asset_overrides=_resolve_per_asset_overrides(config_path),
    ).run(start, end)
    rep = generate_episode_report(
        backtest_result=result,
        strategy_id=buy_name,
        output_dir=report_dir,
        bars_by_asset={a.code: ohlcv_by_asset[a] for a in assets},
    )
    print(f"  episode 리포트: {rep.index_html_path} ({len(rep.episodes)} 구간)")


def _default_reporter(
    config_path: Path, csv_map: dict[str, Path], start: date, end: date,
    capital: int, report_dir: Path,
) -> None:
    """config 종류에 맞는 리포트 생성 (DGT 인터랙티브 / split episode HTML)."""
    from src.cli.main import _detect_config_kind

    if _detect_config_kind(config_path) == "grid":
        _report_grid(config_path, csv_map, start, end, capital, report_dir)
    else:
        _report_split(config_path, csv_map, start, end, capital, report_dir)


def enabled_codes(config_path: Path | str) -> list[str]:
    """config(분할매수/DGT 공통: ``assets: {code: {...}}``)에서 enabled 종목코드."""
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    assets = raw.get("assets") if isinstance(raw, dict) else None
    if not isinstance(assets, dict) or not assets:
        raise ValueError(f"{config_path} 에 assets 가 없습니다.")
    return [
        code
        for code, entry in assets.items()
        if (entry or {}).get("enabled", True)
    ]


def csv_path_for(
    code: str, start: date, end: date, data_dir: Path | None
) -> Path:
    """다운로드/백테스트가 합의하는 CSV 경로. ``data_dir`` 미지정 시 기본 위치."""
    full = derive_csv_path(code, start, end)
    return full if data_dir is None else data_dir / full.name


def _default_downloader(
    code: str, start: date, end: date, out_path: Path
) -> None:
    """실제 pykrx 다운로드 (지연 import — 네트워크 필요 시점까지 미로드)."""
    from scripts.download_kr_assets import download, resolve_target

    ticker, resolved_out, _asset = resolve_target(
        code=code, ticker=None, out=out_path, start=start, end=end
    )
    rows = download(start, end, ticker, resolved_out)
    print(f"  다운로드 완료: {resolved_out} ({rows} 행)")


def _default_runner(args: list[str]) -> int:
    """본 ``trading`` CLI 를 인-프로세스 실행 (백테스트 위임)."""
    import click

    from src.cli.main import main as trading_main

    try:
        trading_main(args, standalone_mode=False)
        return 0
    except SystemExit as exc:  # kill switch 등
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code


def ensure_data(
    code: str,
    start: date,
    end: date,
    *,
    data_dir: Path | None,
    downloader: Downloader,
) -> Path:
    """CSV 가 있으면 그대로, 없으면 다운로드 후 경로 반환."""
    csv = csv_path_for(code, start, end, data_dir)
    if csv.exists():
        print(f"데이터 있음: {code} → {csv}")
        return csv
    print(f"데이터 없음: {code} [{start} ~ {end}] → 다운로드합니다…")
    downloader(code, start, end, csv)
    return csv


def run_pipeline(
    config_path: Path,
    start: date,
    end: date,
    capital: int,
    *,
    as_json: bool = False,
    data_dir: Path | None = None,
    report_dir: Path | None = None,
    report: bool = True,
    downloader: Downloader = _default_downloader,
    runner: Runner = _default_runner,
    reporter: Reporter = _default_reporter,
) -> int:
    """데이터 확보 → ``trading backtest`` 위임 → (기본) 리포트/차트 생성.

    ``report=True`` (기본): 백테스트 후 결과로 인터랙티브 차트(DGT) 또는 episode
    HTML(split)을 ``report_dir`` 에 생성한다. config 종류는 자동 판별.
    """
    codes = enabled_codes(config_path)
    if not codes:
        print(f"{config_path} 에 enabled 종목이 없습니다.", file=sys.stderr)
        return 1

    csv_map: dict[str, Path] = {}
    csv_args: list[str] = []
    for code in codes:
        csv = ensure_data(
            code, start, end, data_dir=data_dir, downloader=downloader
        )
        csv_map[code] = csv
        csv_args += ["--csv", f"{code}={csv}"]

    args = [
        "backtest",
        "--config",
        str(config_path),
        *csv_args,
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--capital",
        str(capital),
    ]
    if as_json:
        args.append("--json")
    print(f"실행: trading {' '.join(args)}")
    rc = runner(args)
    if rc != 0 or not report:
        return rc

    rdir = report_dir or (
        _REPO_ROOT / "reports"
        / f"{config_path.stem}_{start.isoformat()}_{end.isoformat()}"
    )
    print(f"리포트 생성 → {rdir}")
    reporter(config_path, csv_map, start, end, capital, rdir)
    return rc


def _parse_iso(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid YYYY-MM-DD: {s!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_backtest",
        description="데이터 자동 확보 + 백테스트 파이프라인 (분할매수/DGT 공통)",
    )
    p.add_argument("--config", required=True, help="strategies/grid config YAML")
    p.add_argument("--start", required=True, type=_parse_iso, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, type=_parse_iso, help="YYYY-MM-DD")
    p.add_argument("--capital", type=int, default=10_000_000, help="초기 KRW 자본")
    p.add_argument("--json", action="store_true", help="백테스트 JSON 출력")
    p.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="CSV 저장 디렉터리 (기본 data/historical)",
    )
    p.add_argument(
        "--report-dir",
        type=Path,
        default=None,
        help="리포트/차트 출력 디렉터리 (기본 reports/<config>_<start>_<end>)",
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="백테스트 후 차트/리포트 생성 생략",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_pipeline(
            Path(args.config),
            args.start,
            args.end,
            args.capital,
            as_json=args.json,
            data_dir=args.data_dir,
            report_dir=args.report_dir,
            report=not args.no_report,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
