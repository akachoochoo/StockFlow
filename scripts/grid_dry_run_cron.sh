#!/usr/bin/env bash
# scripts/grid_dry_run_cron.sh — DGT grid dry-run cron wrapper (ADR 0022 §12).
#
# 1 호출 = 1 영업일 처리. crontab 일별 등록 → 매일 한 번 호출. 영업일 / 휴장일
# 판정은 KIS get_ohlcv 응답에 위임 (휴장일 = 빈 결과 → CLI 가 ClickException 으로
# fail). cron 으로 매일 호출하되 휴장일 stderr 는 사람 검토 (telegram ERROR
# 알림 발사).
#
# 사용 (수동):
#   bash scripts/grid_dry_run_cron.sh
#
# crontab 등록 예 (KST 16:00, 평일 매일 — 종가 ≈ 15:30 + 데이터 publish 버퍼):
#   0 16 * * 1-5 /Users/USERNAME/workspace/StockFlow/scripts/grid_dry_run_cron.sh
#
# 환경변수 (모두 옵션):
#   STOCKFLOW_ROOT          : repo 루트 (기본 = 스크립트 부모 디렉토리)
#   GRID_DRYRUN_CONFIG      : grid config YAML (기본 = config/grid-095660-dryrun.yaml)
#   GRID_DRYRUN_DB          : SQLite DB 경로 (기본 = grid-dry-run.db, repo 루트 기준)
#   GRID_DRYRUN_CAPITAL     : 초기 자본 KRW (기본 = 10000000)
#   GRID_DRYRUN_LOOKBACK    : KIS lookback 일수 (기본 = 180)
#   GRID_DRYRUN_LOG_DIR     : 로그 디렉토리 (기본 = logs, repo 루트 기준)
#   GRID_DRYRUN_USE_KIS     : 1 = KIS 시세 (기본), 0 = CSV (CSV 경로는 별도 설정)
#   GRID_DRYRUN_CSV         : --use-kis=0 일 때 CSV 경로 (CODE=path 형식 1개)
#   GRID_DRYRUN_DATE        : 강제 처리 date (YYYY-MM-DD). 기본 = today (KST).
#
# 동작:
#   1. flock 으로 단일 인스턴스 보장 (cron 중복 호출 시 즉시 종료).
#   2. .env 로드 (KIS_PAPER_APPKEY 등).
#   3. `uv run trading grid-dry-run --use-kis ...` 실행, stdout/stderr 를
#      날짜별 로그 파일 (logs/grid-dry-run-YYYY-MM-DD.log) 에 append.
#   4. 종료 코드 0 = 성공, !=0 = 실패 (cron MAILTO 가 받음).
#
# 알림: 텔레그램 알림은 CLI 가 발사 (시작/매수매도/종료/오류). 본 스크립트는
# 오로지 실행 / 로깅 / 단일 인스턴스 보장.
#
# 안전: --no-real-orders 등 사용 안 함 — 본 CLI 자체가 dry-run (실주문 zero,
# MockBroker grid 경로, ADR 0022 §12 D19).
set -uo pipefail

# --- 경로 + 디폴트 ---------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STOCKFLOW_ROOT="${STOCKFLOW_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# shellcheck source=lib_heartbeat.sh
source "$SCRIPT_DIR/lib_heartbeat.sh"

GRID_DRYRUN_CONFIG="${GRID_DRYRUN_CONFIG:-config/grid-095660-dryrun.yaml}"
GRID_DRYRUN_DB="${GRID_DRYRUN_DB:-grid-dry-run.db}"
GRID_DRYRUN_CAPITAL="${GRID_DRYRUN_CAPITAL:-10000000}"
GRID_DRYRUN_LOOKBACK="${GRID_DRYRUN_LOOKBACK:-180}"
GRID_DRYRUN_LOG_DIR="${GRID_DRYRUN_LOG_DIR:-logs}"
GRID_DRYRUN_USE_KIS="${GRID_DRYRUN_USE_KIS:-1}"
GRID_DRYRUN_CSV="${GRID_DRYRUN_CSV:-}"
GRID_DRYRUN_DATE="${GRID_DRYRUN_DATE:-}"

cd "$STOCKFLOW_ROOT" || {
    echo "ERROR: STOCKFLOW_ROOT=$STOCKFLOW_ROOT 진입 실패" >&2
    exit 2
}

# --- 로그 디렉토리 + 파일 -------------------------------------------------
mkdir -p "$GRID_DRYRUN_LOG_DIR"
LOG_DATE="$(date '+%Y-%m-%d')"
LOG_FILE="$GRID_DRYRUN_LOG_DIR/grid-dry-run-${LOG_DATE}.log"

# --- 단일 인스턴스 (portable mkdir lock + PID stale detection) ------------
LOCK_DIR="$GRID_DRYRUN_LOG_DIR/grid-dry-run.lock.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    _lock_pid=$(cat "$LOCK_DIR/pid" 2>/dev/null || true)
    if [[ -n "$_lock_pid" ]] && kill -0 "$_lock_pid" 2>/dev/null; then
        echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] ⚠ 이미 실행 중 (lock=$LOCK_DIR, pid=$_lock_pid) — skip" \
            | tee -a "$LOG_FILE" >&2
        exit 0
    fi
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] ⚠ Stale lock (pid=$_lock_pid dead) — clearing $LOCK_DIR" \
        | tee -a "$LOG_FILE" >&2
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" || { echo "lock 재획득 실패" | tee -a "$LOG_FILE" >&2; exit 1; }
fi
echo $$ > "$LOCK_DIR/pid"
# trap: 종료 시 lock 해제 (정상 / 오류 모두).
trap 'rm -rf "$LOCK_DIR" 2>/dev/null || true' EXIT

# --- .env 로드 (KIS_PAPER_APPKEY 등) --------------------------------------
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# --- 명령 구성 -------------------------------------------------------------
CMD=(uv run trading grid-dry-run
    --config "$GRID_DRYRUN_CONFIG"
    --db "$GRID_DRYRUN_DB"
    --capital "$GRID_DRYRUN_CAPITAL"
)
if [[ "$GRID_DRYRUN_USE_KIS" == "1" ]]; then
    CMD+=(--use-kis --lookback-days "$GRID_DRYRUN_LOOKBACK")
elif [[ -n "$GRID_DRYRUN_CSV" ]]; then
    CMD+=(--csv "$GRID_DRYRUN_CSV")
else
    echo "ERROR: GRID_DRYRUN_USE_KIS=0 일 때 GRID_DRYRUN_CSV (CODE=path) 필요" >&2
    exit 2
fi
if [[ -n "$GRID_DRYRUN_DATE" ]]; then
    CMD+=(--date "$GRID_DRYRUN_DATE")
fi

# --- 실행 + 로깅 -----------------------------------------------------------
{
    echo "================================================================"
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] grid-dry-run cron 시작"
    echo "  Root   : $STOCKFLOW_ROOT"
    echo "  Config : $GRID_DRYRUN_CONFIG"
    echo "  DB     : $GRID_DRYRUN_DB"
    echo "  Cmd    : ${CMD[*]}"
    echo "================================================================"
} >> "$LOG_FILE"

"${CMD[@]}" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

{
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] grid-dry-run cron 종료 — exit=$EXIT_CODE"
} >> "$LOG_FILE"

# --- heartbeat (dead man's switch — scripts/lib_heartbeat.sh) --------------
send_heartbeat "grid-dry-run" "$EXIT_CODE" "$LOG_FILE"

exit "$EXIT_CODE"
