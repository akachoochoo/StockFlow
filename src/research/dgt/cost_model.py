"""Phase 0.11.a — KoreanMarketCostModel (KRX 마찰비용 모델).

ADR 0007 §1.3 (D7/D8 defaults) + §1.8 § Sensitivity + §1.10 AC1~AC6 +
§2 (KRX 표 + floor 정합 정정).

Decimal-only (CLAUDE.md §2.1, §2.3 — float 절대 금지). Asset.round_to_tick
호출은 outer→inner read OK (Architect Round 1 (ii), 5th ring → domain).
Registry 미등록 — DGTStrategy 가 buy+sell 동시 strategy 라 §16.1.4 단일
sell strategy 가정 보존을 위해 create_buy_strategy / sell 등록 zero (R5).

Underscore-prefix private export (ADR 0007 §1.6.3). `from src.research.dgt
import *` 는 zero 노출.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.domain.models import Asset, AssetClass


@dataclass(frozen=True)
class _BuyCost:
    """Buy 결과 — gross + commission. tax 는 항상 Decimal('0') (한국 규정)."""

    rounded_price: Decimal
    quantity: Decimal
    gross: Decimal
    commission: Decimal
    tax: Decimal
    total_cost: Decimal


@dataclass(frozen=True)
class _SellCost:
    """Sell 결과 — gross - tax - commission = net_proceeds."""

    rounded_price: Decimal
    quantity: Decimal
    gross: Decimal
    commission: Decimal
    tax: Decimal
    net_proceeds: Decimal


@dataclass(frozen=True)
class _KoreanMarketCostModel:
    """KRX 마찰비용 (위탁수수료 + 거래세) + tick rounding (floor).

    Defaults (ADR 0007 §1.3 박제):
        - commission_rate = 0.015% (양방, 위탁수수료)
        - etf_tax_rate    = 0.18%  (매도 only, KR_ETF)
        - stock_tax_rate  = 0.15%  (매도 only, KR_STOCK — D8 default, 2025 인하 반영)
        - 매수 거래세 = 항상 0 (한국 규정)

    Tick rounding (ADR 0007 §2.2):
        - Asset.round_to_tick(price) = (price // tick) * tick = floor.
        - KR_ETF: 단일 tick_size (069500 = 5원, Phase 0.10.bb 박제).
        - KR_STOCK: 가격대별 동적 (src/domain/tick_size.py:18-57, 2023~ KRX 7-band).

    Sensitivity (ADR 0007 §1.8 + §2): D7 (tick 표) / D8 (거래세 rate) 변경
    시 본 모듈 의 default 갱신 + tests/research/test_cost_model.py
    (AC1~AC6) 재실행 의무 + 0.11.a.5 회고 시 KRX 출처 URL/문서 버전 박제.
    """

    commission_rate: Decimal = Decimal("0.00015")
    etf_tax_rate: Decimal = Decimal("0.0018")
    stock_tax_rate: Decimal = Decimal("0.0015")

    def compute_buy_cost(
        self,
        price: Decimal,
        quantity: Decimal,
        asset: Asset,
    ) -> _BuyCost:
        """매수 비용 계산. tax 는 0, commission 은 gross × rate."""
        rounded = self._round_price(price, asset)
        gross = rounded * quantity
        commission = gross * self.commission_rate
        return _BuyCost(
            rounded_price=rounded,
            quantity=quantity,
            gross=gross,
            commission=commission,
            tax=Decimal("0"),
            total_cost=gross + commission,
        )

    def compute_sell_cost(
        self,
        price: Decimal,
        quantity: Decimal,
        asset: Asset,
    ) -> _SellCost:
        """매도 비용 계산. tax = gross × asset-class별 rate, commission = gross × rate."""
        rounded = self._round_price(price, asset)
        gross = rounded * quantity
        tax = gross * self._tax_rate(asset)
        commission = gross * self.commission_rate
        return _SellCost(
            rounded_price=rounded,
            quantity=quantity,
            gross=gross,
            commission=commission,
            tax=tax,
            net_proceeds=gross - tax - commission,
        )

    def _round_price(self, price: Decimal, asset: Asset) -> Decimal:
        return asset.round_to_tick(price)

    def _tax_rate(self, asset: Asset) -> Decimal:
        if asset.asset_class is AssetClass.KR_STOCK:
            return self.stock_tax_rate
        return self.etf_tax_rate
