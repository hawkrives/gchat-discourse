# ABOUTME: Shared pytest fixtures for Discourse exporter tests
# ABOUTME: Provides reusable database setup for state.db and chat.db

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def discourse_dbs(discourse_state_db, chat_db) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Provide both state and chat databases together.

    Returns:
        Tuple of (state_conn, chat_conn)
    """
    discourse_conn = discourse_state_db.conn
    assert discourse_conn is not None

    chat_conn = chat_db.conn
    assert chat_conn is not None

    return discourse_conn, chat_conn
