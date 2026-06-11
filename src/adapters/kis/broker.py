"""KISBroker — BrokerPort read subset + write surface (Phase 1.1 Stage 2.3 + 3.3 + 5).

Implements ``get_balance`` (cash 예수금) + ``get_holdings`` (reconciliation 대조용
종목별 집계 보유) **and** the Stage 5 write surface (``place_order`` /
``get_order_status`` / ``cancel_order``).

**Option C transition** (ADR 0012 read-before-write): the read subset shipped
first (Stage 2.3); the write methods now exist (Stage 5) but are gated by a
**required** ``order_store`` injection. A read-only construction
(``KISBroker(client=client)``, ``order_store=None``) physically **cannot place,
cancel, or status an order** — every write method raises ``RuntimeError`` — so
the kis-check / reconcile paths (which never wire an order_store) still cannot
move money. Writing this code ≠ live trading: no runner calls ``place_order``
until Stage 8 (composition/CLI wiring), and live order ON is still behind the
D16 gate (ADR 0012 / ADR 0020 §5.1).

부재 / 연기 (do NOT add here):
- ``get_positions``                   → 미구현. KIS ``inquire-balance``
  ``output1[]`` 은 종목별 집계만 보고 → full Position (split-slot 구조) 복원 불가.
  reconciliation 은 ``get_holdings`` (집계 BrokerHolding view) 로 대조 (사용자
  결정 2026-05-22).

Real-money invariants: Decimal 전용 (CLAUDE.md §2), **지정가 only** (LIMIT —
시장가 구조적 불가, CLAUDE.md §4.2), **idempotency dedup** (재-POST zero,
CLAUDE.md §4.1), **timeout/transport 실패 그대로 전파** (자동 재시도 zero —
호출자가 PENDING 저장 후 get_order_status, CLAUDE.md §4.3 / ADR 0012 §1.6 #1),
no secret 로깅 (ADR 0012 R10). Partial fill 은 ``PARTIALLY_FILLED`` 로 정직
보고 — split 증가 차단은 도메인 책임 (ADR 0012 D5 / CLAUDE.md §4.4).

출처: ADR 0020 §2.2 (inquire-balance TTTC8434R + order-cash 매수 TTTC0012U /
매도 TTTC0011U + inquire-daily-ccld TTTC0081R + order-rvsecncl TTTC0013U + 필드)
/ ADR 0012 §4 (주문 의무) / ADR 0012 (Option C read-before-write).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from src.adapters.kis._client import KISApiError
from src.adapters.kis.models import (
    KISBalanceResponse,
    KISCcldItem,
    KISCcldResponse,
    KISOrderResponse,
)
from src.domain.exceptions import (
    BrokerConnectionError,
    BrokerOrderError,
    StateMismatchError,
)
from src.domain.models import (
    Balance,
    BrokerHolding,
    Currency,
    Money,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.adapters.kis._client import KISClient

_logger = logging.getLogger(__name__)
_KST = ZoneInfo("Asia/Seoul")

# inquire-balance endpoint + TR_ID (실; PAPER conversion happens in KISClient).
_BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
_BALANCE_TR_ID = "TTTC8434R"

# order-cash (주문) — POST 지정가. TR_ID: 매수 TTTC0012U / 매도 TTTC0011U
# (모의 V... in KISClient). ADR 0020 §2.2.
_ORDER_PATH = "/uapi/domestic-stock/v1/trading/order-cash"
_ORDER_TR_ID_BUY = "TTTC0012U"
_ORDER_TR_ID_SELL = "TTTC0011U"

# inquire-daily-ccld (체결조회) — GET. TR_ID TTTC0081R (3개월↑ CTSC9215R 미사용,
# Phase 1.1 = 당일 조회). KIS 는 ord_stts 없음 → tot_ccld_qty vs ord_qty 계산.
_CCLD_PATH = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
_CCLD_TR_ID = "TTTC0081R"

# order-rvsecncl (정정/취소) — POST. TR_ID TTTC0013U. RVSE_CNCL_DVSN_CD="02"
# (취소), ORGN_ODNO = 원주문 ODNO, KRX_FWDG_ORD_ORGNO = 주문 조직번호.
_CANCEL_PATH = "/uapi/domestic-stock/v1/trading/order-rvsecncl"
_CANCEL_TR_ID = "TTTC0013U"

# Limit-order division code (지정가). 시장가 ("01") 는 구조적 불가 (CLAUDE.md §4.2).
_ORD_DVSN_LIMIT = "00"

# KRX exchange routing code (EXCG_ID_DVSN_CD) for KRX domestic equities.
_EXCG_ID_KRX = "KRX"

# Read-only construction (order_store=None) write-attempt guard message.
_NO_ORDER_STORE_MSG = (
    "{method} requires order_store (write not wired in read-only construction)"
)

# inquire-balance output1[] page size (모의 20 / 실 50 per page, ADR 0020 §2.2).
# Phase 1.1 holds ≤ 2 symbols → first page always covers all holdings. We log a
# WARNING if output1 reaches the page limit (a truncation guard) so a future
# multi-symbol portfolio cannot silently drop held positions before pagination
# is implemented. Pagination follow-up: Phase 1.x (ctx_area_fk100/nk100).
_HOLDINGS_PAGE_LIMIT = 20


class KISOrderStore(Protocol):
    """Persistent order-state lookup the write surface depends on.

    KIS supports **no client-side idempotency key** (ADR 0020 §4), so the
    durable mapping ``idempotency_key ↔ ODNO(broker_order_id) ↔ org_no`` lives
    in our own store. ``place_order`` consults it for dedup; ``cancel_order``
    consults it to resolve the routing org_no for a given broker_order_id.

    The Stage 8 runner injects a concrete implementation built over the SQLite
    order repository; the read-only kis-check / reconcile constructions inject
    nothing (``order_store=None``) so they structurally cannot place orders.
    """

    def find_by_idempotency_key(self, key: str) -> OrderResult | None:
        """Return the persisted OrderResult for ``key``, or None if unknown."""
        ...

    def find_by_broker_order_id(
        self, broker_order_id: str
    ) -> OrderResult | None:
        """Return the persisted OrderResult for ``broker_order_id``, or None."""
        ...


class KISBroker:
    """BrokerPort read subset + gated write surface over a shared ``KISClient``.

    Read methods (``get_balance`` / ``get_holdings``, reconciliation 대조용) work
    with a bare ``KISBroker(client=client)`` construction. The write methods
    (``place_order`` / ``get_order_status`` / ``cancel_order``) require an
    injected ``order_store`` (idempotency dedup + org_no 해석); a read-only
    construction (``order_store=None``) raises ``RuntimeError`` on any write
    call — money cannot move through the read-only path (Option C boundary).
    Full ``get_positions`` is intentionally NOT implemented — see the module
    docstring.
    """

    def __init__(
        self,
        *,
        client: KISClient,
        order_store: KISOrderStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._order_store = order_store
        self._clock = clock if clock is not None else _utc_now

    def get_balance(self) -> Balance:
        """Return current available cash (예수금 ``dnca_tot_amt``) as KRW.

        GET ``inquire-balance`` (TR_ID ``TTTC8434R`` → ``VTTC8434R`` in PAPER).
        The cash figure is the account summary ``output2[0].dnca_tot_amt``
        (ADR 0020 §2.2). An empty ``output2`` is a malformed / unexpected
        response → ``BrokerConnectionError`` (caller halts — no silent fallback,
        CLAUDE.md §6.3).
        """
        parsed = self._fetch_balance_response()
        if not parsed.output2:
            raise BrokerConnectionError(
                "KIS inquire-balance returned empty output2 (no account summary)"
            )

        cash_amount = parsed.output2[0].dnca_tot_amt
        return Balance(cash=Money(amount=cash_amount, currency=Currency.KRW))

    def get_holdings(self) -> list[BrokerHolding]:
        """Return broker-aggregated per-asset holdings (quantity > 0).

        GET ``inquire-balance`` (same path / TR_ID / params as
        :meth:`get_balance`); each ``output1[]`` row with ``hldg_qty > 0`` maps
        to a :class:`~src.domain.models.BrokerHolding` (code + quantity +
        average price — no split-slot structure; the broker reports an aggregate
        only). Used by reconciliation (CLAUDE.md §11.2) to compare DB Positions
        against the broker's reported holdings.

        Phase 1.1 holds ≤ 2 symbols, so the **first page** always covers all
        holdings (single-page assumption). If ``output1`` reaches the page limit
        (모의 20 / 실 50, ADR 0020 §2.2) a WARNING is logged — a truncation guard
        so a future multi-symbol portfolio cannot silently drop held positions
        before pagination (ctx_area_fk100/nk100) is implemented. Pagination
        follow-up: Phase 1.x.
        """
        parsed = self._fetch_balance_response()
        if len(parsed.output1) >= _HOLDINGS_PAGE_LIMIT:
            _logger.warning(
                "KIS inquire-balance output1 reached the page limit (%d rows) "
                "— holdings may be truncated. Reconciliation pagination is not "
                "yet implemented (Phase 1.x follow-up).",
                len(parsed.output1),
            )
        return [
            BrokerHolding(
                asset_code=item.pdno,
                quantity=item.hldg_qty,
                avg_price=item.pchs_avg_pric,
            )
            for item in parsed.output1
            if item.hldg_qty > 0
        ]

    # ------------------------------------------------------------------
    # BrokerPort — write surface (Stage 5; gated by order_store)
    # ------------------------------------------------------------------
    def place_order(self, request: OrderRequest) -> OrderResult:
        """Submit a 지정가 (LIMIT) order. Idempotent on ``idempotency_key``.

        Flow:
        1. ``order_store`` is required (read-only construction → RuntimeError —
           money cannot move through the read-only path).
        2. **Idempotency dedup** (CLAUDE.md §4.1): if a prior order for this
           ``idempotency_key`` already reached the broker (``broker_order_id``
           set), we re-fetch its status via :meth:`get_order_status` instead of
           re-POSTing — a same-key retry NEVER creates a duplicate order.
        3. LIMIT only (CLAUDE.md §4.2). The enum carries only LIMIT, but we
           defend explicitly so a future enum addition cannot silently route a
           market order.
        4. POST order-cash (매수 ``TTTC0012U`` / 매도 ``TTTC0011U``).
        5. **timeout / transport 실패** (``BrokerConnectionError``) propagates —
           we do NOT catch or retry (CLAUDE.md §4.3 / ADR 0012 §1.6 #1). The
           caller persists PENDING and reconciles later via get_order_status.
        6. Success → ``OrderResult`` with ``status=PENDING`` (the order is
           *accepted*; fills are confirmed later via get_order_status), the KIS
           ``ODNO`` as ``broker_order_id`` and ``KRX_FWDG_ORD_ORGNO`` as
           ``broker_org_no`` (cancel routing).
        """
        store = self._require_order_store("place_order")

        existing = store.find_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if existing.broker_order_id is not None:
                # Already at the broker — re-fetch, never re-POST (idempotency).
                result = self.get_order_status(request.idempotency_key)
                if result is None:  # pragma: no cover - store invariant
                    raise BrokerOrderError(
                        "place_order dedup: order_store has the key but "
                        "get_order_status returned None (inconsistent store)"
                    )
                return result
            if existing.status is OrderStatus.PENDING:
                # Timeout limbo: a POST was attempted but we lost the broker
                # response (BrokerConnectionError). broker_order_id is None so
                # we cannot query KIS for the outcome. Do NOT re-POST — the
                # order may have reached KIS already. Halt for manual review.
                raise StateMismatchError(
                    f"place_order: idempotency_key={request.idempotency_key!r} "
                    "exists as PENDING with no broker_order_id — "
                    "possible timeout limbo; manual reconciliation required "
                    "before re-running (CLAUDE.md §4.3)."
                )
            # status is REJECTED/UNKNOWN/CANCELED/EXPIRED — definitively not at
            # broker; allow re-POST with the same deterministic key.

        if request.order_type is not OrderType.LIMIT:
            raise BrokerOrderError(
                f"KIS place_order supports LIMIT (지정가) only, got "
                f"{request.order_type.value} (시장가 구조적 불가; CLAUDE.md §4.2)"
            )

        tr_id = (
            _ORDER_TR_ID_BUY
            if request.side is OrderSide.BUY
            else _ORDER_TR_ID_SELL
        )
        # Transport failure (BrokerConnectionError) propagates — no retry.
        body = self._client.request(
            "POST",
            _ORDER_PATH,
            tr_id=tr_id,
            json={
                "CANO": self._client.config.cano,
                "ACNT_PRDT_CD": self._client.config.acnt_prdt_cd,
                "PDNO": request.asset.code,
                "ORD_DVSN": _ORD_DVSN_LIMIT,
                "ORD_QTY": str(request.quantity),
                "ORD_UNPR": str(request.target_price),
                "EXCG_ID_DVSN_CD": _EXCG_ID_KRX,
            },
        )
        try:
            parsed = KISOrderResponse.model_validate(body)
        except ValidationError as exc:
            raise BrokerOrderError(
                f"KIS order-cash response invalid "
                f"({len(exc.errors())} field error(s))"
            ) from exc

        return OrderResult(
            idempotency_key=request.idempotency_key,
            asset=request.asset,
            broker_order_id=parsed.output.odno,
            broker_org_no=parsed.output.krx_fwdg_ord_orgno,
            status=OrderStatus.PENDING,
            filled_quantity=Decimal(0),
            filled_price=None,
            submitted_at=self._clock(),
            filled_at=None,
            tax=None,
            commission=None,
        )

    def get_order_status(self, idempotency_key: str) -> OrderResult | None:
        """Look up an order by ``idempotency_key`` (inquire-daily-ccld).

        Returns None if the key is unknown to ``order_store`` (no order was
        ever placed for it). Otherwise GET inquire-daily-ccld for the submit
        date and find the row matching the stored ``broker_order_id``:
        - no matching row → still PENDING (return the stored result unchanged);
        - matching row → rebuild status from KIS fields (KIS has no
          ``ord_stts``; state is computed from ``tot_ccld_qty`` vs ``ord_qty``,
          ``cncl_yn``, ``rjct_qty`` — ADR 0020 §2.2).

        Partial fills are reported honestly as ``PARTIALLY_FILLED`` (the D5
        split-increment block is a domain responsibility — the adapter only
        reports facts; CLAUDE.md §4.4).
        """
        store = self._require_order_store("get_order_status")

        existing = store.find_by_idempotency_key(idempotency_key)
        if existing is None:
            return None
        if existing.broker_order_id is None:
            # Accepted-but-no-ODNO is not expected post-place; nothing to query.
            return existing

        ymd = existing.submitted_at.astimezone(_KST).date().strftime("%Y%m%d")
        body = self._client.request(
            "GET",
            _CCLD_PATH,
            tr_id=_CCLD_TR_ID,
            params=_ccld_params(
                cano=self._client.config.cano,
                acnt_prdt_cd=self._client.config.acnt_prdt_cd,
                inqr_strt_dt=ymd,
                inqr_end_dt=ymd,
            ),
        )
        try:
            parsed = KISCcldResponse.model_validate(body)
        except ValidationError as exc:
            raise BrokerConnectionError(
                f"KIS inquire-daily-ccld response invalid "
                f"({len(exc.errors())} field error(s))"
            ) from exc

        row = next(
            (
                item
                for item in parsed.output1
                if item.odno == existing.broker_order_id
            ),
            None,
        )
        if row is None:
            # Order accepted but not yet visible in the fill query → PENDING.
            return existing

        status = _ccld_status(row)
        filled_price = row.avg_prvs if row.avg_prvs > 0 else None
        filled_at = self._clock() if status is OrderStatus.FILLED else None
        return OrderResult(
            idempotency_key=existing.idempotency_key,
            asset=existing.asset,
            broker_order_id=existing.broker_order_id,
            broker_org_no=existing.broker_org_no,
            status=status,
            filled_quantity=row.tot_ccld_qty,
            filled_price=filled_price,
            submitted_at=existing.submitted_at,
            filled_at=filled_at,
            tax=existing.tax,
            commission=existing.commission,
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        """Request cancellation of ``broker_order_id`` (order-rvsecncl 02취소).

        Resolves the routing org_no (``KRX_FWDG_ORD_ORGNO``) from
        ``order_store`` — KIS cancel needs both the original ODNO and the org_no
        (ADR 0020 §2.2). Returns False for an unknown ``broker_order_id`` (we
        cannot cancel an order we have no record of). A known order with no
        stored ``broker_org_no`` → ``BrokerOrderError`` (cannot route the
        cancel). KIS ``rt_cd`` validation lives in ``KISClient``: if no
        ``KISApiError`` is raised the cancel was accepted → return True.
        """
        store = self._require_order_store("cancel_order")

        existing = store.find_by_broker_order_id(broker_order_id)
        if existing is None:
            return False
        org_no = existing.broker_org_no
        if org_no is None:
            raise BrokerOrderError(
                f"cannot cancel order {broker_order_id} without broker_org_no "
                f"(KRX_FWDG_ORD_ORGNO routing missing in order_store)"
            )

        # KISClient raises KISApiError on rt_cd != "0"; transport failure
        # (BrokerConnectionError) propagates — no retry (ADR 0012 §1.6 #1).
        self._client.request(
            "POST",
            _CANCEL_PATH,
            tr_id=_CANCEL_TR_ID,
            json={
                "CANO": self._client.config.cano,
                "ACNT_PRDT_CD": self._client.config.acnt_prdt_cd,
                "KRX_FWDG_ORD_ORGNO": org_no,
                "ORGN_ODNO": broker_order_id,
                "ORD_DVSN": _ORD_DVSN_LIMIT,
                "RVSE_CNCL_DVSN_CD": "02",
                "ORD_QTY": "0",
                "ORD_UNPR": "0",
                "QTY_ALL_ORD_YN": "Y",
                "EXCG_ID_DVSN_CD": _EXCG_ID_KRX,
            },
        )
        return True

    def _require_order_store(self, method: str) -> KISOrderStore:
        """Return the injected ``order_store`` or raise (read-only guard).

        A read-only construction (``order_store=None``) physically cannot place,
        status, or cancel orders — every write entry point routes through here
        so money cannot move via the kis-check / reconcile paths.
        """
        if self._order_store is None:
            raise RuntimeError(_NO_ORDER_STORE_MSG.format(method=method))
        return self._order_store

    def _fetch_balance_response(self) -> KISBalanceResponse:
        """GET inquire-balance and parse the envelope (shared by balance/holdings).

        A schema-invalid body → ``BrokerConnectionError`` (caller halts — no
        silent fallback, CLAUDE.md §6.3). The body is never echoed (it could
        carry account / position data) — only the error count.
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
            return KISBalanceResponse.model_validate(body)
        except ValidationError as exc:
            raise BrokerConnectionError(
                f"KIS inquire-balance response invalid "
                f"({len(exc.errors())} field error(s))"
            ) from exc


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


def _ccld_params(
    *,
    cano: str,
    acnt_prdt_cd: str,
    inqr_strt_dt: str,
    inqr_end_dt: str,
) -> dict[str, str]:
    """inquire-daily-ccld query params (ADR 0020 §2.2 + KIS 공식 샘플).

    Required keys per the KIS ``inquire_daily_ccld`` reference sample:
    - ``SLL_BUY_DVSN_CD="00"`` (전체 — buy+sell),
    - ``CCLD_DVSN="00"`` (전체 — 체결+미체결; we need PENDING rows too),
    - ``INQR_DVSN="00"`` (역순), ``INQR_DVSN_3="00"`` (전체),
    - ``EXCG_ID_DVSN_CD="KRX"``.

    ``PDNO`` / ``ORD_GNO_BRNO`` / ``ODNO`` / ``INQR_DVSN_1`` are left empty —
    KIS returns all of the date window's rows and ``get_order_status`` filters
    to the stored ``broker_order_id`` (ODNO) locally. The continuation keys
    start empty (Phase 1.1 places few orders/day → single page).
    """
    return {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "INQR_STRT_DT": inqr_strt_dt,
        "INQR_END_DT": inqr_end_dt,
        "SLL_BUY_DVSN_CD": "00",
        "INQR_DVSN": "00",
        "PDNO": "",
        "CCLD_DVSN": "00",
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "EXCG_ID_DVSN_CD": _EXCG_ID_KRX,
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }


def _ccld_status(row: KISCcldItem) -> OrderStatus:
    """Map an inquire-daily-ccld ``output1[]`` row to an OrderStatus.

    KIS has NO ``ord_stts`` field (ADR 0020 §2.2) — state is derived from the
    fill columns. Precedence (most-terminal first):
    - ``cncl_yn == "Y"``      → CANCELED,
    - ``rjct_qty > 0``        → REJECTED,
    - fully filled            → FILLED,
    - partially filled        → PARTIALLY_FILLED (honest report; the D5 split
                                block is the domain's job, CLAUDE.md §4.4),
    - ``tot_ccld_qty == 0``   → PENDING (accepted, not yet filled).
    """
    if row.cncl_yn == "Y":
        return OrderStatus.CANCELED
    if row.rjct_qty > 0:
        return OrderStatus.REJECTED
    if row.is_fully_filled:
        return OrderStatus.FILLED
    if row.is_partial:
        return OrderStatus.PARTIALLY_FILLED
    return OrderStatus.PENDING


def _utc_now() -> datetime:
    """Default ``clock`` — current UTC instant (CLAUDE.md §3.1).

    Used only when no ``clock`` is injected. Adapters may read the wall clock
    (the domain may not — CLAUDE.md §3.2); tests inject a fixed clock so the
    write surface stays deterministic and time-stable.
    """
    return datetime.now(UTC)


# KISApiError re-exported for callers that catch envelope-level failures.
__all__ = ["KISApiError", "KISBroker", "KISOrderStore"]
