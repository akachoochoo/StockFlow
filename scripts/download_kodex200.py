"""Placeholder for KODEX 200 OHLCV downloader (Phase 1+).

Per ADR §10.2, the Phase 0 CSV pipeline accepts arbitrary date,open,
high,low,close,volume files. Real production data acquisition (pykrx
or KIS API) lives in this script — but pykrx adds a network/runtime
dependency, so the actual implementation is deferred until the Phase 0
→ Phase 1 transition (real broker hookup).

Intended Phase 1 contract::

    python scripts/download_kodex200.py \\
        --start 2021-01-01 --end 2026-04-30 \\
        --out data/kodex200.csv

Output: a CSV in the exact format ``load_ohlcv_csv`` expects
(date,open,high,low,close,volume), KRX trading days only.
"""
from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write(
        "scripts/download_kodex200.py is a Phase 1 placeholder — pykrx "
        "is not yet a Phase 0 runtime dependency. "
        "For now, hand-curate the CSV in the format expected by "
        "load_ohlcv_csv (date,open,high,low,close,volume).\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
