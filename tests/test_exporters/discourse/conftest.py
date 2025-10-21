# ABOUTME: Shared pytest fixtures for Discourse exporter tests
# ABOUTME: Provides reusable database setup for state.db and chat.db

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from gchat_mirror.common.migrations import run_migrations


@pytest.fixture
def discourse_state_db(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Create a Discourse exporter state database with production schema."""
    state_db_path = tmp_path / "state.db"
    migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations" / "discourse"
    run_migrations(state_db_path, migrations_dir)
    
    conn = sqlite3.connect(state_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def chat_db(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Create a chat database with production schema."""
    chat_db_path = tmp_path / "chat.db"
    migrations_dir = Path(__file__).parent.parent.parent.parent / "migrations"
    run_migrations(chat_db_path, migrations_dir)
    
    conn = sqlite3.connect(chat_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def discourse_dbs(
    discourse_state_db: sqlite3.Connection,
    chat_db: sqlite3.Connection,
) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Provide both state and chat databases together.
    
    Returns:
        Tuple of (state_conn, chat_conn)
    """
    return discourse_state_db, chat_db
