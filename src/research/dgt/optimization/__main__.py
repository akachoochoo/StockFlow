"""Phase 0.11.b — `python -m src.research.dgt.optimization` entry.

Delegates to `_runner_cli.main`. Terminal entry — ring boundary 위반 아님
(ADR 0007 §1.6.2).
"""
from __future__ import annotations

from src.research.dgt.optimization._runner_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
