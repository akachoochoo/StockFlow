# Phase 1.x — DGT minute (1m) overlay.
# ADR 0023 D15: 5th ring 재진입 — Phase 0.11.a `src/research/dgt/` 의 (b)
# 재설계 promote 경로 (ADR 0007 §1.7.2 (b)). 일봉 `dgt/` 는 invariant 보존
# (ADR 0023 D17), 본 모듈은 분봉(1m) 도메인에 맞게 처음부터 재설계.
#
# Informational namespace. All symbols underscore-prefix private —
# `from src.research.dgt_minute import *` exposes zero symbols.
#
# Outer→inner read OK (예: `from src.domain.models import Asset`,
# `from src.adapters.kis._client import KISClient`).
# Inner→outer import FORBIDDEN — enforced by scripts/check_namespace.sh
# (ADR 0007 §1.6 § Namespace Discipline + ADR 0023 AC13).
#
# Intra-research isolation (ADR 0023 §5.1): dgt_minute → 다른 5th ring
# sub-namespace (dgt / visualization / dynamic_adjustment) import 차단.
# 일봉 `dgt/` 의 cost_model 등을 재사용하지 않고 처음부터 재설계 (D15).
#
# Registry bypass (ADR 0007 §1.5 R5 계승): GridMinuteStrategy 는
# create_buy_strategy / SellStrategy factories 미등록. ADR 0023 D8
# (split 폐기 + DGT-only) 정합 — single-strategy 운영.

__all__: list[str] = []
