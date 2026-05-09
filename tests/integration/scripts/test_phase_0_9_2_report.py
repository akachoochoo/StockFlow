"""End-to-end regen integration test (Phase 0.10.y §15.5 / Patch P2/E3).

Invokes ``scripts/generate_phase_0_9_2_report.py`` end-to-end (yaml + csv +
backtest + report). Asserts the rendered ``episode_1.html`` contains the
``<h2>전략 정보</h2>`` section. Without this, ``strategy_info=None`` silent
wiring regression in the script would be undetectable from unit tests
(unit tests only cover html_writer in isolation).

Marked as integration — uses real csv data (``data/historical/``) and
runs a 5-asset backtest. Skipped if the csv data dir is absent.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "generate_phase_0_9_2_report.py"
CSV_DIR = ROOT / "data" / "historical"


pytestmark = pytest.mark.integration


def _csv_present() -> bool:
    if not CSV_DIR.exists():
        return False
    # At least one of the Phase 0.9.2 5 symbols' csv must exist
    for code in ("005930", "005380", "055550", "097950", "015760"):
        candidates = [
            f"KRX_{code}_2020-2024.csv",
            f"KRX_{code}_2019-2024.csv",
        ]
        if not any((CSV_DIR / name).exists() for name in candidates):
            return False
    return True


@pytest.mark.skipif(
    not _csv_present(),
    reason="Phase 0.9.2 csv data not present (run download_kr_assets.py)",
)
def test_regen_emits_strategy_info_section(tmp_path: Path):
    out_dir = tmp_path / "regen"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--output-dir", str(out_dir),
        ],
        capture_output=True, text=True, cwd=str(ROOT),
        timeout=300,
    )
    assert result.returncode == 0, (
        f"script failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    ep1 = out_dir / "episode_1.html"
    assert ep1.exists(), f"episode_1.html not produced; cwd={list(out_dir.iterdir())}"
    content = ep1.read_text(encoding="utf-8")

    # Patch P2 — three substring asserts to catch silent strategy_info=None
    # wiring regressions in the script
    assert content.count("<summary>전략 정보</summary>") >= 1, (
        "전략 정보 section missing from episode_1.html — "
        "silent strategy_info=None regression in script?"
    )
    assert "price_drop" in content, (
        "buy_strategy_name 'price_drop' missing from rendered section"
    )
    assert "5.00%" in content, (
        "drop_threshold_pct '5.00%' missing — formatter regression?"
    )

    # Index also gets the section
    idx = out_dir / "index.html"
    assert idx.exists()
    idx_content = idx.read_text(encoding="utf-8")
    assert "<summary>전략 정보</summary>" in idx_content
