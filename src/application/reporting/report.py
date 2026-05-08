"""Episode report use case — orchestrates detector + renderer + chart + HTML.

Phase 0.10 (sub-step 0.10.e — ADR 0006 §11). Strategy-agnostic 진입점:
BacktestResult + strategy_id + bars + output_dir → reports/.../episode_*.html
+ index.html.

Phase 0.10.e 한정: scope="portfolio" 만 구현. asset / both scope 는
Phase 0.10.x 후속 (ADR 0006 §5.5 박제 — default portfolio + 옵션).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from src.adapters.reporting.chart import render_episode_chart
from src.adapters.reporting.html_writer import (
    write_episode_html,
    write_index_html,
)
from src.adapters.reporting.renderer_registry import StrategyRendererRegistry
from src.application.reporting.episode import detect_drawdown_episodes
from src.application.reporting.trade_view import trades_from_decisions

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from pathlib import Path

    from src.application.backtest_runner import BacktestResult
    from src.application.reporting.episode import DrawdownEpisode
    from src.application.reporting.trade_view import TradeView
    from src.domain.models import OHLCV, PortfolioSnapshot


ScopeT = Literal["portfolio", "asset", "both"]


@dataclass(frozen=True)
class EpisodeReportResult:
    """generate_episode_report 결과."""

    episodes: list[DrawdownEpisode]
    episode_html_paths: list[Path]
    index_html_path: Path
    trade_count: int


def extract_portfolio_equity_curve(
    snapshots: Sequence[PortfolioSnapshot],
) -> list[tuple[date, Decimal]]:
    """PortfolioSnapshot list → equity curve (date, total_value), sorted."""
    return [
        (snap.snapshot_date, snap.total_value.amount)
        for snap in sorted(snapshots, key=lambda s: s.snapshot_date)
    ]


def generate_episode_report(
    *,
    backtest_result: BacktestResult,
    strategy_id: str,
    output_dir: Path,
    bars_by_asset: dict[str, list[OHLCV]],
    registry: StrategyRendererRegistry | None = None,
    threshold_pct: Decimal = Decimal("-5"),
    scope: ScopeT = "portfolio",
    chart_symbol: str | None = None,
    title: str = "Backtest Drawdown Episodes",
) -> EpisodeReportResult:
    """Generate per-episode HTML report from a BacktestResult.

    Phase 0.10.e 구현 범위 (ADR 0006 §5.5 박제):
        - scope="portfolio" 만 (default). asset / both 는 Phase 0.10.x.

    Pipeline:
        1. Extract portfolio equity curve from snapshots
        2. ``detect_drawdown_episodes`` (threshold_pct, default -5%)
        3. ``trades_from_decisions`` (BacktestResult.decisions → TradeView)
        4. Per-episode: render_episode_chart + diagnostic_panels +
           write_episode_html
        5. write_index_html (모든 episode 링크)

    Args:
        backtest_result: BacktestResult — snapshots (equity curve) +
            decisions (trades)
        strategy_id: yaml buy_strategy field — registry lookup
        output_dir: HTML 출력 디렉토리 (parent dirs 자동 생성)
        bars_by_asset: symbol → OHLCV list. chart 그릴 시점에 사용
        registry: StrategyRendererRegistry (None = default 인스턴스 사용)
        threshold_pct: drawdown 임계 (음수, default -5%)
        scope: Phase 0.10.e 는 "portfolio" 만; 다른 값 → NotImplementedError
        chart_symbol: 차트 그릴 symbol (None = bars_by_asset 첫 키)
        title: index.html 타이틀

    Returns:
        EpisodeReportResult — episodes + 생성된 HTML paths + trade count

    Raises:
        NotImplementedError: scope != "portfolio" (Phase 0.10.e 한정)
        ValueError: bars_by_asset 빈 경우 / chart_symbol 매핑 안됨 /
            threshold_pct >= 0 (detect_drawdown_episodes 가 발생)
    """
    if scope != "portfolio":
        raise NotImplementedError(
            f"scope={scope!r} not supported in Phase 0.10.e — "
            "only 'portfolio' available. asset / both = Phase 0.10.x "
            "(ADR 0006 §5.5)"
        )
    if not bars_by_asset:
        raise ValueError("bars_by_asset is empty")

    if chart_symbol is None:
        chart_symbol = next(iter(bars_by_asset))
    if chart_symbol not in bars_by_asset:
        raise ValueError(
            f"chart_symbol {chart_symbol!r} not in bars_by_asset "
            f"({sorted(bars_by_asset.keys())})"
        )

    # 1. Equity curve
    equity_curve = extract_portfolio_equity_curve(backtest_result.snapshots)

    # 2. Detect episodes
    episodes = detect_drawdown_episodes(
        equity_curve, threshold_pct=threshold_pct, asset_code=None,
    )

    # 3. Trades
    all_trades: list[TradeView] = trades_from_decisions(
        backtest_result.decisions, strategy_id=strategy_id,
    )

    # 4. Renderer (registry default fallback for unknown strategy_id)
    registry_inst = registry or StrategyRendererRegistry()
    renderer = registry_inst.get(strategy_id)

    # 5. Per-episode chart + HTML
    from pathlib import Path as _Path  # local import — type-only top

    output_dir.mkdir(parents=True, exist_ok=True)
    chart_bars = bars_by_asset[chart_symbol]
    episode_html_paths: list[Path] = []

    for i, episode in enumerate(episodes, start=1):
        # Filter trades to episode window for HTML log (chart filters internally)
        ep_trades = _filter_trades_to_episode(all_trades, episode)
        # Render chart (mplfinance — external dep)
        chart_png = render_episode_chart(
            episode=episode,
            ohlcv_bars=chart_bars,
            trades=all_trades,
            renderer=renderer,
        )
        # Diagnostic panels (renderer-specific)
        panels = list(renderer.diagnostic_panels(all_trades, episode))
        # Write HTML
        ep_path = output_dir / f"episode_{i}.html"
        write_episode_html(
            episode=episode,
            chart_png=chart_png,
            trades=ep_trades,
            panels=panels,
            output_path=ep_path,
        )
        episode_html_paths.append(ep_path)

    # 6. Index
    index_path = output_dir / "index.html"
    write_index_html(
        episodes=episodes,
        # Relative paths (so index.html links work from output_dir)
        episode_paths=[_Path(p.name) for p in episode_html_paths],
        output_path=index_path,
        title=title,
    )

    return EpisodeReportResult(
        episodes=episodes,
        episode_html_paths=episode_html_paths,
        index_html_path=index_path,
        trade_count=len(all_trades),
    )


def _filter_trades_to_episode(
    trades: Sequence[TradeView], episode: DrawdownEpisode,
) -> list[TradeView]:
    """Episode 구간 [peak_date, recovery|end] 내 trades 만."""
    out: list[TradeView] = []
    for t in trades:
        td = t.timestamp.date()
        if td < episode.peak_date:
            continue
        if (
            episode.recovered
            and episode.recovery_date is not None
            and td > episode.recovery_date
        ):
            continue
        out.append(t)
    return out
