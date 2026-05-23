"""Wiring tests for composition.build_live_components (Phase 1.1 Stage 8-4).

Builds the live component graph with a **fake HttpClient** + fixed clock +
tmp SQLite DB — **zero real network, 실주문 zero**. Asserts the graph is wired
write-enabled (KIS broker has an order_store; the orchestrator's self._broker is
a write-delegating DbPositionBrokerView) and that *building* the graph issues no
KIS call at all (construction is lazy — orders flow only from the runner, 8-5).

Function names carry ``live_runner`` / ``live_components`` for the Stage gate.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from src.adapters.db_position_broker_view import DbPositionBrokerView
from src.cli import composition
from src.domain.strategies.price_drop import SplitStrategyConfig

if TYPE_CHECKING:
    from collections.abc import Mapping


_FAKE_APPKEY = "PKfakeappkey0123456789"
_FAKE_APPSECRET = "FAKE_APPSECRET_must_never_be_printed=="


def _paper_environ() -> dict[str, str]:
    return {
        "KIS_TRADING_MODE": "paper",
        "KIS_PAPER_APPKEY": _FAKE_APPKEY,
        "KIS_PAPER_APPSECRET": _FAKE_APPSECRET,
        "KIS_PAPER_ACCOUNT_CANO": "50012345",
        "KIS_PAPER_ACCOUNT_PRDT_CD": "01",
    }


class _FakeHttp:
    """HttpClient stand-in that records calls. build_live_components must make
    NONE (construction is lazy) — any call here is a wiring leak."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def post(self, url: str, **_kw: object) -> object:  # pragma: no cover
        self.calls.append(("POST", url))
        raise AssertionError(f"unexpected POST during build: {url}")

    def get(self, url: str, **_kw: object) -> object:  # pragma: no cover
        self.calls.append(("GET", url))
        raise AssertionError(f"unexpected GET during build: {url}")


def _fixed_clock() -> datetime:
    return datetime(2026, 5, 22, 0, 0, tzinfo=UTC)


def _strategy_config() -> SplitStrategyConfig:
    from src.domain.models import Currency, Money

    return SplitStrategyConfig(
        drop_threshold_pct=Decimal("5"),
        max_split_count=7,
        per_split_amount=Money(amount=Decimal("280000"), currency=Currency.KRW),
        max_split_per_day=1,
    )


def _build(tmp_path, environ: Mapping[str, str] | None = None):
    from src.cli.composition import asset_from_code

    fake = _FakeHttp()
    components = composition.build_live_components(
        assets=[asset_from_code("069500")],
        db_path=tmp_path / "trading.db",
        strategy_config=_strategy_config(),
        environ=environ if environ is not None else _paper_environ(),
        http=fake,
        clock=_fixed_clock,
    )
    return components, fake


def test_build_live_components_returns_wired_graph(tmp_path) -> None:
    from src.adapters.kis.config import TradingMode
    from src.use_cases.pending_settler import PendingSettler
    from src.use_cases.reconciliation import Reconciler

    components, _ = _build(tmp_path)
    try:
        assert isinstance(components.settler, PendingSettler)
        assert isinstance(components.reconciler, Reconciler)
        assert components.config.mode is TradingMode.PAPER
    finally:
        components.close()


def test_build_makes_no_kis_call_real_orders_zero(tmp_path) -> None:
    # Constructing the graph must not touch KIS (no token / balance / order).
    components, fake = _build(tmp_path)
    try:
        assert fake.calls == []
    finally:
        components.close()


def test_live_runner_requires_order_store_wired_write_enabled(tmp_path) -> None:
    # The KIS broker is write-enabled (order_store injected) — place_order will
    # not hit the read-only RuntimeError guard. (A read-only KISBroker without
    # order_store raises on write; that path is covered in kis_broker_write.)
    components, _ = _build(tmp_path)
    try:
        assert components.broker._order_store is not None
    finally:
        components.close()


def test_orchestrator_broker_is_write_delegating_db_view(tmp_path) -> None:
    components, _ = _build(tmp_path)
    try:
        view = components.orchestrator._broker
        assert isinstance(view, DbPositionBrokerView)
        # Write delegation wired to the KIS broker (resolves the 8-1.5 stubs).
        assert view._order_broker is components.broker
    finally:
        components.close()


def test_settler_uses_kis_broker_for_status(tmp_path) -> None:
    components, _ = _build(tmp_path)
    try:
        assert components.settler._broker is components.broker
    finally:
        components.close()


def test_build_rejects_empty_assets(tmp_path) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        composition.build_live_components(
            assets=[],
            db_path=tmp_path / "trading.db",
            strategy_config=_strategy_config(),
            environ=_paper_environ(),
            http=_FakeHttp(),
            clock=_fixed_clock,
        )


def test_build_missing_env_raises_configuration_error(tmp_path) -> None:
    from src.cli.composition import asset_from_code
    from src.domain.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError):
        composition.build_live_components(
            assets=[asset_from_code("069500")],
            db_path=tmp_path / "trading.db",
            strategy_config=_strategy_config(),
            environ={"KIS_TRADING_MODE": "paper"},  # required keys missing
            http=_FakeHttp(),
            clock=_fixed_clock,
        )


def test_live_per_asset_overrides_applied(tmp_path) -> None:
    from src.domain.models import Currency, Money
    from src.domain.strategies.profit_target import SellStrategyConfig
    from src.use_cases.asset_context import AssetPolicyOverride

    def _buy(drop: str, per_split: int) -> SplitStrategyConfig:
        return SplitStrategyConfig(
            drop_threshold_pct=Decimal(drop),
            max_split_count=7,
            per_split_amount=Money(amount=Decimal(per_split), currency=Currency.KRW),
            max_split_per_day=1,
        )

    a = composition.asset_from_code("069500")
    b = composition.asset_from_code("132030")
    overrides = {
        "069500": AssetPolicyOverride(
            buy_config=_buy("5", 1000000),
            sell_config=SellStrategyConfig(profit_target_pct=Decimal("15"), max_sells_per_day=7),
            reentry_parameters={"cooldown_days": 60},
        ),
        "132030": AssetPolicyOverride(
            buy_config=_buy("7", 1000000),
            sell_config=SellStrategyConfig(profit_target_pct=Decimal("20"), max_sells_per_day=7),
            reentry_parameters={"cooldown_days": 30},
        ),
    }
    components = composition.build_live_components(
        assets=[a, b],
        db_path=tmp_path / "t.db",
        strategy_config=_buy("5", 1000000),
        environ=_paper_environ(),
        http=_FakeHttp(),
        clock=_fixed_clock,
        per_asset_overrides=overrides,
    )
    try:
        ctx = {c.asset.code: c for c in components.orchestrator._asset_contexts}
        assert ctx["069500"].config.drop_threshold_pct == Decimal("5")
        assert ctx["132030"].config.drop_threshold_pct == Decimal("7")
        assert ctx["132030"].sell_config.profit_target_pct == Decimal("20")
    finally:
        components.close()


def test_default_sell_threshold_is_15_pct(tmp_path) -> None:
    # ADR 0012 D7 — live sell threshold defaults to +15% (paper uses +10%).
    components, _ = _build(tmp_path)
    try:
        ctx = components.orchestrator._asset_contexts[0]
        assert ctx.sell_config.profit_target_pct == Decimal("15.0")
    finally:
        components.close()
