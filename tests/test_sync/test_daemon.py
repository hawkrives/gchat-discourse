# ABOUTME: Tests for sync daemon orchestration
# ABOUTME: Ensures initial sync stores spaces, users, and messages

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest  # type: ignore

from gchat_mirror.sync.daemon import SyncDaemon


@pytest.fixture
def daemon(tmp_path: Path) -> SyncDaemon:
    # Use a random port to avoid port conflicts between tests
    import random

    port = random.randint(10000, 60000)
    config = {"credential_key": "test-key", "monitoring": {"health_check_port": port}}
    return SyncDaemon(tmp_path, config)


def test_sync_daemon_initial_sync(monkeypatch: pytest.MonkeyPatch, daemon: SyncDaemon) -> None:
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.daemon.authenticate", lambda key: mock_creds)

    spaces = [
        {
            "name": "spaces/SPACE1",
            "displayName": "General",
            "type": "SPACE",
            "spaceThreadingState": "THREADED_MESSAGES",
        }
    ]

    messages = {
        "spaces/SPACE1": {
            "messages": [
                {
                    "name": "spaces/SPACE1/messages/MSG1",
                    "text": "Hello",
                    "createTime": "2025-01-01T00:00:00Z",
                    "sender": {"name": "users/USER1", "displayName": "Alice", "type": "HUMAN"},
                    "thread": {"name": "spaces/SPACE1/threads/THREAD1"},
                    "space": {"name": "spaces/SPACE1"},
                }
            ]
        }
    }

    class FakeClient:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_spaces(self):
            return spaces

        def list_messages(self, space_id, page_token=None, page_size=100):
            return messages[space_id]

        def close(self):
            self.closed = True

    fake_client = FakeClient(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.daemon.GoogleChatClient", lambda creds: fake_client)

    daemon.start()

    db_path = daemon.data_dir / "sync" / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        space_row = conn.execute("SELECT display_name FROM spaces WHERE id=?", ("spaces/SPACE1",)).fetchone()
        assert space_row["display_name"] == "General"

        message_row = conn.execute("SELECT text FROM messages WHERE id=?", ("spaces/SPACE1/messages/MSG1",)).fetchone()
        assert message_row["text"] == "Hello"

        user_row = conn.execute("SELECT display_name FROM users WHERE id=?", ("users/USER1",)).fetchone()
        assert user_row["display_name"] == "Alice"
    finally:
        conn.close()

    daemon.stop()
    assert fake_client.closed is True


def test_sync_space_handles_403_access_denied(monkeypatch: pytest.MonkeyPatch, daemon: SyncDaemon) -> None:
    """Test that 403 errors mark spaces as access_denied."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.daemon.authenticate", lambda key: mock_creds)

    class FakeClient403:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_spaces(self):
            return []

        def list_messages(self, space_id, page_token=None, page_size=100):
            import httpx

            response = Mock()
            response.status_code = 403
            raise httpx.HTTPStatusError("Forbidden", request=Mock(), response=response)

        def close(self):
            self.closed = True

    fake_client = FakeClient403(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.daemon.GoogleChatClient", lambda creds: fake_client)

    daemon.start()

    # Insert a space manually
    if daemon.chat_db.conn is None:
        raise RuntimeError("Database connection missing")

    daemon.chat_db.conn.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES (?, ?, ?, ?)
        """,
        ("spaces/SPACE1", "spaces/SPACE1", "Test Space", "active"),
    )
    daemon.chat_db.conn.commit()

    # Try to sync the space (should get 403)
    space = {"name": "spaces/SPACE1", "displayName": "Test Space"}
    daemon.sync_space(space)

    # Verify space is marked as access_denied
    db_path = daemon.data_dir / "sync" / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        space_row = conn.execute(
            "SELECT sync_status, access_denied_reason FROM spaces WHERE id=?", ("spaces/SPACE1",)
        ).fetchone()
        assert space_row["sync_status"] == "access_denied"
        assert "Access denied" in space_row["access_denied_reason"]
    finally:
        conn.close()

    daemon.stop()


def test_sync_space_handles_404_not_found(monkeypatch: pytest.MonkeyPatch, daemon: SyncDaemon) -> None:
    """Test that 404 errors mark spaces as access_denied (deleted)."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.daemon.authenticate", lambda key: mock_creds)

    class FakeClient404:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_spaces(self):
            return []

        def list_messages(self, space_id, page_token=None, page_size=100):
            import httpx

            response = Mock()
            response.status_code = 404
            raise httpx.HTTPStatusError("Not Found", request=Mock(), response=response)

        def close(self):
            self.closed = True

    fake_client = FakeClient404(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.daemon.GoogleChatClient", lambda creds: fake_client)

    daemon.start()

    # Insert a space manually
    if daemon.chat_db.conn is None:
        raise RuntimeError("Database connection missing")

    daemon.chat_db.conn.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES (?, ?, ?, ?)
        """,
        ("spaces/SPACE1", "spaces/SPACE1", "Deleted Space", "active"),
    )
    daemon.chat_db.conn.commit()

    # Try to sync the space (should get 404)
    space = {"name": "spaces/SPACE1", "displayName": "Deleted Space"}
    daemon.sync_space(space)

    # Verify space is marked as access_denied with appropriate reason
    db_path = daemon.data_dir / "sync" / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        space_row = conn.execute(
            "SELECT sync_status, access_denied_reason FROM spaces WHERE id=?", ("spaces/SPACE1",)
        ).fetchone()
        assert space_row["sync_status"] == "access_denied"
        assert "not found" in space_row["access_denied_reason"].lower()
    finally:
        conn.close()

    daemon.stop()


def test_discover_spaces(monkeypatch: pytest.MonkeyPatch, daemon: SyncDaemon) -> None:
    """Test that discover_spaces fetches and stores spaces."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.daemon.authenticate", lambda key: mock_creds)

    spaces = [
        {"name": "spaces/SPACE1", "displayName": "Space One", "type": "SPACE"},
        {"name": "spaces/SPACE2", "displayName": "Space Two", "type": "SPACE"},
    ]

    class FakeClient:
        def __init__(self, creds):
            self.creds = creds
            self.closed = False

        def list_spaces(self):
            return spaces

        def list_messages(self, space_id, page_token=None, page_size=100):
            return {"messages": []}

        def close(self):
            self.closed = True

    fake_client = FakeClient(mock_creds)
    monkeypatch.setattr("gchat_mirror.sync.daemon.GoogleChatClient", lambda creds: fake_client)

    daemon.start()

    # Discover spaces
    discovered = daemon.discover_spaces()

    assert len(discovered) == 2
    assert discovered[0]["name"] == "spaces/SPACE1"
    assert discovered[1]["name"] == "spaces/SPACE2"

    # Verify spaces are in database
    db_path = daemon.data_dir / "sync" / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        space_count = conn.execute("SELECT COUNT(*) FROM spaces").fetchone()[0]
        assert space_count == 2

        space1 = conn.execute("SELECT display_name FROM spaces WHERE id=?", ("spaces/SPACE1",)).fetchone()
        assert space1["display_name"] == "Space One"
    finally:
        conn.close()

    daemon.stop()