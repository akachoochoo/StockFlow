#!/usr/bin/env bash
# Phase 0.11.a § Namespace Discipline enforcement.
# ADR 0007 §1.6.2 + AC13 (D11 plain grep, 7-ring target).
#
# Fails (exit 1) if any inner ring imports from src.research.
# Inner rings (ring direction = outer→inner read OK only):
#   src/adapters, src/application, src/cli, src/domain,
#   src/infrastructure, src/ports, src/use_cases
#
# Usage:
#   bash scripts/check_namespace.sh
#
# Exit codes:
#   0 — namespace discipline preserved
#   1 — violation detected (inner ring imports src.research)

set -euo pipefail

INNER_RINGS=(
  "src/adapters"
  "src/application"
  "src/cli"
  "src/domain"
  "src/infrastructure"
  "src/ports"
  "src/use_cases"
)

violations=0
for ring in "${INNER_RINGS[@]}"; do
  if [ -d "$ring" ]; then
    # Match `from src.research...` or `import src.research...` at line start
    # (after optional whitespace). Ignores comments and string literals best-effort
    # via line-anchored match.
    if grep -rEn "^[[:space:]]*(from|import)[[:space:]]+src\.research(\.|$|[[:space:]])" "$ring" 2>/dev/null; then
      echo "FAIL: $ring contains import from src.research"
      violations=$((violations + 1))
    fi
  fi
done

if [ "$violations" -gt 0 ]; then
  echo "FAIL: namespace discipline violated ($violations inner ring(s))"
  exit 1
fi

echo "OK: namespace discipline preserved (7-ring grep, src.research isolated)"
