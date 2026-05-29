"""DGT grid live runner pipeline (ADR 0022 §13 D30.1).

``run_grid_live_pipeline`` 은 DGT 그리드 live cron 의 safety-critical 흐름을
Click 명령에서 분리한 함수다 — 호출 순서와 게이트를 fake 만으로 테스트 가능.
순서는 hard-coded 이며 split live (``run_live_pipeline``) 와 동형 (ADR 0012
Stage 8 / "recon 우선 + 의사결정 후행"):

    1. **settle**   — 이전 PENDING grid fills 확인 (PendingSettler, D21).
                      새 주문 placement zero. broker-confirmed fills 를 DB 에
                      기록 → 아래 reconciliation 이 settled state 와 대조.
    2. **reconcile** — DB positions (split) + grid net 보유 (D26) vs broker
                       get_holdings (read-only). mismatch → halt + alert +
                       StateMismatchError. in-process 결과를 arm 게이트로 전달.
    3. **arm**       — :func:`assert_armed_for_live` (D32, ``--arm-grid-live``
                       + ``TRADING_ARM_GRID_LIVE`` env 이중확인). 5-AND 게이트
                       통과 못 하면 raise → 실주문 구조적 도달 불가.
    4. **decide**    — per-asset ``orchestrator.step_today`` (KISBroker write
                       + live holdings_provider). 본 단계에서만 실 KIS 주문
                       발생 (D24 KIS broker 변경 zero, D25 holdings 추상화).
    5. **stop-loss** — 보유 종목별 현재 종가 (bar.close) vs grid_states 의
                       avg_cost → ``-max_loss_pct`` breach 시 텔레그램 WARNING.
                       **alert only — 자동 매도 zero** (CLAUDE.md §11.4, D27).
    6. **supervised first-order** — 본 run 이 주문을 한 번이라도 placed 했으면
                       halt sentinel 기록 → 다음 cron 차단. 사람이 체결 확인
                       후 ``trading resume`` (ADR 0012 §2.5(b)/(i), D30 권고).

한계 (정직): stop-loss 는 알림. 자동 per-asset buy-block 은 Phase 1.x 후속
(D27 권고 = 알림-only).

Ring 2 (cli) — domain + use_cases + cli/live_gate 만 inward (split live_runner
패턴 정합). adapters / infrastructure import zero — broker / market_data /
notifier 는 composition 이 주입.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from src.cli.live_gate import assert_armed_for_live
from src.ports.notifications import NotificationLevel

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from src.cli.live_gate import CapitalTier, LiveArmingToken
    from src.domain.models import OHLCV, Asset
    from src.domain.strategies.grid import GridConfig, GridDecision
    from src.ports.notifications import NotifierPort
    from src.ports.unit_of_work import UnitOfWorkPort
    from src.use_cases.grid_dry_run import GridDryRunOrchestrator
    from src.use_cases.pending_settler import PendingSettler, SettleOutcome
    from src.use_cases.reconciliation import Reconciler, ReconciliationResult


@dataclass(frozen=True)
class GridLiveAssetRun:
    """One per-asset input to the live pipeline.

    ``initial_capital`` = 첫 cron 의 초기 자본 (asset 별). 이후 cron 은
    ``reconstruct_grid_broker_state`` 로 복원 (capital 변경 시 broker cash 도
    함께 변하므로 cron 간 일관 유지 필요).
    """

    asset: Asset
    bars: list[OHLCV]
    config: GridConfig
    initial_capital: Decimal  # KRW (Money 의 amount, currency 는 asset 이 가짐)


@dataclass(frozen=True)
class GridAssetOutcome:
    """Per-asset live 실행 결과."""

    asset: Asset
    today_bar: OHLCV
    executed: list[GridDecision]
    stop_loss_breach: tuple[str, Decimal] | None = None  # (asset_fqn, loss_pct)


@dataclass
class GridLivePipelineResult:
    """The outcome of one DGT grid live cron run."""

    settle: SettleOutcome
    recon: ReconciliationResult
    per_asset: list[GridAssetOutcome] = field(default_factory=list)
    supervised_hold: bool = False


def run_grid_live_pipeline(
    *,
    settler: PendingSettler,
    reconciler: Reconciler,
    orchestrator: GridDryRunOrchestrator,
    uow_factory: Callable[[], UnitOfWorkPort],
    notifier: NotifierPort,
    today: date,
    asset_runs: list[GridLiveAssetRun],
    intended_tier: CapitalTier,
    arm_token: LiveArmingToken | None,
    halt_active: bool,
    ntp_synced: bool,
    max_loss_pct: Decimal,
    supervised_first_order: bool = False,
    halt_writer: Callable[[str], None] | None = None,
) -> GridLivePipelineResult:
    """Run the gated grid live pipeline. Orders flow only past the arming gate.

    Raises (and places NO orders) on reconciliation mismatch
    (``StateMismatchError``) or arming refusal (``LiveArmingError`` /
    ``ClockSkewError``). settle + reconcile have already run at that point —
    both are safe (no new orders) and keep the DB synced.
    """
    from src.domain.models import Money  # noqa: PLC0415 — 지역 import 만

    # 0. CRON 시작 알림 (D33) — 종목 / 자본 / armed 여부 요약.
    n_assets = len(asset_runs)
    total_capital = sum((r.initial_capital for r in asset_runs), Decimal("0"))
    armed = arm_token is not None and arm_token.env_confirmed
    notifier.notify(
        level=NotificationLevel.INFO,
        title=f"[GRID LIVE] cron 시작 — {today.isoformat()}",
        body=(
            f"종목 {n_assets} / 자본 {total_capital} KRW / "
            f"intended_tier={intended_tier.name} / "
            f"armed={'YES' if armed else 'NO (settle+reconcile only)'}"
        ),
    )

    # 1. SETTLE — confirm prior PENDING grid fills (no new orders).
    settle = settler.settle(today)
    for event in settle.events:
        notifier.notify(level=event.level, title=event.title, body=event.body)
    # D33 — settle 요약 알림 (grid 건수 + split 건수 + still_pending).
    notifier.notify(
        level=NotificationLevel.INFO,
        title=f"[GRID LIVE] settle — {today.isoformat()}",
        body=(
            f"grid {len(settle.settled_grid)} 건 / "
            f"split buys {len(settle.settled_buys)} / "
            f"split sells {len(settle.settled_sells)} / "
            f"still_pending {len(settle.still_pending_keys)}"
        ),
    )

    # 2. RECONCILE (선행) — read-only; raises on mismatch (split + grid 합산).
    recon = reconciler.reconcile()

    # 3. ARM — strict 5-AND gate (raises → no orders unless fully armed).
    assert_armed_for_live(
        intended_tier=intended_tier,
        token=arm_token,
        recon=recon,
        halt_active=halt_active,
        ntp_synced=ntp_synced,
    )

    # 4. DECIDE — per-asset step_today (실 KIS 주문 placement, D24+D25).
    per_asset: list[GridAssetOutcome] = []
    any_orders_placed = False
    for run in asset_runs:
        capital_money = Money(amount=run.initial_capital, currency=run.asset.currency)
        executed = orchestrator.step_today(
            asset=run.asset,
            bars=run.bars,
            config=run.config,
            initial_capital=capital_money,
        )
        today_bar = run.bars[-1]
        if executed:
            any_orders_placed = True
        for d in executed:
            notifier.notify(
                level=NotificationLevel.INFO,
                title=f"[GRID LIVE] {d.side.value} — {run.asset.fqn} level={d.level_index}",
                body=(
                    f"{d.quantity}주 @{d.rounded_price} "
                    f"({today_bar.trade_date.isoformat()})"
                ),
            )
        # 5. STOP-LOSS breach — per-asset, alert only (D27).
        breach = _check_stop_loss_breach(
            asset=run.asset,
            today_bar=today_bar,
            uow_factory=uow_factory,
            max_loss_pct=max_loss_pct,
            notifier=notifier,
        )
        per_asset.append(
            GridAssetOutcome(
                asset=run.asset,
                today_bar=today_bar,
                executed=executed,
                stop_loss_breach=breach,
            )
        )

    # 6. SUPERVISED first-order hold (D30 권고 ON).
    supervised_hold = _maybe_supervised_hold(
        supervised_first_order=supervised_first_order,
        any_orders_placed=any_orders_placed,
        halt_writer=halt_writer,
        notifier=notifier,
    )

    # 7. CRON 종료 알림 (D33) — 일일 요약. 결정 / breach / supervised hold.
    n_decisions = sum(len(o.executed) for o in per_asset)
    n_breaches = sum(1 for o in per_asset if o.stop_loss_breach is not None)
    notifier.notify(
        level=NotificationLevel.INFO,
        title=f"[GRID LIVE] cron 종료 — {today.isoformat()}",
        body=(
            f"결정 {n_decisions} 건 ({n_assets} 종목) / "
            f"손실 한도 도달 {n_breaches} / "
            f"supervised hold {'YES' if supervised_hold else 'NO'}"
        ),
    )

    return GridLivePipelineResult(
        settle=settle,
        recon=recon,
        per_asset=per_asset,
        supervised_hold=supervised_hold,
    )


def _check_stop_loss_breach(
    *,
    asset: Asset,
    today_bar: OHLCV,
    uow_factory: Callable[[], UnitOfWorkPort],
    max_loss_pct: Decimal,
    notifier: NotifierPort,
) -> tuple[str, Decimal] | None:
    """Per-asset stop-loss alert (ADR 0022 §13 D27 — 알림-only).

    grid_states 의 ``avg_cost`` 와 ``today_bar.close`` 로 평가손 산출 →
    ``-max_loss_pct`` (e.g., -20%) 이하 시 텔레그램 WARNING. **자동 매수 차단
    미구현** — CLAUDE.md §11.4 + D7 정합 (alert only, 사람 개입 대기).

    무보유 (avg_cost == 0) 또는 grid_states 미저장 시 None 반환 (breach 평가
    자체 미실시).
    """
    with uow_factory() as uow:
        runtime = uow.grid_states.get(asset.fqn)
    if runtime is None or runtime.avg_cost <= 0:
        return None
    avg = runtime.avg_cost
    loss_pct = (today_bar.close - avg) / avg * Decimal("100")
    threshold = -abs(max_loss_pct)
    if loss_pct > threshold:
        return None
    breach = (asset.fqn, loss_pct)
    notifier.notify(
        level=NotificationLevel.WARNING,
        title=f"[GRID LIVE] 손실 한도 도달 — {asset.fqn}",
        body=(
            f"평단 {avg} / 현재 {today_bar.close} / "
            f"평가손 {loss_pct:.2f}% (한도 {threshold:.2f}%). "
            "사람 검토 필요 — 자동 매수 차단 미구현 (알림-only, D27/§11.4)."
        ),
    )
    return breach


def _maybe_supervised_hold(
    *,
    supervised_first_order: bool,
    any_orders_placed: bool,
    halt_writer: Callable[[str], None] | None,
    notifier: NotifierPort,
) -> bool:
    """Write the halt sentinel iff supervised mode placed any order this run.

    Mirrors split live ``_maybe_supervised_hold`` 패턴 — 본 run 에서 주문
    placed 시 다음 cron 차단. 사람이 체결 확인 후 ``trading resume`` (UX
    재사용).
    """
    if not supervised_first_order or not any_orders_placed:
        return False
    if halt_writer is not None:
        halt_writer(
            "supervised first-order (GRID LIVE) — 첫 주문 placed. "
            "체결을 사람이 확인한 뒤 `trading resume` 로 재개 "
            "(ADR 0022 §13 D30/D32)."
        )
    notifier.notify(
        level=NotificationLevel.WARNING,
        title="[GRID LIVE] supervised first-order hold",
        body=(
            "첫 주문 placed → halt sentinel 기록. 다음 grid-live cron 차단. "
            "체결/포지션을 확인한 뒤 `trading resume`."
        ),
    )
    return True


__all__ = [
    "GridAssetOutcome",
    "GridLiveAssetRun",
    "GridLivePipelineResult",
    "run_grid_live_pipeline",
]
