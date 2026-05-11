# Phase 0.11.a — DGT (Dynamic Grid Trading) overlay.
# Reference: arXiv:2506.11921v1 (Chen, Chen, Jang 2025).
#
# Informational namespace. All symbols underscore-prefix private —
# `from src.research.dgt import *` exposes zero symbols.
#
# Outer→inner read OK (e.g., `from src.domain.models import Asset`).
# Inner→outer import FORBIDDEN — enforced by scripts/check_namespace.sh
# (ADR 0007 §1.6 § Namespace Discipline + AC13).
#
# Registry bypass (ADR 0007 §1.5 R5): DGTStrategy NOT registered in
# create_buy_strategy / SellStrategy factories. CLAUDE.md §16.1.4
# single-sell-strategy assumption preserved.

__all__: list[str] = []
