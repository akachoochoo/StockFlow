"""HTML report writer (Phase 0.10 — ADR 0006 §7).

stdlib f-string template — episode 1 페이지 HTML + index page. jinja2
미도입 (CLAUDE.md "친절한 추가 금지" + ADR 0006 §7.2 박제).

리포트 1 페이지 구성 (Phase 0.10.h~k 박제 후속):
- KPI strip (5 deterministic facts: drawdown / duration / recovered /
  total trades / total invested) — Phase 0.10.i
- 차트 (PNG base64 embed)
- Episode 메타데이터 테이블 (formatters 적용 — Phase 0.10.h)
- 전략별 진단 패널 (renderer.diagnostic_panels 결과)
- 종목별 ``<details>`` 그룹 + cycle mini-table (FIFO 표시) — Phase 0.10.j
- 거래 로그 (TradeView list, annotation mini-table) — Phase 0.10.h

Index page: 모든 episode 링크 + aggregate 요약 — Phase 0.10.k.
"""
from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import TYPE_CHECKING, Any

from src.adapters.reporting.formatters import (
    format_date,
    format_datetime_kst,
    format_money,
    format_pct,
    format_price,
    format_quantity,
)
from src.adapters.reporting.symbol_names import display_symbol
from src.application.reporting.cycle_pairing import (
    Cycle,
    pair_cycles,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from src.application.reporting.episode import DrawdownEpisode
    from src.application.reporting.risk_metrics import EpisodeRiskMetrics
    from src.application.reporting.strategy_info import StrategyInfo
    from src.application.reporting.trade_view import TradeView
    from src.ports.strategy_renderer import Panel


_EPISODE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                     "Apple SD Gothic Neo", sans-serif;
        margin: 20px; max-width: 1200px; color: #2c3e50; }}
h1 {{ color: #2c3e50; }}
h2 {{ color: #34495e; border-bottom: 2px solid #ecf0f1;
      padding-bottom: 5px; margin-top: 25px; }}
h3 {{ color: #34495e; margin-top: 20px; margin-bottom: 8px;
      font-size: 16px; }}
table {{ border-collapse: collapse; margin: 10px 0; min-width: 50%; }}
th, td {{ padding: 6px 12px; border: 1px solid #ddd; text-align: left;
          font-size: 14px; vertical-align: top; }}
th {{ background: #f8f9fa; font-weight: 600; }}
.chart {{ margin: 20px 0; }}
.chart img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
.recovered-yes {{ color: #27ae60; font-weight: 600; }}
.recovered-no  {{ color: #c0392b; font-weight: 600; }}
.side-buy  {{ color: #27ae60; font-weight: 600; }}
.side-sell {{ color: #c0392b; font-weight: 600; }}
.kpi-strip {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }}
.kpi {{ flex: 1 1 160px; padding: 10px 14px; border: 1px solid #e1e6ec;
        border-radius: 6px; background: #fafbfc; }}
.kpi .label {{ font-size: 12px; color: #7f8c8d;
                text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi .value {{ font-size: 18px; font-weight: 600; color: #2c3e50;
                margin-top: 4px; }}
.risk-metrics {{ margin: 16px 0; padding: 12px 16px; background: #fafbfc;
                  border: 1px solid #e1e6ec; border-radius: 6px; }}
.risk-metrics h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #34495e;
                     border: none; padding: 0; }}
.risk-metrics .metrics-row {{ display: flex; flex-wrap: wrap; gap: 16px; }}
.risk-metrics .metric {{ flex: 1 1 160px; }}
.risk-metrics .label {{ font-size: 12px; color: #7f8c8d; }}
.risk-metrics .value {{ font-size: 16px; font-weight: 600; color: #2c3e50;
                         margin-top: 2px; }}
.symbol-group, .chart-symbol, .strategy-info {{ margin: 14px 0; }}
.symbol-group summary,
.chart-symbol summary,
.strategy-info summary {{ cursor: pointer; padding: 8px 12px;
                           background: #f8f9fa; border: 1px solid #ddd;
                           border-radius: 4px; font-weight: 600; }}
.symbol-group summary:hover,
.chart-symbol summary:hover,
.strategy-info summary:hover {{ background: #ecf0f1; }}
.symbol-group[open] summary,
.chart-symbol[open] summary,
.strategy-info[open] summary {{ background: #e8eef4; }}
.chart-symbol img {{ max-width: 100%; height: auto;
                     border: 1px solid #ddd; margin-top: 8px; }}
.cycle-table {{ margin: 8px 0 16px 0; }}
.cycle-pnl-pos {{ color: #27ae60; }}
.cycle-pnl-neg {{ color: #c0392b; }}
.cycle-pnl-na {{ color: #95a5a6; font-style: italic; }}
.annot-mini {{ margin: 0; min-width: 0; }}
.annot-mini th {{ background: #f8f9fa; font-size: 12px;
                   font-weight: 500; padding: 2px 6px; }}
.annot-mini td {{ font-size: 12px; padding: 2px 6px;
                   font-family: monospace; }}
.annot-empty {{ color: #95a5a6; font-style: italic; }}
.annot-raw {{ font-family: monospace; font-size: 12px; color: #555; }}
.label-badge {{ display: inline-block; padding: 1px 6px; margin-left: 4px;
                 background: #ecf0f1; border-radius: 3px;
                 font-size: 11px; color: #34495e; }}
</style>
</head>
<body>
<h1>{title}</h1>

{strategy_info_html}

{kpi_strip}

{risk_metrics_html}

<h2>Episode 메타데이터</h2>
<table>
{episode_meta_rows}
</table>

<h2>차트</h2>
{charts_html}

{panels_html}

{symbol_groups_html}

<h2>거래 로그 ({trade_count})</h2>
<table>
<thead>
<tr><th>timestamp</th><th>symbol</th><th>side</th><th>price</th>
<th>quantity</th><th>annotations</th></tr>
</thead>
<tbody>
{trade_rows}
</tbody>
</table>

</body>
</html>
"""


_INDEX_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                     "Apple SD Gothic Neo", sans-serif;
        margin: 20px; max-width: 1200px; color: #2c3e50; }}
h1 {{ color: #2c3e50; }}
table {{ border-collapse: collapse; margin: 10px 0; width: 100%; }}
th, td {{ padding: 6px 12px; border: 1px solid #ddd; text-align: left;
          font-size: 14px; }}
th {{ background: #f8f9fa; font-weight: 600; }}
.recovered-yes {{ color: #27ae60; font-weight: 600; }}
.recovered-no  {{ color: #c0392b; font-weight: 600; }}
.dd {{ color: #c0392b; font-weight: 600; }}
.aggregate {{ margin: 12px 0; padding: 10px 16px; background: #fafbfc;
               border: 1px solid #e1e6ec; border-radius: 6px; }}
.aggregate ul {{ margin: 0; padding-left: 20px; }}
.aggregate li {{ font-size: 14px; padding: 2px 0; }}
.strategy-info {{ margin: 14px 0; }}
.strategy-info summary {{ cursor: pointer; padding: 8px 12px;
                           background: #f8f9fa; border: 1px solid #ddd;
                           border-radius: 4px; font-weight: 600; }}
.strategy-info summary:hover {{ background: #ecf0f1; }}
.strategy-info[open] summary {{ background: #e8eef4; }}
</style>
</head>
<body>
<h1>{title}</h1>
{strategy_info_html}
<p>총 {count} 개 episode.</p>
{aggregate_html}
<table>
<thead>
<tr><th>#</th><th>asset</th><th>peak_date</th><th>trough_date</th>
<th>drawdown_pct</th><th>recovered</th><th>duration_days</th><th>상세</th></tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""


def write_episode_html(
    episode: DrawdownEpisode,
    charts: Sequence[tuple[str, bytes]],
    trades: Sequence[TradeView],
    panels: Sequence[Panel],
    output_path: Path,
    *,
    title: str | None = None,
    symbol_names: Mapping[str, str] | None = None,
    strategy_info: StrategyInfo | None = None,
    risk_metrics: EpisodeRiskMetrics | None = None,
) -> None:
    """Episode 1 페이지 HTML 작성.

    Args:
        episode: DrawdownEpisode
        charts: per-symbol chart panel list — ``[(symbol_code, png_bytes), ...]``.
            ``sorted(symbol)`` order 권장 (caller 책임). 각 PNG 는 base64
            embed 되어 ``<details class="chart-symbol" open>`` 블록 안에 표시.
            Phase 0.10.aa (ADR §17) 박제 — 이전 단일 ``chart_png: bytes``
            시그니처 breaking change.
        trades: 거래 로그 (전체 또는 episode 구간 — 호출자가 필터)
        panels: 전략별 진단 패널 (renderer.diagnostic_panels 결과)
        output_path: 출력 HTML 경로 (parent dirs 자동 생성)
        title: 페이지 title (None 시 episode 메타로 자동 생성)
        symbol_names: 종목 코드 → 표시명 mapping. None = 모듈 default
            ``SYMBOL_NAMES`` (Phase 0.10.h). Phase 0.11 yaml 분리 시
            single-arg flip 으로 교체.
        strategy_info: 전략 정보 (Phase 0.10.y, ADR §15.6).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    asset_label = (
        display_symbol(episode.asset_code, symbol_names)
        if episode.asset_code else "(portfolio)"
    )
    if title is None:
        title = (
            f"Episode {asset_label} — peak {episode.peak_date}, "
            f"drawdown {format_pct(episode.drawdown_pct)}"
        )

    charts_html = _render_charts_section(charts, symbol_names)

    # KPI strip — 5 deterministic facts (Phase 0.10.i, ADR §14)
    kpi_strip = _render_kpi_strip(episode, trades)

    # Episode meta — formatted (Phase 0.10.h~i)
    meta_rows = [
        ("asset", asset_label),
        ("peak_date", format_date(episode.peak_date)),
        ("peak_value", format_money(episode.peak_value)),
        ("trough_date", format_date(episode.trough_date)),
        ("trough_value", format_money(episode.trough_value)),
        ("drawdown_pct", format_pct(episode.drawdown_pct)),
        (
            "recovery_date",
            format_date(episode.recovery_date)
            if episode.recovery_date else "(none)",
        ),
        ("recovered", "yes" if episode.recovered else "no"),
        ("duration_days", f"{episode.duration_days}일"),
    ]
    episode_meta_rows = "\n".join(
        f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>"
        for k, v in meta_rows
    )

    # Renderer panels (existing strategy diagnostics)
    panels_html_parts = []
    for p in panels:
        rows_html = "\n".join(
            f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>"
            for k, v in p.rows
        ) or '<tr><td colspan="2"><em>(no rows)</em></td></tr>'
        panels_html_parts.append(
            f"<h2>{escape(p.title)}</h2>\n<table>\n{rows_html}\n</table>"
        )
    panels_html = "\n".join(panels_html_parts)

    # Per-symbol details + cycle pairing (Phase 0.10.j)
    symbol_groups_html = _render_symbol_groups(trades, symbol_names)

    # Trade log (Phase 0.10.h — formatters + annotation mini-table)
    if trades:
        trade_rows = "\n".join(
            _render_trade_row(t, symbol_names) for t in trades
        )
    else:
        trade_rows = (
            '<tr><td colspan="6"><em>(no trades in episode)</em></td></tr>'
        )

    html = _EPISODE_HTML_TEMPLATE.format(
        title=escape(title),
        strategy_info_html=_render_strategy_info_section(strategy_info),
        kpi_strip=kpi_strip,
        risk_metrics_html=_render_risk_adjusted_metrics(risk_metrics),
        episode_meta_rows=episode_meta_rows,
        charts_html=charts_html,
        panels_html=panels_html,
        symbol_groups_html=symbol_groups_html,
        trade_count=len(trades),
        trade_rows=trade_rows,
    )

    output_path.write_text(html, encoding="utf-8")


def write_index_html(
    episodes: Sequence[DrawdownEpisode],
    episode_paths: Sequence[Path],
    output_path: Path,
    *,
    title: str = "Backtest Drawdown Episodes",
    strategy_info: StrategyInfo | None = None,
) -> None:
    """Index page — 모든 episode 링크 + aggregate 요약.

    Args:
        episodes: episode list (peak_date 오름차순 권장)
        episode_paths: 각 episode 의 HTML 파일 경로 — index 위치 기준
            상대 경로 권장 (예: "episode_1.html")
        output_path: index.html 경로
        title: 페이지 title

    Raises:
        ValueError: episodes 와 episode_paths 길이 불일치.
    """
    if len(episodes) != len(episode_paths):
        raise ValueError(
            f"episodes ({len(episodes)}) and episode_paths "
            f"({len(episode_paths)}) length mismatch"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not episodes:
        rows = '<tr><td colspan="8"><em>(no episodes)</em></td></tr>'
        aggregate_html = ""
    else:
        rows = "\n".join(
            f"<tr>"
            f"<td>{i + 1}</td>"
            f"<td>{escape(ep.asset_code or '(portfolio)')}</td>"
            f"<td>{format_date(ep.peak_date)}</td>"
            f"<td>{format_date(ep.trough_date)}</td>"
            f'<td class="dd">{format_pct(ep.drawdown_pct)}</td>'
            f'<td class="recovered-{"yes" if ep.recovered else "no"}">'
            f'{"yes" if ep.recovered else "no"}</td>'
            f"<td>{ep.duration_days}일</td>"
            f'<td><a href="{escape(str(p))}">상세</a></td>'
            f"</tr>"
            for i, (ep, p) in enumerate(
                zip(episodes, episode_paths, strict=True)
            )
        )
        aggregate_html = _render_index_aggregate(episodes)

    html = _INDEX_HTML_TEMPLATE.format(
        title=escape(title),
        strategy_info_html=_render_strategy_info_section(strategy_info),
        count=len(episodes),
        aggregate_html=aggregate_html,
        rows=rows,
    )
    output_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# KPI strip (Phase 0.10.i)
# ---------------------------------------------------------------------------

def _render_kpi_strip(
    episode: DrawdownEpisode, trades: Sequence[TradeView],
) -> str:
    """5 deterministic facts only (synth #5 + Critic patch C1):

    1. drawdown_pct
    2. duration_days
    3. recovered (yes/no badge)
    4. total trades (buys/sells split)
    5. total invested (Σ buy ``actual_cost`` annotation, fallback price * qty)

    Realized P&L 은 KPI strip 에 미포함 — 종목별 cycle table 안에서만 표시.
    """
    n_buys = sum(1 for t in trades if t.side == "BUY")
    n_sells = sum(1 for t in trades if t.side == "SELL")
    total_invested = _sum_total_invested(trades)
    recovered_class = "recovered-yes" if episode.recovered else "recovered-no"
    recovered_text = "yes" if episode.recovered else "no"

    cards = [
        ("Drawdown", format_pct(episode.drawdown_pct), ""),
        ("Duration", f"{episode.duration_days}일", ""),
        ("Recovered", recovered_text, recovered_class),
        ("Trades", f"{n_buys} buys / {n_sells} sells", ""),
        ("Invested", format_money(total_invested), ""),
    ]
    parts = ['<div class="kpi-strip">']
    for label, value, extra_class in cards:
        cls = f"value {extra_class}".strip()
        parts.append(
            f'<div class="kpi"><div class="label">{escape(label)}</div>'
            f'<div class="{cls}">{escape(value)}</div></div>'
        )
    parts.append("</div>")
    return "\n".join(parts)


def _sum_total_invested(trades: Sequence[TradeView]) -> Decimal:
    """Σ buy actual_cost (annotation), fallback price*quantity 시.

    actual_cost annotation 미존재 시 price * quantity 로 계산.
    """
    total = Decimal(0)
    for t in trades:
        if t.side != "BUY":
            continue
        cost = t.annotations.get("actual_cost")
        if cost is not None:
            try:
                total += _to_decimal(cost)
                continue
            except (InvalidOperation, TypeError, ValueError):
                pass
        total += t.price * t.quantity
    return total


# ---------------------------------------------------------------------------
# Per-symbol groups + cycle table (Phase 0.10.j)
# ---------------------------------------------------------------------------

def _render_symbol_groups(
    trades: Sequence[TradeView],
    symbol_names: Mapping[str, str] | None,
) -> str:
    """Render per-symbol ``<details>`` groups with cycle pairing summary.

    각 종목 그룹 안에 cycle mini-table (entry / exit / qty / entry_price /
    exit_price / hold_days / realized_pnl (FIFO 표시) / pnl_pct).
    """
    if not trades:
        return ""

    # Preserve symbol-first-seen order
    by_symbol: dict[str, list[TradeView]] = {}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t)

    parts = ["<h2>종목별 사이클 (FIFO 표시)</h2>"]
    for symbol, sym_trades in by_symbol.items():
        n_buys = sum(1 for t in sym_trades if t.side == "BUY")
        n_sells = sum(1 for t in sym_trades if t.side == "SELL")
        cycles = pair_cycles(sym_trades)
        parts.append(_render_symbol_details(
            symbol, sym_trades, cycles, n_buys, n_sells, symbol_names,
        ))
    return "\n".join(parts)


def _render_symbol_details(
    symbol: str,
    sym_trades: Sequence[TradeView],
    cycles: Sequence[Cycle],
    n_buys: int,
    n_sells: int,
    symbol_names: Mapping[str, str] | None,
) -> str:
    label = display_symbol(symbol, symbol_names)
    closed_cycles = [c for c in cycles if c.exit_date is not None]
    closed_pnl_total = sum(
        (c.realized_pnl for c in closed_cycles
         if c.realized_pnl is not None),
        Decimal(0),
    )
    summary_pnl = (
        f' · realized {format_money(closed_pnl_total)}'
        if closed_cycles else ""
    )
    summary = (
        f"{escape(label)} "
        f'<span class="label-badge">{n_buys} buys / {n_sells} sells'
        f"{escape(summary_pnl)}</span>"
    )

    if not cycles:
        body = "<p><em>(no cycles)</em></p>"
    else:
        rows = [_render_cycle_row(c) for c in cycles]
        body = (
            '<table class="cycle-table">\n<thead>'
            "<tr><th>entry_date</th><th>exit_date</th><th>quantity</th>"
            "<th>entry_price</th><th>exit_price</th><th>hold_days</th>"
            "<th>realized_pnl (FIFO 표시)</th><th>pnl_pct</th></tr>"
            "</thead>\n<tbody>\n"
            + "\n".join(rows)
            + "\n</tbody></table>"
        )

    return (
        '<details class="symbol-group" open>'
        f"<summary>{summary}</summary>\n{body}\n</details>"
    )


def _render_cycle_row(cycle: Cycle) -> str:
    entry_date_str = (
        format_date(cycle.entry_date) if cycle.entry_date
        else "(매칭 BUY 없음)"
    )
    exit_date_str = (
        format_date(cycle.exit_date) if cycle.exit_date else "(open)"
    )
    qty_str = format_quantity(cycle.quantity)
    entry_price_str = (
        format_price(cycle.entry_price) if cycle.entry_price is not None
        else "—"
    )
    exit_price_str = (
        format_price(cycle.exit_price) if cycle.exit_price is not None
        else "—"
    )
    hold_days_str = (
        f"{cycle.hold_days}일" if cycle.hold_days is not None else "—"
    )
    if cycle.realized_pnl is None:
        pnl_str = '<span class="cycle-pnl-na">—</span>'
        pnl_pct_str = '<span class="cycle-pnl-na">—</span>'
    else:
        pnl_class = (
            "cycle-pnl-pos" if cycle.realized_pnl >= 0 else "cycle-pnl-neg"
        )
        pnl_str = (
            f'<span class="{pnl_class}">'
            f"{escape(format_money(cycle.realized_pnl))}</span>"
        )
        pct_value = (
            cycle.realized_pnl_pct if cycle.realized_pnl_pct is not None
            else Decimal(0)
        )
        pnl_pct_str = (
            f'<span class="{pnl_class}">'
            f"{escape(format_pct(pct_value))}</span>"
        )
    return (
        f"<tr>"
        f"<td>{escape(entry_date_str)}</td>"
        f"<td>{escape(exit_date_str)}</td>"
        f"<td>{escape(qty_str)}</td>"
        f"<td>{escape(entry_price_str)}</td>"
        f"<td>{escape(exit_price_str)}</td>"
        f"<td>{escape(hold_days_str)}</td>"
        f"<td>{pnl_str}</td>"
        f"<td>{pnl_pct_str}</td>"
        f"</tr>"
    )


# ---------------------------------------------------------------------------
# Trade row + annotation mini-table (Phase 0.10.h)
# ---------------------------------------------------------------------------

def _render_trade_row(
    trade: TradeView, symbol_names: Mapping[str, str] | None,
) -> str:
    return (
        f"<tr>"
        f"<td>{escape(format_datetime_kst(trade.timestamp))}</td>"
        f"<td>{escape(display_symbol(trade.symbol, symbol_names))}</td>"
        f'<td class="side-{trade.side.lower()}">{escape(trade.side)}</td>'
        f"<td>{escape(format_price(trade.price))}</td>"
        f"<td>{escape(format_quantity(trade.quantity))}</td>"
        f"<td>{_render_annotation_table(trade.annotations)}</td>"
        f"</tr>"
    )


_PRICE_KEYS: frozenset[str] = frozenset(
    {
        "entry_price", "current_price", "trigger_price",
        "target_price", "last_exit_price",
    }
)
_PCT_KEYS: frozenset[str] = frozenset({"profit_pct", "profit_target_pct"})
_QUANTITY_KEYS: frozenset[str] = frozenset({"target_quantity"})
_MONEY_KEYS: frozenset[str] = frozenset({"actual_cost"})
_DATE_KEYS: frozenset[str] = frozenset({"last_exit_date"})
# Phase 0.10.bb (ADR 0006 §18.B): legacy `split_number` removed (pre-Phase
# 0.5 renderer fossil, dead code after Phase 0.10.z uniform `slot_number`
# annotation enrichment). §16.7 reverse rationale: future renderer that
# emits `split_number` directly can re-add via factory or ad-hoc; carrying
# vestigial key in shipped contract masks the intent.
_INT_KEYS: frozenset[str] = frozenset({"slot_number"})


def _render_annotation_table(annotations: Mapping[str, Any]) -> str:
    """Render annotations as a mini-table with per-key formatter dispatch.

    알려진 key (price / pct / quantity / money / date / int) 는 적절한
    formatter 적용. 미지의 key 는 escape 후 monospace span 으로 표기 —
    strategy-agnostic.
    """
    if not annotations:
        return '<span class="annot-empty">—</span>'
    rows = []
    for k, v in annotations.items():
        formatted = _format_annotation_value(k, v)
        rows.append(f"<tr><th>{escape(k)}</th><td>{formatted}</td></tr>")
    return (
        '<table class="annot-mini"><tbody>\n'
        + "\n".join(rows)
        + "\n</tbody></table>"
    )


def _format_annotation_value(key: str, value: Any) -> str:
    try:
        if key in _PRICE_KEYS:
            return escape(format_price(_to_decimal(value)))
        if key in _PCT_KEYS:
            return escape(format_pct(_to_decimal(value)))
        if key in _QUANTITY_KEYS:
            return escape(format_quantity(_to_decimal(value)))
        if key in _MONEY_KEYS:
            return escape(format_money(_to_decimal(value)))
        if key in _DATE_KEYS:
            return escape(_to_date_str(value))
        if key in _INT_KEYS:
            return escape(str(int(_to_decimal(value))))
    except (InvalidOperation, ValueError, TypeError):
        pass
    return f'<span class="annot-raw">{escape(str(value))}</span>'


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return Decimal(str(value))


def _to_date_str(value: Any) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return format_date(value)
    if isinstance(value, datetime):
        return format_date(value.date())
    s = str(value)
    try:
        return format_date(date.fromisoformat(s))
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# Index page aggregate (Phase 0.10.k)
# ---------------------------------------------------------------------------

def _render_charts_section(
    charts: Sequence[tuple[str, bytes]],
    symbol_names: Mapping[str, str] | None,
) -> str:
    """Render per-symbol chart panel stack (Phase 0.10.aa, ADR §17).

    Each chart wrapped in ``<details class="chart-symbol" open>`` with
    ``<summary>차트 — {display_symbol(code)}</summary>`` consistent with the
    per-symbol cycle group pattern (`html_writer.py:.symbol-group`).

    Empty ``charts`` → returns ``""`` (caller controlled via
    ``skip_empty_symbols`` in ``generate_episode_report``).
    """
    if not charts:
        return '<p><em>(no chart panels)</em></p>'
    parts = []
    for symbol, png_bytes in charts:
        b64 = base64.b64encode(png_bytes).decode("ascii")
        label = display_symbol(symbol, symbol_names)
        parts.append(
            f'<details class="chart-symbol" open>'
            f"<summary>차트 — {escape(label)}</summary>\n"
            f'<img src="data:image/png;base64,{b64}" '
            f'alt="Episode chart for {escape(symbol)}">\n'
            "</details>"
        )
    return "\n".join(parts)


def _render_risk_adjusted_metrics(
    metrics: EpisodeRiskMetrics | None,
) -> str:
    """Render Risk-Adjusted Metrics section (Phase 0.10.bb / ADR §18.C).

    Section-level omit (NOT row-level N/A) per Phase 0.10.x §14.7 "silent
    N/A 거부" 정신. None → returns ``""`` (NO ``Risk-Adjusted Metrics``
    substring), 모든 field None → also returns ``""``.

    Field-level None vs Decimal(0): factory ``risk_metrics.py`` 가 이미
    None 으로 wrap (degenerate σ/MDD/recovery). 본 helper 는 None field
    를 row 에서 omit.
    """
    if metrics is None:
        return ""
    # All-None field set → section omit (caller invariant — factory should
    # have returned None, but defensive guard preserves AC-C5 contract).
    if (
        metrics.sharpe is None
        and metrics.calmar is None
        and metrics.recovery_efficiency is None
    ):
        return ""

    rows: list[tuple[str, str]] = []
    if metrics.sharpe is not None:
        rows.append(("Sharpe (episode 내)", f"{metrics.sharpe:.4f}"))
    if metrics.calmar is not None:
        rows.append(("Calmar (episode 내)", f"{metrics.calmar:.4f}"))
    if metrics.recovery_efficiency is not None:
        rows.append((
            "Recovery efficiency",
            f"{metrics.recovery_efficiency:.4f}",
        ))

    metric_html = "\n".join(
        f'<div class="metric"><div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(value)}</div></div>'
        for label, value in rows
    )
    return (
        '<div class="risk-metrics">\n'
        '<h3>Risk-Adjusted Metrics</h3>\n'
        '<div class="metrics-row">\n'
        f"{metric_html}\n"
        "</div>\n"
        "</div>"
    )


def _render_strategy_info_section(info: StrategyInfo | None) -> str:
    """전략 정보 section (Phase 0.10.y §15.5).

    8 rows in fixed order — wrapped in `<details class="strategy-info" open>`
    (Patch S1, mirrors per-symbol details pattern).

    None → returns "" (backwards-compat: AC12).
    """
    if info is None:
        return ""

    n_assets = len(info.asset_codes)
    asset_codes_str = ", ".join(info.asset_codes)
    asset_summary = (
        f"{escape(asset_codes_str)} "
        f"({n_assets} 종목 동일 정책 (loader-enforced uniformity))"
    )

    rows = [
        ("매수 전략", escape(info.buy_strategy_name)),
        ("매수 파라미터", _format_param_kv(info.buy_parameters)),
        ("매도 전략", escape(info.sell_strategy_name)),
        ("매도 파라미터", _format_param_kv(info.sell_parameters)),
        ("재진입 전략", escape(info.reentry_strategy_name)),
        ("재진입 파라미터", _format_param_kv(info.reentry_parameters)),
        ("적용 종목", asset_summary),
        ("설정 파일", escape(info.config_source)),
    ]
    body = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{value}</td></tr>"
        for label, value in rows
    )
    return (
        '<details class="strategy-info" open>'
        "<summary>전략 정보</summary>\n"
        f"<table>\n{body}\n</table>\n"
        "</details>"
    )


def _format_param_kv(params: Mapping[str, str]) -> str:
    """Render dict[str, str] as `key=value, key=value` (already escaped values).

    The values come from StrategyInfo factory which produces display-ready
    strings (e.g. "5.00%", "₩5,000,000"). Escape both sides for HTML safety.
    """
    if not params:
        return "<em>(none)</em>"
    return ", ".join(
        f"{escape(k)}={escape(v)}" for k, v in params.items()
    )


def _render_index_aggregate(episodes: Sequence[DrawdownEpisode]) -> str:
    """4-bullet aggregate row for index page."""
    n = len(episodes)
    n_recovered = sum(1 for ep in episodes if ep.recovered)
    avg_duration = (
        sum(ep.duration_days for ep in episodes) // n if n else 0
    )
    max_dd = min(ep.drawdown_pct for ep in episodes)  # most negative
    recovered_pct = (
        format_pct(
            Decimal(n_recovered) / Decimal(n) * Decimal(100), signed=False,
        )
        if n else "0.00%"
    )

    items = [
        f"총 episode: {n}",
        f"평균 duration: {avg_duration}일",
        f"recovered ratio: {n_recovered}/{n} ({recovered_pct})",
        f"max drawdown: {format_pct(max_dd)}",
    ]
    lis = "\n".join(f"<li>{escape(s)}</li>" for s in items)
    return f'<div class="aggregate"><ul>\n{lis}\n</ul></div>'
