"""SevenSplitRenderer — PriceDropStrategy / SupportLevelStrategy 차수 표기.

Phase 0.10 — ADR 0006 §4.3.1 박제. 세븐 스플릿 (B1~B7 / S1~S7) 의 차수별
색상 + 라벨. PriceDropStrategy 와 SupportLevelStrategy 모두 동일 매핑
(BuyActionRecord.split_number / SellActionRecord.slot_number 키 활용).

Annotation key 매핑:
    BUY  : ``split_number`` (BuyActionRecord.reasoning 내) — 1~7
    SELL : ``slot_number``  (SellActionRecord.reasoning 내) — 1~7

Reasoning dict 에 키 미존재 시 0 fallback (label = "B0" / "S0", 색상 검정).
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, ClassVar

from src.ports.strategy_renderer import MarkerStyle, Panel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.application.reporting.episode import DrawdownEpisode
    from src.application.reporting.trade_view import TradeView


class SevenSplitRenderer:
    """세븐 스플릿 (PriceDropStrategy / SupportLevelStrategy) 차수 표기."""

    # matplotlib tab10 palette — 차수별 구분
    SPLIT_COLORS: ClassVar[dict[int, str]] = {
        1: "#1f77b4",  # blue
        2: "#ff7f0e",  # orange
        3: "#2ca02c",  # green
        4: "#d62728",  # red
        5: "#9467bd",  # purple
        6: "#8c564b",  # brown
        7: "#7f7f7f",  # grey
    }
    DEFAULT_COLOR = "#000000"

    def marker_label(self, trade: TradeView) -> str:
        n = self._slot(trade)
        return f"B{n}" if trade.side == "BUY" else f"S{n}"

    def marker_style(self, trade: TradeView) -> MarkerStyle:
        n = self._slot(trade)
        return MarkerStyle(
            color=self.SPLIT_COLORS.get(n, self.DEFAULT_COLOR),
            marker="^" if trade.side == "BUY" else "v",
            size=10,
            label=self.marker_label(trade),
        )

    def diagnostic_panels(
        self,
        trades: Sequence[TradeView],
        episode: DrawdownEpisode,
    ) -> Sequence[Panel]:
        ep_trades = _trades_in_episode(trades, episode)
        buys = [t for t in ep_trades if t.side == "BUY"]
        sells = [t for t in ep_trades if t.side == "SELL"]

        # Per-slot buy/sell count
        buy_counter: Counter[int] = Counter(self._slot(t) for t in buys)
        sell_counter: Counter[int] = Counter(self._slot(t) for t in sells)

        slot_rows: list[tuple[str, str]] = []
        for n in range(1, 8):
            b = buy_counter.get(n, 0)
            s = sell_counter.get(n, 0)
            if b == 0 and s == 0:
                continue
            slot_rows.append((f"slot {n}", f"buys={b} / sells={s}"))

        summary_rows: list[tuple[str, str]] = [
            ("episode peak", str(episode.peak_value)),
            ("episode trough", str(episode.trough_value)),
            ("drawdown_pct", f"{episode.drawdown_pct:+.4f}%"),
            ("recovered", "yes" if episode.recovered else "no"),
            ("duration_days", str(episode.duration_days)),
            ("total buys", str(len(buys))),
            ("total sells", str(len(sells))),
        ]

        return [
            Panel(title="Episode 요약", rows=summary_rows),
            Panel(title="차수별 거래 횟수", rows=slot_rows),
        ]

    def _slot(self, trade: TradeView) -> int:
        key = "split_number" if trade.side == "BUY" else "slot_number"
        try:
            return int(trade.annotations.get(key, 0))
        except (TypeError, ValueError):
            return 0


def _trades_in_episode(
    trades: Sequence[TradeView], episode: DrawdownEpisode,
) -> list[TradeView]:
    """Episode 구간 [peak_date, recovery_date] (recovered) 또는
    [peak_date, ∞) (unrecovered) 내 trades 필터.
    """
    after_peak = [t for t in trades if t.timestamp.date() >= episode.peak_date]
    if episode.recovered and episode.recovery_date is not None:
        return [
            t for t in after_peak
            if t.timestamp.date() <= episode.recovery_date
        ]
    return after_peak
