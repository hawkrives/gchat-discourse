# ABOUTME: Tests for space activity tracking migration (011)
# ABOUTME: Verifies activity tracking fields and activity log table creation

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest


@pytest.fixture
def chat_db_with_spaces(chat_db) -> Generator[sqlite3.Connection, None, None]:
    """Create a chat.db with spaces table for testing activity fields."""
    conn = chat_db.conn
    assert conn is not None

    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_space_activity_migration_adds_fields(chat_db_with_spaces: sqlite3.Connection) -> None:
    """Test that migration 011 adds activity tracking fields to spaces table."""

    # Insert a test space with activity fields
    chat_db_with_spaces.execute(
        """
        INSERT INTO spaces 
        (id, name, display_name, message_count_24h, message_count_7d, poll_interval_seconds)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("space1", "spaces/space1", "Test Space", 50, 100, 10),
    )
    chat_db_with_spaces.commit()

    # Verify fields exist and have correct values
    cursor = chat_db_with_spaces.execute(
        """
        SELECT message_count_24h, message_count_7d, poll_interval_seconds, last_activity_check
        FROM spaces WHERE id = ?
        """,
        ("space1",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["message_count_24h"] == 50
    assert row["message_count_7d"] == 100
    assert row["poll_interval_seconds"] == 10
    assert row["last_activity_check"] is None  # Not set yet


def test_activity_log_foreign_key_constraint(chat_db_with_spaces: sqlite3.Connection) -> None:
    """Test that activity log enforces foreign key to spaces."""

    # Enable foreign key constraints
    chat_db_with_spaces.execute("PRAGMA foreign_keys = ON")

    # Try to insert activity log for non-existent space
    with pytest.raises(sqlite3.IntegrityError):
        chat_db_with_spaces.execute(
            """
            INSERT INTO space_activity_log
            (space_id, message_count, window_start, window_end)
            VALUES (?, ?, ?, ?)
            """,
            ("nonexistent", 10, "2025-01-15T00:00:00Z", "2025-01-16T00:00:00Z"),
        )


def test_activity_log_index_created(chat_db_with_spaces: sqlite3.Connection) -> None:
    """Test that migration creates index on space_id and window_start."""

    # Check for index
    cursor = chat_db_with_spaces.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='index' AND name='idx_activity_log_space'
        """
    )
    assert cursor.fetchone() is not None


def test_default_poll_interval_is_300(chat_db_with_spaces: sqlite3.Connection) -> None:
    """Test that poll_interval_seconds defaults to 300 (5 minutes)."""

    # Insert space without specifying poll_interval
    chat_db_with_spaces.execute(
        """
        INSERT INTO spaces (id, name) VALUES (?, ?)
        """,
        ("space1", "Test Space"),
    )
    chat_db_with_spaces.commit()

    # Verify default value
    cursor = chat_db_with_spaces.execute(
        "SELECT poll_interval_seconds FROM spaces WHERE id = ?",
        ("space1",),
    )
    row = cursor.fetchone()
    assert row["poll_interval_seconds"] == 300


def test_access_denied_fields_added(chat_db_with_spaces: sqlite3.Connection) -> None:
    """Test that access_denied_at and access_denied_reason fields are added."""

    # Insert space with access denied info
    chat_db_with_spaces.execute(
        """
        INSERT INTO spaces 
        (id, name, sync_status, access_denied_at, access_denied_reason)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("space1", "Denied Space", "access_denied", "2025-01-15T10:00:00Z", "Access denied by API"),
    )
    chat_db_with_spaces.commit()

    # Verify fields exist and have correct values
    cursor = chat_db_with_spaces.execute(
        """
        SELECT sync_status, access_denied_at, access_denied_reason
        FROM spaces WHERE id = ?
        """,
        ("space1",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["sync_status"] == "access_denied"
    assert row["access_denied_at"] == "2025-01-15T10:00:00Z"
    assert row["access_denied_reason"] == "Access denied by API"
