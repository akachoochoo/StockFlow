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
        """grep inner rings for any import of this module."""
        for ring in INNER_RINGS:
            result = subprocess.run(
                ["grep", "-r", module, ring, "--include=*.py"],
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
