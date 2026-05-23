"""Live-trading runner pipeline (Phase 1.1 Stage 8-5).

``run_live_pipeline`` is the safety-critical sequencing of a live cron run,
factored out of the Click command so the *ordering* and *gating* can be tested
in isolation (fakes, no network). The order is hard-coded and load-bearing
(ADR 0012 Stage 8 / roadmap "recon 우선 + 의사결정 후행"):

    1. **settle**   — confirm prior PENDING fills (PendingSettler). NO new
                      orders; records broker-confirmed fills into the DB so the
                      reconciliation below compares against settled state.
    2. **reconcile** — DB positions vs broker holdings (read-only). Raises
                      ``StateMismatchError`` on mismatch (Reconciler already
                      halts + alerts). The **in-process** matched result is
                      threaded into the arming gate — never a filesystem guess.
    3. **arm**       — :func:`assert_armed_for_live` (Stage 8-3). A strict
                      5-AND gate; raises unless fully armed. **Real orders are
                      structurally unreachable until this returns.**
    4. **decide**    — ``orchestrator.run_for_date`` places the day's orders
                      (PENDING in the KIS async model). Reached only when armed.
    5. **stop-loss** — alert (Telegram/Console) on any held position at the
                      ``-max_loss_pct`` breach (ADR 0012 D2(b')). **Alert only —
                      never auto-sells** (CLAUDE.md §11.4).

Limitation (honest): the breach in step 5 is an *alert*, not an automated
per-asset buy-block. Phase 1.1 is supervised (daily human review + small
capital); a breach prompts the operator to ``halt`` / review / ``manual-sell``.
An automated per-asset buy-block would require orchestrator integration (out of
the Option-B "orchestrator source unchanged" scope) and is a follow-up decision.

Ring 2 (cli); imports domain + use_cases + the arming gate (inward) only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from src.cli.live_gate import assert_armed_for_live
from src.domain.strategies.stop_loss import StopLossPolicy
from src.ports.notifications import NotificationLevel

if TYPE_CHECKING:
    from datetime import date

    from src.adapters.db_position_broker_view import DbPositionBrokerView
    from src.cli.live_gate import CapitalTier, LiveArmingToken
    from src.domain.models import Decision, Position
    from src.ports.notifications import NotifierPort
    from src.use_cases.daily_orchestrator import DailyOrchestrator
    from src.use_cases.pending_settler import PendingSettler, SettleOutcome
    from src.use_cases.reconciliation import Reconciler, ReconciliationResult


@dataclass
class LivePipelineResult:
    """The outcome of one live cron run (settle → reconcile → arm → decide)."""

    settle: SettleOutcome
    recon: ReconciliationResult
    decisions: list[Decision]
    stop_loss_breaches: list[tuple[str, Decimal]] = field(default_factory=list)


def run_live_pipeline(
    *,
    settler: PendingSettler,
    reconciler: Reconciler,
    orchestrator: DailyOrchestrator,
    position_source: DbPositionBrokerView,
    notifier: NotifierPort,
    today: date,
    intended_tier: CapitalTier,
    arm_token: LiveArmingToken | None,
    halt_active: bool,
    ntp_synced: bool,
    max_loss_pct: Decimal,
) -> LivePipelineResult:
    """Run the gated live pipeline. Orders flow only past the arming gate.

    Raises (and places NO orders) when reconciliation mismatches
    (``StateMismatchError``) or arming is refused (``LiveArmingError`` /
    ``ClockSkewError``). settle + reconcile have already run when arming
    refuses — both are safe (no new orders) and keep the DB synced.
    """
    # 1. SETTLE — confirm prior PENDING fills (no new orders). Surface events.
    settle = settler.settle(today)
    for event in settle.events:
        notifier.notify(level=event.level, title=event.title, body=event.body)

    # 2. RECONCILE (선행) — read-only; raises StateMismatchError on mismatch.
    recon = reconciler.reconcile()

    # 3. ARM — strict 5-AND gate (raises → no orders unless fully armed).
    assert_armed_for_live(
        intended_tier=intended_tier,
        token=arm_token,
        recon=recon,
        halt_active=halt_active,
        ntp_synced=ntp_synced,
    )

    # 4. DECIDE — places the day's orders (PENDING). Reached only when armed.
    decisions = orchestrator.run_for_date(today)
    for decision in decisions:
        notifier.notify(
            level=NotificationLevel.INFO,
            title=f"[LIVE] {decision.asset.fqn}",
            body=" / ".join(decision.action_kinds()),
        )

    # 5. STOP-LOSS breach alert (ADR 0012 D2(b') — alert only, never auto-sell).
    breaches = _alert_stop_loss_breaches(
        positions=position_source.get_positions(),
        decisions=decisions,
        max_loss_pct=max_loss_pct,
        notifier=notifier,
    )

    return LivePipelineResult(
        settle=settle,
        recon=recon,
        decisions=decisions,
        stop_loss_breaches=breaches,
    )


def _alert_stop_loss_breaches(
    *,
    positions: list[Position],
    decisions: list[Decision],
    max_loss_pct: Decimal,
    notifier: NotifierPort,
) -> list[tuple[str, Decimal]]:
    """Alert (WARNING) on each held position at the -max_loss_pct breach.

    Uses the close price the orchestrator recorded this run
    (``decision.reasoning['current_price']``) — no extra market-data fetch, and
    the exact price the decision saw. Positions whose asset had no priced
    decision this run (e.g. market-closed skip) are not evaluated. Returns the
    list of ``(asset_fqn, loss_pct)`` breaches. Never sells (CLAUDE.md §11.4).
    """
    policy = StopLossPolicy()
    price_by_fqn: dict[str, Decimal] = {}
    for decision in decisions:
        raw = decision.reasoning.get("current_price")
        if raw is not None:
            price_by_fqn[decision.asset.fqn] = Decimal(raw)

    breaches: list[tuple[str, Decimal]] = []
    for position in positions:
        price = price_by_fqn.get(position.asset.fqn)
        if price is None:
            continue
        outcome = policy.evaluate(
            position=position, current_price=price, max_loss_pct=max_loss_pct
        )
        if outcome.breached:
            breaches.append((position.asset.fqn, outcome.loss_pct))
            notifier.notify(
                level=NotificationLevel.WARNING,
                title=f"[LIVE] 손절 임계 도달 {position.asset.fqn}",
                body=(
                    f"평가손 {outcome.loss_pct:.2f}% (≤ -{max_loss_pct}%) — "
                    "사람 매도 검토 권고. 자동 매도 zero (ADR 0012 D2(b') / "
                    "CLAUDE.md §11.4). 추가 매수 중단은 사람이 `trading halt` / "
                    "검토; 매도는 `trading manual-sell` 사람 명시 명령."
                ),
            )
    return breaches


__all__ = ["LivePipelineResult", "run_live_pipeline"]
