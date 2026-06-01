"""분봉 backtest engine — multi-day CSV loader + runner + JSON 결과 박제.

ADR 0023 §10.2 / 세그먼트 1.2.2.d 산출. 1.2.2.c `_MinuteGridRunner` 위에 (a)
multi-day CSV concatenation + (b) B&H 벤치마크 + (c) reproducible run_id +
(d) JSON 직렬화 박제 layer.

본 모듈의 본질:
1. `_load_minute_bars(code, dates, data_root)` — N일치 CSV ascending 연결.
2. `_compute_buy_and_hold(...)` — 첫 bar 전액 매수 → bar별 평가 → MDD.
3. `_run_minute_backtest(...)` — runner.run + B&H + result wrap.
4. `_save_backtest_result(...)` — JSON 박제 (`docs/research/phase-1.x-minute/
   backtest-runs/{run_id}.json`).
5. `_run_id_from_config(...)` — 결정론적 config hash (reproducibility).

5th ring 격리 (D15): inner ring 변경 zero (D17). 1.2.2.e sweep 의
의존성 — sweep 가 본 engine 을 N회 호출 (config grid).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime  # noqa: TC003 — pydantic 런타임 해석
from decimal import Decimal
from pathlib import Path  # noqa: TC003  -- runtime use in mkdir/write_text
from typing import TYPE_CHECKING

from src.research.dgt_minute._csv_writer import _csv_path_for, _read_minute_csv
from src.research.dgt_minute._runner import _MinuteGridRunner, _MinuteRunResult

if TYPE_CHECKING:
    from src.domain.models import Asset, Money
    from src.research.dgt_minute._grid_strategy import _GridMinuteConfig
    from src.research.dgt_minute._kis_minute_downloader import _MinuteBar


@dataclass(frozen=True, slots=True)
class _BuyAndHoldResult:
    """B&H 벤치마크 결과."""

    initial_value: Decimal
    final_value: Decimal
    max_drawdown: Decimal
    quantity: Decimal
    leftover_cash: Decimal


@dataclass(frozen=True, slots=True)
class _BacktestRun:
    """`_run_minute_backtest` 출력 — DGT + B&H + 메타."""

    run_id: str
    asset_code: str
    dates: tuple[date, ...]
    n_bars: int
    dgt: _MinuteRunResult
    bh: _BuyAndHoldResult
    created_at: datetime  # 외부 주입 (시계 의존 zero)


def _load_minute_bars(
    *,
    asset_code: str,
    dates: list[date],
    data_root: Path,
) -> list[_MinuteBar]:
    """N일치 분봉 CSV → 단일 ascending list[_MinuteBar].

    `dates` 는 caller 가 sort 책임. 각 일자 파일 부재 시 `FileNotFoundError`
    (silent skip 금지 — CLAUDE.md §6.3).
    """
    bars: list[_MinuteBar] = []
    for d in dates:
        csv_path = _csv_path_for(
            data_root=data_root, asset_code=asset_code, trade_date=d
        )
        if not csv_path.exists():
            raise FileNotFoundError(
                f"missing minute CSV for {asset_code} {d.isoformat()}: {csv_path}"
            )
        bars.extend(_read_minute_csv(csv_path, asset_code=asset_code))
    return bars


def _compute_buy_and_hold(
    *,
    asset: Asset,
    bars: list[_MinuteBar],
    initial_capital: Money,
) -> _BuyAndHoldResult:
    """첫 bar close 전액 매수 → bar별 평가 → MDD.

    수량 = floor(capital / first_close). 잔여 cash 보유. MDD 는 portfolio
    가치 시계열 기준.
    """
    if not bars:
        raise ValueError("bars must be non-empty")
    if initial_capital.currency != asset.currency:
        raise ValueError(
            "initial_capital.currency != asset.currency"
        )
    first_close = bars[0].close
    if first_close <= 0:
        raise ValueError(f"first bar close must be > 0, got {first_close}")

    quantity = (initial_capital.amount / first_close).quantize(Decimal("1"))
    if quantity < 0:
        quantity = Decimal("0")
    spent = quantity * first_close
    leftover = initial_capital.amount - spent

    peak = initial_capital.amount
    mdd = Decimal("0")
    for bar in bars:
        value = leftover + quantity * bar.close
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak
            if dd > mdd:
                mdd = dd

    final_value = leftover + quantity * bars[-1].close
    return _BuyAndHoldResult(
        initial_value=initial_capital.amount,
        final_value=final_value,
        max_drawdown=mdd,
        quantity=quantity,
        leftover_cash=leftover,
    )


def _run_id_from_config(
    *,
    asset_code: str,
    dates: list[date],
    config: _GridMinuteConfig,
    initial_capital: Money,
) -> str:
    """결정론적 run_id — config + dates + asset + capital sha256.

    동일 입력 → 동일 run_id. JSON canonical 형태로 serialize 후 sha256.
    Reproducibility 토대 (sweep 의 결과 캐싱 / dedup).
    """
    payload = {
        "asset_code": asset_code,
        "dates": [d.isoformat() for d in dates],
        "config": config.model_dump(mode="json"),
        "initial_capital_amount": str(initial_capital.amount),
        "initial_capital_currency": initial_capital.currency.value,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _run_minute_backtest(
    *,
    asset: Asset,
    dates: list[date],
    config: _GridMinuteConfig,
    initial_capital: Money,
    data_root: Path,
    now: datetime,
    runner: _MinuteGridRunner | None = None,
) -> _BacktestRun:
    """Multi-day 분봉 backtest 1회.

    Args:
        asset: 도메인 Asset.
        dates: 거래일 (ascending).
        config: 그리드 설정.
        initial_capital: 초기 자본.
        data_root: CSV 루트 (`data/historical`).
        now: 외부 주입 시각 (`created_at` 박제용, CLAUDE.md §3.2).
        runner: optional runner inject (테스트). 기본 새 instance.

    Returns:
        `_BacktestRun` — DGT + B&H + run_id + 메타.
    """
    bars = _load_minute_bars(
        asset_code=asset.code, dates=dates, data_root=data_root
    )
    if not bars:
        raise ValueError(
            f"no bars loaded for {asset.code} dates {[d.isoformat() for d in dates]}"
        )

    actual_runner = runner or _MinuteGridRunner()
    dgt_result = actual_runner.run(
        asset=asset,
        bars=bars,
        config=config,
        initial_capital=initial_capital,
    )
    bh_result = _compute_buy_and_hold(
        asset=asset, bars=bars, initial_capital=initial_capital
    )
    run_id = _run_id_from_config(
        asset_code=asset.code,
        dates=dates,
        config=config,
        initial_capital=initial_capital,
    )
    return _BacktestRun(
        run_id=run_id,
        asset_code=asset.code,
        dates=tuple(dates),
        n_bars=len(bars),
        dgt=dgt_result,
        bh=bh_result,
        created_at=now,
    )


def _save_backtest_result(
    *,
    run: _BacktestRun,
    config: _GridMinuteConfig,
    output_root: Path,
) -> Path:
    """`_BacktestRun` → JSON 박제.

    경로: `{output_root}/{run_id}.json` (atomic tmp+rename).

    schema (정렬 보존):
    - run_id / created_at / asset_code / dates / n_bars
    - config (model_dump)
    - dgt: initial / final_cash / final_holdings / final_close / final_value
      / n_trades / realized / unrealized / turnover / mdd / avg_cost
    - bh: initial / final / mdd / quantity / leftover_cash

    Trades 시계열 자체는 박제 안 함 (메모리 ↑, sweep 대량 박제 부담). sweep
    의 의사결정에는 metric 집계만 필요. trade 시계열은 단발 실행 시 별도
    --save-trades 옵션 (1.2.2.e CLI 영역).
    """
    output_root.mkdir(parents=True, exist_ok=True)
    realized, unrealized = run.dgt.pnl_split()
    payload = {
        "run_id": run.run_id,
        "created_at": run.created_at.isoformat(),
        "asset_code": run.asset_code,
        "dates": [d.isoformat() for d in run.dates],
        "n_bars": run.n_bars,
        "config": config.model_dump(mode="json"),
        "dgt": {
            "initial_capital": str(run.dgt.initial_capital.amount),
            "currency": run.dgt.initial_capital.currency.value,
            "final_cash": str(run.dgt.final_cash),
            "final_holdings": str(run.dgt.final_holdings),
            "final_close_price": str(run.dgt.final_close_price),
            "final_value": str(run.dgt.final_value),
            "final_avg_cost": str(run.dgt.final_avg_cost),
            "n_trades": len(run.dgt.trades),
            "realized_pnl": str(realized),
            "unrealized_pnl": str(unrealized),
            "turnover": str(run.dgt.turnover()),
            "max_drawdown": str(run.dgt.max_drawdown()),
        },
        "bh": {
            "initial_value": str(run.bh.initial_value),
            "final_value": str(run.bh.final_value),
            "max_drawdown": str(run.bh.max_drawdown),
            "quantity": str(run.bh.quantity),
            "leftover_cash": str(run.bh.leftover_cash),
        },
    }
    out_path = output_root / f"{run.run_id}.json"
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(out_path)
    return out_path
