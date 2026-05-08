"""DefaultRenderer — annotation 무관 fallback marker.

Phase 0.10 — ADR 0006 §4.3.2 박제. 신규 strategy 추가 시 Registry 등록
없이도 Acceptance Criteria 3 (코어 reporting 모듈 변경 zero) 충족 보장.

단순 B (buy, 초록 위쪽 삼각형) / S (sell, 빨강 아래쪽 삼각형) 마커.
diagnostic panels = 단순 buy/sell count + episode 요약.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.adapters.reporting.formatters import format_money, format_pct
from src.ports.strategy_renderer import MarkerStyle, Panel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.application.reporting.episode import DrawdownEpisode
    from src.application.reporting.trade_view import TradeView


class DefaultRenderer:
    """Annotation 무관 단순 B/S 마커 — 신규 strategy 의 default."""

    BUY_COLOR = "#2ca02c"  # green
    SELL_COLOR = "#d62728"  # red

    def marker_label(self, trade: TradeView) -> str:
        return "B" if trade.side == "BUY" else "S"

    def marker_style(self, trade: TradeView) -> MarkerStyle:
        return MarkerStyle(
            color=self.BUY_COLOR if trade.side == "BUY" else self.SELL_COLOR,
            marker="^" if trade.side == "BUY" else "v",
            size=8,
            label=self.marker_label(trade),
        )

    def diagnostic_panels(
        self,
        trades: Sequence[TradeView],
        episode: DrawdownEpisode,
    ) -> Sequence[Panel]:
        from src.adapters.reporting.renderers.seven_split import (
            _trades_in_episode,
        )

        ep_trades = _trades_in_episode(trades, episode)
        buys = sum(1 for t in ep_trades if t.side == "BUY")
        sells = sum(1 for t in ep_trades if t.side == "SELL")

        return [
            Panel(
                title="Episode 요약",
                rows=[
                    ("episode peak", format_money(episode.peak_value)),
                    ("episode trough", format_money(episode.trough_value)),
                    ("drawdown_pct", format_pct(episode.drawdown_pct)),
                    ("recovered", "yes" if episode.recovered else "no"),
                    ("duration_days", f"{episode.duration_days}일"),
                    ("total buys", str(buys)),
                    ("total sells", str(sells)),
                ],
            ),
        ]
