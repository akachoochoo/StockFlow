#!/usr/bin/env bash
# scripts/fetch_kis_minute_daily_cron.sh — KIS 분봉 일일 누적 cron wrapper.
#
# ADR 0023 §10.1 / 세그먼트 1.2.1.b.4 — 매일 직전 거래일 분봉 4종 다운로드.
# `scripts/fetch_kis_minute_daily.py` python 진입점의 cron 환경 wrapper.
#
# 대상 종목 (ADR 0023 D13):
#   069500 KODEX 200 / 132030 KODEX 골드선물(H) / 005930 삼성전자 / 035900 JYP Ent.
#
# 사용 (수동):
#   bash scripts/fetch_kis_minute_daily_cron.sh
#
# crontab 등록 예 (KST 16:15, 평일 매일 — KRX 종가 15:30 + KIS publish 버퍼):
#   15 16 * * 1-5 /Users/USERNAME/workspace/StockFlow/scripts/fetch_kis_minute_daily_cron.sh
#
# 환경변수 (모두 옵션):
#   STOCKFLOW_ROOT            : repo 루트 (기본 = 스크립트 부모 디렉토리)
#   FETCH_MINUTE_LOG_DIR      : 로그 디렉토리 (기본 = logs)
#   FETCH_MINUTE_CODES        : 종목 코드 (공백 구분, 기본 = 4종 ADR 0023 D13)
#   FETCH_MINUTE_DATE         : 강제 처리 date (YYYY-MM-DD). 기본 = 어제 KST
#   FETCH_MINUTE_DATA_ROOT    : 데이터 루트 (기본 = data/historical)
#   FETCH_MINUTE_SLEEP_SEC    : 종목 간 sleep 초 (기본 = 1.0, R3 mitigation)
#
# 동작:
#   1. mkdir 기반 단일 인스턴스 lock (cron 중복 호출 시 즉시 종료).
#   2. .env 로드 (KIS_* — appkey/appsecret/account).
#   3. fetch_kis_minute_daily.py 실행 (default = 4종 어제 KST).
#   4. stdout/stderr → 날짜별 로그 (logs/fetch-kis-minute-YYYY-MM-DD.log).
#   5. exit code 전파 → cron MAILTO 가 실패 이메일 수신.
#
# 안전: read-only (시세 endpoint inquire-time-itemchartprice 만). 실주문 zero.
# 휴장일 호출 자연 처리 (KIS 가 직전 거래일 데이터 반환 → storage 가 target_date
# mismatch 로 필터 → bars=0 → SKIP, exit 0).
#
# 부분 실패 정책: EGW00201 1종목 실패 시 다음 종목 진행 (cron 도구 _run 의
# per-code 예외 격리). 누락된 종목은 다음 영업일 cron 에서 자동 복구는 안 됨
# (target_date = 어제). 수동 복구 = `--codes 069500 --date 2026-MM-DD`.

set -uo pipefail

# --- 경로 + 디폴트 ---------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STOCKFLOW_ROOT="${STOCKFLOW_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

FETCH_MINUTE_LOG_DIR="${FETCH_MINUTE_LOG_DIR:-logs}"
FETCH_MINUTE_CODES="${FETCH_MINUTE_CODES:-069500 132030 005930 035900}"
FETCH_MINUTE_DATE="${FETCH_MINUTE_DATE:-}"
FETCH_MINUTE_DATA_ROOT="${FETCH_MINUTE_DATA_ROOT:-data/historical}"
FETCH_MINUTE_SLEEP_SEC="${FETCH_MINUTE_SLEEP_SEC:-1.0}"

# uv 절대경로 (cron PATH 가 비어있을 수 있음)
UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"

cd "$STOCKFLOW_ROOT" || {
    echo "ERROR: STOCKFLOW_ROOT=$STOCKFLOW_ROOT 진입 실패" >&2
    exit 2
}

# --- 로그 디렉토리 + 파일 -------------------------------------------------
mkdir -p "$FETCH_MINUTE_LOG_DIR"
LOG_DATE="$(date '+%Y-%m-%d')"
LOG_FILE="$FETCH_MINUTE_LOG_DIR/fetch-kis-minute-${LOG_DATE}.log"

# --- 단일 인스턴스 (portable mkdir lock) ----------------------------------
LOCK_DIR="$FETCH_MINUTE_LOG_DIR/fetch-kis-minute.lock.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] ⚠ 이미 실행 중 (lock=$LOCK_DIR) — skip" \
        | tee -a "$LOG_FILE" >&2
    exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# --- .env 로드 (KIS_* 등) --------------------------------------------------
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# --- 명령 구성 -------------------------------------------------------------
# uv 가 --env-file 지원 — .env 변수 명시 주입 (set -a 와 중복이지만 명시적).
CMD=(
    "$UV_BIN" run --env-file .env python scripts/fetch_kis_minute_daily.py
    --data-root "$FETCH_MINUTE_DATA_ROOT"
    --inter-asset-sleep-sec "$FETCH_MINUTE_SLEEP_SEC"
)

# 종목 (공백 구분 → array)
# shellcheck disable=SC2206
CODES_ARR=($FETCH_MINUTE_CODES)
CMD+=(--codes "${CODES_ARR[@]}")

if [[ -n "$FETCH_MINUTE_DATE" ]]; then
    CMD+=(--date "$FETCH_MINUTE_DATE")
fi

# --- 실행 + 로깅 -----------------------------------------------------------
{
    echo "================================================================"
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] fetch-kis-minute cron 시작"
    echo "  Root         : $STOCKFLOW_ROOT"
    echo "  Codes        : $FETCH_MINUTE_CODES"
    echo "  Date         : ${FETCH_MINUTE_DATE:-(어제 KST default)}"
    echo "  Data root    : $FETCH_MINUTE_DATA_ROOT"
    echo "  Sleep sec    : $FETCH_MINUTE_SLEEP_SEC"
    echo "  Cmd          : ${CMD[*]}"
    echo "================================================================"
} >> "$LOG_FILE"

"${CMD[@]}" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

{
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] fetch-kis-minute cron 종료 — exit=$EXIT_CODE"
} >> "$LOG_FILE"

exit "$EXIT_CODE"
