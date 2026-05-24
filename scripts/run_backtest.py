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

import yaml

# Run-as-script: repo root on sys.path so ``from src...`` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.infrastructure.asset_csv import derive_csv_path  # noqa: E402

# Injection seams (tests override; defaults touch network / run the real CLI).
Downloader = Callable[[str, date, date, Path], None]
Runner = Callable[[list[str]], int]


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
    downloader: Downloader = _default_downloader,
    runner: Runner = _default_runner,
) -> int:
    """데이터 확보 → ``trading backtest`` 위임. CLI exit code 반환."""
    codes = enabled_codes(config_path)
    if not codes:
        print(f"{config_path} 에 enabled 종목이 없습니다.", file=sys.stderr)
        return 1

    csv_args: list[str] = []
    for code in codes:
        csv = ensure_data(
            code, start, end, data_dir=data_dir, downloader=downloader
        )
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
    return runner(args)


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
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
