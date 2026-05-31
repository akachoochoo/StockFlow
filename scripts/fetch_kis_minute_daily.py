"""KIS 분봉 일일 누적 cron — ADR 0023 §10.1 / 세그먼트 1.2.1.b.4 산출.

본 script 의 본질:
1. 매일 KRX 마감 후 16:00 KST cron 호출.
2. 4종 (069500/132030/005930/035900) 각각 직전 거래일 분봉 14회 paging.
3. CSV 저장 + manifest 갱신 (`_download_and_persist`).
4. 결과 stdout 로깅 + 종료 코드 (0 = all PASS, 1 = ≥1 실패).

ADR 0023 §8.2 (D7 단기 우선 + 일별 누적 cron) 의 cron 본체.

CLAUDE.md §3.2: `now` 외부 주입 — production 은 `datetime.now(UTC)` 진입점에서
1회 호출, tests 는 고정 datetime 주입 (`_run` 시그니처).
CLAUDE.md §10.1: 단일 프로세스 호출 + lock file 자연 직렬화 (cron 보장).
CLAUDE.md §13.3: 알림 (Telegram) = 운영 관찰성 후속 (1.2.5) — 본 script 는
stdout 만.

사용:
    uv run --env-file .env python scripts/fetch_kis_minute_daily.py \\
        [--codes 069500 132030 005930 035900] \\
        [--date 2026-05-29] \\
        [--data-root data/historical] \\
        [--manifest data/historical/minute/manifest.json]

기본:
    --codes  = 4종 (ADR 0023 D13)
    --date   = 어제 KST (cron 다음 영업일 16:00 호출 정합)
    --data-root = data/historical (repo root 기준)
    --manifest  = {data-root}/minute/manifest.json
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.research.dgt_minute._storage import (
    _download_and_persist,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.research.dgt_minute._kis_minute_downloader import _KISClientLike
    from src.research.dgt_minute._storage import _StorageResult


_KST = ZoneInfo("Asia/Seoul")

# ADR 0023 D13 — 4종 dry-run universe.
_DEFAULT_CODES: tuple[str, ...] = (
    "069500",  # KODEX 200
    "132030",  # KODEX 골드선물(H)
    "005930",  # 삼성전자
    "035900",  # JYP Ent.
)


@dataclass(frozen=True, slots=True)
class _RunSummary:
    """전체 cron 실행 결과 요약."""

    results: tuple[_StorageResult, ...]
    failures: tuple[str, ...]  # error message per failed code

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "KIS 분봉 일일 누적 cron (ADR 0023 §10.1 / 세그먼트 1.2.1.b.4)"
        )
    )
    parser.add_argument(
        "--codes",
        nargs="+",
        default=list(_DEFAULT_CODES),
        help=(
            "종목 코드 다중 (기본 069500 132030 005930 035900, ADR 0023 D13)"
        ),
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="다운로드할 거래일 YYYY-MM-DD (기본 = 어제 KST)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data/historical"),
        help="데이터 루트 디렉토리 (기본 data/historical)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "manifest 파일 경로 (기본 {data-root}/minute/manifest.json)"
        ),
    )
    parser.add_argument(
        "--inter-asset-sleep-sec",
        type=float,
        default=1.0,
        help=(
            "종목 간 sleep 초 (KIS EGW00201 burst 회피, ADR 0023 R3 "
            "mitigation). 0 = sleep 없음. 기본 1.0초 = 14호출/종목 burst "
            "buffer 비움."
        ),
    )
    return parser.parse_args(argv)


def _resolve_default_date(now: datetime) -> date:
    """기본 `--date` = (now KST date) - 1일.

    cron 이 다음 영업일 16:00 KST 호출 → 직전 거래일 분봉 다운로드 정합.
    휴장일/주말 사이 호출 시 KIS 가 직전 거래일 데이터 반환 → storage 의
    `target_date` 와 mismatch → bars 0 → no-op (휴장일 자연 처리).
    """
    return now.astimezone(_KST).date() - timedelta(days=1)


def _build_kis_client() -> _KISClientLike:
    """KISClient 자체 빌드 (composition 우회).

    `composition.build_kis_read_components` 는 read components 묶음
    (broker + market_data + config) 만 노출 — raw `client.request(...)`
    호출에는 부적합. 본 cron 도구는 단일 endpoint 직접 호출이라 client
    직접 빌드 (probe 와 동일 패턴).
    """
    from src.adapters.kis._client import KISClient
    from src.adapters.kis._http import RequestsHttpClient
    from src.adapters.kis.auth import KISAuth
    from src.adapters.kis.config import KISConfig

    config = KISConfig.from_env(os.environ)
    http = RequestsHttpClient()

    def clock() -> datetime:
        return datetime.now(UTC)

    auth = KISAuth(config=config, http=http, clock=clock)
    return KISClient(config=config, http=http, auth=auth, clock=clock)


def _run(
    args: argparse.Namespace,
    *,
    client: _KISClientLike,
    now: datetime,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> _RunSummary:
    """주문되어 받은 args + 외부 client + now 로 cron 본체 실행 (testable).

    - 각 code 마다 `_download_and_persist` 호출.
    - 종목 간 `args.inter_asset_sleep_sec` 초 sleep (ADR 0023 R3 — KIS
      EGW00201 "초당 거래건수 초과" 회피). 1종목 = 14 anchor 호출 + KIS real
      20/s burst window 가 가득 → 다음 종목 첫 호출에서 EGW00201 trigger
      관찰됨 (2026-05-31 실증). 1초 sleep 으로 buffer 비움.
    - 예외 발생 시 해당 code 만 실패 처리 + 다음 code 진행 (운영 단일
      종목 실패가 전체 cron 을 중단시키지 않도록).
    - 결과 stdout 로깅 (DRY-RUN, KPI 알림은 후속).
    """
    target_date: date = args.date or _resolve_default_date(now)
    manifest_path: Path = args.manifest or (
        args.data_root / "minute" / "manifest.json"
    )

    results: list[_StorageResult] = []
    failures: list[str] = []

    for i, code in enumerate(args.codes):
        if i > 0 and args.inter_asset_sleep_sec > 0:
            sleep_fn(args.inter_asset_sleep_sec)
        try:
            result = _download_and_persist(
                client,
                asset_code=code,
                target_date=target_date,
                data_root=args.data_root,
                manifest_path=manifest_path,
                now=now,
            )
        except Exception as exc:
            msg = f"{code}: {type(exc).__name__}: {exc}"
            failures.append(msg)
            print(f"FAIL {msg}", file=sys.stderr)
            continue

        results.append(result)
        status = (
            "OK"
            if result.csv_written
            else "SKIP (holiday or empty)"
        )
        print(
            f"{status} {code} {result.trade_date} "
            f"bars={result.bars_count} csv={result.csv_path}",
            file=sys.stdout,
        )

    return _RunSummary(results=tuple(results), failures=tuple(failures))


def _main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    client = _build_kis_client()
    now = datetime.now(UTC)
    summary = _run(args, client=client, now=now)
    return summary.exit_code


if __name__ == "__main__":
    sys.exit(_main())
