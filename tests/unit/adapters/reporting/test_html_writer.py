"""Unit tests for src.adapters.reporting.html_writer (Phase 0.10 — ADR 0006 §7).

Pure stdlib f-string template — episode 1 페이지 HTML + index page.
"""
from __future__ import annotations

import base64
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.adapters.reporting.html_writer import (
    write_episode_html,
    write_index_html,
)
from src.application.reporting.episode import DrawdownEpisode
from src.application.reporting.trade_view import TradeView
from src.ports.strategy_renderer import Panel


def _episode(
    *,
    asset_code: str | None = None,
    recovered: bool = True,
) -> DrawdownEpisode:
    return DrawdownEpisode(
        peak_date=date(2024, 1, 1),
        peak_value=Decimal("100"),
        trough_date=date(2024, 1, 5),
        trough_value=Decimal("85"),
        recovery_date=date(2024, 1, 10) if recovered else None,
        recovered=recovered,
        drawdown_pct=Decimal("-15.0000"),
        duration_days=9 if recovered else 30,
        asset_code=asset_code,
    )


def _trade(
    *,
    side: str = "BUY",
    timestamp: datetime | None = None,
    annotations: dict[str, str] | None = None,
) -> TradeView:
    return TradeView(
        timestamp=timestamp or datetime(2024, 1, 5, 6, 0, 0, tzinfo=UTC),
        symbol="069500",
        side=side,  # type: ignore[arg-type]
        price=Decimal("90"),
        quantity=Decimal("10"),
        strategy_id="price_drop",
        annotations=annotations or {},
    )


# Tiny PNG header bytes for chart embed test
_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_TINY_PNG = _PNG_HEADER + b"\x00" * 50


class TestWriteEpisodeHtml:
    def test_writes_file(self, tmp_path: Path):
        out = tmp_path / "episode_1.html"
        write_episode_html(_episode(), _TINY_PNG, [], [], out)
        assert out.exists()
        assert out.is_file()

    def test_creates_parent_dirs(self, tmp_path: Path):
        out = tmp_path / "deep" / "nested" / "dir" / "ep.html"
        write_episode_html(_episode(), _TINY_PNG, [], [], out)
        assert out.exists()

    def test_includes_title(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(
            _episode(asset_code="005930"), _TINY_PNG, [], [], out,
        )
        html = out.read_text(encoding="utf-8")
        assert "005930" in html
        assert "2024-01-01" in html  # peak_date

    def test_custom_title(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(
            _episode(), _TINY_PNG, [], [], out, title="Custom Title 42",
        )
        html = out.read_text(encoding="utf-8")
        assert "<title>Custom Title 42</title>" in html
        assert "<h1>Custom Title 42</h1>" in html

    def test_episode_meta_table(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(_episode(), _TINY_PNG, [], [], out)
        html = out.read_text(encoding="utf-8")
        assert "Episode 메타데이터" in html
        assert "<th>peak_date</th><td>2024-01-01</td>" in html
        assert "<th>trough_date</th><td>2024-01-05</td>" in html
        # AC1: places <= 2; AC2: KRW thousand separator
        assert "-15.00%" in html
        assert "<th>peak_value</th><td>₩100</td>" in html
        assert "<th>recovered</th><td>yes</td>" in html
        assert "<th>duration_days</th><td>9일</td>" in html

    def test_unrecovered_episode_meta(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(
            _episode(recovered=False), _TINY_PNG, [], [], out,
        )
        html = out.read_text(encoding="utf-8")
        assert "<th>recovered</th><td>no</td>" in html
        assert "<th>recovery_date</th><td>(none)</td>" in html

    def test_chart_base64_embed(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(_episode(), _TINY_PNG, [], [], out)
        html = out.read_text(encoding="utf-8")
        expected_b64 = base64.b64encode(_TINY_PNG).decode("ascii")
        assert f"data:image/png;base64,{expected_b64}" in html

    def test_panels_rendered(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        panels = [
            Panel(
                title="Episode 요약",
                rows=[("total buys", "5"), ("total sells", "3")],
            ),
            Panel(
                title="차수별 거래 횟수",
                rows=[("slot 1", "buys=2 / sells=1")],
            ),
        ]
        write_episode_html(_episode(), _TINY_PNG, [], panels, out)
        html = out.read_text(encoding="utf-8")
        assert "<h2>Episode 요약</h2>" in html
        assert "<th>total buys</th><td>5</td>" in html
        assert "<h2>차수별 거래 횟수</h2>" in html
        assert "<th>slot 1</th><td>buys=2 / sells=1</td>" in html

    def test_panels_empty_rows(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(
            _episode(),
            _TINY_PNG,
            [],
            [Panel(title="Empty", rows=[])],
            out,
        )
        html = out.read_text(encoding="utf-8")
        assert "<h2>Empty</h2>" in html
        assert "no rows" in html

    def test_trades_logged(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        trades = [
            _trade(
                side="BUY",
                timestamp=datetime(2024, 1, 5, 6, 0, 0, tzinfo=UTC),
                annotations={"split_number": "2"},
            ),
            _trade(
                side="SELL",
                timestamp=datetime(2024, 1, 8, 6, 0, 0, tzinfo=UTC),
                annotations={"slot_number": "1", "profit_pct": "10.0"},
            ),
        ]
        write_episode_html(_episode(), _TINY_PNG, trades, [], out)
        html = out.read_text(encoding="utf-8")
        assert "거래 로그 (2)" in html
        # AC3: code + name display
        assert "069500 KODEX 200" in html
        # AC8: annotations rendered as mini-table, NOT comma string
        assert "split_number=" not in html  # legacy comma format gone
        assert '<table class="annot-mini">' in html
        assert "<th>split_number</th><td>2</td>" in html
        assert "<th>slot_number</th><td>1</td>" in html
        # AC1: profit_pct formatted to 2 places, signed
        assert "<th>profit_pct</th><td>+10.00%</td>" in html
        # CSS class for side
        assert 'class="side-buy">BUY' in html
        assert 'class="side-sell">SELL' in html

    def test_empty_trades_shows_placeholder(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(_episode(), _TINY_PNG, [], [], out)
        html = out.read_text(encoding="utf-8")
        assert "거래 로그 (0)" in html
        assert "no trades in episode" in html

    def test_html_escaped(self, tmp_path: Path):
        """special chars escaped — XSS / 깨진 HTML 방지."""
        out = tmp_path / "ep.html"
        evil_trade = _trade(annotations={"key": "<script>alert(1)</script>"})
        write_episode_html(_episode(), _TINY_PNG, [evil_trade], [], out)
        html = out.read_text(encoding="utf-8")
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_portfolio_asset_label_default(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(
            _episode(asset_code=None), _TINY_PNG, [], [], out,
        )
        html = out.read_text(encoding="utf-8")
        assert "(portfolio)" in html

    def test_doctype_and_charset(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        write_episode_html(_episode(), _TINY_PNG, [], [], out)
        html = out.read_text(encoding="utf-8")
        assert html.startswith("<!DOCTYPE html>")
        assert 'charset="utf-8"' in html

    def test_kpi_strip_renders(self, tmp_path: Path):
        # AC6 — 5 deterministic KPIs, no realized P&L in top strip.
        out = tmp_path / "ep.html"
        trades = [
            _trade(
                side="BUY",
                timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                annotations={"actual_cost": "9990"},
            ),
            _trade(
                side="SELL",
                timestamp=datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC),
            ),
        ]
        write_episode_html(_episode(), _TINY_PNG, trades, [], out)
        html = out.read_text(encoding="utf-8")
        assert '<div class="kpi-strip">' in html
        # 5 KPI labels — exact text
        for label in ("Drawdown", "Duration", "Recovered", "Trades",
                      "Invested"):
            assert f"<div class=\"label\">{label}</div>" in html, label
        # Trades 카운트 split
        assert "1 buys / 1 sells" in html
        # No realized P&L in top strip
        assert "Realized" not in html

    def test_per_symbol_details_renders(self, tmp_path: Path):
        # AC4 — <details> 그룹 per symbol
        out = tmp_path / "ep.html"
        trades = [
            _trade(
                side="BUY",
                timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
            ),
            _trade(
                side="SELL",
                timestamp=datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC),
            ),
        ]
        write_episode_html(_episode(), _TINY_PNG, trades, [], out)
        html = out.read_text(encoding="utf-8")
        assert '<details class="symbol-group" open>' in html
        # Symbol display name in summary
        assert "069500 KODEX 200" in html
        # FIFO 표시 column header (Critic patch C3)
        assert "realized_pnl (FIFO 표시)" in html

    def test_multi_symbol_groups(self, tmp_path: Path):
        out = tmp_path / "ep.html"
        trades = [
            TradeView(
                timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                symbol="005930", side="BUY", price=Decimal("70000"),
                quantity=Decimal("10"), strategy_id="price_drop",
                annotations={},
            ),
            TradeView(
                timestamp=datetime(2024, 1, 3, 0, 0, 0, tzinfo=UTC),
                symbol="005380", side="BUY", price=Decimal("130000"),
                quantity=Decimal("5"), strategy_id="price_drop",
                annotations={},
            ),
        ]
        write_episode_html(_episode(), _TINY_PNG, trades, [], out)
        html = out.read_text(encoding="utf-8")
        # Two <details> groups
        assert html.count('<details class="symbol-group" open>') == 2
        assert "005930 삼성전자" in html
        assert "005380 현대차" in html

    def test_symbol_names_injected_overrides_default(self, tmp_path: Path):
        # AC: symbol_names DI works
        out = tmp_path / "ep.html"
        trades = [
            _trade(
                side="BUY",
                timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
            ),
        ]
        write_episode_html(
            _episode(), _TINY_PNG, trades, [], out,
            symbol_names={"069500": "MyAlias"},
        )
        html = out.read_text(encoding="utf-8")
        assert "069500 MyAlias" in html
        assert "KODEX 200" not in html  # default mapping overridden

    def test_no_thousand_long_decimals_in_html(self, tmp_path: Path):
        # AC1 regression — no Decimal.full_repr (>= 3 decimal places)
        # in trade table values. Excludes annotations container which may
        # hold unknown-key strings (handled by escape only).
        import re
        out = tmp_path / "ep.html"
        trades = [
            _trade(
                side="BUY",
                timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                annotations={
                    "trigger_price": "37947.64529058116232464929860",
                    "profit_pct": "11.11111111111111111",
                },
            ),
        ]
        write_episode_html(_episode(), _TINY_PNG, trades, [], out)
        html = out.read_text(encoding="utf-8")
        # Strip chart base64 line + raw embed lines
        # then check no >\d+\.\d{3,}< (cell-bounded numbers with 3+
        # decimals).
        no_chart = re.sub(
            r'data:image/png;base64,[A-Za-z0-9+/=]+', '', html,
        )
        long_decimal_in_cell = re.search(
            r'>[+-]?\d+\.\d{3,}', no_chart,
        )
        assert long_decimal_in_cell is None, (
            f"Found long decimal: {long_decimal_in_cell.group()}"
        )


class TestWriteIndexHtml:
    def test_writes_file(self, tmp_path: Path):
        out = tmp_path / "index.html"
        write_index_html([], [], out)
        assert out.exists()

    def test_empty_episodes(self, tmp_path: Path):
        out = tmp_path / "index.html"
        write_index_html([], [], out)
        html = out.read_text(encoding="utf-8")
        assert "총 0 개" in html
        assert "no episodes" in html

    def test_episode_rows_include_links(self, tmp_path: Path):
        out = tmp_path / "index.html"
        eps = [
            _episode(asset_code="005930"),
            _episode(asset_code="005380", recovered=False),
        ]
        paths = [Path("episode_1.html"), Path("episode_2.html")]
        write_index_html(eps, paths, out)
        html = out.read_text(encoding="utf-8")
        assert 'href="episode_1.html"' in html
        assert 'href="episode_2.html"' in html
        assert "005930" in html
        assert "005380" in html
        # recovered column
        assert 'class="recovered-yes"' in html
        assert 'class="recovered-no"' in html

    def test_count_in_header(self, tmp_path: Path):
        out = tmp_path / "index.html"
        write_index_html(
            [_episode(), _episode(), _episode()],
            [Path("e1.html"), Path("e2.html"), Path("e3.html")],
            out,
        )
        html = out.read_text(encoding="utf-8")
        assert "총 3 개" in html

    def test_length_mismatch_rejected(self, tmp_path: Path):
        out = tmp_path / "index.html"
        with pytest.raises(ValueError, match="length mismatch"):
            write_index_html(
                [_episode()], [Path("a.html"), Path("b.html")], out,
            )

    def test_drawdown_pct_formatted(self, tmp_path: Path):
        out = tmp_path / "index.html"
        write_index_html([_episode()], [Path("ep.html")], out)
        html = out.read_text(encoding="utf-8")
        # AC1: places <= 2 (was 4 places before Phase 0.10.h)
        assert "-15.00%" in html
        assert "-15.0000%" not in html

    def test_aggregate_row(self, tmp_path: Path):
        # AC: index page aggregate (Phase 0.10.k)
        out = tmp_path / "index.html"
        eps = [
            _episode(asset_code="005930"),
            _episode(asset_code="005380", recovered=False),
        ]
        write_index_html(
            eps, [Path("e1.html"), Path("e2.html")], out,
        )
        html = out.read_text(encoding="utf-8")
        assert '<div class="aggregate">' in html
        assert "총 episode: 2" in html
        assert "recovered ratio: 1/2" in html

    def test_aggregate_omitted_when_empty(self, tmp_path: Path):
        out = tmp_path / "index.html"
        write_index_html([], [], out)
        html = out.read_text(encoding="utf-8")
        # No episodes → no aggregate
        assert '<div class="aggregate">' not in html


class TestStrategyInfoSection:
    """Phase 0.10.y §15.5 — Strategy Info section rendering tests."""

    def _info(self):
        from src.application.reporting.strategy_info import StrategyInfo
        return StrategyInfo(
            buy_strategy_name="price_drop",
            buy_parameters={
                "drop_threshold_pct": "5.00%",
                "max_split_count": "7",
                "per_split_amount": "₩5,000,000",
                "max_split_per_day": "1",
            },
            sell_strategy_name="profit_target",
            sell_parameters={
                "profit_target_pct": "10.00%",
                "max_sells_per_day": "7",
            },
            reentry_strategy_name="hybrid",
            reentry_parameters={"cooldown_days": "60"},
            config_source="config/strategies-0.9.2.yaml",
            asset_codes=("005380", "005930", "055550"),
        )

    def test_episode_html_with_strategy_info_renders_section(
        self, tmp_path: Path,
    ):
        # AC11 — section present with all 8 rows
        out = tmp_path / "ep.html"
        write_episode_html(
            _episode(), _TINY_PNG, [], [], out,
            strategy_info=self._info(),
        )
        html = out.read_text(encoding="utf-8")
        # Wrapped in <details class="strategy-info" open> (Patch S1)
        assert '<details class="strategy-info" open>' in html
        assert "<summary>전략 정보</summary>" in html
        # 8 row labels
        for label in (
            "매수 전략", "매수 파라미터", "매도 전략", "매도 파라미터",
            "재진입 전략", "재진입 파라미터", "적용 종목", "설정 파일",
        ):
            assert f"<th>{label}</th>" in html, f"missing row: {label}"
        # Strategy values
        assert "price_drop" in html
        assert "5.00%" in html
        assert "₩5,000,000" in html
        # 종목 line: hard-coded "{N} 종목 동일 정책 (loader-enforced uniformity)"
        assert "3 종목 동일 정책 (loader-enforced uniformity)" in html
        # Config source
        assert "config/strategies-0.9.2.yaml" in html

    def test_episode_html_without_strategy_info_omits_section(
        self, tmp_path: Path,
    ):
        # AC12 — backwards-compat
        out = tmp_path / "ep.html"
        write_episode_html(_episode(), _TINY_PNG, [], [], out)
        html = out.read_text(encoding="utf-8")
        assert html.count("전략 정보") == 0
        assert '<details class="strategy-info"' not in html

    def test_index_html_with_strategy_info_renders_section(
        self, tmp_path: Path,
    ):
        out = tmp_path / "index.html"
        write_index_html(
            [_episode()], [Path("ep.html")], out,
            strategy_info=self._info(),
        )
        html = out.read_text(encoding="utf-8")
        assert '<details class="strategy-info" open>' in html
        assert "<summary>전략 정보</summary>" in html
        assert "<th>매수 전략</th>" in html
        assert "<th>설정 파일</th>" in html

    def test_index_html_without_strategy_info_omits_section(
        self, tmp_path: Path,
    ):
        # AC12 — backwards-compat on index too
        out = tmp_path / "index.html"
        write_index_html([_episode()], [Path("ep.html")], out)
        html = out.read_text(encoding="utf-8")
        assert html.count("전략 정보") == 0

    def test_strategy_info_html_escaped(self, tmp_path: Path):
        # XSS / HTML escape on yaml path
        from src.application.reporting.strategy_info import StrategyInfo
        info = StrategyInfo(
            buy_strategy_name="<script>",
            buy_parameters={"key<": "val>"},
            sell_strategy_name="profit_target",
            sell_parameters={},
            reentry_strategy_name="hybrid",
            reentry_parameters={},
            config_source="path<with>chars.yaml",
            asset_codes=("AAA",),
        )
        out = tmp_path / "ep.html"
        write_episode_html(
            _episode(), _TINY_PNG, [], [], out, strategy_info=info,
        )
        html = out.read_text(encoding="utf-8")
        # No raw < > in attacker-controlled positions (strategy / params /
        # config_source). Allowed unescaped < > only in legitimate template
        # tags; quick check: <script> tag should NOT appear from the
        # attacker payload.
        assert "<script>" not in html or "&lt;script&gt;" in html
        assert "&lt;" in html  # at least some escape happened
