"""SevenSplitRenderer — PriceDropStrategy / SupportLevelStrategy 차수 표기.

Phase 0.10 — ADR 0006 §4.3.1 박제. 세븐 스플릿 (B1~B7 / S1~S7) 의 차수별
색상 + 라벨. PriceDropStrategy 와 SupportLevelStrategy 모두 동일 매핑.

Annotation key (ADR 0006 §16 박제 후):
    BUY / SELL : ``slot_number`` (uniform — application layer 가
        ``trades_from_decisions`` 에서 ``BuyActionRecord.slot_number`` /
        ``SellActionRecord.slot_number`` 타입 필드를 view-only annotations 로
        enrich. 도메인 reasoning dict 변경 zero — Clean Architecture 정합)

전사: ``split_number`` 는 Phase pre-0.5 시절 renderer-internal 명칭
이었음. 도메인은 0.5 부터 ``slot_number`` 로 통일했고, 본 어댑터는
Phase 0.10.z (라운드 #20, ADR 0006 §16) 에서 도메인 명명에 align —
half-done rename 의 마무리.

Reasoning dict 에 키 미존재 시 0 fallback (label = "B0" / "S0", 색상 검정)
— application layer 가 enrichment 보장하므로 실제 발생 X.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, ClassVar

from src.adapters.reporting.formatters import format_money, format_pct
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
            ("episode peak", format_money(episode.peak_value)),
            ("episode trough", format_money(episode.trough_value)),
            ("drawdown_pct", format_pct(episode.drawdown_pct)),
            ("recovered", "yes" if episode.recovered else "no"),
            ("duration_days", f"{episode.duration_days}일"),
            ("total buys", str(len(buys))),
            ("total sells", str(len(sells))),
        ]

        return [
            Panel(title="Episode 요약", rows=summary_rows),
            Panel(title="차수별 거래 횟수", rows=slot_rows),
        ]

    def _slot(self, trade: TradeView) -> int:
        # Uniform `slot_number` for both BUY and SELL (ADR 0006 §16 박제,
        # 라운드 #20). Application layer (`trades_from_decisions`) enriches
        # view annotations from typed BuyActionRecord/SellActionRecord
        # `slot_number` fields — domain명명 정합.
        try:
            return int(trade.annotations.get("slot_number", 0))
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
