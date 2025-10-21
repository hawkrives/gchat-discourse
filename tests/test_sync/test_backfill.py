# ABOUTME: Tests for backfill manager functionality
# ABOUTME: Verifies historical message retrieval and time window handling

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest  # type: ignore

from gchat_mirror.common.migrations import run_migrations
from gchat_mirror.sync.backfill import BackfillManager


@pytest.fixture
def test_backfill_db(tmp_path: Path) -> Path:
    """Create a test database with migrations applied."""
    db_path = tmp_path / "sync" / "chat.db"
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"

    # Run all migrations to get complete schema
    run_migrations(db_path, migrations_dir)

    return db_path


def test_backfill_space_fetches_historical_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_backfill_db: Path
) -> None:
    """Test that backfill fetches messages older than existing ones."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.backfill.authenticate", lambda key: mock_creds)

    # Setup: Insert a space and a recent message
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES (?, ?, ?, ?)
        """,
        ("spaces/SPACE1", "spaces/SPACE1", "Test Space", "active"),
    )

    # Insert a recent message (from 2 days ago)
    recent_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    conn.execute(
        """
        INSERT INTO messages (id, space_id, text, create_time)
        VALUES (?, ?, ?, ?)
        """,
        ("spaces/SPACE1/messages/RECENT", "spaces/SPACE1", "Recent message", recent_time),
    )
    conn.commit()
    conn.close()

    # Mock API to return older messages
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

    class FakeClient:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_messages(self, space_id, page_token=None, page_size=100):
            return {
                "messages": [
                    {
                        "name": "spaces/SPACE1/messages/OLD1",
                        "text": "Old message",
                        "createTime": old_time,
                        "sender": {"name": "users/USER1", "displayName": "Alice", "type": "HUMAN"},
                    }
                ]
            }

        def close(self):
            self.closed = True

    fake_client = FakeClient(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.backfill.GoogleChatClient", lambda creds: fake_client)

    # Run backfill
    manager = BackfillManager(tmp_path, {"credential_key": "test"})
    manager.backfill_space("spaces/SPACE1", days=365, batch_size=100)

    # Verify old message was stored
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute(
            """
            SELECT text FROM messages WHERE id = ?
            """,
            ("spaces/SPACE1/messages/OLD1",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["text"] == "Old message"
    finally:
        conn.close()


def test_backfill_space_skips_newer_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_backfill_db: Path
) -> None:
    """Test that backfill skips messages newer than oldest existing message."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.backfill.authenticate", lambda key: mock_creds)

    # Setup: Insert a space and message from 5 days ago
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES (?, ?, ?, ?)
        """,
        ("spaces/SPACE1", "spaces/SPACE1", "Test Space", "active"),
    )

    oldest_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    conn.execute(
        """
        INSERT INTO messages (id, space_id, text, create_time)
        VALUES (?, ?, ?, ?)
        """,
        ("spaces/SPACE1/messages/OLDEST", "spaces/SPACE1", "Oldest message", oldest_time),
    )
    conn.commit()

    # Count messages before backfill
    cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE space_id = ?", ("spaces/SPACE1",))
    count_before = cursor.fetchone()[0]
    conn.close()

    # Mock API to return newer message (should be skipped)
    newer_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    class FakeClient:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_messages(self, space_id, page_token=None, page_size=100):
            return {
                "messages": [
                    {
                        "name": "spaces/SPACE1/messages/NEWER",
                        "text": "Newer message",
                        "createTime": newer_time,
                        "sender": {"name": "users/USER1", "displayName": "Alice", "type": "HUMAN"},
                    }
                ]
            }

        def close(self):
            self.closed = True

    fake_client = FakeClient(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.backfill.GoogleChatClient", lambda creds: fake_client)

    # Run backfill
    manager = BackfillManager(tmp_path, {"credential_key": "test"})
    manager.backfill_space("spaces/SPACE1", days=365, batch_size=100)

    # Verify newer message was not stored
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE space_id = ?", ("spaces/SPACE1",))
        count_after = cursor.fetchone()[0]
        # Count should be same (newer message skipped)
        assert count_after == count_before

        cursor = conn.execute(
            """
            SELECT id FROM messages WHERE id = ?
            """,
            ("spaces/SPACE1/messages/NEWER",),
        )
        row = cursor.fetchone()
        assert row is None  # Newer message should not exist
    finally:
        conn.close()


def test_backfill_respects_time_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_backfill_db: Path
) -> None:
    """Test that backfill stops at time window limit."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.backfill.authenticate", lambda key: mock_creds)

    # Setup: Insert a space with no messages
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES (?, ?, ?, ?)
        """,
        ("spaces/SPACE1", "spaces/SPACE1", "Test Space", "active"),
    )
    conn.commit()
    conn.close()

    # Mock API to return very old message (beyond time window)
    very_old_time = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()

    class FakeClient:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_messages(self, space_id, page_token=None, page_size=100):
            return {
                "messages": [
                    {
                        "name": "spaces/SPACE1/messages/VERYOLD",
                        "text": "Very old message",
                        "createTime": very_old_time,
                        "sender": {"name": "users/USER1", "displayName": "Alice", "type": "HUMAN"},
                    }
                ]
            }

        def close(self):
            self.closed = True

    fake_client = FakeClient(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.backfill.GoogleChatClient", lambda creds: fake_client)

    # Run backfill with 365 day limit
    manager = BackfillManager(tmp_path, {"credential_key": "test"})
    manager.backfill_space("spaces/SPACE1", days=365, batch_size=100)

    # Verify very old message was not stored (beyond time window)
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE space_id = ?", ("spaces/SPACE1",))
        count = cursor.fetchone()[0]
        assert count == 0  # No messages should be stored
    finally:
        conn.close()


def test_backfill_all_spaces(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_backfill_db: Path) -> None:
    """Test that backfill_all_spaces processes multiple spaces."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.backfill.authenticate", lambda key: mock_creds)

    # Setup: Insert two active spaces
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES 
        (?, ?, ?, ?),
        (?, ?, ?, ?)
        """,
        (
            "spaces/SPACE1",
            "spaces/SPACE1",
            "Space One",
            "active",
            "spaces/SPACE2",
            "spaces/SPACE2",
            "Space Two",
            "active",
        ),
    )
    conn.commit()
    conn.close()

    # Track which spaces were queried
    queried_spaces = []

    class FakeClient:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_messages(self, space_id, page_token=None, page_size=100):
            queried_spaces.append(space_id)
            return {"messages": []}  # Return empty for simplicity

        def close(self):
            self.closed = True

    fake_client = FakeClient(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.backfill.GoogleChatClient", lambda creds: fake_client)

    # Run backfill for all spaces
    manager = BackfillManager(tmp_path, {"credential_key": "test"})
    manager.backfill_all_spaces(days=30, batch_size=100)

    # Verify both spaces were queried
    assert "spaces/SPACE1" in queried_spaces
    assert "spaces/SPACE2" in queried_spaces


def test_backfill_skips_access_denied_spaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_backfill_db: Path
) -> None:
    """Test that backfill only processes active spaces."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.backfill.authenticate", lambda key: mock_creds)

    # Setup: Insert one active and one access_denied space
    conn = sqlite3.connect(test_backfill_db)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES 
        (?, ?, ?, ?),
        (?, ?, ?, ?)
        """,
        (
            "spaces/SPACE1",
            "spaces/SPACE1",
            "Active Space",
            "active",
            "spaces/SPACE2",
            "spaces/SPACE2",
            "Denied Space",
            "access_denied",
        ),
    )
    conn.commit()
    conn.close()

    # Track which spaces were queried
    queried_spaces = []

    class FakeClient:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_messages(self, space_id, page_token=None, page_size=100):
            queried_spaces.append(space_id)
            return {"messages": []}

        def close(self):
            self.closed = True

    fake_client = FakeClient(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.backfill.GoogleChatClient", lambda creds: fake_client)

    # Run backfill for all spaces
    manager = BackfillManager(tmp_path, {"credential_key": "test"})
    manager.backfill_all_spaces(days=30, batch_size=100)

    # Verify only active space was queried
    assert "spaces/SPACE1" in queried_spaces
    assert "spaces/SPACE2" not in queried_spaces
