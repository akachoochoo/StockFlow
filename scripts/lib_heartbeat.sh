# scripts/lib_heartbeat.sh — cron dead man's switch heartbeat.
#
# 문제: cron 이 아예 실행되지 않으면 (머신 재부팅 / crontab 소실 / 디스크 풀)
# 기존 안전장치 (telegram CRITICAL / cron MAILTO) 는 전부 "실행됐는데 실패"만
# 감지한다. "실행 자체의 부재"는 외부 관찰자만 감지할 수 있다.
#
# 2채널 (모두 best-effort — heartbeat 실패가 cron exit code 를 바꾸지 않음):
#   1. HEARTBEAT_URL ping — healthchecks.io / cronitor 류 부재 감지 서비스.
#      성공 = GET $HEARTBEAT_URL / 실패 = GET $HEARTBEAT_URL/fail.
#      ping 이 예정 시각에 안 오면 서비스가 사람에게 알림 → 부재 감지의 정본.
#      crontab 라인별로 다른 URL 주입:
#        0 16 * * 1-5 HEARTBEAT_URL=https://hc-ping.com/<uuid> /path/to/cron.sh
#   2. Telegram 실패 알림 — exit != 0 시에만 발사 (성공 일일 메시지는 스팸
#      이므로 zero). .env 의 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 재사용
#      (wrapper 가 이미 .env 를 로드함). python 레이어 telegram ERROR 와 중복
#      발사될 수 있으나 (python 실패 시 양쪽 발사), 운영상 0회보다 2회가 낫다 —
#      shell 레이어는 python 도달 전 실패 (uv 부재 / lock 재획득 실패) 를 커버.
#
# 한계 (명시): HEARTBEAT_URL 미설정 시 "아예 안 돈 cron" 감지 수단은 없다 —
# telegram 은 프로세스가 떠야 발사 가능. 부재 감지가 필요하면 채널 1 을 설정하라.
#
# 사용:
#   source "$SCRIPT_DIR/lib_heartbeat.sh"
#   ...
#   EXIT_CODE=$?
#   send_heartbeat "<job-name>" "$EXIT_CODE" "$LOG_FILE"
#   exit "$EXIT_CODE"

send_heartbeat() {
    local job_name="$1"
    local exit_code="$2"
    local log_file="${3:-/dev/null}"

    # 채널 1: HEARTBEAT_URL ping (부재 감지 서비스)
    if [[ -n "${HEARTBEAT_URL:-}" ]]; then
        local ping_url="$HEARTBEAT_URL"
        if [[ "$exit_code" -ne 0 ]]; then
            ping_url="${HEARTBEAT_URL}/fail"
        fi
        if ! curl -fsS -m 10 --retry 2 -o /dev/null "$ping_url" 2>>"$log_file"; then
            echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] ⚠ heartbeat ping 실패 ($job_name → $ping_url) — cron 결과에는 영향 없음" \
                >> "$log_file"
        fi
    fi

    # 채널 2: telegram 실패 알림 (성공 시 zero — 스팸 방지)
    if [[ "$exit_code" -ne 0 && -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        local text="🔴 cron 실패: ${job_name} exit=${exit_code} ($(hostname -s) $(date '+%Y-%m-%dT%H:%M:%S%z'))"
        # stderr → /dev/null: curl 에러 메시지에 token 포함 URL 이 섞일 수
        # 있으므로 로그 파일로 보내지 않는다 (ADR 0012 R10 민감정보 로깅 금지).
        if ! curl -fsS -m 10 -o /dev/null \
            "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "text=${text}" 2>/dev/null; then
            echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] ⚠ telegram 실패 알림 발사 실패 ($job_name) — cron 결과에는 영향 없음" \
                >> "$log_file"
        fi
    fi
    return 0
}
