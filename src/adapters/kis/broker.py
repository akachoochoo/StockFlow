"""KISBroker — BrokerPort **read subset** (Phase 1.1 Stage 2.3).

Implements ONLY ``get_balance`` (cash 예수금). This is the deliberate Option C
"read-before-write" boundary (ADR 0012): the write surface is built later, so
this class **physically lacks** the write methods rather than stubbing them.

부재 / 연기 (do NOT add here — there is no ``NotImplementedError`` stub either):
- ``place_order`` / ``cancel_order``  → Stage 5 (write surface). idempotency =
  내부 UUID + ODNO 매핑은 place_order 에서 생성 (ADR 0020 §4).
- ``get_positions``                   → Stage 3.3 (reconciliation). KIS
  ``inquire-balance`` ``output1[]`` 은 종목별 집계만 보고 → split-slot 구조를
  모름; reconciliation 단계에서 별도 매핑 (사용자 결정 2026-05-22).
- ``get_order_status``                → Stage 2.5 / 5. idempotency_key → ODNO
  매핑이 place_order 에서 생성되므로 그 이후에만 의미 있음.

A ``hasattr`` gate test (``kis_write_endpoints_absent_before_read_gate``) locks
this absence in so a future careless edit cannot quietly add the write surface.

Real-money invariants: Decimal 전용 (CLAUDE.md §2), no-retry (delegated to
``KISClient``), no secret 로깅 (ADR 0012 R10).

출처: ADR 0020 §2.2 (inquire-balance TR_ID TTTC8434R + 필드) / ADR 0012 (Option
C read-before-write).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.adapters.kis._client import KISApiError
from src.adapters.kis.models import KISBalanceResponse
from src.domain.exceptions import BrokerConnectionError
from src.domain.models import Balance, Currency, Money

if TYPE_CHECKING:
    from src.adapters.kis._client import KISClient

# inquire-balance endpoint + TR_ID (실; PAPER conversion happens in KISClient).
_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
_BALANCE_TR_ID = "TTTC8434R"


class KISBroker:
    """BrokerPort read subset (``get_balance`` only) over a shared ``KISClient``.

    The full BrokerPort contract (place_order / cancel_order / get_positions /
    get_order_status) is intentionally NOT implemented here — see the module
    docstring for the staged rollout.
    """

    def __init__(self, *, client: KISClient) -> None:
        self._client = client

    def get_balance(self) -> Balance:
        """Return current available cash (예수금 ``dnca_tot_amt``) as KRW.

        GET ``inquire-balance`` (TR_ID ``TTTC8434R`` → ``VTTC8434R`` in PAPER).
        The cash figure is the account summary ``output2[0].dnca_tot_amt``
        (ADR 0020 §2.2). An empty ``output2`` is a malformed / unexpected
        response → ``BrokerConnectionError`` (caller halts — no silent fallback,
        CLAUDE.md §6.3).
        """
        body = self._client.request(
            "GET",
            _BALANCE_PATH,
            tr_id=_BALANCE_TR_ID,
            params=_balance_params(
                cano=self._client.config.cano,
                acnt_prdt_cd=self._client.config.acnt_prdt_cd,
            ),
        )
        try:
            parsed = KISBalanceResponse.model_validate(body)
        except ValidationError as exc:
            # Do not echo the body (could carry account/position data) — only
            # the error count.
            raise BrokerConnectionError(
                f"KIS inquire-balance response invalid "
                f"({len(exc.errors())} field error(s))"
            ) from exc

        if not parsed.output2:
            raise BrokerConnectionError(
                "KIS inquire-balance returned empty output2 (no account summary)"
            )

        cash_amount = parsed.output2[0].dnca_tot_amt
        return Balance(cash=Money(amount=cash_amount, currency=Currency.KRW))


def _balance_params(*, cano: str, acnt_prdt_cd: str) -> dict[str, str]:
    """inquire-balance query params (ADR 0020 §2.2).

    INQR_DVSN="02" (종목별), UNPR_DVSN="01" (현재가), AFHR_FLPR_YN="N" (시간외
    단일가 미포함). The continuation keys start empty — Phase 1.1 holds few
    positions so the first page covers the summary (output2). KISApiError is
    raised by KISClient on a non-"0" rt_cd before this layer is reached.
    """
    return {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }


# KISApiError re-exported for callers that catch envelope-level failures.
__all__ = ["KISApiError", "KISBroker"]
