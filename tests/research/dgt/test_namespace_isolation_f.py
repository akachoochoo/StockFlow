"""Phase 0.11.f — namespace isolation verification.

5th ring files must not be imported by inner ring modules.
Inner ring = src/{domain,ports,use_cases,application,adapters,cli,infrastructure}.
"""
from __future__ import annotations

import subprocess

import pytest


PHASE_F_MODULES = [
    "dynamic_runner",
    "adaptive_runner",
    "paper_runner",
    "paper_adaptive_runner",
    "kakao_dgt_backtest",
]

INNER_RINGS = [
    "src/domain",
    "src/ports",
    "src/use_cases",
    "src/application",
    "src/adapters",
    "src/cli",
    "src/infrastructure",
]


class TestNamespaceIsolationF:
    """Inner ring must not import Phase 0.11.f modules."""

    @pytest.mark.parametrize("module", PHASE_F_MODULES)
    def test_no_inner_ring_import(self, module: str) -> None:
        """grep inner rings for any *import* of this module.

        ADR 0022 §9.0 (DGT 승격): inner ring 으로 포팅된 grid 코드는 출처를
        docstring 에 인용한다(예: "research ``_compute_atr`` 포팅"). 규칙은
        여전히 "inner ring 이 research 를 **import** 금지" — 따라서 단순 문자열
        매칭이 아니라 **import 라인**(``from``/``import`` 시작)만 검사한다.
        docstring/주석의 출처 인용은 위반이 아니다.
        """
        pattern = rf"^[[:space:]]*(from|import)[[:space:]].*{module}"
        for ring in INNER_RINGS:
            result = subprocess.run(
                ["grep", "-rE", pattern, ring, "--include=*.py"],
                capture_output=True, text=True,
            )
            assert result.returncode != 0, (
                f"Inner ring {ring} imports {module}: {result.stdout.strip()}"
            )

    def test_check_namespace_script_passes(self) -> None:
        """scripts/check_namespace.sh must pass."""
        result = subprocess.run(
            ["bash", "scripts/check_namespace.sh"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"check_namespace.sh failed: {result.stdout}\n{result.stderr}"

    def test_init_all_empty(self) -> None:
        """src/research/dgt/__init__.py must have __all__ = []."""
        import src.research.dgt as dgt_pkg
        assert dgt_pkg.__all__ == []
