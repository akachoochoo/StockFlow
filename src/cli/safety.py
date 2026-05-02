"""CLI-level safety primitives — kill switch + PID-based lock file.

Per ADR §10.5 / CLAUDE.md §11.1 / §10.2:

* Kill switch — ``TRADING_HALT=1`` env var halts every command at entry.
* Lock file — ``~/.trading-system.lock`` (or override) prevents concurrent
  CLI runs on the same machine. Stale locks (PID no longer alive) are
  cleaned up automatically.

The implementations are intentionally tiny and dependency-free (pure
``os`` / ``sys`` / ``pathlib``). Phase 1+ may add fcntl / NFS-aware locking
when distributed runners arrive.
"""
from __future__ import annotations

import atexit
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


_KILL_SWITCH_ENV = "TRADING_HALT"
_DEFAULT_LOCK_PATH = Path.home() / ".trading-system.lock"

_logger = logging.getLogger(__name__)


class ConcurrentRunError(RuntimeError):
    """Another live trading process holds the lock file."""


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------
def check_kill_switch() -> None:
    """Halt the process when ``TRADING_HALT=1`` is set.

    Calls ``sys.exit(0)`` (clean exit, not an error — the operator asked
    for the halt). Any other value, including unset, is a no-op.
    """
    if os.environ.get(_KILL_SWITCH_ENV) == "1":
        _logger.critical(
            "Kill switch active (%s=1) — exiting before any trading action.",
            _KILL_SWITCH_ENV,
        )
        sys.exit(0)


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------
def default_lock_path() -> Path:
    """Public so the CLI flag default and tests share one source of truth."""
    return _DEFAULT_LOCK_PATH


def _is_pid_alive(pid: int) -> bool:
    """Best-effort liveness probe via signal 0.

    ``os.kill(pid, 0)`` raises ProcessLookupError if the PID does not
    exist, PermissionError if it exists but is owned by a different user
    (we count that as alive — safer to refuse than steal a lock).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(path: Path | str | None = None) -> Path:
    """Acquire the trading-system lock file.

    Returns the resolved path written. Raises ConcurrentRunError when a
    different live process already holds the lock; cleans stale lock files
    automatically when the recorded PID is dead.
    """
    lock_path = Path(path) if path is not None else default_lock_path()
    our_pid = os.getpid()

    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text().strip() or "0")
        except ValueError:
            existing_pid = 0  # garbage → treat as stale

        if existing_pid == our_pid:
            # Same process re-acquiring (e.g. nested call) — idempotent.
            return lock_path

        if _is_pid_alive(existing_pid):
            raise ConcurrentRunError(
                f"Another trading process (pid={existing_pid}) holds "
                f"{lock_path}. Refusing to start."
            )
        _logger.warning(
            "Stale lock file %s (pid=%s no longer alive) — clearing.",
            lock_path, existing_pid,
        )
        lock_path.unlink()

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(f"{our_pid}\n")
    return lock_path


def release_lock(path: Path | str | None = None) -> None:
    """Remove the lock file iff we own it.

    Idempotent — silently no-ops when the file is absent or owned by
    another PID (avoids racing with cleanup tools / atexit).
    """
    lock_path = Path(path) if path is not None else default_lock_path()
    if not lock_path.exists():
        return
    try:
        existing_pid = int(lock_path.read_text().strip() or "0")
    except ValueError:
        existing_pid = 0
    if existing_pid != os.getpid():
        return
    lock_path.unlink(missing_ok=True)


@contextmanager
def lock_file(path: Path | str | None = None) -> Iterator[Path]:
    """Context manager pairing acquire/release with atexit safety net.

    Registers ``release_lock`` via ``atexit`` so abnormal exits (uncaught
    exception, SystemExit) still clean up. The context manager also
    releases on normal exit; the atexit hook then no-ops because we no
    longer own the file.
    """
    acquired = acquire_lock(path)
    atexit.register(release_lock, acquired)
    try:
        yield acquired
    finally:
        release_lock(acquired)
