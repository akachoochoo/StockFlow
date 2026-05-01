"""Shared fixtures for infrastructure integration tests."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.infrastructure.db import connect

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """Fresh in-memory SQLite connection with the Phase 0 schema."""
    c = connect(":memory:")
    try:
        yield c
    finally:
        c.close()
