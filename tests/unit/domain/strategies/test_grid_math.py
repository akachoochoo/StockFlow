"""DGT grid 수학 — research 동치 잠금 (ADR 0022 G1).

`src/domain/strategies/grid_math.py` 가 research `grid_levels_table1` +
`_DGTPaperAdaptiveRunner._adaptive_k`(use_trend=False) 와 **동일 Decimal
출력**을 내는지 잠근다.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.cli.composition import asset_from_code
from src.domain.models import OHLCV
from src.domain.strategies.grid_math import adaptive_k, grid_levels
from src.research.dgt.adaptive_runner import _AdaptiveConfig
from src.research.dgt.cost_model import _KoreanMarketCostModel
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.paper_adaptive_runner import _DGTPaperAdaptiveRunner
from src.research.dgt.runner import _DGTConfig

_ASSET = asset_from_code("069500")

_ROWS = [
    ("100", "105", "99", "104", "1000"),
    ("104", "108", "103", "106", "1200"),
    ("106", "107", "101", "102", "1500"),
    ("102", "104", "98", "100", "2000"),
    ("100", "101", "95", "96", "2500"),
    ("96", "99", "94", "98", "1800"),
    ("98", "110", "97", "109", "5000"),
    ("109", "112", "108", "110", "3000"),
    ("110", "111", "104", "105", "2200"),
    ("105", "106", "100", "101", "1900"),
    ("101", "103", "100", "102", "1100"),
    ("102", "102", "99", "100", "1300"),
    ("100", "108", "100", "107", "4200"),
    ("107", "115", "106", "114", "6000"),
    ("114", "116", "112", "113", "2800"),
]


def _bars() -> list[OHLCV]:
    base = date(2024, 1, 1)
    return [
        OHLCV(
            asset=_ASSET,
            trade_date=base + timedelta(days=i),
            open=Decimal(o),
            high=Decimal(h),
            low=Decimal(low),
            close=Decimal(c),
            volume=Decimal(v),
        )
        for i, (o, h, low, c, v) in enumerate(_ROWS)
    ]


class TestGridLevelsEquivalence:
    @pytest.mark.parametrize("n,m", [(11, 5), (4, 2), (7, 3), (8, 0), (6, 6)])
    @pytest.mark.parametrize("k", [Decimal("0.05"), Decimal("0.02"), Decimal("0.1")])
    def test_matches_research(self, n: int, m: int, k: Decimal):
        ref = Decimal("35000")
        assert grid_levels(n, ref, k, m) == grid_levels_table1(
            n=n, reference_price=ref, k=k, levels_above=m
        )

    @pytest.mark.parametrize(
        "n,ref,k,m",
        [
            (0, Decimal("100"), Decimal("0.05"), 0),  # n <= 0
            (4, Decimal("100"), Decimal("0.05"), 5),  # m > n
            (4, Decimal("0"), Decimal("0.05"), 2),  # ref <= 0
            (4, Decimal("100"), Decimal("0"), 2),  # k <= 0
        ],
    )
    def test_validation_parity(self, n, ref, k, m):
        with pytest.raises(ValueError):
            grid_levels(n, ref, k, m)


def _runner(measure: str) -> _DGTPaperAdaptiveRunner:
    return _DGTPaperAdaptiveRunner(
        cost_model=_KoreanMarketCostModel(),
        config=_DGTConfig(
            grid_count=11, grid_spacing_pct=Decimal("5"), levels_above=5
        ),
        adaptive=_AdaptiveConfig(),
        volatility_measure=measure,  # type: ignore[arg-type]
        use_trend=False,
    )


class TestAdaptiveKEquivalence:
    @pytest.mark.parametrize("measure", ["adr", "atr"])
    @pytest.mark.parametrize("end_idx", [0, 5, 10, 14])
    def test_matches_research(self, measure: str, end_idx: int):
        bars = _bars()
        r = _runner(measure)
        cfg = r.adaptive
        close = bars[end_idx].close
        research_k = r._adaptive_k(bars, end_idx, close)
        domain_k = adaptive_k(
            bars,
            end_idx,
            close,
            period=cfg.atr_period,
            multiplier=cfg.multiplier,
            k_min=cfg.k_min,
            k_max=cfg.k_max,
            fallback_k=r.config.k_ratio,
            measure=measure,  # type: ignore[arg-type]
        )
        assert domain_k == research_k

    def test_fallback_on_zero_close(self):
        bars = _bars()
        # close <= 0 → fallback_k (research 동일 경로)
        fb = Decimal("0.05")
        assert (
            adaptive_k(
                bars, 5, Decimal("0"),
                period=14, multiplier=Decimal("1.5"),
                k_min=Decimal("0.02"), k_max=Decimal("0.10"),
                fallback_k=fb, measure="adr",
            )
            == fb
        )
