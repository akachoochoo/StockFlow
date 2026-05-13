"""Phase 0.11.e.3 — `python -m src.research.dynamic_adjustment` entry shim.

ADR 0011 §1.3 D7 정합 — `src/cli/` 변경 zero (production rings 변경 zero
invariant 보존). 본 shim 은 `cli.main` delegation only.
"""
from __future__ import annotations

from src.research.dynamic_adjustment.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
