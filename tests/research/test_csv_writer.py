"""Tests for `_csv_writer` — ADR 0023 §10.1 / 세그먼트 1.2.1.b.3 (CSV part)."""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path  # noqa: TC003  -- pytest fixture annotation runtime

import pytest

from src.research.dgt_minute._csv_writer import (
    _CSV_HEADER,
    _csv_path_for,
    _read_minute_csv,
    _write_minute_csv,
)
from src.research.dgt_minute._kis_minute_downloader import _MinuteBar


def _make_bar(
    *,
    code: str = "069500",
    trade_date: date = date(2026, 5, 29),
    trade_time: time = time(9, 1, 0),
    price: Decimal = Decimal("100"),
    volume: int = 1000,
) -> _MinuteBar:
    return _MinuteBar(
        asset_code=code,
        trade_date=trade_date,
        trade_time=trade_time,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
    )


class TestPath:
    def test_path_pattern(self, tmp_path: Path) -> None:
        p = _csv_path_for(
            data_root=tmp_path, asset_code="069500", trade_date=date(2026, 5, 29)
        )
        assert p == tmp_path / "minute" / "069500" / "2026-05-29.csv"


class TestWrite:
    def test_empty_bars_no_op(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        _write_minute_csv([], path)
        assert not path.exists()

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "deep" / "out.csv"
        _write_minute_csv([_make_bar()], path)
        assert path.exists()

    def test_atomic_tmp_cleanup(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        _write_minute_csv([_make_bar()], path)
        assert path.exists()
        assert not (tmp_path / "out.csv.tmp").exists()

    def test_header_first_line(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        _write_minute_csv([_make_bar()], path)
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == ",".join(_CSV_HEADER)

    def test_decimal_str_round_trip(self, tmp_path: Path) -> None:
        """CLAUDE.md §2.3 — Decimal `str(v)` 정확도 보존 (float 경유 zero)."""
        path = tmp_path / "out.csv"
        bar = _make_bar(price=Decimal("134815.50"))
        _write_minute_csv([bar], path)
        loaded = _read_minute_csv(path, asset_code="069500")
        assert len(loaded) == 1
        assert loaded[0].open == Decimal("134815.50")
        # str round-trip 정확도 보장.
        assert str(loaded[0].open) == "134815.50"

    def test_ascending_preserved_as_input(self, tmp_path: Path) -> None:
        """Caller invariant — writer 는 입력 순서 그대로 (정렬 zero)."""
        path = tmp_path / "out.csv"
        bars = [
            _make_bar(trade_time=time(9, 1)),
            _make_bar(trade_time=time(9, 2)),
            _make_bar(trade_time=time(15, 30)),
        ]
        _write_minute_csv(bars, path)
        loaded = _read_minute_csv(path, asset_code="069500")
        assert [b.trade_time for b in loaded] == [b.trade_time for b in bars]


class TestRead:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _read_minute_csv(tmp_path / "noop.csv", asset_code="069500") == []

    def test_round_trip_full_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        original = [
            _MinuteBar(
                asset_code="069500",
                trade_date=date(2026, 5, 29),
                trade_time=time(15, 30, 0),
                open=Decimal("134815"),
                high=Decimal("134900"),
                low=Decimal("134700"),
                close=Decimal("134815"),
                volume=165274,
            ),
        ]
        _write_minute_csv(original, path)
        loaded = _read_minute_csv(path, asset_code="069500")
        assert loaded == original

    def test_header_mismatch_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        path.write_text(
            "bogus_header\n2026-05-29,09:01:00,100,100,100,100,1000\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="header mismatch"):
            _read_minute_csv(path, asset_code="069500")

    def test_asset_code_injected_from_caller(self, tmp_path: Path) -> None:
        """CSV 에는 asset_code 없음 → caller 가 주입."""
        path = tmp_path / "out.csv"
        _write_minute_csv([_make_bar(code="069500")], path)
        loaded = _read_minute_csv(path, asset_code="999999")
        assert loaded[0].asset_code == "999999"
