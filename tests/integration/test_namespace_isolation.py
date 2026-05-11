"""Phase 0.11.a — Namespace discipline boundary tests (AC13 + Architect Nudge 4).

ADR 0007 §1.6 + §1.6.2: `src/research/` 는 5th ring (outermost). Inner ring
7개 (adapters/application/cli/domain/infrastructure/ports/use_cases) 에서
`from src.research.*` import FORBIDDEN.

본 test 는 `tests/integration/` 에 위치 (기존 convention, Architect Round 2
Nudge 4 — `tests/research/` 위치 정정).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_namespace.sh"
_INNER_RINGS = [
    "src/adapters",
    "src/application",
    "src/cli",
    "src/domain",
    "src/infrastructure",
    "src/ports",
    "src/use_cases",
]


class TestAC13NamespaceCI:
    def test_script_exists_and_executable(self) -> None:
        """scripts/check_namespace.sh 존재 + executable."""
        assert _SCRIPT.exists(), f"missing: {_SCRIPT}"
        import os

        assert os.access(_SCRIPT, os.X_OK), f"not executable: {_SCRIPT}"

    def test_script_passes_on_clean_repo(self) -> None:
        """AC13: 현재 repo 상태에서 exit 0 + 'OK' 메시지."""
        result = subprocess.run(
            ["bash", str(_SCRIPT)],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"namespace check failed (clean repo expected):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout

    def test_script_enumerates_seven_rings(self) -> None:
        """Critic Major #1 흡수: 7-ring 전부 enumerate."""
        content = _SCRIPT.read_text(encoding="utf-8")
        for ring in _INNER_RINGS:
            assert ring in content, f"7-ring grep target missing: {ring}"


class TestAC13BoundarySanity:
    """Architect Round 2 Nudge 4 boundary sanity — grep 패턴이 violation 캐치."""

    def test_grep_pattern_catches_from_import(self, tmp_path: Path) -> None:
        violation = tmp_path / "fake_inner_ring.py"
        violation.write_text("from src.research.dgt import _foo\n", encoding="utf-8")
        result = subprocess.run(
            [
                "grep",
                "-rEn",
                r"^[[:space:]]*(from|import)[[:space:]]+src\.research(\.|$|[[:space:]])",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "src.research" in result.stdout

    def test_grep_pattern_catches_direct_import(self, tmp_path: Path) -> None:
        violation = tmp_path / "fake_inner_ring.py"
        violation.write_text("import src.research.dgt\n", encoding="utf-8")
        result = subprocess.run(
            [
                "grep",
                "-rEn",
                r"^[[:space:]]*(from|import)[[:space:]]+src\.research(\.|$|[[:space:]])",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_grep_pattern_ignores_unrelated_imports(self, tmp_path: Path) -> None:
        """Outer→inner read (research 의 domain import) 는 grep 캐치 안 함 — 정상."""
        non_violation = tmp_path / "ok.py"
        non_violation.write_text(
            "from src.domain.models import Asset\nimport datetime\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "grep",
                "-rEn",
                r"^[[:space:]]*(from|import)[[:space:]]+src\.research(\.|$|[[:space:]])",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        # grep returns 1 when no match (expected)
        assert result.returncode == 1
        assert result.stdout == ""


@pytest.mark.parametrize("ring", _INNER_RINGS)
class TestInnerRingsNoResearchImport:
    """각 inner ring 개별 검증 — `from src.research` import zero."""

    def test_ring_has_no_research_import(self, ring: str) -> None:
        ring_path = _REPO_ROOT / ring
        if not ring_path.exists():
            pytest.skip(f"{ring} does not exist")
        result = subprocess.run(
            [
                "grep",
                "-rEn",
                r"^[[:space:]]*(from|import)[[:space:]]+src\.research(\.|$|[[:space:]])",
                str(ring_path),
            ],
            capture_output=True,
            text=True,
        )
        # grep returncode 1 = no match (expected)
        assert result.returncode == 1, (
            f"{ring} contains src.research import:\n{result.stdout}"
        )
