"""Phase 0.11.e.2 — `src/research/dynamic_adjustment/` namespace isolation tests.

ADR 0011 §1.3 D10 + §1.6 #2 + §1.7 R8:
  - Outer→inner read OK (e.g., `from src.application.backtest_runner
    import BacktestResult`).
  - 정방향 허용: `src.research.dynamic_adjustment` →
    `src.research.dgt` / `src.research.visualization` /
    `src.research.dynamic_adjustment` (intra-self).
  - 역방향 차단: `src.research.{dgt,visualization}` →
    `src.research.dynamic_adjustment` (`scripts/check_namespace.sh`
    grep rule 으로 enforce).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_DA_DIR = Path("src/research/dynamic_adjustment")
_SCRIPT = Path("scripts/check_namespace.sh")
_REPO_ROOT = Path(__file__).resolve().parents[3]


class TestAC1DAOnlyImportsAllowedTargets:
    """`src/research/dynamic_adjustment/**` 는 dgt + visualization +
    dynamic_adjustment (intra-self) 외 sibling sub-namespace 미import.
    """

    def test_no_unauthorized_research_imports(self) -> None:
        da_dir = _REPO_ROOT / _DA_DIR
        if not da_dir.exists():
            pytest.skip("src/research/dynamic_adjustment missing — repo layout issue")
        # Allow dgt + visualization + dynamic_adjustment, block 기타.
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\."
            r"(?!dgt(\.|$|\s))"
            r"(?!visualization(\.|$|\s))"
            r"(?!dynamic_adjustment(\.|$|\s))"
        )
        violations: list[str] = []
        for py in da_dir.rglob("*.py"):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if forbidden.match(line):
                    violations.append(f"{py}:{lineno}: {line}")
        assert not violations, (
            f"intra-research cross-import detected: {violations}"
        )


class TestAC2AllowedForwardImportsRecognized:
    """정방향 import 패턴이 forbidden regex 에 매칭 안 됨 (negative test)."""

    def test_dgt_import_allowed(self) -> None:
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\."
            r"(?!dgt(\.|$|\s))"
            r"(?!visualization(\.|$|\s))"
            r"(?!dynamic_adjustment(\.|$|\s))"
        )
        allowed_lines = [
            "from src.research.dgt.results import _DGTBacktestResult",
            "import src.research.dgt.state",
            "from src.research.visualization._align import _OverlayPayload",
            "from src.research.dynamic_adjustment._proposal import _Proposal",
        ]
        for line in allowed_lines:
            assert not forbidden.match(line), (
                f"line incorrectly flagged as forbidden: {line!r}"
            )

    def test_sibling_blocked(self) -> None:
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\."
            r"(?!dgt(\.|$|\s))"
            r"(?!visualization(\.|$|\s))"
            r"(?!dynamic_adjustment(\.|$|\s))"
        )
        forbidden_lines = [
            "from src.research.optimization_v2 import x",
            "import src.research.new_module",
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


class TestAC4NoSensitiveTokens:
    """§1.6 #2 enforcement — D1 원천 데이터 제약 grep 검증.

    `src/research/dynamic_adjustment/` 에 실시간 데이터 토큰 (VIX / 뉴스 /
    sentiment / twitter) 부재.
    """

    def test_no_realtime_signal_tokens(self) -> None:
        da_dir = _REPO_ROOT / _DA_DIR
        if not da_dir.exists():
            pytest.skip("src/research/dynamic_adjustment missing")
        forbidden_tokens = (
            "vix_value",
            "twitter_feed",
            "news_sentiment",
            "realtime_price",
        )
        violations: list[str] = []
        for py in da_dir.rglob("*.py"):
            content = py.read_text()
            for token in forbidden_tokens:
                # Match as identifier (whole word, case-sensitive lower).
                if re.search(rf"\b{token}\b", content):
                    violations.append(f"{py}: contains forbidden token {token!r}")
        assert not violations, (
            f"D1 원천 데이터 제약 violation: {violations}. "
            f"실시간 신호 token 부재 invariant 위반."
        )
