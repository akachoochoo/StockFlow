"""KR market trading cost model — 위탁수수료 + 거래세 (Phase 1.x, ADR 0022 G1).

`src/research/dgt/cost_model.py` 의 ``_KoreanMarketCostModel`` 을 inner ring 으로
**충실 포팅** (research → domain 승격). GridRunner(backtest/paper 엔진) 가 그리드
체결에 마찰비용을 적용한다. 순수 Decimal, 외부 import 0, 시계 0.

요율 (ADR 0007 §1.3 박제):
- commission_rate = 0.015% (양방, 위탁수수료)
- etf_tax_rate    = 0.18%  (매도 only, KR_ETF)
- stock_tax_rate  = 0.15%  (매도 only, KR_STOCK)
- 매수 거래세 = 0 (한국 규정)

가격은 ``Asset.round_to_tick`` (floor) 로 호가 정렬 후 비용 산출. research 와의
숫자 동치는 테스트로 잠근다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import Field

from src.domain.models import AssetClass, DomainModel, ValueObject

if TYPE_CHECKING:
    from src.domain.models import Asset


class BuyCost(ValueObject):
    """매수 체결 비용 분해 (tax = 0, total_cost = gross + commission)."""

    rounded_price: Decimal = Field(gt=Decimal(0))
    quantity: Decimal = Field(gt=Decimal(0))
    gross: Decimal = Field(gt=Decimal(0))
    commission: Decimal = Field(ge=Decimal(0))
    tax: Decimal = Field(ge=Decimal(0))
    total_cost: Decimal = Field(gt=Decimal(0))


class SellCost(ValueObject):
    """매도 체결 비용 분해 (net_proceeds = gross - tax - commission)."""

    rounded_price: Decimal = Field(gt=Decimal(0))
    quantity: Decimal = Field(gt=Decimal(0))
    gross: Decimal = Field(gt=Decimal(0))
    commission: Decimal = Field(ge=Decimal(0))
    tax: Decimal = Field(ge=Decimal(0))
    net_proceeds: Decimal = Field(ge=Decimal(0))


class KoreanMarketCostModel(DomainModel):
    """KRX 마찰비용 모델 (위탁수수료 + 거래세) + tick 정렬."""

    commission_rate: Decimal = Field(default=Decimal("0.00015"), ge=Decimal(0))
    etf_tax_rate: Decimal = Field(default=Decimal("0.0018"), ge=Decimal(0))
    stock_tax_rate: Decimal = Field(default=Decimal("0.0015"), ge=Decimal(0))

    def compute_buy_cost(
        self, *, price: Decimal, quantity: Decimal, asset: Asset
    ) -> BuyCost:
        """매수 비용. tax = 0, commission = gross x rate, total = gross + commission."""
        rounded = asset.round_to_tick(price)
        gross = rounded * quantity
        commission = gross * self.commission_rate
        return BuyCost(
            rounded_price=rounded,
            quantity=quantity,
            gross=gross,
            commission=commission,
            tax=Decimal("0"),
            total_cost=gross + commission,
        )

    def compute_sell_cost(
        self, *, price: Decimal, quantity: Decimal, asset: Asset
    ) -> SellCost:
        """매도 비용. tax = gross x class별 rate, net = gross - tax - commission."""
        rounded = asset.round_to_tick(price)
        gross = rounded * quantity
        tax = gross * self._tax_rate(asset)
        commission = gross * self.commission_rate
        return SellCost(
            rounded_price=rounded,
            quantity=quantity,
            gross=gross,
            commission=commission,
            tax=tax,
            net_proceeds=gross - tax - commission,
        )

    def _tax_rate(self, asset: Asset) -> Decimal:
        if asset.asset_class is AssetClass.KR_STOCK:
            return self.stock_tax_rate
        return self.etf_tax_rate
