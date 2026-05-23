"""`trading grid-backtest` CLI 통합 테스트 (ADR 0022 G1 증분 4).

CliRunner 로 grid-backtest 명령을 임시 CSV 에 대해 구동 — 사람 출력 + --json +
가드(미등록 코드 / 빈 기간). GridRunner 자체 동치/결정론은 단위 테스트가 담당.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from src.cli.main import main

if TYPE_CHECKING:
    from pathlib import Path

# 35000 기준 swing 종가 (정수). open=전일종가, high/low=±400 band (정수 invariant).
_CLOSES = [
    35000, 36400, 38200, 37100, 34500, 32800, 31000, 33200, 35600, 38800,
    41200, 39500, 36900, 34100, 31500, 29800, 32400, 35100, 37800, 40500,
    42100, 39700, 36300, 33800, 30900, 28500, 31200, 34600, 37200, 39900,
]


def _write_csv(tmp_path: Path) -> Path:
    lines = ["date,open,high,low,close,volume"]
    for i, c in enumerate(_CLOSES):
        opn = _CLOSES[i - 1] if i > 0 else c
        hi = max(opn, c) + 400
        lo = min(opn, c) - 400
        lines.append(f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d},{opn},{hi},{lo},{c},1000000")
    path = tmp_path / "069500.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _args(csv: Path, **over) -> list[str]:
    base = {
        "--csv": str(csv),
        "--code": "069500",
        "--start": "2024-01-01",
        "--end": "2024-02-02",
        "--capital": "25000000",
    }
    base.update(over)
    out = ["grid-backtest"]
    for k, v in base.items():
        out += [k, v]
    return out


class TestGridBacktestCLI:
    def test_human_output(self, tmp_path: Path):
        csv = _write_csv(tmp_path)
        result = CliRunner().invoke(main, _args(csv))
        assert result.exit_code == 0, result.output
        assert "DGT grid-backtest" in result.output
        assert "KRX:069500" in result.output
        assert "Buy&Hold" in result.output
        assert "MDD" in result.output

    def test_json_output(self, tmp_path: Path):
        csv = _write_csv(tmp_path)
        result = CliRunner().invoke(main, [*_args(csv), "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["asset"] == "KRX:069500"
        assert "dgt" in payload and "buy_and_hold" in payload
        assert "max_drawdown_pct" in payload["dgt"]
        assert int(payload["dgt"]["trades"]) >= 0

    def test_unknown_code_errors(self, tmp_path: Path):
        csv = _write_csv(tmp_path)
        result = CliRunner().invoke(main, _args(csv, **{"--code": "999999"}))
        assert result.exit_code != 0
        assert "미등록" in result.output

    def test_empty_window_errors(self, tmp_path: Path):
        csv = _write_csv(tmp_path)
        result = CliRunner().invoke(
            main, _args(csv, **{"--start": "2030-01-01", "--end": "2030-12-31"})
        )
        assert result.exit_code != 0
        assert "데이터가 없습니다" in result.output

    def test_on_breach_atr_no_gate(self, tmp_path: Path):
        csv = _write_csv(tmp_path)
        result = CliRunner().invoke(
            main,
            [
                *_args(csv),
                "--rebalance", "on_breach",
                "--measure", "atr",
                "--no-volume-gate",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "on_breach atr" in result.output
