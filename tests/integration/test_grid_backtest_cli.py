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
        assert "실현" in result.output and "미실현" in result.output  # 손익 분해
        assert "투입" in result.output  # 실현 투입 대비 비율
        assert "보유" in result.output  # 보유 수량
        assert "예수금" in result.output and "회전율" in result.output

    def test_json_output(self, tmp_path: Path):
        csv = _write_csv(tmp_path)
        result = CliRunner().invoke(main, [*_args(csv), "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["asset"] == "KRX:069500"
        assert "dgt" in payload and "buy_and_hold" in payload
        assert "max_drawdown_pct" in payload["dgt"]
        assert int(payload["dgt"]["trades"]) >= 0
        assert "realized_pnl" in payload["dgt"]
        assert "unrealized_pnl" in payload["dgt"]
        for k in ("final_avg_cost", "final_cash", "turnover", "realized_cost_basis"):
            assert k in payload["dgt"]

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


def _write_grid_config(tmp_path: Path, codes: list[str]) -> Path:
    lines = ['version: "1.0"', "assets:"]
    for c in codes:
        lines += [
            f'  "{c}":',
            f'    name: "{c}"',
            "    grid_parameters: {grid_count: 11, fallback_k: 0.05}",
        ]
    p = tmp_path / "grid.yaml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _two_csvs(tmp_path: Path) -> tuple[Path, Path]:
    csv_a = _write_csv(tmp_path)  # 069500.csv
    csv_b = tmp_path / "132030.csv"
    csv_b.write_text(csv_a.read_text(encoding="utf-8"), encoding="utf-8")
    return csv_a, csv_b


class TestGridBacktestConfig:
    def test_multi_asset_human_output(self, tmp_path: Path):
        csv_a, csv_b = _two_csvs(tmp_path)
        cfg = _write_grid_config(tmp_path, ["069500", "132030"])
        result = CliRunner().invoke(
            main,
            ["grid-backtest", "--config", str(cfg),
             "--csv", f"069500={csv_a}", "--csv", f"132030={csv_b}",
             "--start", "2024-01-01", "--end", "2024-02-02",
             "--capital", "100000000"],
        )
        assert result.exit_code == 0, result.output
        assert "멀티에셋" in result.output and "2 종목" in result.output
        assert "KRX:069500" in result.output and "KRX:132030" in result.output
        assert "Buy&Hold" in result.output
        assert "실현" in result.output and "미실현" in result.output  # 손익 분해
        assert "보유" in result.output  # 종목별 보유 수량
        assert "예수금" in result.output and "회전율" in result.output  # 포트폴리오

    def test_json_output(self, tmp_path: Path):
        csv_a, csv_b = _two_csvs(tmp_path)
        cfg = _write_grid_config(tmp_path, ["069500", "132030"])
        result = CliRunner().invoke(
            main,
            ["grid-backtest", "--config", str(cfg),
             "--csv", f"069500={csv_a}", "--csv", f"132030={csv_b}",
             "--start", "2024-01-01", "--end", "2024-02-02",
             "--capital", "100000000", "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["mode"] == "config"
        assert len(payload["dgt"]["per_asset"]) == 2
        assert payload["dgt"]["per_asset"][0]["allocated"] == "50000000"
        assert "realized_pnl" in payload["dgt"] and "unrealized_pnl" in payload["dgt"]
        assert "realized_pnl" in payload["dgt"]["per_asset"][0]
        assert "final_cash" in payload["dgt"] and "turnover" in payload["dgt"]
        assert "realized_cost_basis" in payload["dgt"]
        for k in (
            "final_holdings", "final_avg_cost", "final_cash", "turnover",
            "realized_cost_basis",
        ):
            assert k in payload["dgt"]["per_asset"][0]

    def test_config_and_code_mutually_exclusive(self, tmp_path: Path):
        csv_a, _ = _two_csvs(tmp_path)
        cfg = _write_grid_config(tmp_path, ["069500"])
        result = CliRunner().invoke(
            main,
            ["grid-backtest", "--config", str(cfg), "--code", "069500",
             "--csv", f"069500={csv_a}",
             "--start", "2024-01-01", "--end", "2024-02-02"],
        )
        assert result.exit_code != 0
        assert "함께 쓸 수 없습니다" in result.output

    def test_csv_code_mismatch_errors(self, tmp_path: Path):
        csv_a, _ = _two_csvs(tmp_path)
        cfg = _write_grid_config(tmp_path, ["069500", "132030"])
        result = CliRunner().invoke(
            main,
            ["grid-backtest", "--config", str(cfg),
             "--csv", f"069500={csv_a}",  # 132030 누락
             "--start", "2024-01-01", "--end", "2024-02-02"],
        )
        assert result.exit_code != 0
        assert "불일치" in result.output

    def test_neither_config_nor_code_errors(self, tmp_path: Path):
        csv = _write_csv(tmp_path)
        result = CliRunner().invoke(
            main,
            ["grid-backtest", "--csv", str(csv),
             "--start", "2024-01-01", "--end", "2024-02-02"],
        )
        assert result.exit_code != 0
        assert "필요합니다" in result.output

    def test_rejects_strategy_config(self, tmp_path: Path):
        # 분할매수 strategies config 를 grid-backtest 에 잘못 넣으면 안내(신호등).
        csv_a, _ = _two_csvs(tmp_path)
        strat = tmp_path / "strat.yaml"
        strat.write_text(
            'version: "0.5"\nallocation_policy: EQUAL\nassets:\n'
            '  "069500":\n    name: "KODEX 200"\n    enabled: true\n'
            '    buy_strategy: "price_drop"\n'
            "    buy_parameters: {drop_threshold_pct: 5.0, max_split_count: 7, "
            "per_split_amount: 500000, max_split_per_day: 1}\n"
            '    sell_strategy: "profit_target"\n'
            "    sell_parameters: {profit_target_pct: 10.0, max_sells_per_day: 7}\n"
            '    reentry_strategy: "hybrid"\n'
            "    reentry_parameters: {cooldown_days: 60}\n",
            encoding="utf-8",
        )
        result = CliRunner().invoke(
            main,
            ["grid-backtest", "--config", str(strat),
             "--csv", f"069500={csv_a}",
             "--start", "2024-01-01", "--end", "2024-02-02"],
        )
        assert result.exit_code != 0
        assert "trading backtest" in result.output  # points to the right command
