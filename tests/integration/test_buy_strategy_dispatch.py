"""ADR 0022 §11 D16 — ``--config`` 가 buy_strategy 를 실제 디스패치하는지 회귀.

기존 버그(§11.2): ``_resolve_strategy_configs`` 가 ``buy_strategy_name`` 을
반환하지 않아 backtest/paper 가 strategies.yaml 의 ``support_level`` 도
``price_drop`` 으로 조용히 실행했다(실구동 = 전용 스크립트). 본 테스트는
디스패치가 복구됐고 ``price_drop`` 회귀가 zero 임을 잠근다.
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING, ClassVar

import click
import pytest
from click.testing import CliRunner

from src.cli import safety
from src.cli.main import _resolve_strategy_configs, main

if TYPE_CHECKING:
    from pathlib import Path

# src.cli.__init__ re-exports the `main` group, shadowing the `src.cli.main`
# *submodule* on attribute access — fetch the real module from sys.modules so
# monkeypatch targets the module global the CLI actually calls.
_MAIN = sys.modules["src.cli.main"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "_DEFAULT_LOCK_PATH", tmp_path / "test.lock")


@pytest.fixture
def csv_path(tmp_path) -> Path:
    rows = [
        ("2026-04-27", "30000", "30200", "29800", "30000", "1000"),
        ("2026-04-28", "30000", "30100", "29900", "30000", "1000"),
        ("2026-04-29", "29000", "29100", "27900", "28000", "2000"),
        ("2026-04-30", "28000", "28200", "27900", "28100", "1500"),
    ]
    csv = tmp_path / "kodex.csv"
    csv.write_text(
        "date,open,high,low,close,volume\n"
        + "\n".join(",".join(r) for r in rows)
        + "\n",
        encoding="utf-8",
    )
    return csv


def _write_config(path: Path, buy_strategy: str) -> Path:
    path.write_text(
        f"""version: "0.5"
allocation_policy: EQUAL
assets:
  "069500":
    name: "KODEX 200"
    enabled: true
    buy_strategy: "{buy_strategy}"
    buy_parameters:
      drop_threshold_pct: 5.0
      max_split_count: 7
      per_split_amount: 500000
      max_split_per_day: 1
    sell_strategy: "profit_target"
    sell_parameters:
      profit_target_pct: 10.0
      max_sells_per_day: 7
    reentry_strategy: "hybrid"
    reentry_parameters:
      cooldown_days: 60
""",
        encoding="utf-8",
    )
    return path


_RESOLVE_KW = {
    "drop_pct": "5.0",
    "max_split": 7,
    "per_split_amount": 500000,
    "max_split_per_day": 1,
    "profit_target_pct": "10.0",
    "max_sells_per_day": 7,
    "reentry_strategy": "hybrid",
    "cooldown_days": 60,
}


# ---------------------------------------------------------------------------
# Unit: _resolve_strategy_configs returns buy_strategy_name
# ---------------------------------------------------------------------------
class TestResolveBuyStrategyName:
    def test_config_support_level(self, tmp_path):
        cfg = _write_config(tmp_path / "sl.yaml", "support_level")
        result = _resolve_strategy_configs(click.Context(main), cfg, **_RESOLVE_KW)
        assert result[-1] == "support_level"

    def test_config_price_drop(self, tmp_path):
        cfg = _write_config(tmp_path / "pd.yaml", "price_drop")
        result = _resolve_strategy_configs(click.Context(main), cfg, **_RESOLVE_KW)
        assert result[-1] == "price_drop"

    def test_flag_only_price_drop(self):
        result = _resolve_strategy_configs(click.Context(main), None, **_RESOLVE_KW)
        assert result[-1] == "price_drop"


# ---------------------------------------------------------------------------
# Integration: the resolved name actually reaches BacktestRunner (plumbing)
# ---------------------------------------------------------------------------
class _AbortError(Exception):
    """Short-circuit the spy after capturing constructor kwargs."""


class _SpyBacktestRunner:
    last: ClassVar[dict] = {}

    def __init__(self, **kwargs):
        type(self).last = dict(kwargs)

    def run(self, *_args, **_kwargs):
        raise _AbortError


class TestBacktestDispatchesToRunner:
    def test_config_support_level_reaches_runner(
        self, tmp_path, csv_path, monkeypatch
    ):
        cfg = _write_config(tmp_path / "sl.yaml", "support_level")
        monkeypatch.setattr(_MAIN, "BacktestRunner", _SpyBacktestRunner)
        CliRunner().invoke(
            main,
            ["backtest", "--config", str(cfg), "--csv", f"069500={csv_path}",
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert _SpyBacktestRunner.last.get("buy_strategy_name") == "support_level"

    def test_flag_only_reaches_runner_as_price_drop(self, csv_path, monkeypatch):
        monkeypatch.setattr(_MAIN, "BacktestRunner", _SpyBacktestRunner)
        CliRunner().invoke(
            main,
            ["backtest", "--csv", str(csv_path), "--drop-pct", "5.0",
             "--per-split-amount", "500000",
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert _SpyBacktestRunner.last.get("buy_strategy_name") == "price_drop"


class TestConfigKindGuard:
    """ADR 0022 §11 onboarding — 잘못된 config 타입 → 올바른 명령 안내(신호등)."""

    def test_backtest_rejects_grid_config(self, csv_path, tmp_path):
        grid = tmp_path / "grid.yaml"
        grid.write_text(
            'version: "1.0"\nassets:\n  "069500":\n    name: "KODEX 200"\n'
            "    grid_parameters: {grid_count: 11, fallback_k: 0.05}\n",
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            main,
            ["backtest", "--config", str(grid), "--csv", f"069500={csv_path}",
             "--start", "2026-04-27", "--end", "2026-04-30"],
        )
        assert result.exit_code != 0
        assert "grid-backtest" in result.output  # points to the right command
