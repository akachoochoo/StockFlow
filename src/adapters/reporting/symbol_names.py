"""Symbol code → display name mapping (Phase 0.10.h — ADR 0006 §14).

리포팅 layer 한정 표시명 dict. 미등록 코드는 fallback (code only).
Phase 0.11 yaml 분리 검토 (ADR 0007 trigger). 현재는 코드 박제.

CLAUDE.md §1.1 정합 — Asset 도메인 모델은 인간 친화 이름을 책임지지
않음 (display 메타데이터). 따라서 adapter layer 에 위치.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


SYMBOL_NAMES: dict[str, str] = {
    # Phase 0.9.1 / 0.9.2 — KR 개별 주식
    "005930": "삼성전자",
    "005380": "현대차",
    "055550": "신한지주",
    "097950": "CJ제일제당",
    "015760": "한국전력",
    # Phase 0.7.x — KR ETF
    "069500": "KODEX 200",
    "132030": "KODEX 골드선물(H)",
    "214980": "KODEX 단기채권 PLUS",
}


def display_symbol(
    code: str, names: Mapping[str, str] | None = None,
) -> str:
    """``code`` 를 ``"<code> <이름>"`` 형태로 표기.

    Args:
        code: asset code (예: ``"005930"``)
        names: 매핑 override (None = 모듈 default ``SYMBOL_NAMES``)

    Returns:
        매핑 존재 시 ``"005930 삼성전자"``, 미등록 시 ``code`` 그대로.
    """
    table = names if names is not None else SYMBOL_NAMES
    name = table.get(code)
    return f"{code} {name}" if name else code
