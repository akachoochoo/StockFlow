"""Tests for `_backtest_engine` — ADR 0023 §10.2 / 세그먼트 1.2.2.d."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from src.cli.composition import kodex200
from src.domain.models import Currency, Money
from src.research.dgt_minute._backtest_engine import (
    _BacktestRun,
    _compute_buy_and_hold,
    _load_minute_bars,
    _run_id_from_config,
    _run_minute_backtest,
    _save_backtest_result,
)
from src.research.dgt_minute._csv_writer import _csv_path_for, _write_minute_csv
from src.research.dgt_minute._grid_strategy import _GridMinuteConfig
from src.research.dgt_minute._kis_minute_downloader import _MinuteBar


def _bar(
    *,
    trade_date: date,
    minute: int,
    open: int,
    high: int,
    low: int,
    close: int,
    volume: int = 100,
) -> _MinuteBar:
    return _MinuteBar(
        asset_code="069500",
        trade_date=trade_date,
        trade_time=time(9, minute, 0),
        open=Decimal(str(open)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=volume,
    )


def _config(**overrides: object) -> _GridMinuteConfig:
    base = {
        "grid_count": 4,
        "fallback_k": Decimal("0.05"),
        "rebalance_mode": "on_breach",
        "k_min": Decimal("0.001"),
        "k_max": Decimal("0.1"),
        "multiplier": Decimal("1.5"),
    }
    base.update(overrides)
    return _GridMinuteConfig(**base)  # type: ignore[arg-type]


def _seed_csv(
    *,
    tmp_path: Path,
    code: str,
    trade_date: date,
    bars: list[_MinuteBar],
) -> Path:
    """tmp dir 에 CSV 박제 (_load_minute_bars 가 읽음)."""
    path = _csv_path_for(
        data_root=tmp_path, asset_code=code, trade_date=trade_date
    )
    _write_minute_csv(bars, path)
    return path


# --------------------------------------------------------------------- #
# _load_minute_bars
# --------------------------------------------------------------------- #
class TestLoadBars:
    def test_load_single_day(self, tmp_path: Path) -> None:
        d = date(2026, 5, 29)
        bars = [
            _bar(trade_date=d, minute=i, open=100, high=100, low=100, close=100)
            for i in range(5)
        ]
        _seed_csv(tmp_path=tmp_path, code="069500", trade_date=d, bars=bars)
        loaded = _load_minute_bars(
            asset_code="069500", dates=[d], data_root=tmp_path
        )
        assert len(loaded) == 5

    def test_load_multi_day_concatenated(self, tmp_path: Path) -> None:
        d1 = date(2026, 5, 29)
        d2 = date(2026, 6, 2)
        for d in (d1, d2):
            bars = [
                _bar(trade_date=d, minute=i, open=100, high=100, low=100, close=100)
                for i in range(3)
            ]
            _seed_csv(tmp_path=tmp_path, code="069500", trade_date=d, bars=bars)
        loaded = _load_minute_bars(
            asset_code="069500", dates=[d1, d2], data_root=tmp_path
        )
        assert len(loaded) == 6
        # date 순서 보존
        assert loaded[0].trade_date == d1
        assert loaded[-1].trade_date == d2

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="missing minute CSV"):
            _load_minute_bars(
                asset_code="069500",
                dates=[date(2026, 5, 29)],
                data_root=tmp_path,
            )


# --------------------------------------------------------------------- #
# _compute_buy_and_hold
# --------------------------------------------------------------------- #
class TestBuyAndHold:
    def test_empty_bars_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            _compute_buy_and_hold(
                asset=kodex200(),
                bars=[],
                initial_capital=Money(
                    amount=Decimal("1000000"), currency=Currency.KRW
                ),
            )

    def test_currency_mismatch_raises(self) -> None:
        d = date(2026, 5, 29)
        bars = [_bar(trade_date=d, minute=0, open=100, high=100, low=100, close=100)]
        with pytest.raises(ValueError, match="currency"):
            _compute_buy_and_hold(
                asset=kodex200(),
                bars=bars,
                initial_capital=Money(
                    amount=Decimal("1000"), currency=Currency.USD
                ),
            )

    def test_flat_price_no_drawdown(self) -> None:
        d = date(2026, 5, 29)
        bars = [
            _bar(trade_date=d, minute=i, open=100, high=100, low=100, close=100)
            for i in range(5)
        ]
        result = _compute_buy_and_hold(
            asset=kodex200(),
            bars=bars,
            initial_capital=Money(amount=Decimal("1000"), currency=Currency.KRW),
        )
        # quantity = 1000/100 = 10. final_value = 0 + 10*100 = 1000.
        assert result.quantity == Decimal("10")
        assert result.leftover_cash == Decimal("0")
        assert result.final_value == Decimal("1000")
        assert result.max_drawdown == Decimal("0")

    def test_decline_records_mdd(self) -> None:
        d = date(2026, 5, 29)
        # 100 → 80 → 90: peak=1000, trough=800 → MDD=20%
        bars = [
            _bar(trade_date=d, minute=0, open=100, high=100, low=100, close=100),
            _bar(trade_date=d, minute=1, open=100, high=100, low=80, close=80),
            _bar(trade_date=d, minute=2, open=80, high=90, low=80, close=90),
        ]
        result = _compute_buy_and_hold(
            asset=kodex200(),
            bars=bars,
            initial_capital=Money(amount=Decimal("1000"), currency=Currency.KRW),
        )
        # bar_value: t0=1000, t1=800 (peak=1000, dd=0.2), t2=900
        assert result.max_drawdown == Decimal("0.2")


# --------------------------------------------------------------------- #
# _run_id_from_config
# --------------------------------------------------------------------- #
class TestRunId:
    def test_deterministic_same_input(self) -> None:
        cfg = _config()
        cap = Money(amount=Decimal("1000000"), currency=Currency.KRW)
        dates = [date(2026, 5, 29)]
        id1 = _run_id_from_config(
            asset_code="069500", dates=dates, config=cfg, initial_capital=cap
        )
        id2 = _run_id_from_config(
            asset_code="069500", dates=dates, config=cfg, initial_capital=cap
        )
        assert id1 == id2
        assert len(id1) == 16  # 16-char prefix

    def test_different_config_different_id(self) -> None:
        cap = Money(amount=Decimal("1000000"), currency=Currency.KRW)
        dates = [date(2026, 5, 29)]
        id1 = _run_id_from_config(
            asset_code="069500", dates=dates,
            config=_config(grid_count=4), initial_capital=cap,
        )
        id2 = _run_id_from_config(
            asset_code="069500", dates=dates,
            config=_config(grid_count=10), initial_capital=cap,
        )
        assert id1 != id2

    def test_different_dates_different_id(self) -> None:
        cfg = _config()
        cap = Money(amount=Decimal("1000000"), currency=Currency.KRW)
        id1 = _run_id_from_config(
            asset_code="069500", dates=[date(2026, 5, 29)],
            config=cfg, initial_capital=cap,
        )
        id2 = _run_id_from_config(
            asset_code="069500",
            dates=[date(2026, 5, 29), date(2026, 6, 2)],
            config=cfg, initial_capital=cap,
        )
        assert id1 != id2


# --------------------------------------------------------------------- #
# _run_minute_backtest e2e
# --------------------------------------------------------------------- #
class TestRunBacktest:
    def test_e2e_runs(self, tmp_path: Path) -> None:
        d = date(2026, 5, 29)
        bars = [
            _bar(trade_date=d, minute=0, open=100, high=100, low=100, close=100),
            _bar(trade_date=d, minute=1, open=100, high=100, low=80, close=80),
            _bar(trade_date=d, minute=2, open=80, high=120, low=80, close=120),
        ]
        _seed_csv(tmp_path=tmp_path, code="069500", trade_date=d, bars=bars)

        run = _run_minute_backtest(
            asset=kodex200(),
            dates=[d],
            config=_config(),
            initial_capital=Money(
                amount=Decimal("10000000"), currency=Currency.KRW
            ),
            data_root=tmp_path,
            now=datetime(2026, 6, 2, 16, 0, tzinfo=UTC),
        )
        assert isinstance(run, _BacktestRun)
        assert run.asset_code == "069500"
        assert run.dates == (d,)
        assert run.n_bars == 3
        assert len(run.run_id) == 16

    def test_e2e_no_csv_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _run_minute_backtest(
                asset=kodex200(),
                dates=[date(2026, 5, 29)],
                config=_config(),
                initial_capital=Money(
                    amount=Decimal("1000000"), currency=Currency.KRW
                ),
                data_root=tmp_path,
                now=datetime(2026, 6, 2, 16, 0, tzinfo=UTC),
            )


# --------------------------------------------------------------------- #
# _save_backtest_result
# --------------------------------------------------------------------- #
class TestSaveResult:
    def test_save_creates_json(self, tmp_path: Path) -> None:
        d = date(2026, 5, 29)
        bars = [
            _bar(trade_date=d, minute=i, open=100, high=100, low=100, close=100)
            for i in range(3)
        ]
        _seed_csv(tmp_path=tmp_path, code="069500", trade_date=d, bars=bars)

        config = _config()
        run = _run_minute_backtest(
            asset=kodex200(),
            dates=[d],
            config=config,
            initial_capital=Money(
                amount=Decimal("1000000"), currency=Currency.KRW
            ),
            data_root=tmp_path,
            now=datetime(2026, 6, 2, 16, 0, tzinfo=UTC),
        )
        output_root = tmp_path / "backtest-runs"
        out_path = _save_backtest_result(
            run=run, config=config, output_root=output_root
        )
        assert out_path.exists()
        assert out_path.name == f"{run.run_id}.json"

        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["run_id"] == run.run_id
        assert payload["asset_code"] == "069500"
        assert payload["dates"] == ["2026-05-29"]
        assert payload["n_bars"] == 3
        assert "dgt" in payload
        assert "bh" in payload
        assert "config" in payload
        # Numeric 은 모두 str 박제 (Decimal 정합).
        assert isinstance(payload["dgt"]["final_value"], str)
        assert isinstance(payload["bh"]["max_drawdown"], str)

    def test_save_atomic_tmp_cleanup(self, tmp_path: Path) -> None:
        d = date(2026, 5, 29)
        bars = [_bar(trade_date=d, minute=0, open=100, high=100, low=100, close=100)]
        _seed_csv(tmp_path=tmp_path, code="069500", trade_date=d, bars=bars)
        config = _config()
        run = _run_minute_backtest(
            asset=kodex200(),
            dates=[d],
            config=config,
            initial_capital=Money(
                amount=Decimal("1000000"), currency=Currency.KRW
            ),
            data_root=tmp_path,
            now=datetime(2026, 6, 2, 16, 0, tzinfo=UTC),
        )
        output_root = tmp_path / "runs"
        _save_backtest_result(run=run, config=config, output_root=output_root)
        # *.tmp 파일 없어야 함.
        tmp_files = list(output_root.glob("*.tmp"))
        assert tmp_files == []


# --------------------------------------------------------------------- #
# 실 KIS 5/29 069500 e2e
# --------------------------------------------------------------------- #
class TestRealKisData:
    def test_real_data_full_pipeline(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent
        data_root = repo_root / "data" / "historical"
        csv_path = data_root / "minute" / "069500" / "2026-05-29.csv"
        if not csv_path.exists():
            pytest.skip("real KIS data not present")

        run = _run_minute_backtest(
            asset=kodex200(),
            dates=[date(2026, 5, 29)],
            config=_config(
                grid_count=10, fallback_k=Decimal("0.005"),
                rebalance_mode="on_breach",
            ),
            initial_capital=Money(
                amount=Decimal("5000000"), currency=Currency.KRW
            ),
            data_root=data_root,
            now=datetime(2026, 6, 2, 16, 0, tzinfo=UTC),
        )
        assert run.n_bars == 391
        # DGT 결과 sanity.
        assert run.dgt.final_value > Decimal("0")
        # B&H 결과 sanity.
        assert run.bh.final_value > Decimal("0")
        # MDD 모두 [0, 1].
        assert Decimal("0") <= run.dgt.max_drawdown() <= Decimal("1")
        assert Decimal("0") <= run.bh.max_drawdown <= Decimal("1")
