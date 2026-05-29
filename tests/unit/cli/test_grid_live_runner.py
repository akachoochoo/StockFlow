"""Tests for ``src.cli.grid_live_runner.run_grid_live_pipeline`` (ADR 0022 §13 D30.1).

settle → reconcile → arm → decide → stop-loss → supervised hold 순서 박제.
fake 만 사용 (실 KIS 네트워크 미접속). split live_runner 패턴 정합.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.cli.grid_live_runner import (
    GridLiveAssetRun,
    GridLivePipelineResult,
    run_grid_live_pipeline,
)
from src.cli.live_gate import (
    CapitalTier,
    LiveArmingError,
    LiveArmingToken,
)
from src.domain.exceptions import StateMismatchError
from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    OrderSide,
)
from src.domain.strategies.grid import (
    GridConfig,
    GridDecision,
    GridRuntimeState,
    GridState,
)
from src.ports.notifications import NotificationLevel
from src.use_cases.reconciliation import ReconciliationMismatch, ReconciliationResult


def _asset(code: str = "095660") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_STOCK,
        currency=Currency.KRW,
        name="네오위즈",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        listed_at=date(2014, 3, 3),
    )


def _bar(close: int = 25000, day: date = date(2026, 5, 29)) -> OHLCV:
    return OHLCV(
        asset=_asset(),
        trade_date=day,
        open=Decimal(close - 50),
        high=Decimal(close + 100),
        low=Decimal(close - 100),
        close=Decimal(close),
        volume=Decimal("1000000"),
    )


def _config() -> GridConfig:
    return GridConfig(
        grid_count=6,
        fallback_k=Decimal("0.01"),
        rebalance_mode="on_breach",
        k_min=Decimal("0.005"),
        k_max=Decimal("0.02"),
        profit_guard=True,
        sell_cooldown_bars=5,
        price_based_reentry=True,
        volatility_measure="adr",
    )


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeSettler:
    def __init__(self, events=None):
        self._events = events or []
        self.settle_calls = 0

    def settle(self, today):  # noqa: ARG002
        self.settle_calls += 1
        from src.use_cases.pending_settler import SettleOutcome
        return SettleOutcome(events=list(self._events))


class _FakeReconciler:
    def __init__(self, *, matched: bool = True):
        self._matched = matched
        self.reconcile_calls = 0

    def reconcile(self):
        self.reconcile_calls += 1
        if not self._matched:
            raise StateMismatchError("fake mismatch")
        return ReconciliationResult(matched=True, mismatches=[])


class _FakeOrchestrator:
    """Returns canned decisions per step_today call. Records invocations."""

    def __init__(self, decisions_by_asset: dict[str, list[GridDecision]] | None = None):
        self._decisions = decisions_by_asset or {}
        self.calls: list[str] = []

    def step_today(self, *, asset, bars, config, initial_capital):  # noqa: ARG002
        self.calls.append(asset.fqn)
        return list(self._decisions.get(asset.fqn, []))


class _FakeNotifier:
    def __init__(self):
        self.calls: list[tuple[NotificationLevel, str, str]] = []

    def notify(self, *, level, title, body):
        self.calls.append((level, title, body))


class _FakeGridStateRepo:
    def __init__(self, states: dict[str, GridRuntimeState] | None = None):
        self._states = states or {}

    def get(self, asset_fqn):
        return self._states.get(asset_fqn)

    def save(self, *args, **kwargs):  # noqa: ARG002
        pass

    def delete(self, asset_fqn):  # noqa: ARG002
        return False


class _FakeUoW:
    def __init__(self, grid_states: dict[str, GridRuntimeState] | None = None):
        self.grid_states = _FakeGridStateRepo(grid_states)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def commit(self):
        pass


_UNSET = object()


def _build(
    *,
    matched: bool = True,
    decisions: dict[str, list[GridDecision]] | None = None,
    runtime_states: dict[str, GridRuntimeState] | None = None,
    token=_UNSET,  # _UNSET = default valid token / None = explicit no token
    halt_active: bool = False,
    ntp_synced: bool = True,
    supervised_first_order: bool = False,
    asset_runs: list[GridLiveAssetRun] | None = None,
):
    settler = _FakeSettler()
    reconciler = _FakeReconciler(matched=matched)
    orchestrator = _FakeOrchestrator(decisions)
    notifier = _FakeNotifier()
    halt_calls = []

    def fake_halt(reason):
        halt_calls.append(reason)

    if asset_runs is None:
        asset_runs = [
            GridLiveAssetRun(
                asset=_asset(),
                bars=[_bar()],
                config=_config(),
                initial_capital=Decimal("10000000"),
            )
        ]
    if token is _UNSET:
        token = LiveArmingToken(
            tier_cap=CapitalTier.TIER_500,
            env_confirmed=True,
        )

    return {
        "settler": settler,
        "reconciler": reconciler,
        "orchestrator": orchestrator,
        "notifier": notifier,
        "halt_calls": halt_calls,
        "uow_factory": lambda: _FakeUoW(runtime_states),
        "asset_runs": asset_runs,
        "token": token,
        "halt_active": halt_active,
        "ntp_synced": ntp_synced,
        "supervised_first_order": supervised_first_order,
        "fake_halt": fake_halt,
    }


def _run(**ctx) -> GridLivePipelineResult:
    return run_grid_live_pipeline(
        settler=ctx["settler"],
        reconciler=ctx["reconciler"],
        orchestrator=ctx["orchestrator"],
        uow_factory=ctx["uow_factory"],
        notifier=ctx["notifier"],
        today=date(2026, 5, 29),
        asset_runs=ctx["asset_runs"],
        intended_tier=CapitalTier.TIER_500,
        arm_token=ctx["token"],
        halt_active=ctx["halt_active"],
        ntp_synced=ctx["ntp_synced"],
        max_loss_pct=Decimal("20"),
        supervised_first_order=ctx["supervised_first_order"],
        halt_writer=ctx["fake_halt"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestPipelineOrder:
    def test_happy_path_calls_settle_reconcile_decide_in_order(self):
        ctx = _build()
        result = _run(**ctx)
        assert ctx["settler"].settle_calls == 1
        assert ctx["reconciler"].reconcile_calls == 1
        assert ctx["orchestrator"].calls == ["KRX:095660"]
        assert isinstance(result, GridLivePipelineResult)


class TestArmingGate:
    def test_unarmed_token_blocks_orders(self):
        """token None → LiveArmingError, orchestrator 호출 zero."""
        ctx = _build(token=None)
        with pytest.raises(LiveArmingError):
            _run(**ctx)
        assert ctx["orchestrator"].calls == []

    def test_halt_active_blocks_orders(self):
        ctx = _build(halt_active=True)
        with pytest.raises(LiveArmingError):
            _run(**ctx)
        assert ctx["orchestrator"].calls == []

    def test_ntp_skew_blocks_orders(self):
        from src.domain.exceptions import ClockSkewError
        ctx = _build(ntp_synced=False)
        with pytest.raises(ClockSkewError):
            _run(**ctx)
        assert ctx["orchestrator"].calls == []

    def test_mismatch_blocks_before_arm(self):
        """reconciliation mismatch → orchestrator 호출 zero."""
        ctx = _build(matched=False)
        with pytest.raises(StateMismatchError):
            _run(**ctx)
        assert ctx["orchestrator"].calls == []


class TestDecisionsAndAlerts:
    def test_executed_decisions_notify(self):
        dec = GridDecision(
            side=OrderSide.BUY, level_index=3,
            level_price=Decimal("25000"), rounded_price=Decimal("25000"),
            quantity=Decimal("40"), reasoning={},
        )
        ctx = _build(decisions={"KRX:095660": [dec]})
        result = _run(**ctx)
        # 결정 1건 → INFO 알림 1건 (start/end 없음 — runner 는 per-decision 만)
        info_calls = [c for c in ctx["notifier"].calls if c[0] is NotificationLevel.INFO]
        assert len(info_calls) >= 1
        assert "BUY" in info_calls[0][1] and "095660" in info_calls[0][1]
        assert len(result.per_asset[0].executed) == 1


class TestStopLossBreach:
    def test_breach_triggers_warning(self):
        """avg_cost 30K + 현재 25K = -16.7% > -20% → breach 아님 (한도 미초과)."""
        runtime = GridRuntimeState(
            grid_state=GridState(
                reference_price=Decimal("30000"),
                grid_levels=(Decimal("28000"), Decimal("30000"), Decimal("32000")),
            ),
            cooldown_remaining=0,
            last_sell_price=Decimal("0"),
            avg_cost=Decimal("32000"),  # 평단 32K
        )
        # 현재 close = 25000 → 손실 (25000 - 32000) / 32000 * 100 = -21.875% < -20% → breach
        ctx = _build(runtime_states={"KRX:095660": runtime})
        result = _run(**ctx)
        breach = result.per_asset[0].stop_loss_breach
        assert breach is not None
        assert breach[0] == "KRX:095660"
        assert breach[1] < Decimal("-20")
        warn_calls = [c for c in ctx["notifier"].calls if c[0] is NotificationLevel.WARNING]
        assert any("손실 한도" in c[1] for c in warn_calls)

    def test_no_breach_within_threshold(self):
        runtime = GridRuntimeState(
            grid_state=GridState(
                reference_price=Decimal("30000"),
                grid_levels=(Decimal("28000"), Decimal("30000"), Decimal("32000")),
            ),
            cooldown_remaining=0,
            last_sell_price=Decimal("0"),
            avg_cost=Decimal("26000"),  # 평단 26K
        )
        # 현재 25000 → -3.85% > -20% → 한도 안에 있음
        ctx = _build(runtime_states={"KRX:095660": runtime})
        result = _run(**ctx)
        assert result.per_asset[0].stop_loss_breach is None

    def test_no_holding_no_breach_check(self):
        """avg_cost == 0 (무보유) → breach 미평가."""
        ctx = _build(runtime_states={})  # state 없음
        result = _run(**ctx)
        assert result.per_asset[0].stop_loss_breach is None


class TestSupervisedHold:
    def test_supervised_mode_writes_halt_after_order(self):
        dec = GridDecision(
            side=OrderSide.BUY, level_index=3,
            level_price=Decimal("25000"), rounded_price=Decimal("25000"),
            quantity=Decimal("10"), reasoning={},
        )
        ctx = _build(decisions={"KRX:095660": [dec]}, supervised_first_order=True)
        result = _run(**ctx)
        assert result.supervised_hold is True
        assert len(ctx["halt_calls"]) == 1
        assert "supervised first-order (GRID LIVE)" in ctx["halt_calls"][0]

    def test_supervised_mode_no_orders_no_halt(self):
        ctx = _build(supervised_first_order=True)  # decisions 없음
        result = _run(**ctx)
        assert result.supervised_hold is False
        assert ctx["halt_calls"] == []

    def test_non_supervised_no_halt_even_with_order(self):
        dec = GridDecision(
            side=OrderSide.BUY, level_index=3,
            level_price=Decimal("25000"), rounded_price=Decimal("25000"),
            quantity=Decimal("10"), reasoning={},
        )
        ctx = _build(decisions={"KRX:095660": [dec]}, supervised_first_order=False)
        result = _run(**ctx)
        assert result.supervised_hold is False


class TestMultiAsset:
    def test_per_asset_results(self):
        a1 = _asset("095660")
        a2 = _asset("069500")
        a2_runtime = GridRuntimeState(
            grid_state=GridState(
                reference_price=Decimal("70000"),
                grid_levels=(Decimal("68000"), Decimal("70000"), Decimal("72000")),
            ),
            cooldown_remaining=0,
            last_sell_price=Decimal("0"),
            avg_cost=Decimal("0"),
        )
        runs = [
            GridLiveAssetRun(asset=a1, bars=[_bar()], config=_config(),
                             initial_capital=Decimal("5000000")),
            GridLiveAssetRun(asset=a2, bars=[_bar(close=70000)], config=_config(),
                             initial_capital=Decimal("5000000")),
        ]
        ctx = _build(asset_runs=runs, runtime_states={"KRX:069500": a2_runtime})
        result = _run(**ctx)
        assert len(result.per_asset) == 2
        assert [r.asset.fqn for r in result.per_asset] == ["KRX:095660", "KRX:069500"]
        assert ctx["orchestrator"].calls == ["KRX:095660", "KRX:069500"]
