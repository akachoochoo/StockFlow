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

# Phase 0.11.e ADR 0011 §1.3 D10 — intra-research cross-import 방향성:
# - 정방향 허용: src/research/dynamic_adjustment/* → src/research/dgt/* +
#   src/research/visualization/* + src/research/dynamic_adjustment/* (D11
#   산출 호출 정합).
# - 역방향 차단: dgt → dynamic_adjustment (기존 dgt rule 로 enforce 완료);
#   visualization → dynamic_adjustment 차단 (본 신규 rule).
#
# visualization → dynamic_adjustment 차단 rule — visualization 이 dgt +
# visualization 외 sub-namespace 를 import 하지 않음을 강제.
if [ -d "src/research/visualization" ]; then
  matches=$(grep -rEn "^[[:space:]]*(from|import)[[:space:]]+src\.research\." src/research/visualization 2>/dev/null || true)
  if [ -n "$matches" ]; then
    intra_violations=$(echo "$matches" | grep -vE "src\.research\.(dgt|visualization)(\.|$|[[:space:]])" || true)
    if [ -n "$intra_violations" ]; then
      echo "$intra_violations"
      echo "FAIL: src/research/visualization contains cross-import to non-{dgt,visualization} src.research sub-namespace"
      violations=$((violations + 1))
    fi
  fi
fi

# dynamic_adjustment 의 outgoing 차단 — 허용 = dgt + visualization +
# dynamic_adjustment (intra-self). 그 외 sub-namespace (예: 미래 신규)
# 자동 차단.
if [ -d "src/research/dynamic_adjustment" ]; then
  matches=$(grep -rEn "^[[:space:]]*(from|import)[[:space:]]+src\.research\." src/research/dynamic_adjustment 2>/dev/null || true)
  if [ -n "$matches" ]; then
    intra_violations=$(echo "$matches" | grep -vE "src\.research\.(dgt|visualization|dynamic_adjustment)(\.|$|[[:space:]])" || true)
    if [ -n "$intra_violations" ]; then
      echo "$intra_violations"
      echo "FAIL: src/research/dynamic_adjustment contains cross-import to non-{dgt,visualization,dynamic_adjustment} src.research sub-namespace"
      violations=$((violations + 1))
    fi
  fi
fi

# Phase 1.x ADR 0023 D15 — dgt_minute intra-research isolation.
# dgt_minute 는 처음부터 재설계 경로 (ADR 0007 §1.7.2 (b)) — 일봉 dgt /
# visualization / dynamic_adjustment 와 교차 import 차단. intra-self
# (dgt_minute → dgt_minute) 만 허용.
if [ -d "src/research/dgt_minute" ]; then
  matches=$(grep -rEn "^[[:space:]]*(from|import)[[:space:]]+src\.research\." src/research/dgt_minute 2>/dev/null || true)
  if [ -n "$matches" ]; then
    intra_violations=$(echo "$matches" | grep -vE "src\.research\.dgt_minute(\.|$|[[:space:]])" || true)
    if [ -n "$intra_violations" ]; then
      echo "$intra_violations"
      echo "FAIL: src/research/dgt_minute contains cross-import to non-dgt_minute src.research sub-namespace"
      violations=$((violations + 1))
    fi
  fi
fi

# NOTE (ADR 0023 §18.2 D21 — 2026-06-12): tests/ 는 의도적으로 이 검사에서 제외.
# tests/unit/ 파일이 src.research.* 를 import 하는 것은 활성 연구 overlay 기간 중
# 허용 (inner ring src/ 코드가 오염되지 않는 한). 아카이브 결정 라운드 시
# 해당 overlay 를 import 하는 tests/ 파일을 tests/research/ 로 이동하거나
# 삭제하는 것을 아카이브 작업의 일부로 수행.

if [ "$violations" -gt 0 ]; then
  echo "FAIL: namespace discipline violated ($violations inner ring(s))"
  exit 1
fi

echo "OK: namespace discipline preserved (7-ring grep + dgt/visualization/dynamic_adjustment/dgt_minute intra-research isolation)"
