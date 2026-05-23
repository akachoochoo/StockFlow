"""KIS API response DTOs (Pydantic v2) — Phase 1.1 Stage 2.1.

First production code under ``src/adapters/kis/`` (4-ring entry). Pure schema
only: NO network / auth / order logic (those are Stage 2.2 / 2.3 / 2.5).

**Provisional**: every model here is derived from KIS public documentation
(ADR 0020 §2.2 endpoint→field table), not from a live account response. KIS
returns all values as strings, so numeric fields (quantity / price / amount /
ratio) are coerced str→Decimal via a ``mode="before"`` validator (never via
float — CLAUDE.md §2.3). Strict strict-parse verification against real Mock /
모의투자 responses is deferred to Stage 4 / 7 (ADR 0020 §5).

출처: ADR 0020 (Phase 1.1 KIS API Open Questions) §2.2.

Field naming follows KIS wire keys verbatim (snake_case lower); the only
deviation is ``KISOrderOutput`` whose live response keys may be UPPERCASE
(``ODNO`` / ``KRX_FWDG_ORD_ORGNO`` / ``ORD_TMD``) — handled via ``Field(alias=...)``
+ ``populate_by_name`` so both casings parse (ADR 0020 §5 item 4, live verify
pending).
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Decimal coercion helper (local copy)
# ---------------------------------------------------------------------------
def _to_decimal(v: object) -> Decimal:
    """Coerce KIS wire value (string) to Decimal.

    Local copy of the ``src/infrastructure/yaml_strategy_config_loader.py``
    ``_to_decimal`` pattern — copied (not imported) to avoid an adapter→
    infrastructure sideways dependency (Clean Architecture; both are 4-ring
    but cross-package coupling is undesirable).

    Accepts ``Decimal``, ``int``, ``str``, ``float`` (float round-trips via
    ``str(...)`` to dodge IEEE-754 surprises — CLAUDE.md §2.3). Bools are
    rejected. Unlike the loader copy, an empty string raises rather than
    silently producing ``None`` / ``0`` — KIS price/quantity fields must
    never silently vanish (CLAUDE.md §6.3 침묵의 실패 금지).
    """
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("Cannot construct Decimal from bool")
    if isinstance(v, str) and v.strip() == "":
        raise ValueError(
            "Cannot construct Decimal from empty string "
            "(KIS numeric field must not silently vanish; CLAUDE.md §6.3)"
        )
    if isinstance(v, (int, str, float)):
        return Decimal(str(v))
    raise ValueError(f"Unsupported value type for Decimal: {type(v).__name__}")


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------
class _KISBase(BaseModel):
    """Base for KIS external-API DTOs.

    Divergence from the domain base (``src/domain/models.py`` ``DomainModel``,
    which is ``extra="forbid"``): this base uses ``extra="ignore"``. This is
    intentional — KIS responses carry many fields we do not model, and
    ``ADR 0012 §1.6 #4`` mandates that KIS *additive* field changes pass
    harmlessly while a *missing / removed required* field must surface as a
    required-field-missing parse failure (hard halt). ``extra="ignore"``
    delivers exactly that asymmetry: unknown extra keys are dropped silently,
    but a removed required field still raises ``ValidationError`` because the
    field has no default.

    ``strict=False`` is required so the ``mode="before"`` validators can turn
    the all-string KIS wire values into ``Decimal``; strict mode would reject
    ``str`` for a ``Decimal``-typed field before the validator runs.

    ``frozen=True`` mirrors the domain immutability invariant.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", strict=False)


class _KISEnvelope(_KISBase):
    """Common KIS response envelope (ADR 0020 §2.3).

    Every KIS response carries ``rt_cd`` ("0" = success) / ``msg_cd`` / ``msg1``.
    """

    rt_cd: str
    msg_cd: str
    msg1: str

    @property
    def is_ok(self) -> bool:
        """True when KIS reports success (``rt_cd == "0"``)."""
        return self.rt_cd == "0"


# ---------------------------------------------------------------------------
# OAuth2 token (POST /oauth2/tokenP)
# ---------------------------------------------------------------------------
class KISTokenResponse(_KISBase):
    """OAuth2 access-token response.

    ``access_token_token_expired`` is the KIS wire string "YYYY-MM-DD HH:MM:SS"
    (kept verbatim; datetime parsing is a Stage 2.3 adapter concern).
    """

    access_token: str
    access_token_token_expired: str
    token_type: str
    expires_in: Decimal | None = None

    @field_validator("expires_in", mode="before")
    @classmethod
    def _coerce_expires_in(cls, v: object) -> object:
        if v is None:
            return None
        return _to_decimal(v)


# ---------------------------------------------------------------------------
# Balance / position (GET .../trading/inquire-balance)
# ---------------------------------------------------------------------------
class KISBalanceItem(_KISBase):
    """inquire-balance ``output1[]`` — one held position."""

    pdno: str
    prdt_name: str
    hldg_qty: Decimal
    ord_psbl_qty: Decimal
    pchs_avg_pric: Decimal
    prpr: Decimal
    evlu_pfls_amt: Decimal
    evlu_pfls_rt: Decimal
    pchs_amt: Decimal
    evlu_amt: Decimal

    @field_validator(
        "hldg_qty",
        "ord_psbl_qty",
        "pchs_avg_pric",
        "prpr",
        "evlu_pfls_amt",
        "evlu_pfls_rt",
        "pchs_amt",
        "evlu_amt",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> object:
        return _to_decimal(v)


class KISBalanceSummary(_KISBase):
    """inquire-balance ``output2[]`` — account summary.

    ``thdt_tlex_amt`` = 당일 제비용 *총액* (today's total fees), NOT a
    per-order tax/commission split. ADR 0019 per-fill tax/commission
    attribution is provisional (KIS does not return per-order fees in the
    basic order/balance responses — ADR 0020 §4).
    """

    dnca_tot_amt: Decimal
    tot_evlu_amt: Decimal
    nass_amt: Decimal
    scts_evlu_amt: Decimal
    evlu_pfls_smtl_amt: Decimal
    pchs_amt_smtl_amt: Decimal
    thdt_tlex_amt: Decimal

    @field_validator(
        "dnca_tot_amt",
        "tot_evlu_amt",
        "nass_amt",
        "scts_evlu_amt",
        "evlu_pfls_smtl_amt",
        "pchs_amt_smtl_amt",
        "thdt_tlex_amt",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> object:
        return _to_decimal(v)


class KISBalanceResponse(_KISEnvelope):
    """inquire-balance full response.

    ``ctx_area_fk100`` / ``ctx_area_nk100`` are the continuation keys for
    paginated balance queries (모의 20 / 실 50 per page — ADR 0020 §2.2).
    """

    output1: list[KISBalanceItem]
    output2: list[KISBalanceSummary]
    ctx_area_fk100: str = ""
    ctx_area_nk100: str = ""


# ---------------------------------------------------------------------------
# Current price (GET .../quotations/inquire-price)
# ---------------------------------------------------------------------------
class KISPriceOutput(_KISBase):
    """inquire-price ``output`` — current quote snapshot.

    ``stck_sdpr`` = 전일종가 (previous close).
    """

    stck_prpr: Decimal
    stck_oprc: Decimal
    stck_hgpr: Decimal
    stck_lwpr: Decimal
    acml_vol: Decimal
    stck_sdpr: Decimal
    prdy_vrss: Decimal
    prdy_ctrt: Decimal

    @field_validator(
        "stck_prpr",
        "stck_oprc",
        "stck_hgpr",
        "stck_lwpr",
        "acml_vol",
        "stck_sdpr",
        "prdy_vrss",
        "prdy_ctrt",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> object:
        return _to_decimal(v)


class KISPriceResponse(_KISEnvelope):
    """inquire-price full response."""

    output: KISPriceOutput


# ---------------------------------------------------------------------------
# Daily OHLCV (GET .../quotations/inquire-daily-itemchartprice)
# ---------------------------------------------------------------------------
class KISDailyItem(_KISBase):
    """inquire-daily-itemchartprice ``output2[]`` — one daily OHLCV bar.

    ``stck_bsop_date`` = trade date wire string "YYYYMMDD" (kept verbatim;
    date conversion is a Stage 2.3 adapter concern).
    """

    stck_bsop_date: str
    stck_oprc: Decimal
    stck_hgpr: Decimal
    stck_lwpr: Decimal
    stck_clpr: Decimal
    acml_vol: Decimal

    @field_validator(
        "stck_oprc",
        "stck_hgpr",
        "stck_lwpr",
        "stck_clpr",
        "acml_vol",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> object:
        return _to_decimal(v)


class KISDailyPriceResponse(_KISEnvelope):
    """inquire-daily-itemchartprice full response.

    The ``output1`` summary block is intentionally unmodeled — ``extra="ignore"``
    on ``_KISBase`` absorbs it (ADR 0020 §2.2).
    """

    output2: list[KISDailyItem]


# ---------------------------------------------------------------------------
# Order placement (POST .../trading/order-cash)
# ---------------------------------------------------------------------------
class KISOrderOutput(_KISBase):
    """order-cash ``output`` — order placement result.

    KIS live responses may return UPPERCASE keys (``ODNO`` /
    ``KRX_FWDG_ORD_ORGNO`` / ``ORD_TMD``). Each field declares an UPPERCASE
    alias plus ``populate_by_name=True`` so BOTH the lowercase attribute name
    and the uppercase wire alias parse. Live verification pending (ADR 0020
    §5 item 4).

    ``ord_tmd`` = order time wire string "HHMMSS" (kept verbatim).
    """

    model_config = ConfigDict(
        frozen=True, extra="ignore", strict=False, populate_by_name=True
    )

    krx_fwdg_ord_orgno: str = Field(alias="KRX_FWDG_ORD_ORGNO")
    odno: str = Field(alias="ODNO")
    ord_tmd: str = Field(alias="ORD_TMD")


class KISOrderResponse(_KISEnvelope):
    """order-cash full response."""

    output: KISOrderOutput


# ---------------------------------------------------------------------------
# Execution / fill query (GET .../trading/inquire-daily-ccld)
# ---------------------------------------------------------------------------
class KISCcldItem(_KISBase):
    """inquire-daily-ccld ``output1[]`` — one order's fill status.

    KIS has NO ``ord_stts`` field, so fill state is computed from
    ``tot_ccld_qty`` vs ``ord_qty`` (ADR 0020 §2.2). Partial-fill handling
    stays blocked per D5(a) (CLAUDE.md §4.4) — these properties only report.
    """

    odno: str
    orgn_odno: str
    ord_qty: Decimal
    tot_ccld_qty: Decimal
    rmn_qty: Decimal
    avg_prvs: Decimal
    cncl_yn: str
    rjct_qty: Decimal
    pdno: str
    sll_buy_dvsn_cd: str
    ord_dvsn_cd: str

    @field_validator(
        "ord_qty",
        "tot_ccld_qty",
        "rmn_qty",
        "avg_prvs",
        "rjct_qty",
        mode="before",
    )
    @classmethod
    def _coerce(cls, v: object) -> object:
        return _to_decimal(v)

    @property
    def is_fully_filled(self) -> bool:
        """True when total filled quantity equals ordered quantity."""
        return self.tot_ccld_qty == self.ord_qty

    @property
    def is_partial(self) -> bool:
        """True when 0 < filled < ordered (partial fill)."""
        return Decimal(0) < self.tot_ccld_qty < self.ord_qty


class KISCcldResponse(_KISEnvelope):
    """inquire-daily-ccld full response.

    ``ctx_area_fk100`` / ``ctx_area_nk100`` are continuation keys (ADR 0020 §2.2).
    """

    output1: list[KISCcldItem]
    ctx_area_fk100: str = ""
    ctx_area_nk100: str = ""
