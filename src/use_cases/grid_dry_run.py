"""GridDryRunOrchestrator — broker-driven DGT 그리드 실행 (ADR 0022 §12 D23).

Backtest GridRunner 와 *기능적 동등성* 을 갖되, 거래 결과를 **broker** (실거래
는 KISBroker, dry-run/paper 는 MockBroker grid 경로 D19) 를 통과시키고 결정을
**uow.grid_decisions** (D22.2) 에 영속한다. G2 §7.4 backtest↔dry-run 동치성
의 dry-run 측 토대.

설계 메모:
- GridRunner.run 의 per-bar 루프 로직 (cooldown / price_based_reentry / profit_guard
  / weighted avg_cost / state.next_state) 을 **의도적으로 중복** 한다. 단일
  결정 함수는 ``GridStrategy.evaluate`` (도메인, 양쪽 공통). 이 중복은 두 독립
  구현이 같은 시나리오에서 동일 trade sequence 를 emit 함을 G2 동등성 테스트
  로 *측정 가능하게* 박제하기 위함 (silent drift 위험을 테스트로 노출).
- Broker idempotency: 같은 ``idempotency_key`` 로 재호출 시 broker 가 prior
  result 반환 (`MockBroker.place_order:120-122`). cron 재실행 시 안전.
- D20 (partial fill 차단): 본 orchestrator 도 broker 가 full-fill 반환을
  전제 (FILLED 외 status 면 즉시 halt — Phase 0/dry-run 가정, ADR 0022 §12 D20).
- 한계: in-memory 상태 (cash via broker.get_balance, holdings via broker.
  get_grid_holding, grid_state / cooldown / last_sell_price 는 본 orchestrator
  메모리). 크론 간 grid_state 영속화는 후속 증분.

Clean Architecture (CLAUDE.md §1.1): domain + ports + use_case 만 inward.
adapter / infrastructure 미import (broker 는 BrokerPort 로 받음).
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from src.domain.cost_model import KoreanMarketCostModel
from src.domain.models import Money, OrderRequest, OrderSide, OrderStatus, OrderType
from src.domain.order_keys import build_grid_order_key
from src.domain.strategies.grid import (
    GridDecision,
    GridRuntimeState,
    GridState,
    GridStrategy,
)
from src.domain.strategies.grid_math import adaptive_k, grid_levels

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from src.adapters.mock.broker import _GridHolding
    from src.domain.models import OHLCV, Asset
    from src.domain.strategies.grid import GridConfig
    from src.ports.broker import BrokerPort
    from src.ports.unit_of_work import UnitOfWorkPort


class GridDryRunOrchestrator:
    """Broker-driven 그리드 실행 엔진 (D23 진성 동등성).

    GridRunner 의 backtest 결과와 동등한 trade sequence 를 produce 하되,
    상태 변경은 broker.place_order 를 통과시키고 결정은 uow.grid_decisions 에
    저장.
    """

    def __init__(
        self,
        *,
        broker: BrokerPort,
        uow_factory: Callable[[], UnitOfWorkPort],
        timestamp_for_bar: Callable[[OHLCV], datetime],
        cost_model: KoreanMarketCostModel | None = None,
    ) -> None:
        self._broker = broker
        self._uow_factory = uow_factory
        self._timestamp_for_bar = timestamp_for_bar
        self._cost_model = cost_model or KoreanMarketCostModel()
        self._strategy = GridStrategy()

    def replay_bars(
        self,
        *,
        asset: Asset,
        bars: list[OHLCV],
        config: GridConfig,
        initial_capital: Money,
    ) -> list[GridDecision]:
        """Run the grid strategy bar-by-bar through the broker, return the
        ordered list of GridDecisions actually executed (FILLED).

        Mirrors ``GridRunner.run`` per-bar logic byte-for-byte except that
        fills go through ``broker.place_order`` and decisions persist via
        ``uow.grid_decisions.save``. ``cash`` / ``holdings`` 는 broker 상태에서
        읽어 GridStrategy.evaluate 의 인자로 전달.

        Runtime state (cooldown / last_sell_price / avg_cost / grid_state) 는
        본 메서드 내부 변수로 유지 — 크론 모드는 :meth:`step_today` 가 영속.
        """
        if not bars:
            raise ValueError("bars must be non-empty")
        if initial_capital.currency != asset.currency:
            raise ValueError(
                f"initial_capital.currency ({initial_capital.currency.value}) "
                f"!= asset.currency ({asset.currency.value})"
            )

        runtime = self._bootstrap_runtime(asset, bars, config)
        executed: list[GridDecision] = []

        for bar_idx in range(len(bars)):
            decs, runtime = self._process_one_bar(
                asset=asset,
                bars=bars,
                bar_idx=bar_idx,
                config=config,
                runtime=runtime,
            )
            executed.extend(decs)

        return executed

    def step_today(
        self,
        *,
        asset: Asset,
        bars: list[OHLCV],
        config: GridConfig,
        initial_capital: Money,
    ) -> list[GridDecision]:
        """Process the *latest* bar (``bars[-1]``) with cross-cron state
        persistence via ``uow.grid_states``.

        First call (no saved state): bootstrap from ``bars[0].close`` using
        :meth:`_bootstrap_runtime` (cold-start). Subsequent calls: load saved
        state from prior cron, apply ``_process_one_bar``, save updated state.

        ADR 0022 §12 follow-up — true single-step cron-mode operation. Bars
        list is the full price history including today (loaded by composition
        root from CSV / pykrx). bar_idx = len(bars)-1.
        """
        if not bars:
            raise ValueError("bars must be non-empty")
        if initial_capital.currency != asset.currency:
            raise ValueError(
                f"initial_capital.currency ({initial_capital.currency.value}) "
                f"!= asset.currency ({asset.currency.value})"
            )

        # 1. Load or bootstrap runtime state.
        with self._uow_factory() as uow:
            saved = uow.grid_states.get(asset.fqn)
        runtime = saved if saved is not None else self._bootstrap_runtime(
            asset, bars, config
        )

        # 2. Process today's bar (bars[-1]).
        bar_idx = len(bars) - 1
        executed, new_runtime = self._process_one_bar(
            asset=asset,
            bars=bars,
            bar_idx=bar_idx,
            config=config,
            runtime=runtime,
        )

        # 3. Persist new runtime state.
        ts = self._timestamp_for_bar(bars[bar_idx])
        with self._uow_factory() as uow:
            uow.grid_states.save(
                asset_fqn=asset.fqn,
                state=new_runtime,
                updated_at=ts,
            )
            uow.commit()
        return executed

    def _bootstrap_runtime(
        self,
        asset: Asset,
        bars: list[OHLCV],
        config: GridConfig,
    ) -> GridRuntimeState:
        """Cold-start runtime state from ``bars[0].close`` (initial grid).

        ``cooldown_remaining=0``, ``last_sell_price=0``, ``avg_cost=0`` — no
        prior history. ``grid_state`` = (reference=bars[0].close, levels from
        adaptive_k).
        """
        n = config.grid_count
        reference = bars[0].close
        k0 = adaptive_k(
            bars,
            0,
            reference,
            period=config.atr_period,
            multiplier=config.multiplier,
            k_min=config.k_min,
            k_max=config.k_max,
            fallback_k=config.fallback_k,
            measure=config.volatility_measure,
        )
        return GridRuntimeState(
            grid_state=GridState(
                reference_price=reference,
                grid_levels=tuple(
                    grid_levels(n, reference, k0, config.levels_above)
                ),
            ),
            cooldown_remaining=0,
            last_sell_price=Decimal("0"),
            avg_cost=Decimal("0"),
        )

    def _process_one_bar(
        self,
        *,
        asset: Asset,
        bars: list[OHLCV],
        bar_idx: int,
        config: GridConfig,
        runtime: GridRuntimeState,
    ) -> tuple[list[GridDecision], GridRuntimeState]:
        """Process a single bar — pure-ish (broker / uow writes are side-effects).

        Returns (executed_decisions, new_runtime_state). State transition is
        functional via the ``runtime`` argument — no instance variables. Both
        :meth:`replay_bars` (batch) and :meth:`step_today` (cron) compose
        from this primitive, guaranteeing identical semantics.
        """
        bar = bars[bar_idx]
        state = runtime.grid_state
        cooldown_remaining = runtime.cooldown_remaining
        last_sell_price = runtime.last_sell_price
        avg_cost = runtime.avg_cost

        cooling = cooldown_remaining > 0
        price_blocks_buys = (
            config.price_based_reentry
            and last_sell_price > 0
            and bar.close > last_sell_price
        )
        sold_this_bar = False
        # broker 상태에서 cash + holdings 읽기 (slot 우회 — D19).
        cash_now = self._broker.get_balance().cash.amount
        holding = self._broker.get_grid_holding(asset.fqn)
        holdings = holding.quantity if holding is not None else Decimal("0")

        ev = self._strategy.evaluate(
            asset=asset,
            bars=bars,
            bar_idx=bar_idx,
            state=state,
            available_cash=Money(amount=cash_now, currency=asset.currency),
            holdings=holdings,
            config=config,
        )

        executed: list[GridDecision] = []
        for dec in ev.decisions:
            if dec.side is OrderSide.BUY:
                if cooling:
                    continue
                if price_blocks_buys:
                    continue
                bc = self._cost_model.compute_buy_cost(
                    price=dec.level_price,
                    quantity=dec.quantity,
                    asset=asset,
                )
                if bc.total_cost > cash_now:
                    continue
                avg_cost = (
                    (avg_cost * holdings + bc.rounded_price * dec.quantity)
                    / (holdings + dec.quantity)
                )
                self._submit_and_settle(
                    asset=asset,
                    bar=bar,
                    side=OrderSide.BUY,
                    decision=dec,
                    rounded_price=bc.rounded_price,
                )
                executed.append(dec)
                cash_now -= bc.total_cost
                holdings += dec.quantity
            else:
                sc = self._cost_model.compute_sell_cost(
                    price=dec.level_price,
                    quantity=dec.quantity,
                    asset=asset,
                )
                if (
                    config.profit_guard
                    and avg_cost > 0
                    and sc.rounded_price <= avg_cost
                ):
                    continue
                self._submit_and_settle(
                    asset=asset,
                    bar=bar,
                    side=OrderSide.SELL,
                    decision=dec,
                    rounded_price=sc.rounded_price,
                )
                executed.append(dec)
                sold_this_bar = True
                last_sell_price = sc.rounded_price
                cash_now += sc.net_proceeds
                holdings -= dec.quantity

        # 쿨다운 갱신 (ADR 0022 §11.13)
        if config.sell_cooldown_bars > 0:
            if sold_this_bar:
                cooldown_remaining = config.sell_cooldown_bars
            elif cooldown_remaining > 0:
                cooldown_remaining -= 1

        new_runtime = GridRuntimeState(
            grid_state=ev.next_state,
            cooldown_remaining=cooldown_remaining,
            last_sell_price=last_sell_price,
            avg_cost=avg_cost,
        )
        return executed, new_runtime

    def _submit_and_settle(
        self,
        *,
        asset: Asset,
        bar: OHLCV,
        side: OrderSide,
        decision: GridDecision,
        rounded_price: Decimal,
    ) -> None:
        """Submit OrderRequest via broker, save GridDecision via uow.

        Phase 0/dry-run 가정: broker 가 FILLED 즉시 반환 (full fill, ADR 0022
        §12 D20). 다른 status (PENDING / PARTIAL_FILLED / REJECTED) 면 halt —
        본 orchestrator 는 결정론적 broker 만 가정한다 (실거래 KIS partial
        fill 처리는 PendingSettler 가 다음 cron 에서).
        """
        ts = self._timestamp_for_bar(bar)
        request = OrderRequest(
            idempotency_key=build_grid_order_key(
                asset_fqn=asset.fqn,
                date_iso=bar.trade_date.isoformat(),
                side=side,
                level_idx=decision.level_index,
            ),
            asset=asset,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=decision.quantity,
            target_price=rounded_price,
            grid_level_idx=decision.level_index,
        )
        result = self._broker.place_order(request)
        if result.status is not OrderStatus.FILLED:
            raise RuntimeError(
                f"GridDryRunOrchestrator expected FILLED, got {result.status.value} "
                f"for {request.idempotency_key} (Phase 0/dry-run = full-fill only, "
                "ADR 0022 §12 D20)"
            )
        with self._uow_factory() as uow:
            uow.grid_decisions.save(
                asset=asset,
                timestamp=ts,
                decision=decision,
            )
            uow.commit()


def reconstruct_grid_broker_state(
    *,
    asset: Asset,
    initial_capital: Money,
    decisions: list[GridDecision],
    last_buy_at: datetime | None = None,
) -> tuple[Money, _GridHolding | None]:
    """Replay grid_decisions → (cash, grid_holding) for cron-mode state restore.

    Phase 0 dry-run/paper composition: MockBroker 가 in-memory 라 process 간
    cash + holding 자체는 영속 안 됨. 대신 grid_decisions (audit log, D22.2) +
    initial_capital 으로 *결정론적 재생산* — 매수/매도 시퀀스를 재생해 broker
    상태를 복원.

    Args:
        asset: 대상 자산 (assertion 용).
        initial_capital: 첫 cron 시작 시점의 현금 (Money).
        decisions: 시간순 정렬된 GridDecision 시퀀스 (uow.grid_decisions.
            list_by_date_range 결과).
        last_buy_at: 최근 매수 timestamp (선택; 마지막 BUY 의 timestamp 가 있다면
            전달. None 이면 _GridHolding 의 last_buy_at 도 None).

    Returns:
        (현재 cash, 현재 grid_holding 또는 None if qty==0).

    가정:
        - Broker 는 gross 만 추적 (commission/tax 제외) — ADR 0022 §12 D23
          아이덜라이제이션 정합.
        - 매도 시 평균가 (avg_price) 유지 (FIFO 아님, average cost).
        - 시퀀스가 인과적으로 일관 (sell qty <= 보유 qty).
    """
    # 지연 import — adapters 의존 (composition 경계 정합). use_case 가 adapter
    # 의 private 클래스를 알아야 하는 이유: MockBroker 가 dry-run 의 정본
    # broker 라 별도 GridHolding 도메인 모델 없이 직접 사용.
    from src.adapters.mock.broker import _GridHolding as _GH  # noqa: PLC0415

    cash = initial_capital.amount
    quantity = Decimal("0")
    avg_price = Decimal("0")
    cost_basis = Decimal("0")

    for dec in decisions:
        if dec.side is OrderSide.BUY:
            gross = dec.rounded_price * dec.quantity
            cash -= gross
            new_qty = quantity + dec.quantity
            new_cost = cost_basis + gross
            avg_price = new_cost / new_qty
            cost_basis = new_cost
            quantity = new_qty
        else:  # SELL
            if dec.quantity > quantity:
                raise ValueError(
                    f"grid_decisions 시퀀스 inconsistency — SELL {dec.quantity} "
                    f"exceeds holding {quantity} for {asset.fqn}"
                )
            gross = dec.rounded_price * dec.quantity
            cash += gross
            new_qty = quantity - dec.quantity
            if new_qty == 0:
                quantity = Decimal("0")
                avg_price = Decimal("0")
                cost_basis = Decimal("0")
            else:
                # average cost: avg_price 유지, cost_basis 비례 감소.
                cost_basis = new_qty * avg_price
                quantity = new_qty

    new_cash = Money(amount=cash, currency=initial_capital.currency)
    if quantity == 0:
        return new_cash, None
    return new_cash, _GH(
        asset=asset,
        quantity=quantity,
        avg_price=avg_price,
        cost_basis=cost_basis,
        last_buy_at=last_buy_at,
    )
