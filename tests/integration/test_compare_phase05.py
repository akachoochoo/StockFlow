"""Tests for scripts/compare_phase05.py (ADR 0002 §8 D-vs-F).

Smoke-level: synthetic ``trading backtest --json`` payloads are written
to tmp files and the script's ``main()`` is invoked with the same argv
shape the ADR §8.4 documented usage uses. Output is captured via
``capsys`` and asserted on metric labels + numeric correctness.

Heavy-weight 5-year KOSPI 200 D-vs-F runs live in steps 0.5.24 / 0.5.25;
those produce real JSON inputs for this script.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Add the project root to sys.path so ``import scripts.compare_phase05``
# resolves cleanly when pytest is run from the repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.compare_phase05 import (  # noqa: E402
    Summary,
    main,
    render,
    summarize,
)


def _money(amount: str) -> dict:
    return {"amount": amount, "currency": "KRW"}


def _make_payload(
    *,
    n_days: int = 5,
    total_return: str = "5.0",
    cagr: str = "12.0",
    mdd: str = "-7.5",
    sharpe: str = "0.45",
    calmar: str = "1.6",
    initial: str = "100000000",
    buys: list[tuple[int, str, str]] | None = None,
    sells: list[tuple[int, int, str, str, str]] | None = None,
    committed: list[str] | None = None,
) -> dict:
    """Build a minimal ``trading backtest --json``-shaped payload.

    ``buys`` items: (day_index, qty, price)
    ``sells`` items: (day_index, slot_number, qty, price, profit_pct)
    ``committed`` items: total_market_value per day (length == n_days)
    """
    buys = buys or []
    sells = sells or []
    committed = committed or [str(0)] * n_days

    decisions: list[dict] = []
    # Group sells by day_index so each day has at most one Decision row.
    by_day: dict[int, dict] = {}
    for day_index, qty, price in buys:
        d = by_day.setdefault(day_index, {"sell_actions": []})
        d["buy_action"] = {
            "slot_number": 1,
            "split_level_after": 1,
            "filled_quantity": qty,
            "filled_price": price,
            "target_price": price,
            "idempotency_key": f"buy-day-{day_index}",
            "order_id": f"mock-{day_index}",
            "reasoning": {},
        }
    for day_index, slot_n, qty, price, profit in sells:
        d = by_day.setdefault(day_index, {"sell_actions": []})
        d["sell_actions"].append({
            "slot_number": slot_n,
            "filled_quantity": qty,
            "filled_price": price,
            "profit_pct": profit,
            "idempotency_key": f"sell-day-{day_index}-slot-{slot_n}",
            "order_id": f"mock-sell-{day_index}-{slot_n}",
            "reasoning": {},
        })
    for day_index in sorted(by_day):
        body = by_day[day_index]
        decisions.append({
            "timestamp": f"2024-01-{day_index + 1:02d}T00:00:00+00:00",
            "asset": {
                "code": "069500",
                "exchange": "KRX",
                "asset_class": "KR_ETF",
                "currency": "KRW",
                "name": "KODEX 200",
                "tick_size": "5",
                "lot_size": "1",
            },
            "sell_actions": body.get("sell_actions", []),
            "buy_action": body.get("buy_action"),
            "skip_reason": None,
            "reasoning": {},
        })

    snapshots = [
        {
            "snapshot_date": f"2024-01-{i + 1:02d}",
            "snapshot_at": f"2024-01-{i + 1:02d}T07:00:00+00:00",
            "initial_capital": _money(initial),
            "cash": _money(str(Decimal(initial) - Decimal(committed[i]))),
            "valuations": [],
            "total_market_value": _money(committed[i]),
            "total_value": _money(initial),
            "total_cost_basis": _money(committed[i]),
            "total_unrealized_pnl": _money("0"),
        }
        for i in range(n_days)
    ]

    return {
        "start_date": "2024-01-01",
        "end_date": f"2024-01-{n_days:02d}",
        "n_trading_days": n_days,
        "initial_capital": _money(initial),
        "final_value": _money(initial),
        "total_return_pct": total_return,
        "cagr_pct": cagr,
        "max_drawdown_pct": mdd,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "decisions": decisions,
        "snapshots": snapshots,
    }


@pytest.fixture
def payload_d() -> dict:
    # 1 buy + 0 sells, 50 % capital utilization across 5 days.
    return _make_payload(
        n_days=5,
        total_return="2.5",
        buys=[(0, "100", "30000")],
        committed=[
            "50000000",
            "50000000",
            "50000000",
            "50000000",
            "50000000",
        ],
    )


@pytest.fixture
def payload_f() -> dict:
    # 2 buys + 1 sell, 30 % avg utilization.
    return _make_payload(
        n_days=5,
        total_return="4.0",
        buys=[(0, "100", "30000"), (3, "50", "31000")],
        sells=[(2, 1, "100", "33000", "10.0")],
        committed=[
            "50000000",
            "30000000",
            "10000000",
            "30000000",
            "30000000",
        ],
    )


# ---------------------------------------------------------------------------
# summarize() correctness
# ---------------------------------------------------------------------------
class TestSummarize:
    def test_basic_metrics_passthrough(self, payload_d: dict):
        summary = summarize("Policy D-2", payload_d)
        assert summary.label == "Policy D-2"
        assert summary.n_trading_days == 5
        assert summary.total_return_pct == Decimal("2.5")
        assert summary.cagr_pct == Decimal("12.0")
        assert summary.sharpe_ratio == Decimal("0.45")

    def test_capital_turnover(self, payload_d: dict):
        # 1 buy of 100 * 30000 = 3,000,000. initial 100M. (3M / 100M) * 252 / 5
        #   = 0.03 * 50.4 = 1.512
        summary = summarize("D", payload_d)
        assert summary.capital_turnover == Decimal("1.512")

    def test_sell_count_zero_when_no_sells(self, payload_d: dict):
        summary = summarize("D", payload_d)
        assert summary.sell_count == 0

    def test_sell_count_aggregates_across_days(self, payload_f: dict):
        summary = summarize("F", payload_f)
        assert summary.sell_count == 1

    def test_avg_capital_utilization(self, payload_d: dict):
        # 50M / 100M = 0.5 every day → mean 0.5
        summary = summarize("D", payload_d)
        assert summary.avg_capital_utilization == Decimal("0.5")

    def test_avg_capital_utilization_varying_days(self, payload_f: dict):
        # (50 + 30 + 10 + 30 + 30) / 5 = 30M average → 0.30
        summary = summarize("F", payload_f)
        assert summary.avg_capital_utilization == Decimal("0.30")

    def test_zero_initial_capital_does_not_divide_by_zero(self):
        payload = _make_payload(n_days=2, initial="0")
        summary = summarize("Edge", payload)
        assert summary.capital_turnover == Decimal(0)
        assert summary.avg_capital_utilization == Decimal(0)

    def test_no_snapshots_yields_zero_metrics(self):
        payload = _make_payload(n_days=0)
        summary = summarize("Empty", payload)
        assert summary.capital_turnover == Decimal(0)
        assert summary.avg_capital_utilization == Decimal(0)


# ---------------------------------------------------------------------------
# render() formatting
# ---------------------------------------------------------------------------
class TestRender:
    def test_table_contains_all_metric_labels(
        self, payload_d: dict, payload_f: dict
    ):
        d = summarize("Policy D-2", payload_d)
        f = summarize("Policy F", payload_f)
        out = render(d, f)
        for label in (
            "Trading days",
            "Total return %",
            "CAGR %",
            "Max drawdown %",
            "Sharpe ratio",
            "Calmar ratio",
            "Capital turnover",
            "Cumulative sells",
            "Avg capital util",
        ):
            assert label in out

    def test_table_includes_both_policy_columns(
        self, payload_d: dict, payload_f: dict
    ):
        d = summarize("Policy D-2", payload_d)
        f = summarize("Policy F", payload_f)
        out = render(d, f)
        assert "Policy D-2" in out
        assert "Policy F" in out
        assert "F - D" in out

    def test_delta_column_shows_diff_with_sign(self):
        # Hand-rolled summaries to assert the delta column rendering.
        d = Summary(
            label="D",
            n_trading_days=10,
            total_return_pct=Decimal("5.0"),
            cagr_pct=Decimal(0),
            max_drawdown_pct=Decimal(0),
            sharpe_ratio=Decimal(0),
            calmar_ratio=Decimal(0),
            capital_turnover=Decimal(0),
            sell_count=0,
            avg_capital_utilization=Decimal(0),
        )
        f = Summary(
            label="F",
            n_trading_days=10,
            total_return_pct=Decimal("8.5"),
            cagr_pct=Decimal(0),
            max_drawdown_pct=Decimal(0),
            sharpe_ratio=Decimal(0),
            calmar_ratio=Decimal(0),
            capital_turnover=Decimal(0),
            sell_count=3,
            avg_capital_utilization=Decimal(0),
        )
        out = render(d, f)
        # 8.5 - 5.0 = 3.5 (Decimal preserves trailing zeros).
        assert "3.5000" in out
        # 3 - 0 = 3 (int delta)
        assert "3" in out


# ---------------------------------------------------------------------------
# main() entry point (CLI shape per ADR §8.4)
# ---------------------------------------------------------------------------
def test_main_invocation_smoke(
    tmp_path: Path,
    payload_d: dict,
    payload_f: dict,
    capsys: pytest.CaptureFixture[str],
):
    d_path = tmp_path / "D.json"
    f_path = tmp_path / "F.json"
    d_path.write_text(json.dumps(payload_d), encoding="utf-8")
    f_path.write_text(json.dumps(payload_f), encoding="utf-8")

    rc = main([str(d_path), str(f_path)])
    captured = capsys.readouterr()

    assert rc == 0
    assert "Phase 0.5 Policy comparison" in captured.out
    assert "Policy D-2" in captured.out
    assert "Policy F" in captured.out
    assert "Capital turnover" in captured.out


def test_main_accepts_custom_labels(
    tmp_path: Path,
    payload_d: dict,
    payload_f: dict,
    capsys: pytest.CaptureFixture[str],
):
    d_path = tmp_path / "D.json"
    f_path = tmp_path / "F.json"
    d_path.write_text(json.dumps(payload_d), encoding="utf-8")
    f_path.write_text(json.dumps(payload_f), encoding="utf-8")

    rc = main([
        str(d_path), str(f_path),
        "--d-label", "MA-20",
        "--f-label", "Hybrid-60",
    ])
    captured = capsys.readouterr()

    assert rc == 0
    assert "MA-20" in captured.out
    assert "Hybrid-60" in captured.out
