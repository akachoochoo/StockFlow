"""Tests for scripts/run_backtest.py — 데이터 자동 확보 + 백테스트 파이프라인.

네트워크(pykrx) 없이: downloader/runner 를 주입해 (1) 없는 데이터만 다운로드,
(2) trading backtest 로 올바른 인자 위임, (3) 있는 데이터는 스킵을 잠근다.
"""
from __future__ import annotations

import sys
from datetime import date
from typing import TYPE_CHECKING

import pytest

_PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.run_backtest import (  # noqa: E402
    csv_path_for,
    enabled_codes,
    run_pipeline,
)

if TYPE_CHECKING:
    from pathlib import Path

_START = date(2025, 12, 2)
_END = date(2026, 5, 20)


def _strategies_cfg(path: Path, *, extra_disabled: bool = False) -> Path:
    body = """version: "0.5"
allocation_policy: EQUAL
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "price_drop"
    buy_parameters: {drop_threshold_pct: 5.0, max_split_count: 7, per_split_amount: 500000, max_split_per_day: 1}
    sell_strategy: "profit_target"
    sell_parameters: {profit_target_pct: 10.0, max_sells_per_day: 7}
    reentry_strategy: "hybrid"
    reentry_parameters: {cooldown_days: 60}
"""
    if extra_disabled:
        body += """  "132030":
    name: "KODEX 골드"
    enabled: false
    buy_strategy: "price_drop"
    buy_parameters: {drop_threshold_pct: 5.0, max_split_count: 7, per_split_amount: 500000, max_split_per_day: 1}
    sell_strategy: "profit_target"
    sell_parameters: {profit_target_pct: 10.0, max_sells_per_day: 7}
    reentry_strategy: "hybrid"
    reentry_parameters: {cooldown_days: 60}
"""
    path.write_text(body, encoding="utf-8")
    return path


def _grid_cfg(path: Path) -> Path:
    path.write_text(
        'version: "1.0"\nassets:\n  "069500":\n    name: "KODEX 200"\n'
        "    grid_parameters: {grid_count: 11, fallback_k: 0.05}\n",
        encoding="utf-8",
    )
    return path


class TestEnabledCodes:
    def test_strategies_config(self, tmp_path):
        assert enabled_codes(_strategies_cfg(tmp_path / "s.yaml")) == ["069500"]

    def test_skips_disabled(self, tmp_path):
        cfg = _strategies_cfg(tmp_path / "s.yaml", extra_disabled=True)
        assert enabled_codes(cfg) == ["069500"]  # 132030 disabled

    def test_grid_config(self, tmp_path):
        assert enabled_codes(_grid_cfg(tmp_path / "g.yaml")) == ["069500"]


class TestRunPipeline:
    def test_downloads_missing_then_delegates(self, tmp_path):
        cfg = _strategies_cfg(tmp_path / "s.yaml")
        data_dir = tmp_path / "data"
        downloaded: list[tuple] = []
        captured: dict = {}

        def fake_dl(code, start, end, out):
            downloaded.append((code, start, end, out))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("placeholder", encoding="utf-8")

        def fake_run(args):
            captured["args"] = args
            return 0

        rc = run_pipeline(
            cfg, _START, _END, 10_000_000,
            data_dir=data_dir, downloader=fake_dl, runner=fake_run,
        )
        assert rc == 0
        # 없는 데이터 → 다운로드 1회 (069500), 경로 = data_dir/표준파일명
        expected_csv = data_dir / "KRX_069500_2025-2026.csv"
        assert downloaded == [("069500", _START, _END, expected_csv)]
        # trading backtest 로 올바른 인자 위임
        args = captured["args"]
        assert args[0] == "backtest"
        assert "--config" in args and str(cfg) in args
        assert f"069500={expected_csv}" in args
        assert "2025-12-02" in args and "2026-05-20" in args
        assert "10000000" in args

    def test_skips_existing_data(self, tmp_path):
        cfg = _strategies_cfg(tmp_path / "s.yaml")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "KRX_069500_2025-2026.csv").write_text("x", encoding="utf-8")
        called: list = []
        run_pipeline(
            cfg, _START, _END, 10_000_000, data_dir=data_dir,
            downloader=lambda *a: called.append(a), runner=lambda args: 0,
        )
        assert called == []  # 이미 있으므로 다운로드 스킵

    def test_json_flag_forwarded(self, tmp_path):
        cfg = _grid_cfg(tmp_path / "g.yaml")
        data_dir = tmp_path / "data"
        captured: dict = {}
        run_pipeline(
            cfg, _START, _END, 25_000_000, as_json=True, data_dir=data_dir,
            downloader=lambda c, s, e, out: out.parent.mkdir(parents=True, exist_ok=True)
            or out.write_text("x", encoding="utf-8"),
            runner=lambda args: captured.update(args=args) or 0,
        )
        assert "--json" in captured["args"]

    def test_runner_exit_code_propagates(self, tmp_path):
        cfg = _strategies_cfg(tmp_path / "s.yaml")
        rc = run_pipeline(
            cfg, _START, _END, 10_000_000, data_dir=tmp_path / "d",
            downloader=lambda c, s, e, out: out.parent.mkdir(parents=True, exist_ok=True)
            or out.write_text("x", encoding="utf-8"),
            runner=lambda args: 2,
        )
        assert rc == 2

    def test_empty_config_errors(self, tmp_path):
        cfg = tmp_path / "empty.yaml"
        cfg.write_text('version: "0.5"\nassets: {}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="assets"):
            run_pipeline(cfg, _START, _END, 10_000_000)


class TestCsvPathFor:
    def test_default_dir(self):
        p = csv_path_for("069500", _START, _END, None)
        assert p.name == "KRX_069500_2025-2026.csv"

    def test_custom_dir(self, tmp_path):
        p = csv_path_for("069500", _START, _END, tmp_path)
        assert p == tmp_path / "KRX_069500_2025-2026.csv"
