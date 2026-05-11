"""Phase 0.11.a — KoreanMarketCostModel tests (AC1~AC6).

ADR 0007 §1.10 oracle + §2 (정정) 박제. Decimal tolerance = `Decimal("0.0001")`.

- AC1: compute_buy_cost Decimal 정확성 (거래세=0, 수수료=0.015%).
- AC2: compute_sell_cost 거래세 적용 (KR_ETF 0.18%).
- AC3: compute_sell_cost KR_STOCK 거래세 (D8 default 0.15%, §2.3 정정 반영).
- AC4: 매수 시 거래세 0 invariant (양 asset class).
- AC5: float 금지 grep (CLAUDE.md §2.1 / §2.3).
- AC6: Asset.round_to_tick floor 5 cases enum (§2.2 정정 반영).
"""
from __future__ import annotations

import inspect
from decimal import Decimal

from src.domain.models import Asset
from src.research.dgt.cost_model import _KoreanMarketCostModel


_TOL = Decimal("0.0001")


# ---------------------------------------------------------------------------
# AC1: compute_buy_cost Decimal 정확성
# ---------------------------------------------------------------------------


class TestAC1BuyCost:
    def test_kr_etf_buy_cost_decimal_exact(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_etf_069500: Asset,
    ) -> None:
        # price=100_000 (tick=5 정합), quantity=10
        # gross       = 100_000 * 10 = 1_000_000
        # commission  = 1_000_000 * 0.00015 = 150
        # tax         = 0 (buy)
        # total_cost  = 1_000_000 + 150 = 1_000_150
        result = cost_model.compute_buy_cost(
            price=Decimal("100000"),
            quantity=Decimal("10"),
            asset=kr_etf_069500,
        )
        assert abs(result.total_cost - Decimal("1000150")) < _TOL
        assert result.tax == Decimal("0")
        assert abs(result.commission - Decimal("150")) < _TOL
        assert result.rounded_price == Decimal("100000")
        assert result.gross == Decimal("1000000")


# ---------------------------------------------------------------------------
# AC2: compute_sell_cost 거래세 적용 (KR_ETF 0.18%)
# ---------------------------------------------------------------------------


class TestAC2SellCostKrEtf:
    def test_kr_etf_sell_cost_etf_tax(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_etf_069500: Asset,
    ) -> None:
        # gross       = 1_000_000
        # tax (ETF)   = 1_000_000 * 0.0018 = 1_800
        # commission  = 1_000_000 * 0.00015 = 150
        # net         = 1_000_000 - 1_800 - 150 = 998_050
        result = cost_model.compute_sell_cost(
            price=Decimal("100000"),
            quantity=Decimal("10"),
            asset=kr_etf_069500,
        )
        assert abs(result.net_proceeds - Decimal("998050")) < _TOL
        assert abs(result.tax - Decimal("1800")) < _TOL
        assert abs(result.commission - Decimal("150")) < _TOL


# ---------------------------------------------------------------------------
# AC3: KR_STOCK sell tax (D8 default 0.15%, §2.3 정정 반영)
# ---------------------------------------------------------------------------


class TestAC3SellCostKrStock:
    def test_kr_stock_sell_cost_d8_default_0_15(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_stock_005930: Asset,
    ) -> None:
        # price=50_000 → 50_000~100_000 가격대 tick=100 → floor 50_000
        # gross       = 50_000 * 100 = 5_000_000
        # tax (STOCK) = 5_000_000 * 0.0015 = 7_500 (D8 default 0.15%)
        # commission  = 5_000_000 * 0.00015 = 750
        result = cost_model.compute_sell_cost(
            price=Decimal("50000"),
            quantity=Decimal("100"),
            asset=kr_stock_005930,
        )
        assert result.rounded_price == Decimal("50000")
        assert abs(result.tax - Decimal("7500")) < _TOL
        assert abs(result.commission - Decimal("750")) < _TOL


# ---------------------------------------------------------------------------
# AC4: 매수 시 거래세 0 invariant (양 asset class)
# ---------------------------------------------------------------------------


class TestAC4BuyTaxZero:
    def test_kr_etf_buy_tax_zero(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_etf_069500: Asset,
    ) -> None:
        result = cost_model.compute_buy_cost(
            price=Decimal("100000"),
            quantity=Decimal("10"),
            asset=kr_etf_069500,
        )
        assert result.tax == Decimal("0")

    def test_kr_stock_buy_tax_zero(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_stock_005930: Asset,
    ) -> None:
        result = cost_model.compute_buy_cost(
            price=Decimal("50000"),
            quantity=Decimal("100"),
            asset=kr_stock_005930,
        )
        assert result.tax == Decimal("0")


# ---------------------------------------------------------------------------
# AC5: Decimal precision invariant (float 금지, CLAUDE.md §2.1 / §2.3)
# ---------------------------------------------------------------------------


class TestAC5NoFloat:
    def test_cost_model_source_has_no_float(self) -> None:
        from src.research.dgt import cost_model as module

        src = inspect.getsource(module)
        assert "float(" not in src, "float() 사용 금지 (CLAUDE.md §2.3)"
        # 타입 힌트 ": float" 검사 — docstring/comment 라인 제외
        in_docstring = False
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                in_docstring = not in_docstring if stripped.count('"""') == 1 else in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            assert ": float" not in line, f"float 타입 힌트 금지: {line!r}"


# ---------------------------------------------------------------------------
# AC6: Asset.round_to_tick floor 5 cases enum (§2.2 정정 반영)
# ---------------------------------------------------------------------------


class TestAC6RoundToTickFloor:
    """Asset.round_to_tick(price) = (price // tick) * tick — floor.
    Round-to-nearest 아님. CLAUDE.md §4.2 "지정가 conservatism" 정신.
    """

    def test_kr_etf_tick_5_floor_100003(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_etf_069500: Asset,
    ) -> None:
        # KR_ETF tick=5, floor 100003 → 100000 (NOT 100005)
        assert (
            cost_model._round_price(Decimal("100003"), kr_etf_069500)
            == Decimal("100000")
        )

    def test_kr_stock_lt_1000_tick_1(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_stock_005930: Asset,
    ) -> None:
        # KR_STOCK <1000원 가격대 tick=1: 999 → 999 (identity)
        assert (
            cost_model._round_price(Decimal("999"), kr_stock_005930)
            == Decimal("999")
        )

    def test_kr_stock_1k_5k_tick_5(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_stock_005930: Asset,
    ) -> None:
        # 1000~5000원 tick=5: 1234 → 1230 (floor)
        assert (
            cost_model._round_price(Decimal("1234"), kr_stock_005930)
            == Decimal("1230")
        )

    def test_kr_stock_5k_10k_tick_10(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_stock_005930: Asset,
    ) -> None:
        # 5000~10000원 tick=10: 7891 → 7890 (floor)
        assert (
            cost_model._round_price(Decimal("7891"), kr_stock_005930)
            == Decimal("7890")
        )

    def test_kr_stock_10k_50k_tick_50(
        self,
        cost_model: _KoreanMarketCostModel,
        kr_stock_005930: Asset,
    ) -> None:
        # 10000~50000원 tick=50: 15678 → 15650 (floor)
        assert (
            cost_model._round_price(Decimal("15678"), kr_stock_005930)
            == Decimal("15650")
        )
