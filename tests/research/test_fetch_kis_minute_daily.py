"""Tests for `scripts/fetch_kis_minute_daily.py` — ADR 0023 §10.1 / 1.2.1.b.4."""
from __future__ import annotations

import copy
import importlib.util
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.research.dgt_minute._manifest import _load_manifest

KST = ZoneInfo("Asia/Seoul")

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "fetch_kis_minute_daily.py"
)
_SAMPLE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "research"
    / "phase-1.x-minute"
)


def _import_script():  # type: ignore[no-untyped-def]
    """Load `fetch_kis_minute_daily.py` as module (avoid sys.path mutation).

    sys.modules 등록 필수 — `from __future__ import annotations` + dataclass
    조합이 `dataclasses._is_type` 에서 `sys.modules.get(cls.__module__)` 호출,
    미등록 시 `AttributeError: NoneType.__dict__` (Python 3.11 알려진 함정).
    """
    import sys

    name = "_fetch_kis_minute_daily"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_sample(code: str) -> dict[str, object]:
    path = _SAMPLE_DIR / f"sample-{code}.json"
    if not path.exists():
        pytest.skip(f"sample-{code}.json not present")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@dataclass
class _FakeKISClient:
    bodies_by_code: dict[str, dict[str, object]]
    calls_by_code: dict[str, int] = field(default_factory=dict)

    def request(
        self,
        method: str,
        path: str,
        *,
        tr_id: str,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        tr_cont: str = "",
    ) -> dict[str, object]:
        code = (params or {}).get("FID_INPUT_ISCD", "")
        self.calls_by_code[code] = self.calls_by_code.get(code, 0) + 1
        return copy.deepcopy(self.bodies_by_code[code])


# --------------------------------------------------------------------- #
# _parse_args
# --------------------------------------------------------------------- #
class TestParseArgs:
    def test_defaults(self) -> None:
        m = _import_script()
        args = m._parse_args([])
        assert args.codes == list(m._DEFAULT_CODES)
        assert args.date is None
        assert args.data_root == Path("data/historical")
        assert args.manifest is None
        assert args.inter_asset_sleep_sec == 1.0

    def test_explicit_codes(self) -> None:
        m = _import_script()
        args = m._parse_args(["--codes", "069500", "005930"])
        assert args.codes == ["069500", "005930"]

    def test_explicit_date(self) -> None:
        m = _import_script()
        args = m._parse_args(["--date", "2026-05-29"])
        assert args.date == date(2026, 5, 29)

    def test_invalid_date_rejected(self) -> None:
        m = _import_script()
        with pytest.raises(SystemExit):
            m._parse_args(["--date", "2026/05/29"])

    def test_explicit_data_root_and_manifest(self, tmp_path: Path) -> None:
        m = _import_script()
        args = m._parse_args(
            [
                "--data-root", str(tmp_path),
                "--manifest", str(tmp_path / "x.json"),
            ]
        )
        assert args.data_root == tmp_path
        assert args.manifest == tmp_path / "x.json"


# --------------------------------------------------------------------- #
# _resolve_default_date
# --------------------------------------------------------------------- #
class TestResolveDefaultDate:
    def test_utc_evening_returns_kst_yesterday(self) -> None:
        m = _import_script()
        # 2026-05-30 16:00 KST = 07:00 UTC.
        now_utc = datetime(2026, 5, 30, 7, 0, tzinfo=UTC)
        assert m._resolve_default_date(now_utc) == date(2026, 5, 29)

    def test_kst_midnight_boundary(self) -> None:
        m = _import_script()
        # 2026-05-30 00:30 KST = 2026-05-29 15:30 UTC → KST date = 5/30 → -1 = 5/29.
        now_utc = datetime(2026, 5, 29, 15, 30, tzinfo=UTC)
        assert m._resolve_default_date(now_utc) == date(2026, 5, 29)


# --------------------------------------------------------------------- #
# _run (testable cron body)
# --------------------------------------------------------------------- #
class TestRun:
    def test_4_codes_all_succeed(self, tmp_path: Path) -> None:
        m = _import_script()
        bodies = {code: _load_sample(code) for code in m._DEFAULT_CODES}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        args = m._parse_args(
            ["--date", "2026-05-29", "--data-root", str(tmp_path)]
        )
        summary = m._run(args, client=client, now=now, sleep_fn=lambda _: None)

        assert summary.exit_code == 0
        assert len(summary.results) == 4
        assert summary.failures == ()
        # 각 code 마다 30봉, 14 anchor 호출 = 56 호출 total.
        assert sum(client.calls_by_code.values()) == 56
        for code in m._DEFAULT_CODES:
            csv_path = tmp_path / "minute" / code / "2026-05-29.csv"
            assert csv_path.exists()
        # manifest = 4종 모두 등록.
        manifest = _load_manifest(tmp_path / "minute" / "manifest.json")
        assert set(manifest.assets.keys()) == set(m._DEFAULT_CODES)
        for code in m._DEFAULT_CODES:
            assert manifest.assets[code].total_bars == 30

    def test_per_code_failure_isolated(self, tmp_path: Path) -> None:
        m = _import_script()
        # 005930 sample = rt_cd 1 (fail), 069500 정상.
        broken = _load_sample("005930")
        broken["rt_cd"] = "1"
        broken["msg1"] = "유량 초과"
        bodies = {"069500": _load_sample("069500"), "005930": broken}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        args = m._parse_args(
            ["--codes", "069500", "005930",
             "--date", "2026-05-29",
             "--data-root", str(tmp_path)]
        )
        summary = m._run(args, client=client, now=now, sleep_fn=lambda _: None)

        assert summary.exit_code == 1
        assert len(summary.results) == 1
        assert summary.results[0].asset_code == "069500"
        assert len(summary.failures) == 1
        assert "005930" in summary.failures[0]

    def test_holiday_zero_bars_no_failure(self, tmp_path: Path) -> None:
        """휴장일 호출 (target_date != KIS 응답 date) = 정상 종료 + 0봉."""
        m = _import_script()
        bodies = {"069500": _load_sample("069500")}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        args = m._parse_args(
            ["--codes", "069500",
             "--date", "2026-05-30",  # 부처님오신날 휴장
             "--data-root", str(tmp_path)]
        )
        summary = m._run(args, client=client, now=now, sleep_fn=lambda _: None)

        assert summary.exit_code == 0  # 휴장 = failure 아님
        assert summary.results[0].bars_count == 0
        assert not summary.results[0].csv_written

    def test_default_date_uses_now(self, tmp_path: Path) -> None:
        m = _import_script()
        # KIS 응답이 5/29 인 sample 을 그대로 사용 — now=5/30 KST → default
        # date = 5/29 → match → bars 30.
        bodies = {"069500": _load_sample("069500")}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 7, 0, tzinfo=UTC)  # 16:00 KST

        args = m._parse_args(
            ["--codes", "069500", "--data-root", str(tmp_path)]
        )
        summary = m._run(args, client=client, now=now, sleep_fn=lambda _: None)

        assert summary.results[0].trade_date == date(2026, 5, 29)
        assert summary.results[0].bars_count == 30

    def test_explicit_manifest_path(self, tmp_path: Path) -> None:
        m = _import_script()
        bodies = {"069500": _load_sample("069500")}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        manifest_path = tmp_path / "alt-manifest.json"
        args = m._parse_args(
            ["--codes", "069500",
             "--date", "2026-05-29",
             "--data-root", str(tmp_path),
             "--manifest", str(manifest_path)]
        )
        summary = m._run(args, client=client, now=now, sleep_fn=lambda _: None)

        assert summary.exit_code == 0
        assert manifest_path.exists()
        # default manifest path 는 생성 안 됨.
        assert not (tmp_path / "minute" / "manifest.json").exists()


# --------------------------------------------------------------------- #
# _RunSummary
# --------------------------------------------------------------------- #
class TestRunSummary:
    def test_empty_success(self) -> None:
        m = _import_script()
        s = m._RunSummary(results=(), failures=())
        assert s.exit_code == 0

    def test_any_failure_exit_1(self) -> None:
        m = _import_script()
        s = m._RunSummary(results=(), failures=("X",))
        assert s.exit_code == 1


# --------------------------------------------------------------------- #
# Inter-asset sleep (ADR 0023 R3 mitigation — EGW00201 burst 회피)
# --------------------------------------------------------------------- #
class TestInterAssetSleep:
    def test_sleep_called_n_times_for_n_codes(
        self, tmp_path: Path
    ) -> None:
        m = _import_script()
        bodies = {code: _load_sample(code) for code in m._DEFAULT_CODES}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        sleeps: list[float] = []
        args = m._parse_args(
            ["--date", "2026-05-29", "--data-root", str(tmp_path)]
        )
        summary = m._run(
            args, client=client, now=now, sleep_fn=lambda s: sleeps.append(s)
        )

        assert summary.exit_code == 0
        # 4 codes → sleep 4회 (첫 호출 포함, 연속 cron 호출 보호), 각 1.0초.
        assert sleeps == [1.0, 1.0, 1.0, 1.0]

    def test_sleep_zero_disables_pause(self, tmp_path: Path) -> None:
        m = _import_script()
        bodies = {"069500": _load_sample("069500")}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        sleeps: list[float] = []
        args = m._parse_args(
            ["--codes", "069500", "069500", "069500",
             "--date", "2026-05-29",
             "--data-root", str(tmp_path),
             "--inter-asset-sleep-sec", "0"]
        )
        m._run(args, client=client, now=now,
               sleep_fn=lambda s: sleeps.append(s))
        assert sleeps == []

    def test_custom_sleep_value_propagates(self, tmp_path: Path) -> None:
        m = _import_script()
        bodies = {"069500": _load_sample("069500")}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        sleeps: list[float] = []
        args = m._parse_args(
            ["--codes", "069500", "069500",
             "--date", "2026-05-29",
             "--data-root", str(tmp_path),
             "--inter-asset-sleep-sec", "2.5"]
        )
        m._run(args, client=client, now=now,
               sleep_fn=lambda s: sleeps.append(s))
        assert sleeps == [2.5, 2.5]

    def test_single_code_sleeps_once(self, tmp_path: Path) -> None:
        """단발 종목도 첫 호출 전 1초 sleep — 연속 cron 호출 보호."""
        m = _import_script()
        bodies = {"069500": _load_sample("069500")}
        client = _FakeKISClient(bodies_by_code=bodies)
        now = datetime(2026, 5, 30, 16, 0, tzinfo=KST)

        sleeps: list[float] = []
        args = m._parse_args(
            ["--codes", "069500", "--date", "2026-05-29",
             "--data-root", str(tmp_path)]
        )
        m._run(args, client=client, now=now,
               sleep_fn=lambda s: sleeps.append(s))
        assert sleeps == [1.0]
