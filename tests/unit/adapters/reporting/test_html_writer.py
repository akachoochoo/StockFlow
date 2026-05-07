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
        assert "-15.0000%" in html
        assert "<th>recovered</th><td>yes</td>" in html
        assert "<th>duration_days</th><td>9</td>" in html

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
        assert "069500" in html
        assert "split_number=2" in html
        assert "slot_number=1" in html
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
        assert "-15.0000%" in html
