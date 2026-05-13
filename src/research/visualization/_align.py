"""Phase 0.11.c.4 — `_align_results_for_overlay` adapter (ADR 0009 §1.3 D6).

`BacktestResult` (production, B&H/7split snapshots) ↔ `_DGTBacktestResult`
(research, DGT daily_snapshots) 의 공통 축 (time + pnl_cumulative +
drawdown) 매핑.

D6 공통 축 정의:
    time            : snapshot date → UTC midnight datetime
    pnl_cumulative  : total_value(t) - initial_capital
    drawdown        : pnl(t) - running_peak (≤ 0)

5th ring (research overlay) → inner ring read OK (`src.application.
backtest_runner.BacktestResult`, `src.domain.models.PortfolioSnapshot`).
Production rings 변경 zero (CLAUDE.md §1.1).

Lifecycle (ADR 0009 §1.7): permanent. Underscore-prefix private
(ADR 0007 §1.6.3, `__all__ = []`).
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.research.visualization._visualization_renderer import _OverlayPayload

if TYPE_CHECKING:
    from src.application.backtest_runner import BacktestResult
    from src.research.dgt.results import _DGTBacktestResult


__all__: list[str] = []


def _align_backtest_result_for_overlay(
    result: BacktestResult,
    *,
    strategy_id: str,
) -> _OverlayPayload:
    """`BacktestResult.snapshots` → `_OverlayPayload` (D6 공통 축).

    Args:
        result: production `BacktestResult` (B&H / 7split / 임의 전략).
        strategy_id: overlay legend label (예: "buy_and_hold", "price_drop").

    Returns:
        `_OverlayPayload` — time / pnl_cumulative / drawdown / strategy_id.
        snapshots 가 비어 있으면 빈 payload.
    """
    initial = result.initial_capital.amount
    time_series: list[datetime] = []
    pnl_series: list[Decimal] = []
    drawdown_series: list[Decimal] = []

    peak = Decimal("0")
    first = True
    for snap in result.snapshots:
        ts = datetime(
            snap.snapshot_date.year,
            snap.snapshot_date.month,
            snap.snapshot_date.day,
            tzinfo=UTC,
        )
        pnl = snap.total_value.amount - initial
        if first or pnl > peak:
            peak = pnl
            first = False
        drawdown = pnl - peak

        time_series.append(ts)
        pnl_series.append(pnl)
        drawdown_series.append(drawdown)

    return _OverlayPayload(
        time_series=time_series,
        pnl_cumulative=pnl_series,
        drawdown=drawdown_series,
        strategy_id=strategy_id,
    )


def _align_dgt_result_for_overlay(
    result: _DGTBacktestResult,
    *,
    strategy_id: str = "dgt",
) -> _OverlayPayload:
    """`_DGTBacktestResult.daily_snapshots` → `_OverlayPayload`.

    DGT runner 의 `_DGTSnapshot.total_value` (= cash + holdings·close)
    그대로 사용 — cost_model 적용 후 값이므로 production snapshot 과
    동일 회계 의미.

    Args:
        result: research `_DGTBacktestResult` (DGT prototype runner 산출).
        strategy_id: 보통 "dgt" — 다른 grid variants 비교 시 변경.

    Returns:
        `_OverlayPayload` — DGT 공통 축. daily_snapshots 가 비어 있으면
        빈 payload (informational runner 가 short input 거부 시 발생).
    """
    initial = result.initial_capital.amount
    time_series: list[datetime] = []
    pnl_series: list[Decimal] = []
    drawdown_series: list[Decimal] = []

    peak = Decimal("0")
    first = True
    for snap in result.daily_snapshots:
        ts = datetime(
            snap.trade_date.year,
            snap.trade_date.month,
            snap.trade_date.day,
            tzinfo=UTC,
        )
        pnl = snap.total_value - initial
        if first or pnl > peak:
            peak = pnl
            first = False
        drawdown = pnl - peak

        time_series.append(ts)
        pnl_series.append(pnl)
        drawdown_series.append(drawdown)

    return _OverlayPayload(
        time_series=time_series,
        pnl_cumulative=pnl_series,
        drawdown=drawdown_series,
        strategy_id=strategy_id,
    )


def _align_results_for_overlay(
    result: object,
    *,
    strategy_id: str,
) -> _OverlayPayload:
    """Dispatch wrapper — `BacktestResult` 또는 `_DGTBacktestResult` 정합.

    `isinstance` 분기 — 두 dataclass 모두 frozen + 명시적 schema 보유.
    `hasattr` 기반 duck typing 거부 — 명시적 type 확인이 schema 변경 시
    early-fail 보장.

    Args:
        result: `BacktestResult` 또는 `_DGTBacktestResult` instance.
        strategy_id: overlay legend label.

    Returns:
        `_OverlayPayload` — 공통 축 매핑.

    Raises:
        TypeError: result 가 지원 타입 아님.
    """
    # Lazy import — 5th ring 에서 inner ring read OK 이지만 import 실패
    # 시 ImportError 가 ring 위반으로 잘못 진단될 수 있어 함수 내부 박제.
    from src.application.backtest_runner import BacktestResult
    from src.research.dgt.results import _DGTBacktestResult

    if isinstance(result, BacktestResult):
        return _align_backtest_result_for_overlay(
            result, strategy_id=strategy_id,
        )
    if isinstance(result, _DGTBacktestResult):
        return _align_dgt_result_for_overlay(
            result, strategy_id=strategy_id,
        )
    raise TypeError(
        f"Unsupported result type: {type(result).__name__}. "
        f"Expected BacktestResult or _DGTBacktestResult."
    )
