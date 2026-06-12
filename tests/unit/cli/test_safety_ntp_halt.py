"""Unit tests for Phase 1.1 Stage 3.1+3.2 safety primitives.

Covers:
  * verify_ntp_sync — fail-closed clock-sync gate (CLAUDE.md §3.3).
  * persistent halt sentinel — write/clear/check/is_halted/halt_reason.
  * CLI wiring — ``trading halt`` / ``trading resume`` + entry-time blocking.

No real subprocess / network is exercised: the NTP runner is injected.
All filesystem state uses tmp_path (home directory is never touched).
"""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner

from src.cli import safety
from src.cli.main import main as cli
from src.domain.exceptions import ClockSkewError, IntegrityError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fake_runner(returncode: int, *, stdout: str = "", stderr: str = ""):
    """Return a subprocess.run-compatible callable yielding a fixed result."""

    def _run(args, **kwargs):  # mirrors subprocess.run signature
        return subprocess.CompletedProcess(
            args=args, returncode=returncode, stdout=stdout, stderr=stderr
        )

    return _run


def _fixed_clock(dt: datetime):
    return lambda: dt


# ---------------------------------------------------------------------------
# verify_ntp_sync — fail-closed clock gate
# ---------------------------------------------------------------------------
class TestVerifyNtpSync:
    def test_ntp_sync_within_1_second_passes(self):
        # Exit 0 = synced within threshold → no-op (no exception).
        runner = _fake_runner(0, stdout="NTP synced: offset=0.01s")
        assert safety.verify_ntp_sync(runner=runner) is None

    def test_offset_exceeded_raises_clock_skew(self):
        # Exit 1 = offset > threshold → ClockSkewError (fail-closed).
        runner = _fake_runner(1, stderr="NTP offset EXCEEDED: 2.5s > 1.0s")
        with pytest.raises(ClockSkewError) as exc:
            safety.verify_ntp_sync(runner=runner)
        assert "exceed" in str(exc.value).lower()
        # Detail from the script is surfaced.
        assert "2.5s" in str(exc.value)

    def test_unmeasurable_raises_clock_skew_fail_closed(self):
        # Exit 2 = no tool / unreachable → ClockSkewError (fail-closed).
        runner = _fake_runner(2, stderr="no NTP tool found")
        with pytest.raises(ClockSkewError) as exc:
            safety.verify_ntp_sync(runner=runner)
        assert "unmeasurable" in str(exc.value).lower()

    def test_clock_skew_is_integrity_error(self):
        # ClockSkewError must be an IntegrityError → halt all trading.
        runner = _fake_runner(2)
        with pytest.raises(IntegrityError):
            safety.verify_ntp_sync(runner=runner)

    def test_unknown_nonzero_exit_raises(self):
        runner = _fake_runner(127, stderr="bash: command not found")
        with pytest.raises(ClockSkewError) as exc:
            safety.verify_ntp_sync(runner=runner)
        assert "127" in str(exc.value)

    def test_runner_invoked_with_script_path(self, tmp_path):
        captured: dict[str, object] = {}

        def _run(args, **kwargs):
            captured["args"] = args
            return subprocess.CompletedProcess(args, 0, "", "")

        script = tmp_path / "fake_check.sh"
        safety.verify_ntp_sync(runner=_run, script_path=script)
        assert captured["args"] == ["bash", str(script)]

    def test_default_script_path_points_to_repo_script(self):
        # The default resolves to the real shipped script (sanity check).
        assert safety._NTP_SCRIPT_PATH.name == "check_ntp_sync.sh"
        assert safety._NTP_SCRIPT_PATH.exists()


# ---------------------------------------------------------------------------
# Persistent halt sentinel
# ---------------------------------------------------------------------------
class TestPersistentHalt:
    def test_write_halt_creates_sentinel_with_reason(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        clock = _fixed_clock(datetime(2026, 5, 22, 12, 0, tzinfo=UTC))
        result = safety.write_halt("reconciliation mismatch", path=path, clock=clock)
        assert result == path
        assert safety.is_halted(path=path) is True
        assert safety.halt_reason(path=path) == "reconciliation mismatch"
        # Timestamp recorded as second line.
        lines = path.read_text().splitlines()
        assert lines[1] == "2026-05-22T12:00:00+00:00"

    def test_write_halt_preserves_first_reason(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        safety.write_halt("first reason", path=path)
        safety.write_halt("second reason", path=path)
        # First (root-cause) reason wins; second call is a no-clobber no-op.
        assert safety.halt_reason(path=path) == "first reason"

    def test_clear_halt_removes_sentinel(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        safety.write_halt("boom", path=path)
        assert safety.is_halted(path=path) is True
        safety.clear_halt(path=path)
        assert safety.is_halted(path=path) is False

    def test_clear_halt_is_idempotent(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        # No file present — must not raise.
        safety.clear_halt(path=path)
        assert safety.is_halted(path=path) is False

    def test_clear_halt_appends_resume_audit_history(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        halt_clock = _fixed_clock(datetime(2026, 6, 11, 1, 0, tzinfo=UTC))
        resume_clock = _fixed_clock(datetime(2026, 6, 12, 9, 0, tzinfo=UTC))
        safety.write_halt("reconciliation mismatch", path=path, clock=halt_clock)
        safety.clear_halt(path=path, clock=resume_clock)

        history = tmp_path / ".trading-system.halt.history"
        assert history.exists()
        line = history.read_text().splitlines()[0]
        assert line.startswith("resumed_at=2026-06-12T09:00:00+00:00")
        # halt 사유 + halt 시각 모두 보존 (sentinel 삭제 후 유일한 기록)
        assert "reconciliation mismatch" in line
        assert "2026-06-11T01:00:00+00:00" in line

    def test_clear_halt_history_accumulates_across_cycles(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        safety.write_halt("first", path=path)
        safety.clear_halt(path=path)
        safety.write_halt("second", path=path)
        safety.clear_halt(path=path)

        history = tmp_path / ".trading-system.halt.history"
        lines = history.read_text().splitlines()
        assert len(lines) == 2
        assert "first" in lines[0]
        assert "second" in lines[1]

    def test_clear_halt_without_sentinel_writes_no_history(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        safety.clear_halt(path=path)
        assert not (tmp_path / ".trading-system.halt.history").exists()

    def test_is_halted_false_when_absent(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        assert safety.is_halted(path=path) is False
        assert safety.halt_reason(path=path) is None

    def test_check_halt_exits_nonzero_when_present(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        safety.write_halt("integrity violation", path=path)
        with pytest.raises(SystemExit) as exc:
            safety.check_halt(path=path)
        # Abnormal stop → non-zero (cron error signal for a human).
        assert exc.value.code != 0
        assert exc.value.code == 1

    def test_check_halt_noop_when_absent(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        assert safety.check_halt(path=path) is None


# ---------------------------------------------------------------------------
# check_halt (exit != 0) vs check_kill_switch (exit 0) — distinct semantics
# ---------------------------------------------------------------------------
class TestHaltVsKillSwitchExitCodes:
    def test_kill_switch_halts_immediately_exit_zero(self, monkeypatch):
        monkeypatch.setenv("TRADING_HALT", "1")
        with pytest.raises(SystemExit) as exc:
            safety.check_kill_switch()
        # Operator-requested clean stop → exit 0.
        assert exc.value.code == 0

    def test_check_halt_exit_nonzero_distinct_from_kill_switch(self, tmp_path):
        path = tmp_path / ".trading-system.halt"
        safety.write_halt("abnormal", path=path)
        with pytest.raises(SystemExit) as exc:
            safety.check_halt(path=path)
        # Persistent halt = abnormal → non-zero, NOT the kill switch's 0.
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# CLI wiring — halt / resume + entry-time blocking
# ---------------------------------------------------------------------------
class TestHaltResumeCLI:
    def _isolate_halt_path(self, monkeypatch, tmp_path):
        """Point the default halt path at tmp_path (home stays clean)."""
        path = tmp_path / ".trading-system.halt"
        monkeypatch.setattr(safety, "_HALT_PATH", path)
        return path

    def test_halt_command_creates_sentinel(self, monkeypatch, tmp_path):
        path = self._isolate_halt_path(monkeypatch, tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["halt", "--reason", "manual stop"])
        assert result.exit_code == 0
        assert path.exists()
        assert safety.halt_reason(path=path) == "manual stop"
        assert "HALTED" in result.output

    def test_resume_command_removes_sentinel(self, monkeypatch, tmp_path):
        path = self._isolate_halt_path(monkeypatch, tmp_path)
        safety.write_halt("manual stop", path=path)
        runner = CliRunner()
        result = runner.invoke(cli, ["resume"])
        assert result.exit_code == 0
        assert not path.exists()
        assert "RESUMED" in result.output

    def test_resume_when_not_halted_is_noop(self, monkeypatch, tmp_path):
        path = self._isolate_halt_path(monkeypatch, tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["resume"])
        assert result.exit_code == 0
        assert not path.exists()
        assert "nothing to clear" in result.output.lower()

    def test_halted_blocks_trading_command(self, monkeypatch, tmp_path):
        path = self._isolate_halt_path(monkeypatch, tmp_path)
        safety.write_halt("integrity violation", path=path)
        runner = CliRunner()
        # config validate is a normal (non-exempt) subcommand → blocked at entry.
        result = runner.invoke(cli, ["config", "validate", "--config", "x"])
        assert result.exit_code != 0

    def test_resume_reachable_while_halted(self, monkeypatch, tmp_path):
        # The whole point: a halt must not lock out its own resume.
        path = self._isolate_halt_path(monkeypatch, tmp_path)
        safety.write_halt("integrity violation", path=path)
        runner = CliRunner()
        result = runner.invoke(cli, ["resume"])
        assert result.exit_code == 0
        assert not path.exists()

    def test_halt_preserves_reason_when_already_halted(self, monkeypatch, tmp_path):
        path = self._isolate_halt_path(monkeypatch, tmp_path)
        safety.write_halt("first reason", path=path)
        runner = CliRunner()
        result = runner.invoke(cli, ["halt", "--reason", "second reason"])
        assert result.exit_code == 0
        assert safety.halt_reason(path=path) == "first reason"
        assert "preserved" in result.output.lower()
