"""Unit tests for src.adapters.kis.broker — KISBroker write surface (Stage 5).

Uses a fake ``KISClient`` (records request() calls, returns canned bodies or
raises) + a fake ``KISOrderStore`` (in-memory dict) + a fixed injected clock —
**zero real network, zero real orders**.

Coverage (function names carry ``kis_write`` for the Stage gate selector):
- place_order: 매수 → TR_ID TTTC0012U / 매도 → TTTC0011U, body ORD_DVSN="00" +
  ORD_QTY + ORD_UNPR, resp ODNO → broker_order_id + org_no → broker_org_no +
  status PENDING + filled_quantity 0.
- idempotency dedup: 동일 key 기존 주문 존재 시 재-POST zero (get_order_status
  경로) — POST 호출 0회.
- timeout no-retry: client BrokerConnectionError → place_order 전파 + POST 1회.
- order_store None → place_order / get_order_status / cancel_order RuntimeError
  (read-only 구성 주문 차단).
- get_order_status: FILLED / PARTIALLY_FILLED / PENDING / CANCELED / REJECTED,
  미상 key → None, filled_price = avg_prvs.
- cancel_order: org_no 해석 → order-rvsecncl POST → True, 미상 → False,
  org_no None → BrokerOrderError.
- all_orders_have_idempotency_key: OrderResult.idempotency_key == request key.
- secret 미로깅 + Decimal 타입.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.adapters.kis._client import KISApiError
from src.adapters.kis.broker import KISBroker
from src.adapters.kis.config import KISConfig, TradingMode
from src.domain.exceptions import BrokerConnectionError, BrokerOrderError, StateMismatchError
from src.domain.models import (
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)

# Fixed injected clock (CLAUDE.md §3.2 — adapter time injection, deterministic).
_FIXED_NOW = datetime(2026, 5, 22, 1, 0, 0, tzinfo=UTC)


def _fixed_clock() -> datetime:
    return _FIXED_NOW


def _asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


# ---------------------------------------------------------------------------
# Fakes (zero real network / order)
# ---------------------------------------------------------------------------
class _FakeKISClient:
    """KISClient stand-in: queues canned ``request()`` bodies or raises."""

    def __init__(
        self,
        bodies: list[dict[str, object]] | None = None,
        *,
        cano: str = "50012345",
        acnt_prdt_cd: str = "01",
        raise_exc: BaseException | None = None,
    ) -> None:
        self._bodies = list(bodies) if bodies is not None else []
        self._raise_exc = raise_exc
        self._config = KISConfig(
            mode=TradingMode.PAPER,
            base_url="https://openapivts.koreainvestment.com:29443",
            appkey="PKabcdefghijklmnop",
            appsecret="SECRETsecret==",
            cano=cano,
            acnt_prdt_cd=acnt_prdt_cd,
        )
        self.calls: list[dict[str, object]] = []

    @property
    def config(self) -> KISConfig:
        return self._config

    def request(
        self,
        method: str,
        path: str,
        *,
        tr_id: str,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        tr_cont: str = "",
    ) -> dict[str, object]:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "tr_id": tr_id,
                "params": params,
                "json": json,
            }
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        if not self._bodies:
            raise KISApiError("no more canned bodies")
        return self._bodies.pop(0)

    def post_calls(self) -> list[dict[str, object]]:
        return [c for c in self.calls if c["method"] == "POST"]


class _FakeOrderStore:
    """In-memory KISOrderStore: dict keyed by idempotency_key + broker_order_id."""

    def __init__(self) -> None:
        self.by_key: dict[str, OrderResult] = {}
        self.by_oid: dict[str, OrderResult] = {}

    def add(self, result: OrderResult) -> None:
        self.by_key[result.idempotency_key] = result
        if result.broker_order_id is not None:
            self.by_oid[result.broker_order_id] = result

    def find_by_idempotency_key(self, key: str) -> OrderResult | None:
        return self.by_key.get(key)

    def find_by_broker_order_id(
        self, broker_order_id: str
    ) -> OrderResult | None:
        return self.by_oid.get(broker_order_id)


# ---------------------------------------------------------------------------
# Sample wire bodies (numeric fields as strings — ADR 0020 §2.2)
# ---------------------------------------------------------------------------
def _order_body(
    odno: str = "0000117057",
    krx_fwdg_ord_orgno: str = "00950",
    ord_tmd: str = "100000",
) -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "APBK0013",
        "msg1": "주문 전송 완료 되었습니다.",
        "output": {
            "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
            "ODNO": odno,
            "ORD_TMD": ord_tmd,
        },
    }


def _ccld_item(
    *,
    odno: str = "0000117057",
    ord_qty: str = "10",
    tot_ccld_qty: str = "10",
    rmn_qty: str = "0",
    avg_prvs: str = "35000",
    cncl_yn: str = "N",
    rjct_qty: str = "0",
    pdno: str = "069500",
) -> dict[str, object]:
    return {
        "odno": odno,
        "orgn_odno": "",
        "ord_qty": ord_qty,
        "tot_ccld_qty": tot_ccld_qty,
        "rmn_qty": rmn_qty,
        "avg_prvs": avg_prvs,
        "cncl_yn": cncl_yn,
        "rjct_qty": rjct_qty,
        "pdno": pdno,
        "sll_buy_dvsn_cd": "02",
        "ord_dvsn_cd": "00",
    }


def _ccld_body(
    output1: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": output1 if output1 is not None else [],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


def _cancel_body() -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "APBK0013",
        "msg1": "정정/취소 전송 완료 되었습니다.",
        "output": {
            "KRX_FWDG_ORD_ORGNO": "00950",
            "ODNO": "0000117099",
            "ORD_TMD": "100500",
        },
    }


def _buy_request(
    key: str = "idem-buy-1", qty: str = "10", price: str = "35000"
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=key,
        asset=_asset(),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        target_price=Decimal(price),
    )


def _sell_request(
    key: str = "idem-sell-1", qty: str = "10", price: str = "36000"
) -> OrderRequest:
    return OrderRequest(
        idempotency_key=key,
        asset=_asset(),
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        target_price=Decimal(price),
        slot_number=1,
    )


def _broker(
    client: _FakeKISClient, store: _FakeOrderStore | None
) -> KISBroker:
    return KISBroker(client=client, order_store=store, clock=_fixed_clock)


# ---------------------------------------------------------------------------
# place_order — happy path (TR_ID / body / response mapping)
# ---------------------------------------------------------------------------
class TestKisWritePlaceOrder:
    def test_kis_write_buy_uses_tttc0012u_tr_id(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        broker.place_order(_buy_request())
        assert client.calls[0]["tr_id"] == "TTTC0012U"

    def test_kis_write_sell_uses_tttc0011u_tr_id(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        broker.place_order(_sell_request())
        assert client.calls[0]["tr_id"] == "TTTC0011U"

    def test_kis_write_place_order_posts_to_order_cash_path(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        broker.place_order(_buy_request())
        assert client.calls[0]["method"] == "POST"
        assert "order-cash" in client.calls[0]["path"]  # type: ignore[operator]

    def test_kis_write_place_order_body_limit_qty_price(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        broker.place_order(_buy_request(qty="10", price="35000"))
        body = client.calls[0]["json"]
        assert body["ORD_DVSN"] == "00"  # type: ignore[index]
        assert body["ORD_QTY"] == "10"  # type: ignore[index]
        assert body["ORD_UNPR"] == "35000"  # type: ignore[index]
        assert body["PDNO"] == "069500"  # type: ignore[index]
        assert body["EXCG_ID_DVSN_CD"] == "KRX"  # type: ignore[index]
        assert body["CANO"] == "50012345"  # type: ignore[index]
        assert body["ACNT_PRDT_CD"] == "01"  # type: ignore[index]

    def test_kis_write_place_order_maps_odno_to_broker_order_id(self) -> None:
        client = _FakeKISClient([_order_body(odno="0000117057")])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request())
        assert result.broker_order_id == "0000117057"

    def test_kis_write_place_order_maps_org_no(self) -> None:
        client = _FakeKISClient([_order_body(krx_fwdg_ord_orgno="00950")])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request())
        assert result.broker_org_no == "00950"

    def test_kis_write_place_order_status_pending(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request())
        assert result.status is OrderStatus.PENDING

    def test_kis_write_place_order_filled_quantity_zero(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request())
        assert result.filled_quantity == Decimal(0)
        assert result.filled_price is None
        assert result.filled_at is None

    def test_kis_write_place_order_submitted_at_uses_injected_clock(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request())
        assert result.submitted_at == _FIXED_NOW

    def test_kis_write_place_order_issues_exactly_one_post(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        broker.place_order(_buy_request())
        assert len(client.post_calls()) == 1


# ---------------------------------------------------------------------------
# Idempotency dedup — same key → re-fetch, never re-POST
# ---------------------------------------------------------------------------
class TestKisWriteIdempotencyDedup:
    def test_kis_write_idempotency_dedup_no_repost(self) -> None:
        """A second place_order with a known key must NOT re-POST order-cash."""
        store = _FakeOrderStore()
        # Prior accepted order for this key (broker_order_id set).
        prior = OrderResult(
            idempotency_key="idem-buy-1",
            asset=_asset(),
            broker_order_id="0000117057",
            broker_org_no="00950",
            status=OrderStatus.PENDING,
            filled_quantity=Decimal(0),
            filled_price=None,
            submitted_at=_FIXED_NOW,
            filled_at=None,
        )
        store.add(prior)
        # Only a ccld body queued (the dedup re-fetch path) — no order body.
        client = _FakeKISClient([_ccld_body([_ccld_item()])])
        broker = _broker(client, store)
        broker.place_order(_buy_request(key="idem-buy-1"))
        # Zero POSTs to order-cash; the only call is the GET inquire-daily-ccld.
        assert len(client.post_calls()) == 0
        assert any(
            "inquire-daily-ccld" in str(c["path"]) for c in client.calls
        )

    def test_kis_write_idempotency_dedup_returns_refetched_status(self) -> None:
        store = _FakeOrderStore()
        store.add(
            OrderResult(
                idempotency_key="idem-buy-1",
                asset=_asset(),
                broker_order_id="0000117057",
                broker_org_no="00950",
                status=OrderStatus.PENDING,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=_FIXED_NOW,
                filled_at=None,
            )
        )
        # ccld reports the order now fully filled.
        client = _FakeKISClient([_ccld_body([_ccld_item(tot_ccld_qty="10")])])
        broker = _broker(client, store)
        result = broker.place_order(_buy_request(key="idem-buy-1"))
        assert result.status is OrderStatus.FILLED

    def test_kis_write_unknown_key_does_post(self) -> None:
        """A fresh key (no prior order) → a real POST happens."""
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        broker.place_order(_buy_request(key="brand-new"))
        assert len(client.post_calls()) == 1


# ---------------------------------------------------------------------------
# Timeout / transport failure — propagate, no retry
# ---------------------------------------------------------------------------
class TestKisWriteTimeoutNoRetry:
    def test_kis_write_timeout_propagates_broker_connection_error(self) -> None:
        client = _FakeKISClient(raise_exc=BrokerConnectionError("timeout"))
        broker = _broker(client, _FakeOrderStore())
        with pytest.raises(BrokerConnectionError):
            broker.place_order(_buy_request())

    def test_kis_write_timeout_posts_exactly_once_no_retry(self) -> None:
        """On transport failure the adapter must NOT auto-retry (ADR 0012 §1.6)."""
        client = _FakeKISClient(raise_exc=BrokerConnectionError("timeout"))
        broker = _broker(client, _FakeOrderStore())
        with pytest.raises(BrokerConnectionError):
            broker.place_order(_buy_request())
        assert len(client.calls) == 1

    def test_kis_write_pending_no_odno_raises_state_mismatch(self) -> None:
        """PENDING record with broker_order_id=None → StateMismatchError (timeout limbo).

        Caller already persisted a PENDING row after a prior timeout (CLAUDE.md §4.3).
        A same-day re-POST must be blocked before touching the network.
        """
        store = _FakeOrderStore()
        store.add(
            OrderResult(
                idempotency_key="idem-buy-1",
                asset=_asset(),
                broker_order_id=None,
                status=OrderStatus.PENDING,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=_FIXED_NOW,
                filled_at=None,
            )
        )
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, store)
        with pytest.raises(StateMismatchError, match="timeout limbo"):
            broker.place_order(_buy_request(key="idem-buy-1"))
        assert len(client.post_calls()) == 0  # no re-POST


# ---------------------------------------------------------------------------
# order_store None — read-only construction blocks every write
# ---------------------------------------------------------------------------
class TestKisWriteReadOnlyBlocksOrders:
    def test_kis_write_place_order_requires_order_store(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = KISBroker(client=client)  # read-only construction
        with pytest.raises(RuntimeError, match="place_order requires order_store"):
            broker.place_order(_buy_request())

    def test_kis_write_get_order_status_requires_order_store(self) -> None:
        client = _FakeKISClient([])
        broker = KISBroker(client=client)
        with pytest.raises(
            RuntimeError, match="get_order_status requires order_store"
        ):
            broker.get_order_status("idem-buy-1")

    def test_kis_write_cancel_order_requires_order_store(self) -> None:
        client = _FakeKISClient([])
        broker = KISBroker(client=client)
        with pytest.raises(
            RuntimeError, match="cancel_order requires order_store"
        ):
            broker.cancel_order("0000117057")

    def test_kis_write_read_only_construction_issues_no_call(self) -> None:
        """A blocked write must never reach the client (no network attempt)."""
        client = _FakeKISClient([_order_body()])
        broker = KISBroker(client=client)
        with pytest.raises(RuntimeError):
            broker.place_order(_buy_request())
        assert client.calls == []


# ---------------------------------------------------------------------------
# get_order_status — status derivation from ccld fields
# ---------------------------------------------------------------------------
def _pending_stored(
    key: str = "idem-buy-1",
    broker_order_id: str = "0000117057",
    org_no: str = "00950",
) -> OrderResult:
    return OrderResult(
        idempotency_key=key,
        asset=_asset(),
        broker_order_id=broker_order_id,
        broker_org_no=org_no,
        status=OrderStatus.PENDING,
        filled_quantity=Decimal(0),
        filled_price=None,
        submitted_at=_FIXED_NOW,
        filled_at=None,
    )


class TestKisWriteGetOrderStatus:
    def test_kis_write_get_order_status_unknown_key_returns_none(self) -> None:
        client = _FakeKISClient([])
        broker = _broker(client, _FakeOrderStore())
        assert broker.get_order_status("nope") is None
        # No network call for an unknown key.
        assert client.calls == []

    def test_kis_write_get_order_status_filled(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(
            [_ccld_body([_ccld_item(ord_qty="10", tot_ccld_qty="10")])]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert result.status is OrderStatus.FILLED
        assert result.filled_quantity == Decimal("10")
        assert result.filled_at == _FIXED_NOW

    def test_kis_write_get_order_status_partially_filled(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(
            [_ccld_body([_ccld_item(ord_qty="10", tot_ccld_qty="4")])]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert result.status is OrderStatus.PARTIALLY_FILLED
        assert result.filled_quantity == Decimal("4")
        # Partial fill is reported honestly; filled_at stays None (not FILLED).
        assert result.filled_at is None

    def test_kis_write_get_order_status_pending_zero_fill(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(
            [_ccld_body([_ccld_item(ord_qty="10", tot_ccld_qty="0")])]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert result.status is OrderStatus.PENDING
        assert result.filled_quantity == Decimal("0")

    def test_kis_write_get_order_status_canceled(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(
            [_ccld_body([_ccld_item(tot_ccld_qty="0", cncl_yn="Y")])]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert result.status is OrderStatus.CANCELED

    def test_kis_write_get_order_status_rejected(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(
            [_ccld_body([_ccld_item(tot_ccld_qty="0", rjct_qty="10")])]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert result.status is OrderStatus.REJECTED

    def test_kis_write_get_order_status_filled_price_is_avg_prvs(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(
            [
                _ccld_body(
                    [_ccld_item(tot_ccld_qty="10", avg_prvs="35250")]
                )
            ]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert result.filled_price == Decimal("35250")

    def test_kis_write_get_order_status_no_matching_row_stays_pending(
        self,
    ) -> None:
        """ODNO not yet in the ccld query → stored (PENDING) returned unchanged."""
        store = _FakeOrderStore()
        store.add(_pending_stored(broker_order_id="0000117057"))
        client = _FakeKISClient(
            [_ccld_body([_ccld_item(odno="9999999999")])]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert result.status is OrderStatus.PENDING
        assert result.broker_order_id == "0000117057"

    def test_kis_write_get_order_status_uses_ccld_tr_id_and_date(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient([_ccld_body([_ccld_item()])])
        broker = _broker(client, store)
        broker.get_order_status("idem-buy-1")
        call = client.calls[0]
        assert call["tr_id"] == "TTTC0081R"
        assert "inquire-daily-ccld" in str(call["path"])
        params = call["params"]
        assert params["INQR_STRT_DT"] == "20260522"  # type: ignore[index]
        assert params["INQR_END_DT"] == "20260522"  # type: ignore[index]


# ---------------------------------------------------------------------------
# cancel_order — org_no resolution
# ---------------------------------------------------------------------------
class TestKisWriteCancelOrder:
    def test_kis_write_cancel_order_resolves_org_no_and_posts(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored(broker_order_id="0000117057", org_no="00950"))
        client = _FakeKISClient([_cancel_body()])
        broker = _broker(client, store)
        assert broker.cancel_order("0000117057") is True
        call = client.post_calls()[0]
        assert call["tr_id"] == "TTTC0013U"
        assert "order-rvsecncl" in str(call["path"])
        body = call["json"]
        assert body["ORGN_ODNO"] == "0000117057"  # type: ignore[index]
        assert body["KRX_FWDG_ORD_ORGNO"] == "00950"  # type: ignore[index]
        assert body["RVSE_CNCL_DVSN_CD"] == "02"  # type: ignore[index]
        assert body["QTY_ALL_ORD_YN"] == "Y"  # type: ignore[index]
        assert body["EXCG_ID_DVSN_CD"] == "KRX"  # type: ignore[index]

    def test_kis_write_cancel_order_unknown_broker_order_id_returns_false(
        self,
    ) -> None:
        client = _FakeKISClient([_cancel_body()])
        broker = _broker(client, _FakeOrderStore())
        assert broker.cancel_order("unknown-oid") is False
        # No POST issued for an unknown order.
        assert client.post_calls() == []

    def test_kis_write_cancel_order_missing_org_no_raises(self) -> None:
        store = _FakeOrderStore()
        # Stored order has no broker_org_no (cannot route cancel).
        store.add(
            OrderResult(
                idempotency_key="idem-buy-1",
                asset=_asset(),
                broker_order_id="0000117057",
                broker_org_no=None,
                status=OrderStatus.PENDING,
                filled_quantity=Decimal(0),
                filled_price=None,
                submitted_at=_FIXED_NOW,
                filled_at=None,
            )
        )
        client = _FakeKISClient([_cancel_body()])
        broker = _broker(client, store)
        with pytest.raises(BrokerOrderError, match="broker_org_no"):
            broker.cancel_order("0000117057")

    def test_kis_write_cancel_order_kis_rejection_propagates(self) -> None:
        """KISClient raises KISApiError on rt_cd != 0 → propagates (no swallow)."""
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(raise_exc=KISApiError("rt_cd=1"))
        broker = _broker(client, store)
        with pytest.raises(KISApiError):
            broker.cancel_order("0000117057")


# ---------------------------------------------------------------------------
# Limit-only guard (지정가 only — CLAUDE.md §4.2)
# ---------------------------------------------------------------------------
class TestKisWriteLimitOnly:
    def test_kis_write_place_order_limit_only_succeeds(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request())
        assert result.status is OrderStatus.PENDING


# ---------------------------------------------------------------------------
# idempotency_key preservation + Decimal/secret invariants
# ---------------------------------------------------------------------------
class TestKisWriteInvariants:
    def test_kis_write_all_orders_have_idempotency_key(self) -> None:
        """place_order preserves the request's idempotency_key on the result."""
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request(key="my-unique-key"))
        assert result.idempotency_key == "my-unique-key"

    def test_kis_write_endpoints_active_with_order_store(self) -> None:
        """With an order_store the write surface is live (not RuntimeError)."""
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        # Does not raise RuntimeError (the read-only guard) — order is accepted.
        result = broker.place_order(_buy_request())
        assert result.broker_order_id is not None

    def test_kis_write_filled_quantity_is_decimal(self) -> None:
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        result = broker.place_order(_buy_request())
        assert isinstance(result.filled_quantity, Decimal)
        assert not isinstance(result.filled_quantity, float)

    def test_kis_write_filled_price_is_decimal_on_fill(self) -> None:
        store = _FakeOrderStore()
        store.add(_pending_stored())
        client = _FakeKISClient(
            [_ccld_body([_ccld_item(tot_ccld_qty="10", avg_prvs="35000")])]
        )
        broker = _broker(client, store)
        result = broker.get_order_status("idem-buy-1")
        assert result is not None
        assert isinstance(result.filled_price, Decimal)
        assert not isinstance(result.filled_price, float)

    def test_kis_write_no_secret_in_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No appkey / appsecret may appear in any log line (ADR 0012 R10)."""
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        with caplog.at_level(logging.DEBUG, logger="src.adapters.kis.broker"):
            broker.place_order(_buy_request())
        joined = " ".join(rec.getMessage() for rec in caplog.records)
        assert "PKabcdefghijklmnop" not in joined
        assert "SECRETsecret==" not in joined

    def test_kis_write_request_body_carries_no_secret(self) -> None:
        """The order-cash POST body must not echo appkey/appsecret (header-only)."""
        client = _FakeKISClient([_order_body()])
        broker = _broker(client, _FakeOrderStore())
        broker.place_order(_buy_request())
        body = client.calls[0]["json"]
        assert "PKabcdefghijklmnop" not in str(body)
        assert "SECRETsecret==" not in str(body)
