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
            data_dir=data_dir, downloader=fake_dl, runner=fake_run, report=False,
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
            downloader=lambda *a: called.append(a), runner=lambda args: 0, report=False,
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
            runner=lambda args: captured.update(args=args) or 0, report=False,
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


# ---------------------------------------------------------------------------
# Reporter (백테스트 후 차트/리포트 생성)
# ---------------------------------------------------------------------------
def _noop_dl(code, start, end, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("x", encoding="utf-8")


class TestReporterDispatch:
    def test_reporter_called_on_success(self, tmp_path):
        cfg = _grid_cfg(tmp_path / "g.yaml")
        rec: dict = {}
        run_pipeline(
            cfg, _START, _END, 1_000_000, data_dir=tmp_path / "d",
            downloader=_noop_dl, runner=lambda args: 0,
            reporter=lambda *a: rec.update(args=a),
        )
        assert rec.get("args") is not None
        assert rec["args"][0] == cfg  # config_path 전달
        assert "069500" in rec["args"][1]  # csv_map

    def test_reporter_skipped_when_runner_fails(self, tmp_path):
        cfg = _grid_cfg(tmp_path / "g.yaml")
        rec: list = []
        rc = run_pipeline(
            cfg, _START, _END, 1_000_000, data_dir=tmp_path / "d",
            downloader=_noop_dl, runner=lambda args: 1,
            reporter=lambda *a: rec.append(a),
        )
        assert rc == 1 and rec == []  # 실패 → 리포트 스킵

    def test_reporter_skipped_when_disabled(self, tmp_path):
        cfg = _grid_cfg(tmp_path / "g.yaml")
        rec: list = []
        run_pipeline(
            cfg, _START, _END, 1_000_000, data_dir=tmp_path / "d", report=False,
            downloader=_noop_dl, runner=lambda args: 0,
            reporter=lambda *a: rec.append(a),
        )
        assert rec == []


_RS, _RE = date(2024, 1, 1), date(2024, 1, 20)
_CLOSES = [
    35000, 36400, 38200, 37100, 34500, 32800, 31000, 33200, 35600, 38800,
    41200, 39500, 36900, 34100, 31500, 29800, 32400, 35100, 37800, 40500,
]


def _write_ohlcv(path: Path) -> Path:
    import datetime as _dt

    lines = ["date,open,high,low,close,volume"]
    for i, c in enumerate(_CLOSES):
        opn = _CLOSES[i - 1] if i > 0 else c
        hi, lo = max(opn, c) + 400, min(opn, c) - 400
        d = _RS + _dt.timedelta(days=i)
        lines.append(f"{d.isoformat()},{opn},{hi},{lo},{c},1000000")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestReporterE2E:
    def test_build_dgt_chart_html(self):
        import tempfile
        from decimal import Decimal

        from scripts.run_backtest import build_dgt_chart_html

        from src.cli.composition import asset_from_code
        from src.domain.models import Currency, Money
        from src.domain.strategies.grid import GridConfig
        from src.infrastructure.csv_market_data_loader import load_ohlcv_csv
        from src.use_cases.grid_runner import GridRunner

        asset = asset_from_code("069500")
        with tempfile.TemporaryDirectory() as d:
            csv = _write_ohlcv(__import__("pathlib").Path(d) / "x.csv")
            bars = load_ohlcv_csv(csv, asset)
        cfg = GridConfig(grid_count=11, fallback_k=Decimal("0.05"))
        result = GridRunner().run(
            asset=asset, bars=bars, config=cfg,
            initial_capital=Money(amount=Decimal("10000000"), currency=Currency.KRW),
        )
        html = build_dgt_chart_html(asset, bars, cfg, result)
        assert "lightweight-charts" in html.lower() or "candlestick" in html.lower()
        assert "069500" in html

    def test_report_grid_writes_interactive_chart(self, tmp_path):
        from scripts.run_backtest import _report_grid

        csv = _write_ohlcv(tmp_path / "x.csv")
        cfg = _grid_cfg(tmp_path / "g.yaml")
        rdir = tmp_path / "rpt"
        _report_grid(cfg, {"069500": csv}, _RS, _RE, 10_000_000, rdir)
        chart = rdir / "069500.html"
        assert chart.exists()
        assert "lightweight-charts" in chart.read_text(encoding="utf-8").lower()

    def test_report_split_writes_episode_index(self, tmp_path):
        from scripts.run_backtest import _report_split

        csv = _write_ohlcv(tmp_path / "x.csv")
        cfg = _strategies_cfg(tmp_path / "s.yaml")
        rdir = tmp_path / "rpt"
        _report_split(cfg, {"069500": csv}, _RS, _RE, 10_000_000, rdir)
        assert (rdir / "index.html").exists()
