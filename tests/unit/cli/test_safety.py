"""Unit tests for src.cli.safety — kill switch + lock file."""
from __future__ import annotations

import os

import pytest

from src.cli import safety
from src.cli.safety import (
    ConcurrentRunError,
    acquire_lock,
    check_kill_switch,
    lock_file,
    release_lock,
)


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------
class TestKillSwitch:
    def test_no_env_var_is_noop(self, monkeypatch):
        monkeypatch.delenv("TRADING_HALT", raising=False)
        # Returns None, does not raise.
        assert check_kill_switch() is None

    def test_env_var_one_exits_with_code_zero(self, monkeypatch):
        monkeypatch.setenv("TRADING_HALT", "1")
        with pytest.raises(SystemExit) as exc:
            check_kill_switch()
        assert exc.value.code == 0

    def test_env_var_other_values_are_noop(self, monkeypatch):
        # Only "1" triggers; "0", "true", etc. do nothing (operator must
        # choose the explicit "1" sentinel — avoids accidental halts).
        for val in ("0", "true", "yes", ""):
            monkeypatch.setenv("TRADING_HALT", val)
            assert check_kill_switch() is None


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------
class TestAcquireLock:
    def test_acquires_when_path_missing(self, tmp_path):
        lock = tmp_path / "test.lock"
        result = acquire_lock(lock)
        assert result == lock
        assert lock.read_text().strip() == str(os.getpid())

    def test_concurrent_run_with_alive_pid_raises(self, tmp_path, monkeypatch):
        lock = tmp_path / "test.lock"
        # Pretend pid 99999 is alive and not ours.
        lock.write_text("99999\n")
        monkeypatch.setattr(safety, "_is_pid_alive", lambda pid: pid == 99999)
        with pytest.raises(ConcurrentRunError):
            acquire_lock(lock)
        # File untouched (still belongs to "other" pid)
        assert lock.read_text().strip() == "99999"

    def test_stale_lock_is_cleared_and_acquired(self, tmp_path, monkeypatch):
        lock = tmp_path / "test.lock"
        lock.write_text("99999\n")
        # Simulate dead pid
        monkeypatch.setattr(safety, "_is_pid_alive", lambda pid: False)
        result = acquire_lock(lock)
        assert result == lock
        assert lock.read_text().strip() == str(os.getpid())

    def test_garbage_lock_treated_as_stale(self, tmp_path):
        lock = tmp_path / "test.lock"
        lock.write_text("not-a-pid\n")
        # No pid alive check needed — invalid content is handled directly.
        result = acquire_lock(lock)
        assert result == lock
        assert lock.read_text().strip() == str(os.getpid())

    def test_re_acquire_by_same_pid_is_idempotent(self, tmp_path):
        lock = tmp_path / "test.lock"
        acquire_lock(lock)
        # Same process acquiring again: no error, no rewrite churn needed.
        result = acquire_lock(lock)
        assert result == lock
        assert lock.read_text().strip() == str(os.getpid())


class TestReleaseLock:
    def test_release_removes_owned_lock(self, tmp_path):
        lock = tmp_path / "test.lock"
        acquire_lock(lock)
        release_lock(lock)
        assert not lock.exists()

    def test_release_when_missing_is_noop(self, tmp_path):
        lock = tmp_path / "missing.lock"
        # Should not raise
        release_lock(lock)
        assert not lock.exists()

    def test_release_does_not_remove_other_pid_lock(self, tmp_path):
        lock = tmp_path / "test.lock"
        lock.write_text("99999\n")  # not us
        release_lock(lock)
        # Still there — we don't own it.
        assert lock.exists()
        assert lock.read_text().strip() == "99999"


class TestLockFileContext:
    def test_context_manager_acquires_and_releases(self, tmp_path):
        lock = tmp_path / "test.lock"
        with lock_file(lock) as acquired:
            assert acquired == lock
            assert lock.exists()
        assert not lock.exists()

    def test_context_manager_releases_on_exception(self, tmp_path):
        lock = tmp_path / "test.lock"
        with pytest.raises(RuntimeError, match="boom"), lock_file(lock):
            assert lock.exists()
            raise RuntimeError("boom")
        assert not lock.exists()
