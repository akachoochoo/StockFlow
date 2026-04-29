"""Domain-level constants.

Per CLAUDE.md §1.1, stdlib imports are allowed in the domain. zoneinfo (Python
3.9+) is part of stdlib.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

# Korea Standard Time (UTC+9, no DST). Used by KRX market session checks.
# Storage and computation always use UTC (CLAUDE.md §3.1); KST is for the
# market-local conversions that adapters need to perform.
KST = ZoneInfo("Asia/Seoul")
