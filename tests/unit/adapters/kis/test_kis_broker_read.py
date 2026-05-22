"""Unit tests for src.adapters.kis.broker — KISBroker read subset (Stage 2.3 + 3.3).

Uses a fake ``KISClient`` (records request() calls, returns canned bodies) —
**zero real network**.

Coverage:
- get_balance: dnca_tot_amt → Balance(Money KRW) 매핑.
- get_balance: output2 빈 응답 → BrokerConnectionError.
- get_holdings: output1[] → BrokerHolding 매핑, hldg_qty>0 필터, 빈 보유 → [].
- get_holdings: page-limit 도달 시 truncation WARNING 로깅.
- kis_write_endpoints_absent_before_read_gate: hasattr 게이트.
- kis_broker_port_signature: get_balance / get_holdings 존재, write 메서드 부재.
- kis_decimal_only: Balance.cash.amount is Decimal (float zero).

Function names carry ``kis_broker_`` (Stage gate selector).
"""
from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from src.adapters.kis._client import KISApiError
from src.adapters.kis.broker import KISBroker
from src.adapters.kis.config import KISConfig, TradingMode
from src.domain.exceptions import BrokerConnectionError
from src.domain.models import BrokerHolding, Currency


# ---------------------------------------------------------------------------
# Fake KISClient that bypasses real HTTP/auth/throttle.
# ---------------------------------------------------------------------------
class _FakeKISClient:
    """Minimal KISClient stand-in: queues canned ``request()`` return values."""

    def __init__(
        self,
        bodies: list[dict[str, object]],
        *,
        cano: str = "50012345",
        acnt_prdt_cd: str = "01",
    ) -> None:
        self._bodies = list(bodies)
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
        self.calls.append({"method": method, "path": path, "tr_id": tr_id, "params": params})
        if not self._bodies:
            raise KISApiError("no more canned bodies")
        return self._bodies.pop(0)


# ---------------------------------------------------------------------------
# Sample wire bodies (all numeric fields as strings — ADR 0020 §2.2)
# ---------------------------------------------------------------------------
def _balance_body(dnca_tot_amt: str = "5000000") -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": [],
        "output2": [
            {
                "dnca_tot_amt": dnca_tot_amt,
                "tot_evlu_amt": "5200000",
                "nass_amt": "5200000",
                "scts_evlu_amt": "200000",
                "evlu_pfls_smtl_amt": "15000",
                "pchs_amt_smtl_amt": "185000",
                "thdt_tlex_amt": "0",
            }
        ],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


def _empty_output2_body() -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": [],
        "output2": [],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


def _holding_item(
    pdno: str = "069500",
    hldg_qty: str = "10",
    pchs_avg_pric: str = "35000",
    prdt_name: str = "KODEX 200",
) -> dict[str, object]:
    """One inquire-balance output1[] row (all numeric fields as strings)."""
    return {
        "pdno": pdno,
        "prdt_name": prdt_name,
        "hldg_qty": hldg_qty,
        "ord_psbl_qty": hldg_qty,
        "pchs_avg_pric": pchs_avg_pric,
        "prpr": "36000",
        "evlu_pfls_amt": "10000",
        "evlu_pfls_rt": "2.85",
        "pchs_amt": "350000",
        "evlu_amt": "360000",
    }


def _holdings_body(
    output1: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리",
        "output1": output1 if output1 is not None else [],
        "output2": [
            {
                "dnca_tot_amt": "5000000",
                "tot_evlu_amt": "5200000",
                "nass_amt": "5200000",
                "scts_evlu_amt": "200000",
                "evlu_pfls_smtl_amt": "15000",
                "pchs_amt_smtl_amt": "185000",
                "thdt_tlex_amt": "0",
            }
        ],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


# ---------------------------------------------------------------------------
# get_balance — happy path
# ---------------------------------------------------------------------------
class TestKisBrokerGetBalance:
    def test_kis_broker_get_balance_maps_dnca_tot_amt_to_krw(self) -> None:
        client = _FakeKISClient([_balance_body("5000000")])
        broker = KISBroker(client=client)
        balance = broker.get_balance()
        assert balance.cash.currency is Currency.KRW
        assert balance.cash.amount == Decimal("5000000")

    def test_kis_broker_get_balance_zero_cash(self) -> None:
        client = _FakeKISClient([_balance_body("0")])
        broker = KISBroker(client=client)
        balance = broker.get_balance()
        assert balance.cash.amount == Decimal("0")

    def test_kis_broker_get_balance_large_amount(self) -> None:
        client = _FakeKISClient([_balance_body("100000000")])
        broker = KISBroker(client=client)
        balance = broker.get_balance()
        assert balance.cash.amount == Decimal("100000000")

    def test_kis_broker_get_balance_issues_exactly_one_request(self) -> None:
        client = _FakeKISClient([_balance_body()])
        broker = KISBroker(client=client)
        broker.get_balance()
        assert len(client.calls) == 1

    def test_kis_broker_get_balance_uses_inquire_balance_path(self) -> None:
        client = _FakeKISClient([_balance_body()])
        broker = KISBroker(client=client)
        broker.get_balance()
        assert "inquire-balance" in client.calls[0]["path"]  # type: ignore[operator]

    def test_kis_broker_get_balance_uses_tttc8434r_tr_id(self) -> None:
        """TR_ID TTTC8434R for balance (paper conversion happens in KISClient)."""
        client = _FakeKISClient([_balance_body()])
        broker = KISBroker(client=client)
        broker.get_balance()
        assert client.calls[0]["tr_id"] == "TTTC8434R"

    def test_kis_broker_get_balance_params_include_cano(self) -> None:
        client = _FakeKISClient([_balance_body()], cano="99887766", acnt_prdt_cd="02")
        broker = KISBroker(client=client)
        broker.get_balance()
        params = client.calls[0]["params"]
        assert params["CANO"] == "99887766"  # type: ignore[index]
        assert params["ACNT_PRDT_CD"] == "02"  # type: ignore[index]


# ---------------------------------------------------------------------------
# get_balance — error paths
# ---------------------------------------------------------------------------
class TestKisBrokerGetBalanceErrors:
    def test_kis_broker_empty_output2_raises_broker_connection_error(self) -> None:
        client = _FakeKISClient([_empty_output2_body()])
        broker = KISBroker(client=client)
        with pytest.raises(BrokerConnectionError, match="output2"):
            broker.get_balance()

    def test_kis_broker_invalid_response_schema_raises_broker_connection_error(self) -> None:
        """Missing required fields in output2 → ValidationError → BrokerConnectionError."""
        # Empty dict in output2 → missing all required fields → ValidationError → wrapped.
        bad_body: dict[str, object] = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "ok",
            "output1": [],
            "output2": [{}],
        }
        client = _FakeKISClient([bad_body])
        broker = KISBroker(client=client)
        with pytest.raises(BrokerConnectionError):
            broker.get_balance()


# ---------------------------------------------------------------------------
# get_holdings — reconciliation 대조용 (Stage 3.3)
# ---------------------------------------------------------------------------
class TestKisBrokerGetHoldings:
    def test_kis_broker_get_holdings_empty_returns_empty_list(self) -> None:
        client = _FakeKISClient([_holdings_body([])])
        broker = KISBroker(client=client)
        assert broker.get_holdings() == []

    def test_kis_broker_get_holdings_maps_output1_to_broker_holding(self) -> None:
        client = _FakeKISClient(
            [_holdings_body([_holding_item("069500", "10", "35000")])]
        )
        broker = KISBroker(client=client)
        holdings = broker.get_holdings()
        assert holdings == [
            BrokerHolding(
                asset_code="069500",
                quantity=Decimal("10"),
                avg_price=Decimal("35000"),
            )
        ]

    def test_kis_broker_get_holdings_multiple_symbols(self) -> None:
        client = _FakeKISClient(
            [
                _holdings_body(
                    [
                        _holding_item("069500", "10", "35000"),
                        _holding_item("005930", "7", "71500", "삼성전자"),
                    ]
                )
            ]
        )
        broker = KISBroker(client=client)
        holdings = broker.get_holdings()
        assert len(holdings) == 2
        by_code = {h.asset_code: h for h in holdings}
        assert by_code["069500"].quantity == Decimal("10")
        assert by_code["005930"].quantity == Decimal("7")
        assert by_code["005930"].avg_price == Decimal("71500")

    def test_kis_broker_get_holdings_filters_zero_quantity(self) -> None:
        """A row with hldg_qty == 0 must be excluded (quantity > 0 only)."""
        client = _FakeKISClient(
            [
                _holdings_body(
                    [
                        _holding_item("069500", "10", "35000"),
                        _holding_item("005930", "0", "71500", "삼성전자"),
                    ]
                )
            ]
        )
        broker = KISBroker(client=client)
        holdings = broker.get_holdings()
        assert [h.asset_code for h in holdings] == ["069500"]

    def test_kis_broker_get_holdings_uses_inquire_balance_path_and_tr_id(
        self,
    ) -> None:
        """Same path / TR_ID as get_balance (reuses inquire-balance)."""
        client = _FakeKISClient([_holdings_body([])])
        broker = KISBroker(client=client)
        broker.get_holdings()
        assert "inquire-balance" in client.calls[0]["path"]  # type: ignore[operator]
        assert client.calls[0]["tr_id"] == "TTTC8434R"

    def test_kis_broker_get_holdings_decimal_only(self) -> None:
        client = _FakeKISClient(
            [_holdings_body([_holding_item("069500", "10", "35000")])]
        )
        broker = KISBroker(client=client)
        holding = broker.get_holdings()[0]
        assert isinstance(holding.quantity, Decimal)
        assert isinstance(holding.avg_price, Decimal)
        assert not isinstance(holding.quantity, float)

    def test_kis_broker_get_holdings_invalid_schema_raises(self) -> None:
        """A malformed output1 row → ValidationError → BrokerConnectionError."""
        bad_body: dict[str, object] = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "ok",
            "output1": [{"pdno": "069500"}],  # missing required numeric fields
            "output2": [],
        }
        client = _FakeKISClient([bad_body])
        broker = KISBroker(client=client)
        with pytest.raises(BrokerConnectionError):
            broker.get_holdings()

    def test_kis_broker_get_holdings_warns_on_page_limit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """output1 at the page limit logs a truncation WARNING (guard)."""
        # 20 distinct held symbols == page limit (모의 20) → truncation guard.
        rows = [
            _holding_item(f"{100000 + i:06d}", "1", "1000")
            for i in range(20)
        ]
        client = _FakeKISClient([_holdings_body(rows)])
        broker = KISBroker(client=client)
        with caplog.at_level(logging.WARNING, logger="src.adapters.kis.broker"):
            holdings = broker.get_holdings()
        assert len(holdings) == 20
        assert any(
            "page limit" in rec.message for rec in caplog.records
        ), "expected a truncation WARNING at the page limit"

    def test_kis_broker_get_holdings_no_warning_below_limit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _FakeKISClient(
            [_holdings_body([_holding_item("069500", "10", "35000")])]
        )
        broker = KISBroker(client=client)
        with caplog.at_level(logging.WARNING, logger="src.adapters.kis.broker"):
            broker.get_holdings()
        assert not any("page limit" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Decimal invariant
# ---------------------------------------------------------------------------
class TestKisBrokerDecimalOnly:
    def test_kis_decimal_only_balance_cash_amount_is_decimal(self) -> None:
        """CLAUDE.md §2: all money values must be Decimal, never float."""
        client = _FakeKISClient([_balance_body("3750000")])
        broker = KISBroker(client=client)
        balance = broker.get_balance()
        assert isinstance(balance.cash.amount, Decimal)
        assert not isinstance(balance.cash.amount, float)


# ---------------------------------------------------------------------------
# Port-signature gate: read methods present, write methods absent
# ---------------------------------------------------------------------------
class TestKisBrokerPortSignature:
    def test_kis_broker_port_signature_get_balance_exists(self) -> None:
        """BrokerPort read method get_balance must be present."""
        assert hasattr(KISBroker, "get_balance")
        assert callable(KISBroker.get_balance)

    def test_kis_broker_port_signature_get_holdings_exists(self) -> None:
        """Stage 3.3 read method get_holdings must be present (reconciliation)."""
        assert hasattr(KISBroker, "get_holdings")
        assert callable(KISBroker.get_holdings)

    def test_kis_write_endpoints_absent_before_read_gate(self) -> None:
        """Stage gate: write methods must NOT exist until Stage 5.

        Locks Option C (read-before-write) boundary: a careless Stage 5 edit
        that forgets to update this test will cause an immediate failure.
        """
        assert not hasattr(KISBroker, "place_order"), (
            "place_order must not exist until Stage 5 (write surface)"
        )
        assert not hasattr(KISBroker, "cancel_order"), (
            "cancel_order must not exist until Stage 5 (write surface)"
        )
        assert not hasattr(KISBroker, "get_positions"), (
            "get_positions (full Position) is NOT implemented — KIS "
            "inquire-balance output1[] is aggregate-only; reconciliation uses "
            "get_holdings (BrokerHolding) instead (사용자 결정 2026-05-22)"
        )
        assert not hasattr(KISBroker, "get_order_status"), (
            "get_order_status must not exist until Stage 2.5/5"
        )
