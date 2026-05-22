#!/usr/bin/env bash
# Phase 1.1 Stage 3.1 — NTP clock-sync verification (CLAUDE.md §3.3).
# ADR 0012 D14 (NTP cron entry hook). Fail-closed: when the clock offset
# cannot be measured, refuse to proceed (treat as unsafe to trade).
#
# Measures the local clock offset (seconds) against an NTP server using the
# first available tool, in this preference order:
#   1. sntp        (macOS dev + Linux ntp pkg)
#   2. ntpdate -q  (Linux, classic ntp pkg)
#   3. chronyc     (Linux, chrony — uses already-tracked offset, no server arg)
#
# Threshold (seconds): $1 arg, else $NTP_MAX_OFFSET_SEC env, else 1.0.
# Server: $NTP_SERVER env, else time.apple.com (sntp/ntpdate only).
#
# Usage:
#   bash scripts/check_ntp_sync.sh [max_offset_sec]
#
# Exit codes:
#   0 — synced            (|offset| <= threshold)
#   1 — offset exceeded   (|offset| >  threshold)
#   2 — unmeasurable      (no tool, or measurement failed) — FAIL-CLOSED
set -uo pipefail

THRESHOLD="${1:-${NTP_MAX_OFFSET_SEC:-1.0}}"
NTP_SERVER="${NTP_SERVER:-time.apple.com}"

# --- helpers ---------------------------------------------------------------

# abs_le <offset> <threshold> -> exit 0 if |offset| <= threshold, else 1.
# Pure awk (no bc dependency); handles signs + floats.
abs_le() {
  awk -v o="$1" -v t="$2" 'BEGIN { if (o < 0) o = -o; exit (o <= t) ? 0 : 1 }'
}

# is_number <str> -> exit 0 if str parses as a finite number.
is_number() {
  awk -v v="$1" 'BEGIN { exit (v + 0 == v && v != "") ? 0 : 1 }'
}

# --- measurement (each prints offset in seconds to stdout, or fails) --------

# sntp output:
#   macOS : "+0.009212 +/- 0.009903 server ip"           (offset = $1)
#   Linux : "<date> (+0000) +0.001 +/- 0.01 server ..."  (offset = field before "+/-")
measure_sntp() {
  local out
  out="$(sntp -t 5 "$NTP_SERVER" 2>/dev/null)" || return 1
  [ -n "$out" ] || return 1
  # Take the last non-empty line, then the token immediately before "+/-".
  echo "$out" | awk '
    NF { line = $0 }
    END {
      if (line == "") exit 1
      n = split(line, f, /[ \t]+/)
      for (i = 1; i <= n; i++) {
        if (f[i] == "+/-" && i > 1) { print f[i-1]; exit 0 }
      }
      # No "+/-" marker — fall back to first field (defensive).
      print f[1]
      exit 0
    }'
}

# ntpdate -q output (last line): "... offset 0.001234, delay 0.0..."
measure_ntpdate() {
  local out
  out="$(ntpdate -q "$NTP_SERVER" 2>/dev/null)" || return 1
  [ -n "$out" ] || return 1
  echo "$out" | awk '
    { for (i = 1; i <= NF; i++) if ($i == "offset") { o = $(i+1); sub(/,$/, "", o); val = o } }
    END { if (val == "") exit 1; print val; exit 0 }'
}

# chronyc tracking output line:
#   "System time : 0.000001234 seconds slow of NTP time"
# (chrony tracks continuously; no server argument is used.)
measure_chronyc() {
  local out
  out="$(chronyc tracking 2>/dev/null)" || return 1
  [ -n "$out" ] || return 1
  echo "$out" | awk '
    /System time/ {
      for (i = 1; i <= NF; i++) if ($i == ":") { o = $(i+1); print o; exit 0 }
    }
    END { exit 1 }'
}

# --- tool dispatch ---------------------------------------------------------

offset=""
tool=""
tools_present=""
for candidate in sntp ntpdate chronyc; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  tools_present="${tools_present:+$tools_present }$candidate"
  case "$candidate" in
    sntp)     offset="$(measure_sntp)" || offset="" ;;
    ntpdate)  offset="$(measure_ntpdate)" || offset="" ;;
    chronyc)  offset="$(measure_chronyc)" || offset="" ;;
  esac
  if [ -n "$offset" ] && is_number "$offset"; then
    tool="$candidate"
    break
  fi
  offset=""
done

if [ -z "$tool" ] || [ -z "$offset" ]; then
  if [ -z "$tools_present" ]; then
    echo "NTP check FAILED: no NTP tool found (tried sntp/ntpdate/chronyc) — fail-closed, refusing to trade." >&2
  else
    echo "NTP check FAILED: tools present (${tools_present}) but offset unmeasurable (server unreachable?) — fail-closed, refusing to trade." >&2
  fi
  exit 2
fi

if abs_le "$offset" "$THRESHOLD"; then
  echo "NTP synced: offset=${offset}s (threshold=${THRESHOLD}s, tool=${tool})"
  exit 0
fi

echo "NTP offset EXCEEDED: offset=${offset}s > threshold=${THRESHOLD}s (tool=${tool}) — refusing to trade." >&2
exit 1
