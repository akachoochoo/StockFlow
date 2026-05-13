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

# Phase 0.11.b ADR 0008 §1.6 D9 — intra-research cross-import 차단.
# src/research/dgt/** MUST NOT import from non-dgt src.research sub-namespaces
# (예: src.research.visualization, src.research.dynamic_adjustment 등).
# Allowed: intra-dgt (src.research.dgt.* → src.research.dgt.*).
#
# Phase 0.11.c ADR 0009 §1.6 D9 — intra-research 방향성 명시:
# - 정방향 허용: src/research/visualization/* → src/research/dgt/*
#   (visualization 이 DGT 결과 읽기 = outer→inner read 의 5th ring 내부 확장).
#   별도 grep rule 추가 zero — 기존 dgt 차단 rule 의 negative 조건 자동 만족
#   (visualization 디렉토리는 dgt 디렉토리 grep 범위에 포함되지 않음).
# - 역방향 차단: src/research/dgt/* → src/research/visualization/*
#   본 dgt 차단 rule (line 49~58) 로 enforce — visualization 은 non-dgt
#   sub-namespace 이므로 자동 차단.
#
# BSD grep (macOS) negative-lookahead 미지원 → 2-step grep (extract all
# src.research imports, then exclude src.research.dgt matches).
if [ -d "src/research/dgt" ]; then
  matches=$(grep -rEn "^[[:space:]]*(from|import)[[:space:]]+src\.research\." src/research/dgt 2>/dev/null || true)
  if [ -n "$matches" ]; then
    intra_violations=$(echo "$matches" | grep -vE "src\.research\.dgt(\.|$|[[:space:]])" || true)
    if [ -n "$intra_violations" ]; then
      echo "$intra_violations"
      echo "FAIL: src/research/dgt contains cross-import to non-dgt src.research sub-namespace"
      violations=$((violations + 1))
    fi
  fi
fi

if [ "$violations" -gt 0 ]; then
  echo "FAIL: namespace discipline violated ($violations inner ring(s))"
  exit 1
fi

echo "OK: namespace discipline preserved (7-ring grep + dgt intra-research isolation)"
