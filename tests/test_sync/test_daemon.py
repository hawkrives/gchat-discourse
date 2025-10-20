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
    config = {"credential_key": "test-key"}
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