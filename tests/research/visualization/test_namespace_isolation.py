"""Phase 0.11.c.2 — `src/research/visualization/` namespace isolation tests.

ADR 0009 §1.6 namespace + §1.3 D9 cross-import 방향성:
  - 정방향 허용: `src.research.visualization` → `src.research.dgt`
    (outer→inner read 의 5th ring 내부 확장).
  - 역방향 차단: ADR 0008 D9 grep rule 로 enforce (`src.research.dgt` →
    `src.research.visualization` 금지) — `check_namespace.sh` exit 0
    의무로 검증.
  - `src.research.visualization` → `src.research.{dynamic_adjustment,
    optimization 외 sibling}` 차단 (intra-research isolation 대칭 확장).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_VIS_DIR = Path("src/research/visualization")
_SCRIPT = Path("scripts/check_namespace.sh")
_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestAC1VisualizationNoSiblingResearchImport:
    """`src/research/visualization/**` 는 dgt 외 sibling research sub-namespace 미import."""

    def test_no_non_dgt_research_imports(self) -> None:
        vis_dir = _REPO_ROOT / _VIS_DIR
        if not vis_dir.exists():
            pytest.skip("src/research/visualization missing — repo layout issue")
        # visualization → dgt 정방향 허용, 그 외 src.research sub-namespace 차단.
        # 단, src.research.visualization 자기 자신 import (intra-vis) 도 허용.
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\.(?!dgt(\.|$|\s))"
            r"(?!visualization(\.|$|\s))"
        )
        violations: list[str] = []
        for py in vis_dir.rglob("*.py"):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if forbidden.match(line):
                    violations.append(f"{py}:{lineno}: {line}")
        assert not violations, (
            f"intra-research cross-import detected: {violations}"
        )


class TestAC2VisualizationToDGTForwardAllowed:
    """Visualization → DGT 정방향 import 패턴 인식 (negative test)."""

    def test_forward_import_pattern_allowed(self) -> None:
        # The forbidden regex must NOT match visualization → dgt imports.
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\.(?!dgt(\.|$|\s))"
            r"(?!visualization(\.|$|\s))"
        )
        allowed_lines = [
            "from src.research.dgt.results import _DGTBacktestResult",
            "import src.research.dgt.state",
            "from src.research.dgt import _x",
            "from src.research.visualization._artifacts import _GridSnapshot",
        ]
        for line in allowed_lines:
            assert not forbidden.match(line), (
                f"line incorrectly flagged as forbidden: {line!r}"
            )

    def test_forbidden_sibling_pattern_recognized(self) -> None:
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\.(?!dgt(\.|$|\s))"
            r"(?!visualization(\.|$|\s))"
        )
        # Hypothetical future siblings — confirm regex flags them.
        forbidden_lines = [
            "from src.research.dynamic_adjustment._x import _y",
            "import src.research.optimization._z",
        ]
        for line in forbidden_lines:
            assert forbidden.match(line), (
                f"line should be flagged as forbidden: {line!r}"
            )


class TestAC3CheckNamespaceScriptPasses:
    """`bash scripts/check_namespace.sh` exit code 0."""

    def test_script_exits_zero(self) -> None:
        script = _REPO_ROOT / _SCRIPT
        if not script.exists():
            pytest.skip("check_namespace.sh missing — repo layout issue")
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, (
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
