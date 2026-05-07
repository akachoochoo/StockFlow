"""HTML report writer (Phase 0.10 — ADR 0006 §7).

stdlib f-string template — episode 1 페이지 HTML + index page. jinja2
미도입 (CLAUDE.md "친절한 추가 금지" + ADR 0006 §7.2 박제).

리포트 1 페이지 구성:
- 차트 (PNG base64 embed)
- Episode 메타데이터 테이블 (peak / trough / recovery / duration / drawdown_pct)
- 전략별 진단 패널 (renderer.diagnostic_panels 결과)
- 거래 로그 (TradeView list)

Index page: 모든 episode 링크 + 요약.
"""
from __future__ import annotations

import base64
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from src.application.reporting.episode import DrawdownEpisode
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
table {{ border-collapse: collapse; margin: 10px 0; min-width: 50%; }}
th, td {{ padding: 6px 12px; border: 1px solid #ddd; text-align: left;
          font-size: 14px; }}
th {{ background: #f8f9fa; font-weight: 600; }}
.chart {{ margin: 20px 0; }}
.chart img {{ max-width: 100%; height: auto; border: 1px solid #ddd; }}
.recovered-yes {{ color: #27ae60; font-weight: 600; }}
.recovered-no  {{ color: #c0392b; font-weight: 600; }}
.side-buy  {{ color: #27ae60; font-weight: 600; }}
.side-sell {{ color: #c0392b; font-weight: 600; }}
.annot {{ font-family: monospace; font-size: 12px; color: #7f8c8d; }}
</style>
</head>
<body>
<h1>{title}</h1>

<h2>Episode 메타데이터</h2>
<table>
{episode_meta_rows}
</table>

<div class="chart">
<h2>차트</h2>
<img src="data:image/png;base64,{chart_b64}" alt="Episode chart">
</div>

{panels_html}

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
</style>
</head>
<body>
<h1>{title}</h1>
<p>총 {count} 개 episode.</p>
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
    chart_png: bytes,
    trades: Sequence[TradeView],
    panels: Sequence[Panel],
    output_path: Path,
    *,
    title: str | None = None,
) -> None:
    """Episode 1 페이지 HTML 작성.

    Args:
        episode: DrawdownEpisode
        chart_png: render_episode_chart() 결과 (PNG bytes, base64 embed)
        trades: 거래 로그 (전체 또는 episode 구간 — 호출자가 필터)
        panels: 전략별 진단 패널 (renderer.diagnostic_panels 결과)
        output_path: 출력 HTML 경로 (parent dirs 자동 생성)
        title: 페이지 title (None 시 episode 메타로 자동 생성)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    asset_label = episode.asset_code or "(portfolio)"
    if title is None:
        title = (
            f"Episode {asset_label} — peak {episode.peak_date}, "
            f"drawdown {episode.drawdown_pct:+.4f}%"
        )

    chart_b64 = base64.b64encode(chart_png).decode("ascii")

    # Episode meta
    meta_rows = [
        ("asset", asset_label),
        ("peak_date", str(episode.peak_date)),
        ("peak_value", str(episode.peak_value)),
        ("trough_date", str(episode.trough_date)),
        ("trough_value", str(episode.trough_value)),
        ("drawdown_pct", f"{episode.drawdown_pct:+.4f}%"),
        (
            "recovery_date",
            str(episode.recovery_date) if episode.recovery_date else "(none)",
        ),
        ("recovered", "yes" if episode.recovered else "no"),
        ("duration_days", str(episode.duration_days)),
    ]
    episode_meta_rows = "\n".join(
        f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>"
        for k, v in meta_rows
    )

    # Panels
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

    # Trades
    if trades:
        trade_rows = "\n".join(
            f"<tr>"
            f"<td>{escape(t.timestamp.isoformat())}</td>"
            f"<td>{escape(t.symbol)}</td>"
            f'<td class="side-{t.side.lower()}">{escape(t.side)}</td>'
            f"<td>{escape(str(t.price))}</td>"
            f"<td>{escape(str(t.quantity))}</td>"
            f'<td class="annot">{escape(_format_annotations(t.annotations))}</td>'
            f"</tr>"
            for t in trades
        )
    else:
        trade_rows = '<tr><td colspan="6"><em>(no trades in episode)</em></td></tr>'

    html = _EPISODE_HTML_TEMPLATE.format(
        title=escape(title),
        episode_meta_rows=episode_meta_rows,
        chart_b64=chart_b64,
        panels_html=panels_html,
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
) -> None:
    """Index page — 모든 episode 링크 + 요약 표.

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
    else:
        rows = "\n".join(
            f"<tr>"
            f"<td>{i + 1}</td>"
            f"<td>{escape(ep.asset_code or '(portfolio)')}</td>"
            f"<td>{ep.peak_date}</td>"
            f"<td>{ep.trough_date}</td>"
            f'<td class="dd">{ep.drawdown_pct:+.4f}%</td>'
            f'<td class="recovered-{"yes" if ep.recovered else "no"}">'
            f'{"yes" if ep.recovered else "no"}</td>'
            f"<td>{ep.duration_days}</td>"
            f'<td><a href="{escape(str(p))}">상세</a></td>'
            f"</tr>"
            for i, (ep, p) in enumerate(
                zip(episodes, episode_paths, strict=True)
            )
        )

    html = _INDEX_HTML_TEMPLATE.format(
        title=escape(title), count=len(episodes), rows=rows,
    )
    output_path.write_text(html, encoding="utf-8")


def _format_annotations(annotations: Mapping[str, object]) -> str:
    if not annotations:
        return "—"
    return ", ".join(f"{k}={v}" for k, v in annotations.items())
