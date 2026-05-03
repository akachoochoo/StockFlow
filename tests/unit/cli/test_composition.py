"""Unit tests for src.cli.composition — asset registry (Phase 0.7.1)."""
from __future__ import annotations

import pytest

from src.cli.composition import asset_from_code, kodex200, kodex_short_bond_plus
from src.domain.models import AssetClass, Currency, Exchange


class TestAssetFromCode:
    def test_kodex200_registered(self):
        asset = asset_from_code("069500")
        assert asset.code == "069500"
        assert asset.exchange is Exchange.KRX
        assert asset.asset_class is AssetClass.KR_ETF
        assert asset.currency is Currency.KRW
        assert asset.name == "KODEX 200"

    def test_kodex200_factory_matches_direct(self):
        assert asset_from_code("069500") == kodex200()

    def test_kodex_short_bond_plus_registered(self):
        asset = asset_from_code("214980")
        assert asset.code == "214980"
        assert asset.exchange is Exchange.KRX
        assert asset.asset_class is AssetClass.KR_ETF
        assert asset.currency is Currency.KRW
        assert asset.name == "KODEX 단기채권 PLUS"

    def test_kodex_short_bond_plus_factory_matches_direct(self):
        assert asset_from_code("214980") == kodex_short_bond_plus()

    def test_unknown_code_raises_key_error(self):
        with pytest.raises(KeyError) as exc_info:
            asset_from_code("999999")
        msg = str(exc_info.value)
        # Error message must name the unknown code and list supported codes.
        assert "999999" in msg
        assert "069500" in msg
        assert "214980" in msg
