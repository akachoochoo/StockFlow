"""Portfolio flow HTML report — ECharts stacked area visualization (viz tool).

자본 흐름을 시간 축으로 시각화: 예수금(idle cash) + 종목별 시가(보유x종가) + 누적
실현 수익. cooldown OFF vs ON 두 config 를 한 페이지에 위·아래로 비교.

ECharts 5.4.3 vendored (`src/research/dgt/assets/echarts.min.js`, ~1 MB) —
self-contained offline-openable HTML 와 동일 패턴(lightweight-charts).

Architecture: research overlay 5th ring. ``GridPortfolioResult`` (use_case) 만
읽음 — outer→inner. domain/use_case 무변경.
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from src.domain.models import OrderSide

if TYPE_CHECKING:
    from src.application.grid_portfolio_backtest import GridPortfolioResult

_ASSETS_DIR = Path(__file__).parent / "assets"


def _load_echarts_js() -> str:
    """Read vendored ECharts JS (Apache 2.0). SHA-256 박제 = PROVENANCE-echarts.txt."""
    return (_ASSETS_DIR / "echarts.min.js").read_text(encoding="utf-8")


def _serialize_port(port: GridPortfolioResult) -> dict[str, object]:
    """GridPortfolioResult → JSON-safe dict 시계열 (ECharts 입력)."""
    common = sorted({d for d, _ in port.daily_values})
    # 예수금 = Σ asset.cash + unallocated (per common date)
    cash_by_d = []
    for d in common:
        c = port.unallocated
        for run in port.per_asset:
            for dv in run.result.daily_values:
                if dv.trade_date == d:
                    c += dv.cash
                    break
        cash_by_d.append(c)

    # 종목별 시가 = holdings_t x close_t (per common date)
    stocks = []
    for run in port.per_asset:
        d_to_v = {
            dv.trade_date: dv.holdings * dv.close_price
            for dv in run.result.daily_values
        }
        stocks.append({
            "name": run.asset.code,
            "values": [int(d_to_v.get(d, Decimal("0"))) for d in common],
        })

    # 누적 실현 수익 by date (평균원가법)
    by_date: dict = defaultdict(lambda: Decimal("0"))
    for run in port.per_asset:
        hold = Decimal("0")
        cost_basis = Decimal("0")
        for t in run.result.trades:
            if t.side is OrderSide.BUY:
                cost_basis += -t.cash_delta
                hold += t.quantity
            else:
                basis_sold = (
                    cost_basis / hold * t.quantity if hold > 0 else Decimal("0")
                )
                by_date[t.trade_date] += t.cash_delta - basis_sold
                cost_basis -= basis_sold
                hold -= t.quantity
    cum = Decimal("0")
    realized_cum = []
    for d in common:
        cum += by_date.get(d, Decimal("0"))
        realized_cum.append(int(cum))

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in common],
        "cash": [int(c) for c in cash_by_d],
        "stocks": stocks,
        "realized_cum": realized_cum,
        "initial_capital": int(port.initial_capital.amount),
        "final_value": int(port.final_value),
    }


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font: 14px/1.5 system-ui, sans-serif; background: #1a1a2e;
            color: #eee; min-height: 100vh; }}
    h1 {{ padding: 14px 18px; font-size: 14px; font-weight: 600;
          color: #a8b2d8; border-bottom: 1px solid #2d2d4e; }}
    .section {{ padding: 10px 18px 6px; }}
    .section h2 {{ font-size: 13px; color: #a8b2d8; margin-bottom: 4px;
                   font-weight: 600; }}
    .section .stats {{ font-size: 12px; color: #c8cee8; margin-bottom: 6px; }}
    .stats b {{ color: #fac858; margin-right: 5px; }}
    .chart {{ width: 100%; height: 460px; }}
  </style>
  <script>{echarts_js}</script>
</head>
<body>
  <h1>{title_html}</h1>
  <div class="section">
    <h2>OFF (cooldown=0)</h2>
    <div class="stats">{off_stats}</div>
    <div id="chart-off" class="chart"></div>
  </div>
  <div class="section">
    <h2>ON (cooldown=5)</h2>
    <div class="stats">{on_stats}</div>
    <div id="chart-on" class="chart"></div>
  </div>
  <script type="application/json" id="data-off">{off_json}</script>
  <script type="application/json" id="data-on">{on_json}</script>
  <script>
{init_script}
  </script>
</body>
</html>
"""


_INIT_SCRIPT = r"""
const COLORS = ['#5470c6','#91cc75','#ee6666','#73c0de','#3ba272','#fc8452','#9a60b4','#ea7ccc','#d48265','#749f83'];
function fmtKRW(v) {
  if (v === null || v === undefined) return '';
  const a = Math.abs(v);
  if (a >= 1e8) return (v/1e8).toFixed(2) + '억';
  if (a >= 1e4) return (v/1e4).toFixed(1) + '만';
  return Math.round(v).toLocaleString();
}
function buildOption(data) {
  const stockSeries = data.stocks.map((s, i) => ({
    name: s.name,
    type: 'line',
    stack: 'asset',
    areaStyle: { opacity: 0.85 },
    emphasis: { focus: 'series' },
    symbol: 'none',
    lineStyle: { width: 0 },
    data: s.values,
    color: COLORS[i % COLORS.length],
  }));
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(45,45,78,0.95)',
      borderColor: '#444',
      textStyle: { color: '#eee', fontSize: 12 },
      valueFormatter: fmtKRW,
    },
    legend: {
      textStyle: { color: '#c8cee8' },
      type: 'scroll',
      top: 8,
      itemWidth: 12,
      itemHeight: 8,
    },
    grid: { left: 60, right: 70, top: 50, bottom: 36 },
    xAxis: {
      type: 'category',
      data: data.dates,
      boundaryGap: false,
      axisLabel: { color: '#888' },
      axisLine: { lineStyle: { color: '#444' } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'KRW',
        nameTextStyle: { color: '#a8b2d8' },
        axisLabel: { color: '#888', formatter: fmtKRW },
        axisLine: { show: true, lineStyle: { color: '#444' } },
        splitLine: { lineStyle: { color: '#2d2d4e' } },
      },
      {
        type: 'value',
        name: '누적 실현',
        nameTextStyle: { color: '#fac858' },
        position: 'right',
        axisLabel: { color: '#fac858', formatter: fmtKRW },
        axisLine: { show: true, lineStyle: { color: '#fac858' } },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '예수금',
        type: 'line',
        stack: 'asset',
        areaStyle: { opacity: 0.6, color: '#5a6488' },
        symbol: 'none',
        lineStyle: { width: 0 },
        data: data.cash,
        color: '#5a6488',
      },
      ...stockSeries,
      {
        name: '누적 실현',
        type: 'line',
        yAxisIndex: 1,
        symbol: 'none',
        lineStyle: { color: '#fac858', width: 2, type: 'dashed' },
        data: data.realized_cum,
        color: '#fac858',
        z: 10,
      },
      {
        name: '초기자본',
        type: 'line',
        data: [],
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: '#a8b2d8', type: 'dotted', width: 1 },
          label: { show: true, position: 'insideEndTop', color: '#a8b2d8',
                   formatter: '초기자본 ' + fmtKRW(data.initial_capital) },
          data: [{ yAxis: data.initial_capital }],
        },
      },
    ],
  };
}
const off = JSON.parse(document.getElementById('data-off').textContent);
const on  = JSON.parse(document.getElementById('data-on').textContent);
const chartOff = echarts.init(document.getElementById('chart-off'), null, { renderer: 'canvas' });
const chartOn  = echarts.init(document.getElementById('chart-on'),  null, { renderer: 'canvas' });
chartOff.setOption(buildOption(off));
chartOn.setOption(buildOption(on));
window.addEventListener('resize', () => { chartOff.resize(); chartOn.resize(); });
"""


def _stats_line(data: dict) -> str:
    init = data["initial_capital"]
    final = data["final_value"]
    realized = data["realized_cum"][-1] if data["realized_cum"] else 0
    ret_pct = (final - init) / init * 100 if init > 0 else 0
    parts = [
        f"<b>최종</b>{final:,} KRW",
        f"<b>수익</b>{ret_pct:+.2f}%",
        f"<b>누적 실현</b>{realized:+,} KRW",
        f"<b>종목 수</b>{len(data['stocks'])}",
    ]
    return " · ".join(parts)


def build_portfolio_flow_html(
    *,
    off_port: GridPortfolioResult,
    on_port: GridPortfolioResult,
    title: str,
) -> str:
    """OFF/ON portfolio flow 비교 HTML (ECharts stacked area).

    두 ``GridPortfolioResult`` 를 한 페이지에 위·아래로 비교: 자본 흐름(예수금 +
    종목별 시가 stack) + 누적 실현 수익 라인 + 초기자본 markLine. ECharts JS 는
    inline embed (offline-openable, self-contained).
    """
    off_data = _serialize_port(off_port)
    on_data = _serialize_port(on_port)
    return _PAGE_TEMPLATE.format(
        title=escape(title),
        title_html=escape(title),
        echarts_js=_load_echarts_js(),
        off_json=json.dumps(off_data, ensure_ascii=False),
        on_json=json.dumps(on_data, ensure_ascii=False),
        off_stats=_stats_line(off_data),
        on_stats=_stats_line(on_data),
        init_script=_INIT_SCRIPT,
    )
