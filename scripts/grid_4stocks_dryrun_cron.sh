#!/usr/bin/env bash
# scripts/grid_4stocks_dryrun_cron.sh — 4종 DGT grid dry-run cron wrapper.
#
# ADR 0022 §13 D28 권고 정합 — 실거래 진입 전 10 영업일 dry-run 운영 단계.
# 매일 1 회 호출 → grid_decisions + grid_states 영속 + 텔레그램 알림.
#
# 대상 종목 (config/grid-4stocks-dryrun.yaml):
#   095660 네오위즈 / 035420 NAVER / 068270 셀트리온 / 035900 JYP Ent.
#
# 사용 (수동):
#   bash scripts/grid_4stocks_dryrun_cron.sh
#
# crontab 등록 예 (KST 16:00, 평일 매일 — KRX 종가 15:30 + KIS publish 버퍼):
#   0 16 * * 1-5 /Users/USERNAME/workspace/StockFlow/scripts/grid_4stocks_dryrun_cron.sh
#
# 환경변수 (모두 옵션):
#   STOCKFLOW_ROOT              : repo 루트 (기본 = 스크립트 부모 디렉토리)
#   GRID_DRYRUN_CONFIG          : grid config YAML (기본 = config/grid-4stocks-dryrun.yaml)
#   GRID_DRYRUN_DB              : SQLite DB (기본 = grid-4stocks-dryrun.db)
#   GRID_DRYRUN_CAPITAL         : 총 자본 KRW (기본 = 20000000 — 종목당 500만)
#   GRID_DRYRUN_LOOKBACK        : KIS lookback 일수 (기본 = 180)
#   GRID_DRYRUN_LOG_DIR         : 로그 디렉토리 (기본 = logs)
#   GRID_DRYRUN_USE_KIS         : 1 = KIS 시세 (기본), 0 = CSV
#   GRID_DRYRUN_DATE            : 강제 처리 date (YYYY-MM-DD). 기본 = today (KST)
#
# 동작:
#   1. mkdir 기반 단일 인스턴스 lock (cron 중복 호출 시 즉시 종료).
#   2. .env 로드 (KIS_PAPER_APPKEY + TELEGRAM_BOT_TOKEN 등).
#   3. trading grid-dry-run 실행 (USE_KIS=1 → --use-kis, 0 → 4종 --csv).
#   4. stdout/stderr → 날짜별 로그 (logs/grid-4stocks-dryrun-YYYY-MM-DD.log).
#   5. exit code 전파 → cron MAILTO 가 실패 이메일 수신.
#
# 텔레그램 알림: CLI 가 직접 발사 (cron 시작/매수매도/종료/오류). 본 스크립트는
# 오로지 실행 / 로깅 / 단일 인스턴스 보장.
#
# 안전: --use-kis 사용 시도 KIS get_ohlcv (read-only) 만 — 주문은 MockBroker
# grid 경로 (D19), 실주문 zero. live 진입은 별 명령 (trading grid-live + arming).
set -uo pipefail

# --- 경로 + 디폴트 ---------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STOCKFLOW_ROOT="${STOCKFLOW_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# shellcheck source=lib_heartbeat.sh
source "$SCRIPT_DIR/lib_heartbeat.sh"

GRID_DRYRUN_CONFIG="${GRID_DRYRUN_CONFIG:-config/grid-4stocks-dryrun.yaml}"
GRID_DRYRUN_DB="${GRID_DRYRUN_DB:-grid-4stocks-dryrun.db}"
GRID_DRYRUN_CAPITAL="${GRID_DRYRUN_CAPITAL:-20000000}"
GRID_DRYRUN_LOOKBACK="${GRID_DRYRUN_LOOKBACK:-180}"
GRID_DRYRUN_LOG_DIR="${GRID_DRYRUN_LOG_DIR:-logs}"
GRID_DRYRUN_USE_KIS="${GRID_DRYRUN_USE_KIS:-1}"
GRID_DRYRUN_DATE="${GRID_DRYRUN_DATE:-}"

# 4종 CSV 경로 (--use-kis=0 시 사용). 종목 변경 시 본 변수도 갱신.
CSV_095660="${CSV_095660:-data/historical/KRX_095660_2025-2026.csv}"
CSV_035420="${CSV_035420:-data/historical/KRX_035420_2025-2026.csv}"
CSV_068270="${CSV_068270:-data/historical/KRX_068270_2025-2026.csv}"
CSV_035900="${CSV_035900:-data/historical/KRX_035900_2025-2026.csv}"

cd "$STOCKFLOW_ROOT" || {
    echo "ERROR: STOCKFLOW_ROOT=$STOCKFLOW_ROOT 진입 실패" >&2
    exit 2
}

# --- 로그 디렉토리 + 파일 -------------------------------------------------
mkdir -p "$GRID_DRYRUN_LOG_DIR"
LOG_DATE="$(date '+%Y-%m-%d')"
LOG_FILE="$GRID_DRYRUN_LOG_DIR/grid-4stocks-dryrun-${LOG_DATE}.log"

# --- 단일 인스턴스 (portable mkdir lock + PID stale detection) ------------
LOCK_DIR="$GRID_DRYRUN_LOG_DIR/grid-4stocks-dryrun.lock.d"
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
trap 'rm -rf "$LOCK_DIR" 2>/dev/null || true' EXIT

# --- .env 로드 (KIS_PAPER_APPKEY / TELEGRAM_* 등) --------------------------
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
else
    CMD+=(
        --csv "095660=$CSV_095660"
        --csv "035420=$CSV_035420"
        --csv "068270=$CSV_068270"
        --csv "035900=$CSV_035900"
    )
fi
if [[ -n "$GRID_DRYRUN_DATE" ]]; then
    CMD+=(--date "$GRID_DRYRUN_DATE")
fi

# --- 실행 + 로깅 -----------------------------------------------------------
{
    echo "================================================================"
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] grid-4stocks-dryrun cron 시작"
    echo "  Root      : $STOCKFLOW_ROOT"
    echo "  Config    : $GRID_DRYRUN_CONFIG"
    echo "  DB        : $GRID_DRYRUN_DB"
    echo "  Capital   : $GRID_DRYRUN_CAPITAL KRW (종목당 $((GRID_DRYRUN_CAPITAL / 4)))"
    echo "  USE_KIS   : $GRID_DRYRUN_USE_KIS"
    echo "  Cmd       : ${CMD[*]}"
    echo "================================================================"
} >> "$LOG_FILE"

"${CMD[@]}" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

{
    echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] grid-4stocks-dryrun cron 종료 — exit=$EXIT_CODE"
} >> "$LOG_FILE"

# --- heartbeat (dead man's switch — scripts/lib_heartbeat.sh) --------------
send_heartbeat "grid-4stocks-dryrun" "$EXIT_CODE" "$LOG_FILE"

exit "$EXIT_CODE"
