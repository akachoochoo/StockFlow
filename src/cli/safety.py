"""CLI-level safety primitives — kill switch, PID lock, NTP sync, halt file.

Per ADR §10.5 / ADR 0012 D14+D15 / CLAUDE.md §3.3 / §11.1 / §11.2 / §10.2:

* Kill switch — ``TRADING_HALT=1`` env var halts every command at entry
  (operator-requested clean stop, ``sys.exit(0)``).
* Lock file — ``~/.trading-system.lock`` (or override) prevents concurrent
  CLI runs on the same machine. Stale locks (PID no longer alive) are
  cleaned up automatically.
* NTP sync — ``verify_ntp_sync()`` shells out to ``scripts/check_ntp_sync.sh``
  before any live trade (CLAUDE.md §3.3). Fail-closed: any non-zero exit
  raises ``ClockSkewError`` (an IntegrityError → halt all trading).
* Persistent halt — ``~/.trading-system.halt`` sentinel survives across cron
  processes (env vars do not). ``check_halt()`` exits **non-zero** (abnormal
  stop → cron error signal for a human) distinct from the kill switch's
  ``exit(0)`` (operator-requested clean stop). CLAUDE.md §11.2.

The implementations are intentionally tiny and dependency-free (pure
``os`` / ``sys`` / ``pathlib`` / ``subprocess``). Phase 1+ may add fcntl /
NFS-aware locking when distributed runners arrive.
"""
from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.domain.exceptions import ClockSkewError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


_KILL_SWITCH_ENV = "TRADING_HALT"
_DEFAULT_LOCK_PATH = Path.home() / ".trading-system.lock"
_HALT_PATH = Path.home() / ".trading-system.halt"
_NTP_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_ntp_sync.sh"
)

_logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Module-level UTC clock (default for write_halt; injectable in tests)."""
    return datetime.now(UTC)


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


# ---------------------------------------------------------------------------
# NTP sync (CLAUDE.md §3.3 — refuse to trade when clock drift > threshold)
# ---------------------------------------------------------------------------
def verify_ntp_sync(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    script_path: Path | None = None,
) -> None:
    """Verify the system clock is NTP-synced before any live trade.

    Shells out to ``scripts/check_ntp_sync.sh`` (exit 0 = synced, 1 = offset
    exceeded, 2 = unmeasurable). Any non-zero exit — including a missing tool —
    raises :class:`ClockSkewError` (an IntegrityError → halt all trading).
    This is **fail-closed**: if we cannot prove the clock is good, we refuse.

    ``runner`` is injectable so tests can simulate exit codes without touching
    the network or a real subprocess. ``script_path`` defaults to the repo's
    ``scripts/check_ntp_sync.sh``.
    """
    path = script_path if script_path is not None else _NTP_SCRIPT_PATH
    result = runner(
        ["bash", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return

    detail = (result.stderr or result.stdout or "").strip()
    reason = {
        1: "NTP offset exceeds threshold",
        2: "NTP offset unmeasurable (no tool / server unreachable)",
    }.get(result.returncode, f"NTP check exit {result.returncode}")
    message = f"{reason} — refusing to trade (fail-closed)."
    if detail:
        message = f"{message} {detail}"
    _logger.critical("Clock sync check failed: %s", message)
    raise ClockSkewError(message)


# ---------------------------------------------------------------------------
# Persistent halt sentinel (CLAUDE.md §11.2 — survives across cron processes)
# ---------------------------------------------------------------------------
def default_halt_path() -> Path:
    """Public so the CLI and tests share one source of truth."""
    return _HALT_PATH


def write_halt(
    reason: str,
    *,
    path: Path | str | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> Path:
    """Write the persistent halt sentinel and return its path.

    Records ``{reason}\\n{ISO-8601 UTC timestamp}``. If the sentinel already
    exists it is **left untouched** — the first (root-cause) halt reason is
    the one a human needs to see, so subsequent halts must not clobber it.
    """
    halt_path = Path(path) if path is not None else default_halt_path()
    if halt_path.exists():
        _logger.warning(
            "Halt sentinel already present at %s — preserving original reason.",
            halt_path,
        )
        return halt_path
    halt_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = clock().isoformat()
    halt_path.write_text(f"{reason}\n{timestamp}\n")
    _logger.critical("Halt sentinel written: %s (reason=%r)", halt_path, reason)
    return halt_path


def clear_halt(*, path: Path | str | None = None) -> None:
    """Remove the halt sentinel (explicit human resume). Idempotent."""
    halt_path = Path(path) if path is not None else default_halt_path()
    halt_path.unlink(missing_ok=True)


def is_halted(*, path: Path | str | None = None) -> bool:
    """True iff the persistent halt sentinel exists."""
    halt_path = Path(path) if path is not None else default_halt_path()
    return halt_path.exists()


def halt_reason(*, path: Path | str | None = None) -> str | None:
    """Return the recorded halt reason (first line), or None if not halted."""
    halt_path = Path(path) if path is not None else default_halt_path()
    if not halt_path.exists():
        return None
    text = halt_path.read_text()
    first_line = text.splitlines()[0] if text else ""
    return first_line


def check_halt(*, path: Path | str | None = None) -> None:
    """Halt the process when the persistent sentinel exists.

    Logs CRITICAL with the recorded reason and calls ``sys.exit(1)`` — a
    **non-zero** exit so cron flags the run as an error and alerts a human.
    This is deliberately distinct from :func:`check_kill_switch` (``exit(0)``,
    an operator-requested clean stop). Absent sentinel is a no-op.
    """
    halt_path = Path(path) if path is not None else default_halt_path()
    if not halt_path.exists():
        return
    reason = halt_reason(path=halt_path) or "(no reason recorded)"
    _logger.critical(
        "Persistent halt active (%s) — exiting non-zero. Reason: %s",
        halt_path, reason,
    )
    sys.exit(1)
