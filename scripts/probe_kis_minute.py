"""KIS 분봉 API 단발성 probe — ADR 0023 §10.1 (세그먼트 1.2.1) schema 박제 도구.

본 script 의 본질 = **`inquire-time-itemchartprice` 실제 응답 형식 확인**.
ADR 0020 §2.2 KIS 매핑 표는 일봉만 박제 (FHKST03010100 / output1+output2).
분봉 (FHKST03010200) 의 응답 field 명·dtype 은 미박제 → KIS 응답 raw
JSON 을 출력해 ADR 0020 §2 분봉 확장 박제용 sample 확보.

**Production 미통합** — 본 script 는 dgt_minute 모듈/cli 와 분리. 1.2.1.b
KIS 분봉 다운로더는 본 probe 의 응답 schema 박제 후 별도 commit.

CLAUDE.md §13.3 정합: "친절한 추가" 아닌 ADR 0023 §10.1 명시 도구.
CLAUDE.md §3.1: UTC clock 사용, naive `datetime.now()` 호출 zero.
CLAUDE.md §5.1: 외부 데이터 검증 skip 의도 — 본 probe 의 산출은 raw
JSON dump (도메인 진입 zero).
CLAUDE.md §9.3: 비밀 정보 (appkey/appsecret/token) 출력 zero —
KISClient 내부에서만 사용, response body 만 출력.

사용법:
    uv run --env-file .env python scripts/probe_kis_minute.py \\
        --code 069500 --time 1530 --out docs/research/phase-1.x-minute/sample.json

옵션:
    --code   종목 코드 (필수, 예: 069500 / 132030 / 005930 / 035900)
    --time   조회 종료 시각 HHMM KST (기본 1530 = 장마감)
    --past   과거 데이터 포함 여부 (Y/N, FID_PW_DATA_INCU_YN)
    --out    응답 저장 경로 (옵션, 기본 stdout)

본 probe 1회 호출 후:
1. 응답 raw JSON 파일 박제 → `docs/research/phase-1.x-minute/`
2. 응답 schema (`output1` / `output2` field 명·dtype) 분석 → ADR 0020 §2.2 확장
3. 그 후 1.2.1.b KIS 분봉 다운로더 (`src/research/dgt_minute/_kis_minute_downloader.py`)
   본격 작성.

출처:
- ADR 0020 §2.2 (KIS 매핑 표 — 일봉 박제, 분봉 확장 대기)
- ADR 0023 §10.1 (세그먼트 1.2.1)
- KIS 공식 inquire-time-itemchartprice spec (실증 대기, 본 probe 산출로 박제)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# KIS `inquire-time-itemchartprice` (분봉 OHLCV).
# 추정 (ADR 0020 §2 일봉 패턴 추론, 실증 대기):
# - Path:  /uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice
# - TR_ID: FHKST03010200 (FH... → 실/모의 공통; 본 probe 호출로 실증)
# - Method: GET
# - Params (KIS 공식 추정, 본 probe 호출로 실증):
#     FID_ETC_CLS_CODE     ""     (기본)
#     FID_COND_MRKT_DIV_CODE "J"  (일봉과 동일)
#     FID_INPUT_ISCD       종목코드
#     FID_INPUT_HOUR_1     조회 종료 시각 (HHMMSS)
#     FID_PW_DATA_INCU_YN  "Y"/"N" (과거 데이터 포함 여부)
_MINUTE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
_MINUTE_TR_ID = "FHKST03010200"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "KIS 분봉 API 단발성 probe (ADR 0023 §10.1 / "
            "ADR 0020 §2 분봉 확장 박제 도구)"
        )
    )
    parser.add_argument(
        "--code", required=True, help="종목 코드 (예: 069500)"
    )
    parser.add_argument(
        "--time",
        default="1530",
        help="조회 종료 시각 HHMM (KST, 기본 1530 = 장마감)",
    )
    parser.add_argument(
        "--past",
        default="N",
        choices=["Y", "N"],
        help="과거 데이터 포함 여부 (FID_PW_DATA_INCU_YN, 기본 N)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="응답 저장 파일 (옵션, 기본 stdout)",
    )
    return parser.parse_args(argv)


def _build_client() -> object:
    """Build a KISClient from environment — independent from composition root.

    `composition.build_kis_read_components()` returns a `KISReadComponents`
    that does not expose the raw client. Probe needs raw `client.request(...)`
    access for an arbitrary endpoint, so we wire it directly here. This is
    intentional — the probe is single-shot tooling, not a production component.
    """
    # Local imports to keep the script invocable without the full app graph.
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


def _to_hhmmss(hhmm: str) -> str:
    """HHMM (4 chars) → HHMMSS (6 chars). Already-6-char input is passed through."""
    if len(hhmm) == 4 and hhmm.isdigit():
        return hhmm + "00"
    if len(hhmm) == 6 and hhmm.isdigit():
        return hhmm
    raise ValueError(f"--time must be HHMM or HHMMSS digits, got {hhmm!r}")


def _main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    client = _build_client()

    body = client.request(  # type: ignore[attr-defined]
        "GET",
        _MINUTE_PATH,
        tr_id=_MINUTE_TR_ID,
        params={
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": args.code,
            "FID_INPUT_HOUR_1": _to_hhmmss(args.time),
            "FID_PW_DATA_INCU_YN": args.past,
        },
    )

    pretty = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(pretty, encoding="utf-8")
        print(
            f"saved {len(pretty)} chars to {args.out}",
            file=sys.stderr,
        )
    else:
        print(pretty)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
