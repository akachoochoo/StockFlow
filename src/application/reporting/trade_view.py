"""Trade view model for backtest reporting (Phase 0.10 — ADR 0006 §3).

도메인 엔티티 추가 zero — 기존 ``Decision`` + ``BuyActionRecord`` /
``SellActionRecord`` 에서 lazy 변환한 application view model. 영구화 X
(in-memory only). 리포팅 layer 가 strategy 무관 단일 인터페이스로
거래 정보를 다룰 수 있도록.

ADR 0006 §3.2 박제 (옵션 B 채택) — 사용자 spec ADR-1 의 ``Trade``
도메인 엔티티는 거부 (기존 모델과 중복 + 영구화 부담).

Phase 0.10 = single-strategy assumption (BacktestRunner 가 단일
buy_strategy_name 보유). 다중 전략 운용은 Phase 1 ADR 0007 검토.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from src.domain.models import Decision


SideT = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class TradeView:
    """리포팅 layer view model — Decision/BuyActionRecord/SellActionRecord
    에서 변환한 분석용 dto.

    domain 엔티티 아님 (영구화 X). 변환 함수
    :func:`trades_from_decisions` 가 ``BacktestResult.decisions`` 를 iterate
    하여 TradeView list 생성.

    Fields:
        timestamp: UTC datetime — Decision.timestamp 그대로
        symbol: asset.code (예: "069500")
        side: "BUY" | "SELL"
        price: filled_price (Decimal, > 0)
        quantity: filled_quantity (Decimal, > 0)
        strategy_id: yaml buy_strategy field (예: "price_drop", "support_level")
        annotations: 전략별 자유 메타데이터 (BuyActionRecord/SellActionRecord
            의 reasoning dict 복사). dict[str, Any] — 영구화 X 이므로
            JSON serializable 제약 없음 (단, 현재 reasoning 은 dict[str, str]).
    """

    timestamp: datetime
    symbol: str
    side: SideT
    price: Decimal
    quantity: Decimal
    strategy_id: str
    annotations: dict[str, Any]


def trades_from_decisions(
    decisions: list[Decision],
    strategy_id: str,
) -> list[TradeView]:
    """``BacktestResult.decisions`` → list[TradeView].

    각 Decision 에서 buy_action (있으면) + sell_actions (전체) 를 순서대로
    변환. skip_reason 만 있는 Decision 은 trade view 미생성.

    Args:
        decisions: BacktestResult.decisions list.
        strategy_id: yaml buy_strategy field (Phase 0.10 single-strategy).
            다중 전략 운용은 Phase 1+ 별도 ADR.

    Returns:
        TradeView list — Decision 순서 (= timestamp 오름차순) 보존,
        한 Decision 내에서는 sell_actions 가 buy_action 보다 먼저
        (Phase 0.5 sells-then-buys 흐름 정합 — ADR 0002 §5.4).
    """
    out: list[TradeView] = []
    for d in decisions:
        # ADR 0002 §5.4 — sells-then-buys 흐름 그대로 (sells 먼저, buy 나중)
        for sa in d.sell_actions:
            out.append(
                TradeView(
                    timestamp=d.timestamp,
                    symbol=d.asset.code,
                    side="SELL",
                    price=sa.filled_price,
                    quantity=sa.filled_quantity,
                    strategy_id=strategy_id,
                    annotations=dict(sa.reasoning),
                )
            )
        if d.buy_action is not None:
            out.append(
                TradeView(
                    timestamp=d.timestamp,
                    symbol=d.asset.code,
                    side="BUY",
                    price=d.buy_action.filled_price,
                    quantity=d.buy_action.filled_quantity,
                    strategy_id=strategy_id,
                    annotations=dict(d.buy_action.reasoning),
                )
            )
    return out
