"""Tests for CSV market data loader (ADR §10.2)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from src.domain.models import Asset, AssetClass, Currency, Exchange, Market
from src.infrastructure.csv_market_data_loader import load_ohlcv_csv

if TYPE_CHECKING:
    from pathlib import Path


def _asset() -> Asset:
    return Asset(
        code="069500",
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "ohlcv.csv"
    p.write_text(content)
    return p


HEADER = "date,open,high,low,close,volume\n"


class TestHappyPath:
    def test_loads_three_bars_sorted(self, tmp_path):
        # Provide rows out of order to verify the loader sorts ascending.
        csv = _write(
            tmp_path,
            HEADER
            + "2026-01-07,35200,35300,35100,35200,2000000\n"
            + "2026-01-05,35000,35100,34900,35050,1234567\n"
            + "2026-01-06,35050,35200,35000,35150,1500000\n",
        )
        bars = load_ohlcv_csv(csv, _asset())
        assert [b.trade_date for b in bars] == [
            date(2026, 1, 5),
            date(2026, 1, 6),
            date(2026, 1, 7),
        ]
        assert bars[0].close == Decimal("35050")
        assert bars[1].volume == Decimal("1500000")

    def test_empty_file_returns_empty_list(self, tmp_path):
        csv = _write(tmp_path, "")
        assert load_ohlcv_csv(csv, _asset()) == []

    def test_header_only_returns_empty_list(self, tmp_path):
        csv = _write(tmp_path, HEADER)
        assert load_ohlcv_csv(csv, _asset()) == []

    def test_decimal_precision_preserved(self, tmp_path):
        csv = _write(tmp_path, HEADER + "2026-01-05,35000.50,35100.75,34900.25,35050.10,1000\n")
        bars = load_ohlcv_csv(csv, _asset())
        assert bars[0].close == Decimal("35050.10")


class TestValidation:
    def test_missing_required_column_raises(self, tmp_path):
        # Drop the volume column.
        csv = _write(
            tmp_path,
            "date,open,high,low,close\n2026-01-05,35000,35100,34900,35050\n",
        )
        with pytest.raises(ValueError, match="missing required columns"):
            load_ohlcv_csv(csv, _asset())

    def test_duplicate_trade_date_raises(self, tmp_path):
        csv = _write(
            tmp_path,
            HEADER
            + "2026-01-05,35000,35100,34900,35050,1000\n"
            + "2026-01-05,35100,35200,35000,35150,1000\n",
        )
        with pytest.raises(ValueError, match="duplicate trade_date"):
            load_ohlcv_csv(csv, _asset())

    def test_bad_date_raises(self, tmp_path):
        csv = _write(
            tmp_path,
            HEADER + "2026/01/05,35000,35100,34900,35050,1000\n",
        )
        with pytest.raises(ValueError, match="bad date"):
            load_ohlcv_csv(csv, _asset())

    def test_bad_numeric_raises(self, tmp_path):
        csv = _write(
            tmp_path,
            HEADER + "2026-01-05,oops,35100,34900,35050,1000\n",
        )
        with pytest.raises(ValueError, match="bad numeric value"):
            load_ohlcv_csv(csv, _asset())

    def test_ohlc_inconsistency_propagates_validation_error(self, tmp_path):
        # high (34000) < low (35000) — caught by OHLCV model_validator.
        csv = _write(
            tmp_path,
            HEADER + "2026-01-05,35000,34000,34900,35050,1000\n",
        )
        with pytest.raises(ValidationError):
            load_ohlcv_csv(csv, _asset())

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_ohlcv_csv(tmp_path / "nope.csv", _asset())
