"""Unit tests for src.infrastructure.asset_csv.

Phase 0.9 — sub-step 0.9.e (ADR 0005 §1.7 + §3 합병 박제 후속).
Pure logic — derive_csv_path + validate_asset_for_window.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.domain.models import Asset, AssetClass, Currency, Exchange, Market
from src.infrastructure.asset_csv import (
    derive_csv_path,
    validate_asset_for_window,
)


def _asset(
    *,
    code: str = "069500",
    asset_class: AssetClass = AssetClass.KR_ETF,
    listed_at: date = date(2002, 10, 14),
    delisted_at: date | None = None,
    tick_size: Decimal = Decimal("5"),
) -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=asset_class,
        currency=Currency.KRW,
        name="X",
        tick_size=tick_size,
        lot_size=Decimal("1"),
        listed_at=listed_at,
        delisted_at=delisted_at,
    )


class TestDeriveCsvPath:
    """Phase 0.7.x convention — KRX_{code}_{start_year}-{end_year}.csv."""

    def test_canonical_phase_0_7_3_format(self):
        p = derive_csv_path("069500", date(2019, 1, 2), date(2024, 12, 30))
        assert p == Path("data/historical/KRX_069500_2019-2024.csv")

    def test_kr_stock_format(self):
        p = derive_csv_path("005930", date(2019, 1, 2), date(2024, 12, 30))
        assert p == Path("data/historical/KRX_005930_2019-2024.csv")

    def test_same_year_window(self):
        p = derive_csv_path("069500", date(2024, 1, 2), date(2024, 12, 30))
        assert p == Path("data/historical/KRX_069500_2024-2024.csv")

    def test_custom_base_dir(self):
        p = derive_csv_path(
            "069500",
            date(2019, 1, 2),
            date(2024, 12, 30),
            base_dir="/tmp/historical",
        )
        assert p == Path("/tmp/historical/KRX_069500_2019-2024.csv")

    def test_returns_path_type(self):
        result = derive_csv_path(
            "069500", date(2019, 1, 2), date(2024, 12, 30)
        )
        assert isinstance(result, Path)


class TestValidateAssetForWindow:
    """Phase 0.9 (ADR 0005 §1.7.2 박제) — listed_at + delisted_at 검증."""

    def test_window_inside_listing_passes(self):
        # 069500 listed 2002-10-14, no delisting → window 2019~2024 OK.
        a = _asset()
        validate_asset_for_window(a, date(2019, 1, 2), date(2024, 12, 30))

    def test_start_equals_listed_at_passes(self):
        a = _asset(listed_at=date(2019, 1, 2))
        validate_asset_for_window(a, date(2019, 1, 2), date(2024, 12, 30))

    def test_start_before_listed_at_rejected(self):
        a = _asset(listed_at=date(2019, 7, 19))  # mimics 329200 부동산 ETF
        with pytest.raises(ValueError, match="listed_at"):
            validate_asset_for_window(
                a, date(2019, 1, 2), date(2024, 12, 30)
            )

    def test_delisted_during_window_rejected(self):
        a = _asset(
            listed_at=date(2002, 10, 14),
            delisted_at=date(2024, 6, 30),
        )
        with pytest.raises(ValueError, match="delisted_at"):
            validate_asset_for_window(
                a, date(2019, 1, 2), date(2024, 12, 30)
            )

    def test_delisted_at_window_end_boundary_rejected(self):
        # delisted_at <= end → reject (boundary).
        a = _asset(
            listed_at=date(2002, 10, 14),
            delisted_at=date(2024, 12, 30),
        )
        with pytest.raises(ValueError, match="delisted_at"):
            validate_asset_for_window(
                a, date(2019, 1, 2), date(2024, 12, 30)
            )

    def test_delisted_after_window_passes(self):
        a = _asset(
            listed_at=date(2002, 10, 14),
            delisted_at=date(2025, 1, 1),
        )
        validate_asset_for_window(a, date(2019, 1, 2), date(2024, 12, 30))

    def test_no_delisted_passes(self):
        a = _asset()  # delisted_at None
        validate_asset_for_window(a, date(2019, 1, 2), date(2024, 12, 30))

    def test_inverted_window_rejected(self):
        a = _asset()
        with pytest.raises(ValueError, match="must be <= end"):
            validate_asset_for_window(
                a, date(2024, 12, 30), date(2019, 1, 2)
            )

    def test_phase_0_9_assets_all_valid_for_5_year_window(self):
        """ADR 0005 §1.6.2 박제 5 종 — 2019-01-02 ~ 2024-12-30 윈도우 통과 검증.

        listed_at < 2019 인 종목만 통과 (sub-step 0.9.c 사전 검증 정합).
        """
        start = date(2019, 1, 2)
        end = date(2024, 12, 30)
        for code, listed_at in (
            ("005930", date(1975, 6, 11)),
            ("005380", date(1974, 6, 28)),
            ("055550", date(2001, 9, 10)),
            ("097950", date(2007, 9, 19)),
            ("015760", date(1989, 8, 10)),
        ):
            a = _asset(
                code=code,
                asset_class=AssetClass.KR_STOCK,
                listed_at=listed_at,
                tick_size=Decimal("1"),
            )
            validate_asset_for_window(a, start, end)
