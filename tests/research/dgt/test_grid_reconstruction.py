"""Phase 0.11.j — Tests for src/research/dgt/_grid_reconstruction.py.

Plan §2 Step 2 + §3 test plan (Step 1 parity + Step 1b ADR-branch).

Two test groups:
  Step 1 parity tests — extraction is behavior-preserving vs the old
    _draw_grid_levels logic (ATR path, golden values).
  Step 1b ADR-branch tests — measure="adr" yields different k; regression
    that measure="atr" still matches Step 1 goldens.

Fixtures: synthetic OHLCV + _DGTBacktestResult (reuse patterns from
test_kakao_chart_render.py).

CLAUDE.md §2.1 — all money/price values Decimal.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.domain.models import (
    OHLCV,
    Asset,
    AssetClass,
    Currency,
    Exchange,
    Market,
    Money,
)
from src.research.dgt._grid_reconstruction import _reconstruct_grid_envelope
from src.research.dgt.adaptive_runner import _AdaptiveConfig, _compute_adr, _compute_atr
from src.research.dgt.formulas import grid_levels_table1
from src.research.dgt.results import _DGTBacktestResult, _DGTSnapshot
from src.research.dgt.runner import _DGTConfig


# ---------------------------------------------------------------------------
# Fixture helpers (mirror test_kakao_chart_render.py patterns)
# ---------------------------------------------------------------------------

def _make_asset(code: str = "069500") -> Asset:
    return Asset(
        code=code,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        asset_class=AssetClass.KR_ETF,
        currency=Currency.KRW,
        name="KODEX 200",
        tick_size=Decimal("5"),
        lot_size=Decimal("1"),
        listed_at=date(2002, 10, 14),
    )


def _make_bars(n: int, base_price: int = 50_000, gap: int = 100) -> list[OHLCV]:
    """n synthetic daily OHLCV bars with controlled ATR / ADR.

    high = close + 200, low = close - 200, prev_close gap = 50.
    ATR > ADR when overnight gap matters (high-prev_close or low-prev_close
    exceeds high-low).
    """
    asset = _make_asset()
    base = date(2024, 1, 2)
    bars: list[OHLCV] = []
    for i in range(n):
        close = Decimal(base_price + i * gap)
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base + timedelta(days=i),
                open=close - Decimal("50"),
                high=close + Decimal("200"),
                low=close - Decimal("200"),
                close=close,
                volume=Decimal("5000"),
            )
        )
    return bars


def _make_bars_large_gap(n: int, base_price: int = 50_000) -> list[OHLCV]:
    """Bars with large overnight gaps so ATR >> ADR (forces measure divergence)."""
    asset = _make_asset()
    base = date(2024, 1, 2)
    bars: list[OHLCV] = []
    prev_close = Decimal(base_price)
    for i in range(n):
        # Each bar opens far above prev_close (large gap), narrow intraday range
        open_ = prev_close + Decimal("2000")   # large overnight gap
        close = open_ + Decimal("100")
        high = close + Decimal("50")
        low = open_ - Decimal("50")            # intraday range = 150
        bars.append(
            OHLCV(
                asset=asset,
                trade_date=base + timedelta(days=i),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=Decimal("5000"),
            )
        )
        prev_close = close
    return bars


def _make_result(
    bars: list[OHLCV],
    capital: Decimal = Decimal("10_000_000"),
    close_override: list[Decimal] | None = None,
) -> _DGTBacktestResult:
    """_DGTBacktestResult whose daily_snapshots match bars exactly."""
    asset = bars[0].asset
    money = Money(amount=capital, currency=Currency.KRW)
    closes = close_override or [b.close for b in bars]
    snapshots = [
        _DGTSnapshot(
            trade_date=b.trade_date,
            cash=capital,
            holdings=Decimal("0"),
            close_price=closes[i],
            total_value=capital,
        )
        for i, b in enumerate(bars)
    ]
    return _DGTBacktestResult(
        asset=asset,
        start=bars[0].trade_date,
        end=bars[-1].trade_date,
        initial_capital=money,
        final_cash=capital,
        final_holdings=Decimal("0"),
        final_close_price=bars[-1].close,
        final_balance=money,
        wallet_total=capital,
        reference_price=bars[0].close,
        grid_levels=[bars[0].close],
        trades=[],
        daily_snapshots=snapshots,
    )


def _make_config(
    n: int = 11,
    k_pct: Decimal = Decimal("5"),
    m: int = 5,
) -> _DGTConfig:
    return _DGTConfig(grid_count=n, grid_spacing_pct=k_pct, levels_above=m)


def _make_adaptive_cfg(
    k_min: Decimal = Decimal("0.005"),
    k_max: Decimal = Decimal("0.05"),
    multiplier: Decimal = Decimal("1.0"),
    atr_period: int = 14,
) -> _AdaptiveConfig:
    return _AdaptiveConfig(
        atr_period=atr_period,
        multiplier=multiplier,
        k_min=k_min,
        k_max=k_max,
    )


# ---------------------------------------------------------------------------
# Step 1 parity tests — behavior-preserving extraction (ATR path)
# ---------------------------------------------------------------------------

class TestBhAndEmptyReturnEmpty:
    """bh mode and empty snapshots both return [] (§3 Step 1 parity)."""

    def test_bh_mode_returns_empty(self) -> None:
        bars = _make_bars(10)
        result = _make_result(bars)
        config = _make_config()
        envelope = _reconstruct_grid_envelope(result, config, mode="bh")
        assert envelope == [], "bh mode must return []"

    def test_empty_snapshots_returns_empty(self) -> None:
        bars = _make_bars(5)
        result = _make_result(bars)
        # Replace daily_snapshots with empty list by constructing a new result
        empty_result = _DGTBacktestResult(
            asset=result.asset,
            start=result.start,
            end=result.end,
            initial_capital=result.initial_capital,
            final_cash=result.final_cash,
            final_holdings=result.final_holdings,
            final_close_price=result.final_close_price,
            final_balance=result.final_balance,
            wallet_total=result.wallet_total,
            reference_price=result.reference_price,
            grid_levels=result.grid_levels,
            trades=[],
            daily_snapshots=[],
        )
        config = _make_config()
        envelope = _reconstruct_grid_envelope(empty_result, config, mode="daily")
        assert envelope == [], "empty snapshots must return []"


class TestEnvelopeLengthAndShape:
    """len(envelope) == len(daily_snapshots) and each entry has n+1 levels."""

    def test_length_matches_snapshots_daily(self) -> None:
        n_bars = 20
        bars = _make_bars(n_bars)
        result = _make_result(bars)
        config = _make_config(n=11)
        envelope = _reconstruct_grid_envelope(result, config, mode="daily")
        assert len(envelope) == n_bars

    def test_length_matches_snapshots_paper_adaptive_daily(self) -> None:
        n_bars = 15
        bars = _make_bars(n_bars)
        result = _make_result(bars)
        config = _make_config(n=11)
        envelope = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily"
        )
        assert len(envelope) == n_bars

    def test_each_bar_has_n_plus_one_levels(self) -> None:
        n = 11
        bars = _make_bars(10)
        result = _make_result(bars)
        config = _make_config(n=n)
        envelope = _reconstruct_grid_envelope(result, config, mode="daily")
        for bar_idx, bar_levels in enumerate(envelope):
            assert len(bar_levels) == n + 1, (
                f"bar {bar_idx}: expected {n + 1} levels, got {len(bar_levels)}"
            )

    def test_levels_are_ascending(self) -> None:
        """grid_levels_table1 returns ascending levels — must be preserved."""
        bars = _make_bars(10)
        result = _make_result(bars)
        config = _make_config(n=11)
        envelope = _reconstruct_grid_envelope(result, config, mode="daily")
        for bar_idx, bar_levels in enumerate(envelope):
            for i in range(len(bar_levels) - 1):
                assert bar_levels[i] < bar_levels[i + 1], (
                    f"bar {bar_idx}: levels not ascending at index {i}: "
                    f"{bar_levels[i]} >= {bar_levels[i + 1]}"
                )

    def test_levels_are_decimal(self) -> None:
        """All values in the envelope must be Decimal (P3 discipline)."""
        bars = _make_bars(5)
        result = _make_result(bars)
        config = _make_config(n=5)
        envelope = _reconstruct_grid_envelope(result, config, mode="daily")
        for bar_idx, bar_levels in enumerate(envelope):
            for lv in bar_levels:
                assert isinstance(lv, Decimal), (
                    f"bar {bar_idx}: level {lv!r} is {type(lv)}, expected Decimal"
                )


class TestDailyModeRebalancesEveryBar:
    """daily / paper_adaptive_daily → rebalances every bar (ref moves)."""

    def test_daily_ref_follows_close(self) -> None:
        """In daily mode each bar resets reference to close_price."""
        bars = _make_bars(5)
        result = _make_result(bars)
        config = _make_config(n=4, k_pct=Decimal("5"), m=2)
        envelope = _reconstruct_grid_envelope(result, config, mode="daily")
        # For daily mode every bar rebalances: ref == bar close_price
        for bar_idx, (snap, bar_levels) in enumerate(
            zip(result.daily_snapshots, envelope)
        ):
            expected_ref = snap.close_price
            expected = grid_levels_table1(
                n=config.grid_count,
                reference_price=expected_ref,
                k=config.k_ratio,
                levels_above=config.levels_above,
            )
            assert bar_levels == expected, (
                f"bar {bar_idx}: daily mode should reset grid to close_price ref"
            )

    def test_paper_adaptive_daily_ref_follows_close(self) -> None:
        """paper_adaptive_daily (no adaptive_cfg) → also rebalances every bar."""
        bars = _make_bars(5)
        result = _make_result(bars)
        config = _make_config(n=4, k_pct=Decimal("5"), m=2)
        envelope = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily"
        )
        # m re-symmetrizes to n//2 on each rebalance
        m_sym = config.grid_count // 2
        for bar_idx, (snap, bar_levels) in enumerate(
            zip(result.daily_snapshots, envelope)
        ):
            expected_ref = snap.close_price
            expected = grid_levels_table1(
                n=config.grid_count,
                reference_price=expected_ref,
                k=config.k_ratio,
                levels_above=m_sym,
            )
            assert bar_levels == expected, (
                f"bar {bar_idx}: paper_adaptive_daily should re-symmetrize m"
            )


class TestOnBreachModeRebalancesOnlyOnBreach:
    """on_breach mode rebalances only when close crosses the grid bounds."""

    def test_no_breach_grid_stays_fixed(self) -> None:
        """When close stays within [levels[0], levels[-1]], grid never rebalances."""
        # Use a wide grid (k=20%) and small price moves so no breach occurs
        n = 4
        k_pct = Decimal("20")
        config = _make_config(n=n, k_pct=k_pct, m=2)
        ref_price = Decimal("50000")
        k = config.k_ratio
        initial_levels = grid_levels_table1(
            n=n, reference_price=ref_price, k=k, levels_above=config.levels_above
        )
        lo = float(initial_levels[0])
        hi = float(initial_levels[-1])

        # Bars whose close stays strictly inside [lo, hi]
        n_bars = 8
        asset = _make_asset()
        base_date = date(2024, 1, 2)
        bars: list[OHLCV] = []
        close_prices: list[Decimal] = []
        for i in range(n_bars):
            # oscillate between lo + 1% and hi - 1%
            fraction = (i % 2) * 0.4 + 0.3   # 0.3 or 0.7 of band
            close_f = lo + (hi - lo) * fraction
            close = Decimal(str(round(close_f, 0)))
            close_prices.append(close)
            p = close
            bars.append(
                OHLCV(
                    asset=asset,
                    trade_date=base_date + timedelta(days=i),
                    open=p,
                    high=p + Decimal("100"),
                    low=p - Decimal("100"),
                    close=p,
                    volume=Decimal("1000"),
                )
            )

        # Override first bar close to be ref_price
        close_prices[0] = ref_price
        result = _make_result(bars, close_override=close_prices)
        envelope = _reconstruct_grid_envelope(result, config, mode="on_breach")

        # First bar sets initial grid; subsequent in-band bars keep same bounds
        first_levels = envelope[0]
        assert first_levels[0] < initial_levels[0] * Decimal("1.01")  # approx match
        # Confirm all bars have the same bounds (no rebalance occurred)
        for bar_idx in range(1, n_bars):
            assert envelope[bar_idx] == envelope[0], (
                f"bar {bar_idx}: on_breach should not rebalance when no breach"
            )

    def test_breach_triggers_rebalance(self) -> None:
        """When close crosses below levels[0], grid rebalances."""
        n = 4
        k_pct = Decimal("5")
        config = _make_config(n=n, k_pct=k_pct, m=2)

        ref_price = Decimal("50000")
        k = config.k_ratio
        initial_levels = grid_levels_table1(
            n=n, reference_price=ref_price, k=k, levels_above=config.levels_above
        )
        breach_price = initial_levels[0] - Decimal("100")  # below band

        asset = _make_asset()
        base_date = date(2024, 1, 2)
        # Bar 0: ref price; Bar 1: well inside band; Bar 2: breach below
        bars = [
            OHLCV(asset=asset, trade_date=base_date,
                  open=ref_price, high=ref_price + Decimal("200"),
                  low=ref_price - Decimal("200"), close=ref_price,
                  volume=Decimal("1000")),
            OHLCV(asset=asset, trade_date=base_date + timedelta(days=1),
                  open=ref_price, high=ref_price + Decimal("200"),
                  low=ref_price - Decimal("200"), close=ref_price,
                  volume=Decimal("1000")),
            OHLCV(asset=asset, trade_date=base_date + timedelta(days=2),
                  open=breach_price, high=breach_price + Decimal("50"),
                  low=breach_price - Decimal("50"), close=breach_price,
                  volume=Decimal("1000")),
        ]
        close_prices = [ref_price, ref_price, breach_price]
        result = _make_result(bars, close_override=close_prices)
        envelope = _reconstruct_grid_envelope(result, config, mode="on_breach")

        # Bar 0 and 1 share the same grid (no breach)
        assert envelope[0] == envelope[1], "bar 1 should not rebalance (no breach)"
        # Bar 2 rebalances: new ref = breach_price
        expected_after_breach = grid_levels_table1(
            n=n, reference_price=breach_price, k=k, levels_above=config.levels_above
        )
        assert envelope[2] == expected_after_breach, (
            "bar 2 should rebalance grid to breach_price as new reference"
        )


class TestAdaptiveKVariation:
    """Adaptive mode with adaptive_cfg + measure="atr" → k varies in [k_min, k_max]."""

    def test_adaptive_k_stays_within_bounds(self) -> None:
        """ATR-driven k is clamped to [k_min, k_max] on every bar.

        Note: k_eff derived from adjacent level ratios may differ by tiny
        Decimal rounding. A small epsilon is used for both bounds.
        """
        n_bars = 30
        bars = _make_bars(n_bars, base_price=50_000, gap=100)
        result = _make_result(bars)
        config = _make_config(n=11, k_pct=Decimal("5"), m=5)
        acfg = _make_adaptive_cfg(
            k_min=Decimal("0.005"),
            k_max=Decimal("0.05"),
            multiplier=Decimal("1.0"),
        )
        envelope = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="atr",
        )
        assert len(envelope) == n_bars
        eps = Decimal("0.0001")
        for bar_idx, bar_levels in enumerate(envelope):
            if len(bar_levels) < 2:
                continue
            # Derive effective k from adjacent levels ratio: level[i+1]/level[i] = 1+k
            for i in range(len(bar_levels) - 1):
                ratio = bar_levels[i + 1] / bar_levels[i]
                k_effective = ratio - Decimal("1")
                assert acfg.k_min - eps <= k_effective <= acfg.k_max + eps, (
                    f"bar {bar_idx}: k_effective={k_effective} outside "
                    f"[{acfg.k_min}, {acfg.k_max}]"
                )

    def test_adaptive_k_varies_across_bars(self) -> None:
        """With non-uniform ATR, k should not be the same on every bar."""
        n_bars = 50
        bars = _make_bars_large_gap(n_bars)
        result = _make_result(bars)
        config = _make_config(n=11)
        acfg = _make_adaptive_cfg(
            k_min=Decimal("0.005"),
            k_max=Decimal("0.05"),
            multiplier=Decimal("1.0"),
        )
        envelope = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="atr",
        )
        # Extract k values from consecutive level ratios
        k_values: set[Decimal] = set()
        for bar_levels in envelope:
            if len(bar_levels) >= 2:
                ratio = bar_levels[1] / bar_levels[0]
                k_values.add(ratio.quantize(Decimal("0.000001")))
        # k should vary (not all identical) across bars with large_gap bars
        # At minimum we expect k to take on more than 1 unique value after warmup
        assert len(k_values) > 1, (
            "k should vary across bars in adaptive mode with non-uniform ATR"
        )


# ---------------------------------------------------------------------------
# Step 1 parity — golden value test
# ---------------------------------------------------------------------------

class TestParityWithOldDrawGridLevels:
    """_reconstruct_grid_envelope (ATR path) matches the old _draw_grid_levels logic.

    Golden values captured from the pre-Step-1b ATR behavior:
    The old code in _draw_grid_levels (lines 529-563 of kakao_dgt_backtest.py)
    is the reference. We replicate its behavior directly in the test as the
    golden oracle.
    """

    def _draw_grid_levels_golden(
        self,
        result: _DGTBacktestResult,
        config: _DGTConfig,
        mode: str,
        ohlcv_bars: list[OHLCV] | None = None,
        adaptive_cfg: _AdaptiveConfig | None = None,
    ) -> list[list[float]]:
        """Verbatim replica of the old _draw_grid_levels reconstruction logic
        (kakao_dgt_backtest.py lines 529-563, pre-Step-1b), returning float lists."""
        snapshots = result.daily_snapshots
        if not snapshots or mode == "bh":
            return []

        ref = snapshots[0].close_price
        k = config.k_ratio
        m = config.grid_count // 2 if mode in ("paper", "paper_adaptive") else config.levels_above
        levels = grid_levels_table1(
            n=config.grid_count, reference_price=ref, k=k, levels_above=m,
        )

        per_bar_levels: list[list[float]] = []
        for bar_idx, snap in enumerate(snapshots):
            close = snap.close_price
            should_rebalance = False
            if mode in ("on_breach", "paper", "paper_adaptive"):
                should_rebalance = close < levels[0] or close > levels[-1]
            elif mode in ("daily", "adaptive", "paper_adaptive_daily"):
                should_rebalance = True

            if should_rebalance:
                ref = close
                if mode in ("paper", "paper_adaptive", "paper_adaptive_daily"):
                    m = config.grid_count // 2
                if mode in ("adaptive", "paper_adaptive", "paper_adaptive_daily") and ohlcv_bars and adaptive_cfg:
                    atr = _compute_atr(ohlcv_bars, adaptive_cfg.atr_period, bar_idx)
                    if atr > 0 and close > 0:
                        atr_pct = atr / close
                        k = max(adaptive_cfg.k_min, min(adaptive_cfg.k_max,
                                atr_pct * adaptive_cfg.multiplier))
                levels = grid_levels_table1(
                    n=config.grid_count, reference_price=ref, k=k, levels_above=m,
                )
            per_bar_levels.append([float(lv) for lv in levels])

        return per_bar_levels

    def test_parity_daily_mode(self) -> None:
        """daily mode: _reconstruct (ATR) matches old golden exactly."""
        bars = _make_bars(25)
        result = _make_result(bars)
        config = _make_config(n=11, k_pct=Decimal("5"), m=5)

        golden = self._draw_grid_levels_golden(result, config, mode="daily")
        new_result = _reconstruct_grid_envelope(result, config, mode="daily",
                                                volatility_measure="atr")
        new_float = [[float(lv) for lv in bar] for bar in new_result]

        assert len(new_float) == len(golden)
        for bar_idx, (gold_bar, new_bar) in enumerate(zip(golden, new_float)):
            assert gold_bar == pytest.approx(new_bar, rel=1e-12), (
                f"parity failure at bar {bar_idx}: golden={gold_bar}, new={new_bar}"
            )

    def test_parity_on_breach_mode(self) -> None:
        """on_breach mode: _reconstruct (ATR) matches old golden exactly."""
        bars = _make_bars(20)
        result = _make_result(bars)
        config = _make_config(n=7, k_pct=Decimal("3"), m=3)

        golden = self._draw_grid_levels_golden(result, config, mode="on_breach")
        new_result = _reconstruct_grid_envelope(result, config, mode="on_breach",
                                                volatility_measure="atr")
        new_float = [[float(lv) for lv in bar] for bar in new_result]

        assert len(new_float) == len(golden)
        for bar_idx, (gold_bar, new_bar) in enumerate(zip(golden, new_float)):
            assert gold_bar == pytest.approx(new_bar, rel=1e-12), (
                f"on_breach parity failure at bar {bar_idx}"
            )

    def test_parity_paper_adaptive_daily_with_adaptive_cfg(self) -> None:
        """paper_adaptive_daily + adaptive_cfg + atr: matches old golden exactly."""
        bars = _make_bars(30)
        result = _make_result(bars)
        config = _make_config(n=11, k_pct=Decimal("5"), m=5)
        acfg = _make_adaptive_cfg(
            k_min=Decimal("0.005"),
            k_max=Decimal("0.05"),
            multiplier=Decimal("1.0"),
        )

        golden = self._draw_grid_levels_golden(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
        )
        new_result = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="atr",
        )
        new_float = [[float(lv) for lv in bar] for bar in new_result]

        assert len(new_float) == len(golden)
        for bar_idx, (gold_bar, new_bar) in enumerate(zip(golden, new_float)):
            assert gold_bar == pytest.approx(new_bar, rel=1e-12), (
                f"paper_adaptive_daily parity failure at bar {bar_idx}"
            )

    def test_parity_bh_returns_empty(self) -> None:
        """bh mode: both old and new return []."""
        bars = _make_bars(10)
        result = _make_result(bars)
        config = _make_config()
        golden = self._draw_grid_levels_golden(result, config, mode="bh")
        new_result = _reconstruct_grid_envelope(result, config, mode="bh")
        assert new_result == [] == golden


# ---------------------------------------------------------------------------
# Step 1b ADR-branch tests
# ---------------------------------------------------------------------------

class TestAdrBranchDifferentFromAtr:
    """measure="adr" produces DIFFERENT k from "atr" on bars with overnight gaps."""

    def test_adr_differs_from_atr_on_large_gap_bars(self) -> None:
        """ADR ignores overnight gaps → tighter range → smaller k (typically)."""
        n_bars = 40
        bars = _make_bars_large_gap(n_bars)
        result = _make_result(bars)
        config = _make_config(n=11)
        acfg = _make_adaptive_cfg(
            k_min=Decimal("0.001"),
            k_max=Decimal("0.10"),
            multiplier=Decimal("1.0"),
        )

        env_atr = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="atr",
        )
        env_adr = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="adr",
        )

        assert len(env_atr) == len(env_adr) == n_bars

        # At least one bar must differ between ATR and ADR paths
        any_different = False
        for atr_bar, adr_bar in zip(env_atr, env_adr):
            if atr_bar != adr_bar:
                any_different = True
                break
        assert any_different, (
            "ATR and ADR paths should diverge on bars with large overnight gaps"
        )

    def test_adr_k_smaller_than_atr_on_large_gap_bars(self) -> None:
        """ADR < ATR on large-gap bars → tighter k (narrower grid)."""
        bars = _make_bars_large_gap(50)
        # Verify the underlying primitives first
        # ATR includes overnight gap (high - prev_close) → larger
        # ADR ignores overnight gap (high - low only) → smaller
        bar_idx = 20
        period = 14
        atr_val = _compute_atr(bars, period, bar_idx)
        adr_val = _compute_adr(bars, period, bar_idx)
        assert adr_val < atr_val, (
            f"ADR ({adr_val}) should be < ATR ({atr_val}) on large-gap bars"
        )

    def test_adr_k_within_bounds(self) -> None:
        """ADR-driven k also stays clamped to [k_min, k_max].

        Note: k_eff is derived from adjacent level ratios in the geometric grid,
        so it may differ from k by tiny Decimal rounding errors. A small epsilon
        is used for the lower-bound check.
        """
        n_bars = 30
        bars = _make_bars_large_gap(n_bars)
        result = _make_result(bars)
        config = _make_config(n=11)
        acfg = _make_adaptive_cfg(
            k_min=Decimal("0.005"),
            k_max=Decimal("0.05"),
            multiplier=Decimal("1.0"),
        )
        envelope = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="adr",
        )
        assert len(envelope) == n_bars
        # Tiny epsilon to absorb Decimal geometric-spacing rounding
        eps = Decimal("0.0001")
        for bar_idx, bar_levels in enumerate(envelope):
            for i in range(len(bar_levels) - 1):
                ratio = bar_levels[i + 1] / bar_levels[i]
                k_eff = ratio - Decimal("1")
                assert acfg.k_min - eps <= k_eff <= acfg.k_max + eps, (
                    f"bar {bar_idx}: ADR k_eff={k_eff} outside bounds"
                )

    def test_adr_golden_values_stable(self) -> None:
        """ADR-mode golden: fixed bars produce deterministic levels."""
        # Use a small, fully-determined fixture so the golden is predictable.
        n = 4
        k_pct = Decimal("5")
        config = _make_config(n=n, k_pct=k_pct, m=2)
        acfg = _make_adaptive_cfg(
            k_min=Decimal("0.01"),
            k_max=Decimal("0.08"),
            multiplier=Decimal("1.0"),
            atr_period=3,
        )
        bars = _make_bars_large_gap(10, base_price=50_000)
        result = _make_result(bars)

        env1 = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="adr",
        )
        # Run twice — must be deterministic
        env2 = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="adr",
        )
        assert env1 == env2, "ADR path must be deterministic on same inputs"

    def test_atr_path_unchanged_after_step_1b(self) -> None:
        """Regression: measure="atr" still matches Step 1 golden after Step 1b."""
        # This is the critical Step 1b regression test:
        # adding the ADR branch must not touch the ATR path at all.
        bars = _make_bars(25)
        result = _make_result(bars)
        config = _make_config(n=11, k_pct=Decimal("5"), m=5)
        acfg = _make_adaptive_cfg(
            k_min=Decimal("0.005"),
            k_max=Decimal("0.05"),
            multiplier=Decimal("1.0"),
        )

        # Replicate old _draw_grid_levels (ATR only) as the oracle
        def _golden_atr(r: _DGTBacktestResult, cfg: _DGTConfig) -> list[list[Decimal]]:
            snapshots = r.daily_snapshots
            ref = snapshots[0].close_price
            k = cfg.k_ratio
            m = cfg.grid_count // 2  # paper_adaptive_daily
            levels = grid_levels_table1(n=cfg.grid_count, reference_price=ref, k=k, levels_above=m)
            envelope: list[list[Decimal]] = []
            for bar_idx, snap in enumerate(snapshots):
                ref = snap.close_price  # daily → always rebalances
                m = cfg.grid_count // 2
                atr = _compute_atr(bars, acfg.atr_period, bar_idx)
                if atr > 0 and snap.close_price > 0:
                    atr_pct = atr / snap.close_price
                    k = max(acfg.k_min, min(acfg.k_max, atr_pct * acfg.multiplier))
                levels = grid_levels_table1(n=cfg.grid_count, reference_price=ref, k=k, levels_above=m)
                envelope.append(list(levels))
            return envelope

        golden = _golden_atr(result, config)
        new_result = _reconstruct_grid_envelope(
            result, config, mode="paper_adaptive_daily",
            ohlcv_bars=bars, adaptive_cfg=acfg,
            volatility_measure="atr",
        )
        assert new_result == golden, (
            "measure='atr' must match Step 1 golden exactly after Step 1b addition"
        )


# ---------------------------------------------------------------------------
# Step 1b ADR vs ATR: modes without adaptive_cfg are unaffected
# ---------------------------------------------------------------------------

class TestNonAdaptiveModesUnaffectedByMeasure:
    """Non-adaptive modes ignore volatility_measure (no adaptive_cfg)."""

    def test_daily_mode_same_regardless_of_measure(self) -> None:
        """daily mode (no adaptive_cfg): ATR and ADR paths produce identical output."""
        bars = _make_bars_large_gap(15)
        result = _make_result(bars)
        config = _make_config(n=7)

        env_atr = _reconstruct_grid_envelope(
            result, config, mode="daily", volatility_measure="atr"
        )
        env_adr = _reconstruct_grid_envelope(
            result, config, mode="daily", volatility_measure="adr"
        )
        assert env_atr == env_adr, (
            "daily mode without adaptive_cfg: measure has no effect"
        )

    def test_on_breach_mode_same_regardless_of_measure(self) -> None:
        bars = _make_bars_large_gap(15)
        result = _make_result(bars)
        config = _make_config(n=5)

        env_atr = _reconstruct_grid_envelope(
            result, config, mode="on_breach", volatility_measure="atr"
        )
        env_adr = _reconstruct_grid_envelope(
            result, config, mode="on_breach", volatility_measure="adr"
        )
        assert env_atr == env_adr, (
            "on_breach mode without adaptive_cfg: measure has no effect"
        )
