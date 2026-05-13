"""Phase 0.11.c.4 — CLI smoke test (ADR 0009 §1.3 D7).

`python -m src.research.visualization compare` 진입점 smoke test.
실제 5y CSV 미사용 (test 격리) — `_load_ohlcv_csv` 가 매번 호출되므로
임시 CSV 를 생성해서 e2e 검증.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _synth_ohlcv_csv(path: Path, *, n_days: int = 40) -> None:
    """단순 sinusoid CSV 생성 — DGT runner + B&H 동작 충분."""
    base = date(2024, 1, 2)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["date", "open", "high", "low", "close", "volume"],
        )
        writer.writeheader()
        for i in range(n_days):
            # 100원 기준 ±10원 변동 — DGT 5% spacing 으로 multiple grid 발화 보장.
            price = 100 + ((i % 7) - 3) * 3
            writer.writerow(
                {
                    "date": (base + timedelta(days=i)).isoformat(),
                    "open": str(price),
                    "high": str(price + 1),
                    "low": str(price - 1),
                    "close": str(price),
                    "volume": "1000",
                }
            )


class TestAC1CompareDGTAndBH:
    """`compare --skip-7split` — DGT + B&H 만 산출."""

    def test_compare_runs_end_to_end(self, tmp_path: Path) -> None:
        pytest.importorskip("matplotlib")
        from src.research.visualization.cli import main

        csv_path = tmp_path / "synth.csv"
        _synth_ohlcv_csv(csv_path, n_days=40)
        out_dir = tmp_path / "out"
        exit_code = main(
            [
                "compare",
                "--start", "2024-01-02",
                "--end", "2024-12-30",
                "--csv", str(csv_path),
                "--output-dir", str(out_dir),
                "--initial-capital", "1000000",
                "--n", "4",
                "--k", "5",
                "--m", "2",
                "--skip-7split",
            ]
        )
        assert exit_code == 0
        # All expected outputs present.
        for fname in (
            "dgt_full_period.png",
            "comparison_overlay_pnl.png",
            "comparison_overlay_drawdown.png",
            "comparison_grid.png",
            "overlay_metrics.json",
        ):
            assert (out_dir / fname).exists(), f"{fname} missing"
            if fname.endswith(".png"):
                assert (out_dir / fname).read_bytes().startswith(b"\x89PNG")

    def test_unsupported_asset_rejected(self, tmp_path: Path) -> None:
        from src.research.visualization.cli import main

        with pytest.raises(SystemExit, match="D3 default = 069500"):
            main(
                [
                    "compare",
                    "--asset", "005930",
                    "--start", "2024-01-02",
                    "--end", "2024-12-30",
                    "--output-dir", str(tmp_path),
                ]
            )

    def test_metrics_json_valid(self, tmp_path: Path) -> None:
        pytest.importorskip("matplotlib")
        import json

        from src.research.visualization.cli import main

        csv_path = tmp_path / "synth.csv"
        _synth_ohlcv_csv(csv_path, n_days=40)
        out_dir = tmp_path / "out"
        main(
            [
                "compare",
                "--start", "2024-01-02",
                "--end", "2024-12-30",
                "--csv", str(csv_path),
                "--output-dir", str(out_dir),
                "--initial-capital", "1000000",
                "--n", "4",
                "--k", "5",
                "--m", "2",
                "--skip-7split",
            ]
        )
        metrics = json.loads((out_dir / "overlay_metrics.json").read_text())
        assert "dgt" in metrics
        assert "buy_and_hold" in metrics
        for strategy_metrics in metrics.values():
            # Decimal str values (CLAUDE.md §2.1)
            assert "final_pnl" in strategy_metrics
            assert "final_drawdown" in strategy_metrics
            # Parse back to Decimal — verifies valid numeric str format.
            Decimal(strategy_metrics["final_pnl"])
            Decimal(strategy_metrics["final_drawdown"])
