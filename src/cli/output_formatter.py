"""CLI output formatting (text + JSON).

Per ADR §10.6: human-readable text is the default; ``--json`` opt-in
produces a structured payload suitable for downstream tooling. JSON
serialization uses pydantic ``model_dump_json`` for domain models and
explicit string conversion for ``Decimal`` so precision is preserved
(CLAUDE.md §2.1).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.application.backtest_runner import BacktestResult
    from src.domain.models import Decision, Money, PortfolioSnapshot


def _money_payload(m: Money) -> dict[str, str]:
    return {"amount": str(m.amount), "currency": m.currency.value}


def _model_to_dict(m: Any) -> dict[str, Any]:
    """Round-trip a pydantic model to a JSON-safe dict.

    ``model_dump`` returns Python objects (Decimal, date, etc.) which
    ``json.dumps`` cannot encode by default. ``model_dump_json`` produces
    a string with stable Decimal-as-string handling — round-tripping
    through json.loads gives us the JSON-safe dict we want.
    """
    result: dict[str, Any] = json.loads(m.model_dump_json())
    return result


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------
def format_backtest_result(result: BacktestResult, *, as_json: bool) -> str:
    if as_json:
        return _backtest_result_to_json(result)
    return _backtest_result_to_text(result)


def _backtest_result_to_json(result: BacktestResult) -> str:
    payload = {
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "n_trading_days": result.n_trading_days,
        "initial_capital": _money_payload(result.initial_capital),
        "final_value": _money_payload(result.final_value),
        "total_return_pct": str(result.total_return_pct),
        "cagr_pct": str(result.cagr_pct),
        "max_drawdown_pct": str(result.max_drawdown_pct),
        "sharpe_ratio": str(result.sharpe_ratio),
        "calmar_ratio": str(result.calmar_ratio),
        "decisions": [_model_to_dict(d) for d in result.decisions],
        "snapshots": [_model_to_dict(s) for s in result.snapshots],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _backtest_result_to_text(result: BacktestResult) -> str:
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("Backtest result")
    lines.append("=" * 64)
    lines.append(f"Range:           {result.start_date} → {result.end_date}")
    lines.append(f"Trading days:    {result.n_trading_days}")
    lines.append(
        f"Initial cap:     {result.initial_capital.amount} "
        f"{result.initial_capital.currency.value}"
    )
    lines.append(
        f"Final value:     {result.final_value.amount} "
        f"{result.final_value.currency.value}"
    )
    lines.append(f"Total return:    {result.total_return_pct:.4f}%")
    lines.append("")
    lines.append("Performance metrics (annualized; trading_days_per_year=252):")
    lines.append(f"  CAGR:          {result.cagr_pct:.4f}%")
    lines.append(f"  Max drawdown:  {result.max_drawdown_pct:.4f}%")
    lines.append(f"  Sharpe ratio:  {result.sharpe_ratio:.4f}")
    lines.append(f"  Calmar ratio:  {result.calmar_ratio:.4f}")
    lines.append("")
    counts = Counter(
        kind for d in result.decisions for kind in d.action_kinds()
    )
    if counts:
        lines.append("Decisions by action:")
        for action, count in sorted(counts.items()):
            lines.append(f"  {action:48s} {count:>3d}")
        lines.append("")
    buys = [
        d for d in result.decisions if d.buy_action is not None
    ]
    if buys:
        lines.append(f"Buy decisions ({len(buys)}):")
        for d in buys:
            assert d.buy_action is not None
            lines.append(
                f"  {d.timestamp.date()}  buy_split_{d.buy_action.slot_number:<2d}      "
                f"qty={d.buy_action.filled_quantity!s:>3} "
                f"price={d.buy_action.filled_price!s:>6}"
            )
        lines.append("")
    sells = [d for d in result.decisions if d.sell_actions]
    if sells:
        n_sell_actions = sum(len(d.sell_actions) for d in sells)
        lines.append(f"Sell decisions ({n_sell_actions} sells across {len(sells)} days):")
        for d in sells:
            for sa in d.sell_actions:
                lines.append(
                    f"  {d.timestamp.date()}  sell_slot_{sa.slot_number:<2d}      "
                    f"qty={sa.filled_quantity!s:>3} "
                    f"price={sa.filled_price!s:>6} "
                    f"profit={sa.profit_pct:.2f}%"
                )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Paper trading single-day output
# ---------------------------------------------------------------------------
def format_paper_decision(
    decision: Decision,
    snapshot: PortfolioSnapshot,
    *,
    as_json: bool,
) -> str:
    if as_json:
        payload = {
            "decision": _model_to_dict(decision),
            "snapshot": _model_to_dict(snapshot),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f"Paper trading — {decision.asset.fqn}")
    lines.append("=" * 64)
    lines.append(f"Date:            {snapshot.snapshot_date}")
    lines.append(f"Decision:        {' / '.join(decision.action_kinds())}")
    for sa in decision.sell_actions:
        lines.append(
            f"  Sell slot {sa.slot_number}: qty={sa.filled_quantity} "
            f"@ {sa.filled_price} (profit {sa.profit_pct:.2f}%, "
            f"order={sa.order_id or '-'})"
        )
    if decision.buy_action is not None:
        ba = decision.buy_action
        lines.append(
            f"  Buy slot {ba.slot_number}: qty={ba.filled_quantity} "
            f"@ {ba.filled_price} (level after={ba.split_level_after}, "
            f"order={ba.order_id or '-'})"
        )
    lines.append(
        f"Cash:            {snapshot.cash.amount} {snapshot.cash.currency.value}"
    )
    lines.append(
        f"Total value:     {snapshot.total_value.amount} "
        f"{snapshot.total_value.currency.value} "
        f"(return {snapshot.total_return_pct:.4f}%)"
    )
    if snapshot.valuations:
        lines.append("Positions:")
        for v in snapshot.valuations:
            lines.append(
                f"  {v.asset.fqn}  level={v.split_level}  "
                f"qty={v.quantity}  avg={v.avg_price}  mkt={v.market_price}  "
                f"PnL={v.unrealized_pnl.amount} ({v.unrealized_pnl_pct:.2f}%)"
            )
    return "\n".join(lines)
