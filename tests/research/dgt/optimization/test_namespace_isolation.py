"""Phase 0.11.b — Namespace isolation tests (ADR 0008 §1.6 D9).

`src/research/dgt/optimization/` 모듈 들이:
  - src.research.{visualization, dynamic_adjustment, ...} (dgt 외 sub-namespace)
    import 금지 (intra-research cross-import 차단).
  - src.research.dgt.* 정방향 import 허용 (intra-dgt OK).

추가: `bash scripts/check_namespace.sh` exit code 0 의무.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


_OPT_DIR = Path("src/research/dgt/optimization")
_SCRIPT = Path("scripts/check_namespace.sh")
_REPO_ROOT = Path(__file__).resolve().parents[4]


class TestAC1NoIntraResearchImport:
    """`src/research/dgt/**` does NOT import from sibling research sub-packages."""

    def test_no_non_dgt_research_imports(self) -> None:
        opt_dir = _REPO_ROOT / _OPT_DIR
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\.(?!dgt(\.|$|\s))"
        )
        violations: list[str] = []
        for py in opt_dir.rglob("*.py"):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if forbidden.match(line):
                    violations.append(f"{py}:{lineno}: {line}")
        assert not violations, (
            f"intra-research cross-import detected: {violations}"
        )


class TestAC2DGTSubmoduleImportsOK:
    """`src.research.dgt.<sub>` (intra-dgt) import 는 허용."""

    def test_intra_dgt_imports_allowed(self) -> None:
        # Verify imports work — sanity-check optimization modules load OK.
        # noqa references silence: these are isolation checks.
        from src.research.dgt.optimization import _dsr  # noqa: F401
        from src.research.dgt.optimization import _grid_generator  # noqa: F401
        from src.research.dgt.optimization import _wfo_splitter  # noqa: F401

    def test_dgt_sibling_import_pattern_recognized(self) -> None:
        # Allow regex must accept `src.research.dgt.formulas` etc.
        allowed_lines = [
            "from src.research.dgt.formulas import _x",
            "import src.research.dgt.cost_model",
            "from src.research.dgt import _y",
        ]
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\.(?!dgt(\.|$|\s))"
        )
        for line in allowed_lines:
            assert not forbidden.match(line), line


class TestAC3CheckNamespaceScript:
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
        )
        assert result.returncode == 0, (
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
