# Phase 0.11.a — 5th ring (outermost) namespace.
#
# Ring direction:
#   src/research/  ← outermost, MAY import from inner rings
#       ↓ outer→inner read OK
#   src/cli/, src/adapters/, src/infrastructure/
#       ↓
#   src/application/, src/use_cases/
#       ↓
#   src/ports/
#       ↓
#   src/domain/  ← innermost
#
# Rule (ADR 0007 §1.6): inner→outer import FORBIDDEN. Enforced by
# scripts/check_namespace.sh (D11 plain grep, 7-ring target).
#
# Lifecycle (ADR 0007 §1.7): D10 default = archive after Phase 0.11.a.5.
# Staleness tripwire = tests/integration/test_namespace_isolation.py FAIL.
