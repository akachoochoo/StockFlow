"""Phase 0.11.e.4 — 회귀 invariant cross-check tests.

ADR 0011 §1.3 D12 — 본 phase 산출이 0.11.a~d 의 모든 invariant 를
보존하는지 cross-check.

검증 대상:
    - Phase 0.7.3 baseline (069500+132030 EQUAL + PriceDropStrategy)
      회귀 invariant — `BacktestRunner.per_asset_strategy_overrides`
      None default 시 single-strategy 동작 보존 (ADR 0010 §2.3 의사
      코드 정합).
    - ADR 0006 reporting layer 보존:
      * `StrategyRenderer` Protocol frozen (§4.2 invariant).
      * `BacktestResult` frozen dataclass 변경 zero.
    - ADR 0011 §1.6 #1 Production rings 변경 zero (Phase 0.11.x
      invariant).
    - namespace isolation 14 tests 영향 zero (intra-research forward /
      reverse 패턴 보존).
"""
from __future__ import annotations

import inspect

from src.application.backtest_runner import BacktestResult, BacktestRunner
from src.ports.strategy_renderer import (
    MarkerStyle,
    Panel,
    StrategyRenderer,
)


class TestPhase073BaselineCompat:
    """Phase 0.7.3 baseline 시그니처 보존 (ADR 0010 §2.3 회귀 invariant 정합)."""

    def test_backtest_runner_has_per_asset_strategy_overrides(self) -> None:
        """`per_asset_strategy_overrides` 인자 존재 — None default invariant."""
        sig = inspect.signature(BacktestRunner.__init__)
        assert "per_asset_strategy_overrides" in sig.parameters, (
            "Phase 0.7.3 baseline 회귀 invariant 위반: "
            "per_asset_strategy_overrides 인자 부재"
        )
        # None default = single-strategy 동작 보존.
        param = sig.parameters["per_asset_strategy_overrides"]
        assert param.default is None, (
            f"per_asset_strategy_overrides default 변경: {param.default}"
        )

    def test_backtest_runner_signature_stable(self) -> None:
        """BacktestRunner 핵심 인자 시그니처 보존 — ADR 0010 §1.2 진단 정합."""
        sig = inspect.signature(BacktestRunner.__init__)
        expected_params = {
            "assets",
            "strategy_config",
            "initial_capital",
            "ohlcv_by_asset",
            "sell_strategy_config",
            "reentry_strategy_name",
            "reentry_parameters",
            "per_asset_strategy_overrides",
            "buy_strategy_name",
        }
        actual_params = set(sig.parameters.keys()) - {"self"}
        missing = expected_params - actual_params
        assert not missing, (
            f"Phase 0.7.3 baseline 회귀 invariant 위반 — missing params: {missing}"
        )

    def test_backtest_result_frozen_dataclass_fields(self) -> None:
        """`BacktestResult` 핵심 필드 보존 (ADR 0010 §1.2 진단 정합)."""
        expected_fields = {
            "start_date",
            "end_date",
            "initial_capital",
            "decisions",
            "snapshots",
            "final_positions",
            "n_trading_days",
            "cagr_pct",
            "max_drawdown_pct",
            "sharpe_ratio",
            "calmar_ratio",
        }
        # BacktestResult is a frozen dataclass — extract field names.
        from dataclasses import fields

        actual_fields = {f.name for f in fields(BacktestResult)}
        missing = expected_fields - actual_fields
        assert not missing, (
            f"BacktestResult 필드 변경 — Phase 0.10.bb 박제 invariant 위반: "
            f"missing {missing}"
        )


class TestAdr0006ReportingLayerFrozen:
    """ADR 0006 §4.2 `StrategyRenderer` Protocol frozen invariant.

    본 phase D7 (iii) Strategy Registry 후보 채택 시 `StrategyRenderer`
    Protocol 시그니처 변경 major (frozen 위반) — 본 phase 는 *후보 박제
    only*, 채택 안 함 → Protocol 변경 zero.
    """

    def test_strategy_renderer_protocol_methods(self) -> None:
        """ADR 0006 §4.2 Protocol 3 method 보존."""
        for name in ("marker_label", "marker_style", "diagnostic_panels"):
            assert hasattr(StrategyRenderer, name), (
                f"ADR 0006 §4.2 frozen invariant 위반: StrategyRenderer.{name} 부재"
            )

    def test_marker_style_dataclass_fields(self) -> None:
        """`MarkerStyle` 4 필드 (color/marker/size/label) 보존."""
        from dataclasses import fields

        expected = {"color", "marker", "size", "label"}
        actual = {f.name for f in fields(MarkerStyle)}
        assert actual == expected, (
            "MarkerStyle 필드 변경 — ADR 0006 §4.2 frozen invariant 위반"
        )

    def test_panel_dataclass_fields(self) -> None:
        """`Panel` 2 필드 (title/rows) 보존."""
        from dataclasses import fields

        expected = {"title", "rows"}
        actual = {f.name for f in fields(Panel)}
        assert actual == expected, (
            "Panel 필드 변경 — ADR 0006 §4.2 frozen invariant 위반"
        )


class TestVisualizationProtocolFrozen:
    """ADR 0009 `_VisualizationRenderer` Protocol frozen (D7 (ii) 영향 zero)."""

    def test_visualization_renderer_protocol_methods(self) -> None:
        """`_VisualizationRenderer` 2 method 보존."""
        from src.research.visualization._visualization_renderer import (
            _VisualizationRenderer,
        )

        for name in ("render_full_period", "extract_overlay_metric"):
            assert hasattr(_VisualizationRenderer, name), (
                f"ADR 0009 frozen invariant 위반: "
                f"_VisualizationRenderer.{name} 부재"
            )


class TestProductionRingsUnchanged:
    """Phase 0.11.x invariant — production rings 변경 zero."""

    def test_no_dynamic_adjustment_imports_in_production_rings(self) -> None:
        """`src/{domain,application,adapters,use_cases,cli,infrastructure,
        ports}/` 어디서도 `src.research.dynamic_adjustment` import 부재.

        본 test = check_namespace.sh 의 코드화 — Python regex 기반.
        """
        import re
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        production_rings = (
            "src/domain",
            "src/application",
            "src/adapters",
            "src/use_cases",
            "src/cli",
            "src/infrastructure",
            "src/ports",
        )
        forbidden = re.compile(
            r"^\s*(from|import)\s+src\.research\.dynamic_adjustment(\.|$|\s)"
        )
        violations: list[str] = []
        for ring in production_rings:
            ring_path = repo_root / ring
            if not ring_path.exists():
                continue
            for py in ring_path.rglob("*.py"):
                content = py.read_text(encoding="utf-8")
                for lineno, line in enumerate(content.splitlines(), start=1):
                    if forbidden.match(line):
                        violations.append(f"{py}:{lineno}: {line.strip()}")
        assert not violations, (
            f"Phase 0.11.x invariant 위반 — production rings import "
            f"dynamic_adjustment: {violations}"
        )


class TestNamespaceIsolationStillPasses:
    """기존 namespace isolation 14 tests + 본 phase 신규 5 tests 모두 통과."""

    def test_check_namespace_script_exit_zero(self) -> None:
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["bash", str(repo_root / "scripts/check_namespace.sh")],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=False,
        )
        assert result.returncode == 0, (
            f"check_namespace.sh failed:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_dynamic_adjustment_namespace_in_script_output(self) -> None:
        """script 의 success message 에 dynamic_adjustment 박제 확인."""
        import subprocess
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            ["bash", str(repo_root / "scripts/check_namespace.sh")],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=False,
        )
        assert "dynamic_adjustment" in result.stdout, (
            f"script success message missing 'dynamic_adjustment': {result.stdout}"
        )
