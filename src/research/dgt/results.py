"""Phase 0.11.a — DGT runner 결과 view model (D5 default = 신규).

ADR 0007 §1.5 R7 (registry 충돌 회피) + Architect Round 1 (iii):
src/application/BacktestResult 재사용 안 함 — Phase 0.10.bb 박제 시그니처
회귀 invariant 보존.

Underscore-prefix private (ADR 0007 §1.6.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.domain.models import Asset, Money


@dataclass(frozen=True)
class _DGTSnapshot:
    """End-of-bar portfolio snapshot — AC9 metrics computation 의 입력.

    Per-bar (cash, holdings, close_price, total_value). Phase 0.10.bb
    PortfolioSnapshot 와 격리 (D5 default — 5th ring 독립 model).
    """

    trade_date: date
    cash: Decimal
    holdings: Decimal
    close_price: Decimal
    total_value: Decimal


@dataclass(frozen=True)
class _DGTTrade:
    """Single mock fill — DGT prototype 의 trade 기록.

    Cost breakdown 은 KoreanMarketCostModel 결과 직역.
    """

    trade_date: date
    side: str  # "BUY" or "SELL"
    grid_level_price: Decimal
    quantity: Decimal
    rounded_price: Decimal
    gross: Decimal
    tax: Decimal
    commission: Decimal
    cash_delta: Decimal  # signed: BUY 음수 (cash 감소), SELL 양수 (cash 증가)


@dataclass(frozen=True)
class _DGTBacktestResult:
    """DGT prototype runner 산출.

    Phase 0.10.bb BacktestResult 와 격리 (D5 default, ADR 0007 §1.5 R7).
    IRR 수치는 informational only (R1 mitigation — 일봉 ≠ 분봉 본질).
    """

    asset: Asset
    start: date
    end: date
    initial_capital: Money
    final_cash: Decimal
    final_holdings: Decimal
    final_close_price: Decimal
    final_balance: Money
    wallet_total: Decimal
    reference_price: Decimal
    grid_levels: list[Decimal]
    trades: list[_DGTTrade]
    daily_snapshots: list[_DGTSnapshot]
