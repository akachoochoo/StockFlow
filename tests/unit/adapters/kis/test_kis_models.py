"""Unit tests for src.adapters.kis.models (Phase 1.1 Stage 2.1).

Documented-shape sample dicts (ADR 0020 §2.2 / KIS public examples — NOT live
account data; all wire values are strings). Verifies str→Decimal coercion,
bool/empty-string rejection, additive-extra tolerance + required-missing
failure (ADR 0012 §1.6 #4), uppercase/lowercase alias parsing, and partial-fill
properties.

Function names carry ``kis_api_schema_validation`` (gate selector).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.adapters.kis.models import (
    KISBalanceItem,
    KISBalanceResponse,
    KISBalanceSummary,
    KISCcldItem,
    KISCcldResponse,
    KISDailyPriceResponse,
    KISOrderOutput,
    KISOrderResponse,
    KISPriceOutput,
    KISPriceResponse,
    KISTokenResponse,
)

# ---------------------------------------------------------------------------
# Documented-shape sample fixtures (string wire values — not live data)
# ---------------------------------------------------------------------------
_ENVELOPE_OK = {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리 되었습니다."}


def _token_sample() -> dict[str, object]:
    return {
        "access_token": "eyJ0eXAiOiJKV1QiL...",
        "access_token_token_expired": "2026-05-23 09:00:00",
        "token_type": "Bearer",
        "expires_in": "86400",
    }


def _balance_item_sample() -> dict[str, object]:
    return {
        "pdno": "069500",
        "prdt_name": "KODEX 200",
        "hldg_qty": "10",
        "ord_psbl_qty": "10",
        "pchs_avg_pric": "35000",
        "prpr": "36000",
        "evlu_pfls_amt": "10000",
        "evlu_pfls_rt": "2.86",
        "pchs_amt": "350000",
        "evlu_amt": "360000",
    }


def _balance_summary_sample() -> dict[str, object]:
    return {
        "dnca_tot_amt": "5000000",
        "tot_evlu_amt": "5360000",
        "nass_amt": "5360000",
        "scts_evlu_amt": "360000",
        "evlu_pfls_smtl_amt": "10000",
        "pchs_amt_smtl_amt": "350000",
        "thdt_tlex_amt": "150",
    }


def _balance_response_sample() -> dict[str, object]:
    return {
        **_ENVELOPE_OK,
        "output1": [_balance_item_sample()],
        "output2": [_balance_summary_sample()],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


def _price_output_sample() -> dict[str, object]:
    return {
        "stck_prpr": "70000",
        "stck_oprc": "69500",
        "stck_hgpr": "70500",
        "stck_lwpr": "69000",
        "acml_vol": "12345678",
        "stck_sdpr": "69000",
        "prdy_vrss": "1000",
        "prdy_ctrt": "1.45",
    }


def _price_response_sample() -> dict[str, object]:
    return {**_ENVELOPE_OK, "output": _price_output_sample()}


def _daily_item_sample() -> dict[str, object]:
    return {
        "stck_bsop_date": "20260521",
        "stck_oprc": "69500",
        "stck_hgpr": "70500",
        "stck_lwpr": "69000",
        "stck_clpr": "70000",
        "acml_vol": "12345678",
    }


def _daily_response_sample() -> dict[str, object]:
    return {
        **_ENVELOPE_OK,
        "output1": {"hts_kor_isnm": "KODEX 200"},  # unmodeled summary block
        "output2": [_daily_item_sample()],
    }


def _order_output_sample_lower() -> dict[str, object]:
    return {
        "krx_fwdg_ord_orgno": "00950",
        "odno": "0000117057",
        "ord_tmd": "121052",
    }


def _order_output_sample_upper() -> dict[str, object]:
    return {
        "KRX_FWDG_ORD_ORGNO": "00950",
        "ODNO": "0000117057",
        "ORD_TMD": "121052",
    }


def _order_response_sample() -> dict[str, object]:
    return {**_ENVELOPE_OK, "output": _order_output_sample_upper()}


def _ccld_item_sample() -> dict[str, object]:
    return {
        "odno": "0000117057",
        "orgn_odno": "0000000000",
        "ord_qty": "10",
        "tot_ccld_qty": "10",
        "rmn_qty": "0",
        "avg_prvs": "35000",
        "cncl_yn": "N",
        "rjct_qty": "0",
        "pdno": "069500",
        "sll_buy_dvsn_cd": "02",
        "ord_dvsn_cd": "00",
    }


def _ccld_response_sample() -> dict[str, object]:
    return {
        **_ENVELOPE_OK,
        "output1": [_ccld_item_sample()],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


# ---------------------------------------------------------------------------
# 1. Each response model parses its documented sample (is_ok True)
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationParsing:
    def test_kis_api_schema_validation_token_parses(self) -> None:
        m = KISTokenResponse.model_validate(_token_sample())
        assert m.access_token == "eyJ0eXAiOiJKV1QiL..."
        assert m.access_token_token_expired == "2026-05-23 09:00:00"
        assert m.token_type == "Bearer"
        assert m.expires_in == Decimal("86400")

    def test_kis_api_schema_validation_token_expires_in_optional(self) -> None:
        sample = _token_sample()
        del sample["expires_in"]
        m = KISTokenResponse.model_validate(sample)
        assert m.expires_in is None

    def test_kis_api_schema_validation_balance_parses(self) -> None:
        m = KISBalanceResponse.model_validate(_balance_response_sample())
        assert m.is_ok is True
        assert len(m.output1) == 1
        assert len(m.output2) == 1
        assert m.output1[0].pdno == "069500"
        assert m.output2[0].dnca_tot_amt == Decimal("5000000")
        assert m.ctx_area_fk100 == ""

    def test_kis_api_schema_validation_price_parses(self) -> None:
        m = KISPriceResponse.model_validate(_price_response_sample())
        assert m.is_ok is True
        assert m.output.stck_prpr == Decimal("70000")
        assert m.output.stck_sdpr == Decimal("69000")

    def test_kis_api_schema_validation_daily_parses(self) -> None:
        m = KISDailyPriceResponse.model_validate(_daily_response_sample())
        assert m.is_ok is True
        assert len(m.output2) == 1
        assert m.output2[0].stck_bsop_date == "20260521"
        assert m.output2[0].stck_clpr == Decimal("70000")

    def test_kis_api_schema_validation_order_parses(self) -> None:
        m = KISOrderResponse.model_validate(_order_response_sample())
        assert m.is_ok is True
        assert m.output.odno == "0000117057"
        assert m.output.ord_tmd == "121052"

    def test_kis_api_schema_validation_ccld_parses(self) -> None:
        m = KISCcldResponse.model_validate(_ccld_response_sample())
        assert m.is_ok is True
        assert len(m.output1) == 1
        assert m.output1[0].odno == "0000117057"
        assert m.output1[0].ord_qty == Decimal("10")

    def test_kis_api_schema_validation_is_ok_false_when_error(self) -> None:
        sample = _price_response_sample()
        sample["rt_cd"] = "1"
        m = KISPriceResponse.model_validate(sample)
        assert m.is_ok is False


# ---------------------------------------------------------------------------
# 2. Decimal coercion: str→Decimal, asserts type is Decimal (not float)
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationDecimalCoercion:
    def test_kis_api_schema_validation_str_coerces_to_decimal(self) -> None:
        item = KISBalanceItem.model_validate(_balance_item_sample())
        assert item.prpr == Decimal("36000")
        assert isinstance(item.prpr, Decimal)

    def test_kis_api_schema_validation_coerced_value_is_not_float(self) -> None:
        out = KISPriceOutput.model_validate(_price_output_sample())
        # Every numeric field must be Decimal, never float.
        for name in (
            "stck_prpr",
            "stck_oprc",
            "stck_hgpr",
            "stck_lwpr",
            "acml_vol",
            "stck_sdpr",
            "prdy_vrss",
            "prdy_ctrt",
        ):
            value = getattr(out, name)
            assert isinstance(value, Decimal)
            assert not isinstance(value, float)

    def test_kis_api_schema_validation_summary_all_decimal(self) -> None:
        summ = KISBalanceSummary.model_validate(_balance_summary_sample())
        assert isinstance(summ.thdt_tlex_amt, Decimal)
        assert summ.thdt_tlex_amt == Decimal("150")

    def test_kis_api_schema_validation_decimal_precision_preserved(self) -> None:
        item = KISBalanceItem.model_validate(_balance_item_sample())
        # 2.86 must round-trip exactly via str path (no IEEE-754 artefact).
        assert item.evlu_pfls_rt == Decimal("2.86")


# ---------------------------------------------------------------------------
# 3. bool input rejected
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationBoolRejected:
    def test_kis_api_schema_validation_bool_in_numeric_raises(self) -> None:
        sample = _balance_item_sample()
        sample["hldg_qty"] = True
        with pytest.raises(ValidationError):
            KISBalanceItem.model_validate(sample)

    def test_kis_api_schema_validation_bool_in_price_raises(self) -> None:
        sample = _price_output_sample()
        sample["stck_prpr"] = False
        with pytest.raises(ValidationError):
            KISPriceOutput.model_validate(sample)


# ---------------------------------------------------------------------------
# 4. Required numeric field empty string "" → raise (silent None forbidden)
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationEmptyStringRejected:
    def test_kis_api_schema_validation_empty_price_raises(self) -> None:
        sample = _price_output_sample()
        sample["stck_prpr"] = ""
        with pytest.raises(ValidationError):
            KISPriceOutput.model_validate(sample)

    def test_kis_api_schema_validation_empty_qty_raises(self) -> None:
        sample = _balance_item_sample()
        sample["hldg_qty"] = ""
        with pytest.raises(ValidationError):
            KISBalanceItem.model_validate(sample)

    def test_kis_api_schema_validation_empty_ccld_qty_raises(self) -> None:
        sample = _ccld_item_sample()
        sample["tot_ccld_qty"] = ""
        with pytest.raises(ValidationError):
            KISCcldItem.model_validate(sample)


# ---------------------------------------------------------------------------
# 5. Extra unmodeled fields ignored (additive harmless — ADR 0012 §1.6 #4)
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationExtraIgnored:
    def test_kis_api_schema_validation_extra_field_on_item_ignored(self) -> None:
        sample = _balance_item_sample()
        sample["kis_brand_new_field"] = "whatever"
        item = KISBalanceItem.model_validate(sample)
        assert item.pdno == "069500"
        assert not hasattr(item, "kis_brand_new_field")

    def test_kis_api_schema_validation_extra_field_on_envelope_ignored(
        self,
    ) -> None:
        sample = _price_response_sample()
        sample["future_kis_meta"] = {"nested": "value"}
        m = KISPriceResponse.model_validate(sample)
        assert m.is_ok is True

    def test_kis_api_schema_validation_daily_output1_summary_ignored(self) -> None:
        # output1 summary block is unmodeled; extra='ignore' absorbs it.
        m = KISDailyPriceResponse.model_validate(_daily_response_sample())
        assert len(m.output2) == 1


# ---------------------------------------------------------------------------
# 6. Required field missing → raise (breaking change detected — §1.6 #4)
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationRequiredMissing:
    def test_kis_api_schema_validation_missing_price_field_raises(self) -> None:
        sample = _price_output_sample()
        del sample["stck_prpr"]
        with pytest.raises(ValidationError):
            KISPriceOutput.model_validate(sample)

    def test_kis_api_schema_validation_missing_envelope_field_raises(self) -> None:
        sample = _price_response_sample()
        del sample["rt_cd"]
        with pytest.raises(ValidationError):
            KISPriceResponse.model_validate(sample)

    def test_kis_api_schema_validation_missing_required_id_raises(self) -> None:
        sample = _balance_item_sample()
        del sample["pdno"]
        with pytest.raises(ValidationError):
            KISBalanceItem.model_validate(sample)


# ---------------------------------------------------------------------------
# 7. Uppercase alias + lowercase both parse for KISOrderOutput
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationOrderAlias:
    def test_kis_api_schema_validation_order_lowercase_parses(self) -> None:
        out = KISOrderOutput.model_validate(_order_output_sample_lower())
        assert out.odno == "0000117057"
        assert out.krx_fwdg_ord_orgno == "00950"
        assert out.ord_tmd == "121052"

    def test_kis_api_schema_validation_order_uppercase_parses(self) -> None:
        out = KISOrderOutput.model_validate(_order_output_sample_upper())
        assert out.odno == "0000117057"
        assert out.krx_fwdg_ord_orgno == "00950"
        assert out.ord_tmd == "121052"


# ---------------------------------------------------------------------------
# 8. KISCcldItem partial-fill properties: full / partial / none
# ---------------------------------------------------------------------------
class TestKisApiSchemaValidationCcldFillProperties:
    def test_kis_api_schema_validation_fully_filled(self) -> None:
        sample = _ccld_item_sample()
        sample["ord_qty"] = "10"
        sample["tot_ccld_qty"] = "10"
        item = KISCcldItem.model_validate(sample)
        assert item.is_fully_filled is True
        assert item.is_partial is False

    def test_kis_api_schema_validation_partial_fill(self) -> None:
        sample = _ccld_item_sample()
        sample["ord_qty"] = "10"
        sample["tot_ccld_qty"] = "4"
        item = KISCcldItem.model_validate(sample)
        assert item.is_fully_filled is False
        assert item.is_partial is True

    def test_kis_api_schema_validation_no_fill(self) -> None:
        sample = _ccld_item_sample()
        sample["ord_qty"] = "10"
        sample["tot_ccld_qty"] = "0"
        item = KISCcldItem.model_validate(sample)
        assert item.is_fully_filled is False
        assert item.is_partial is False
