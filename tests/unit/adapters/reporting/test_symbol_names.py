"""Unit tests for src.adapters.reporting.symbol_names (Phase 0.10.h)."""
from __future__ import annotations

from src.adapters.reporting.symbol_names import SYMBOL_NAMES, display_symbol


class TestDisplaySymbolDefault:
    def test_known_kr_stock(self):
        assert display_symbol("005930") == "005930 삼성전자"

    def test_known_kr_etf(self):
        assert display_symbol("069500") == "069500 KODEX 200"

    def test_unknown_falls_back_to_code(self):
        assert display_symbol("999999") == "999999"

    def test_phase_0_9_2_five_symbols_all_present(self):
        for code in ("005930", "005380", "055550", "097950", "015760"):
            assert code in SYMBOL_NAMES, f"missing {code}"

    def test_phase_0_7_etfs_all_present(self):
        for code in ("069500", "132030", "214980"):
            assert code in SYMBOL_NAMES, f"missing {code}"


class TestDisplaySymbolInjected:
    def test_custom_mapping_used(self):
        names = {"AAA": "Acme Corp"}
        assert display_symbol("AAA", names) == "AAA Acme Corp"

    def test_custom_mapping_unknown_falls_back(self):
        names = {"AAA": "Acme Corp"}
        assert display_symbol("BBB", names) == "BBB"

    def test_empty_mapping_falls_back(self):
        # Explicit empty dict — overrides default; ALL codes fall back
        assert display_symbol("005930", {}) == "005930"

    def test_none_uses_default_mapping(self):
        # None override = use module-level SYMBOL_NAMES
        assert display_symbol("005930", None) == "005930 삼성전자"
