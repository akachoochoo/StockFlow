"""Tests for src.infrastructure.yaml_asset_loader (Phase 1.1 data-driven).

Each scenario writes an assets YAML temp file and asserts the loader output
or its raised error. Strict / extra='forbid' schema means a typo or unknown
key surfaces here, not silently downstream — mirrors the strategy loader.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from src.domain.models import AssetClass, Currency, Exchange, Market
from src.infrastructure.yaml_asset_loader import load_asset_registry


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "assets.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_FULL = """\
version: "1.0"
assets:
  "035720":
    name: "카카오"
    market: KOSPI
    asset_class: KR_STOCK
    tick_size: 1
    lot_size: 1
    listed_at: 2017-07-10
"""


class TestHappyPath:
    def test_load_full_entry(self, tmp_path: Path):
        reg = load_asset_registry(_write(tmp_path, _FULL))
        assert list(reg) == ["035720"]
        a = reg["035720"]
        assert a.code == "035720"
        assert a.name == "카카오"
        assert a.market is Market.KOSPI
        assert a.asset_class is AssetClass.KR_STOCK
        assert a.exchange is Exchange.KRX  # defaulted
        assert a.currency is Currency.KRW  # defaulted
        assert a.tick_size == Decimal("1")
        assert a.lot_size == Decimal("1")
        assert a.listed_at == date(2017, 7, 10)
        assert a.delisted_at is None

    def test_default_tick_etf(self, tmp_path: Path):
        body = (
            'version: "1.0"\n'
            "assets:\n"
            '  "069500":\n'
            '    name: "KODEX 200"\n'
            "    market: KOSPI\n"
            "    asset_class: KR_ETF\n"
            "    listed_at: 2002-10-14\n"
        )
        a = load_asset_registry(_write(tmp_path, body))["069500"]
        assert a.tick_size == Decimal("5")  # ETF default

    def test_default_tick_stock(self, tmp_path: Path):
        body = (
            'version: "1.0"\n'
            "assets:\n"
            '  "005930":\n'
            '    name: "삼성전자"\n'
            "    market: KOSPI\n"
            "    asset_class: KR_STOCK\n"
            "    listed_at: 1975-06-11\n"
        )
        a = load_asset_registry(_write(tmp_path, body))["005930"]
        assert a.tick_size == Decimal("1")  # KR_STOCK default

    def test_kosdaq_and_delisted(self, tmp_path: Path):
        body = (
            'version: "1.0"\n'
            "assets:\n"
            '  "247540":\n'
            '    name: "에코프로비엠"\n'
            "    market: KOSDAQ\n"
            "    asset_class: KR_STOCK\n"
            "    listed_at: 2019-03-05\n"
            "    delisted_at: 2030-01-01\n"
        )
        a = load_asset_registry(_write(tmp_path, body))["247540"]
        assert a.market is Market.KOSDAQ
        assert a.delisted_at == date(2030, 1, 1)


class TestEmptyAndMissing:
    def test_empty_assets_map(self, tmp_path: Path):
        assert load_asset_registry(_write(tmp_path, 'version: "1.0"\nassets: {}\n')) == {}

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert load_asset_registry(tmp_path / "nope.yaml") == {}

    def test_empty_file_returns_empty(self, tmp_path: Path):
        assert load_asset_registry(_write(tmp_path, "")) == {}


class TestValidation:
    def test_unknown_key_rejected(self, tmp_path: Path):
        body = (
            'version: "1.0"\n'
            "assets:\n"
            '  "035720":\n'
            '    name: "카카오"\n'
            "    market: KOSPI\n"
            "    asset_class: KR_STOCK\n"
            "    listed_at: 2017-07-10\n"
            "    typo_field: 1\n"
        )
        with pytest.raises(ValidationError):
            load_asset_registry(_write(tmp_path, body))

    def test_bad_market_rejected(self, tmp_path: Path):
        body = (
            'version: "1.0"\n'
            "assets:\n"
            '  "035720":\n'
            '    name: "카카오"\n'
            "    market: NASDAQ\n"
            "    asset_class: KR_STOCK\n"
            "    listed_at: 2017-07-10\n"
        )
        with pytest.raises(ValidationError):
            load_asset_registry(_write(tmp_path, body))

    def test_missing_listed_at_rejected(self, tmp_path: Path):
        body = (
            'version: "1.0"\n'
            "assets:\n"
            '  "035720":\n'
            '    name: "카카오"\n'
            "    market: KOSPI\n"
            "    asset_class: KR_STOCK\n"
        )
        with pytest.raises(ValidationError):
            load_asset_registry(_write(tmp_path, body))

    def test_bad_version_rejected(self, tmp_path: Path):
        with pytest.raises(ValidationError):
            load_asset_registry(_write(tmp_path, 'version: "9.9"\nassets: {}\n'))

    def test_non_mapping_root_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError):
            load_asset_registry(_write(tmp_path, "- a\n- b\n"))
