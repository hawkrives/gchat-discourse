# ABOUTME: Integration tests for sync daemon
# ABOUTME: Validates full sync flow using mocked Google Chat API responses

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest  # type: ignore

from gchat_mirror.common.migrations import run_migrations
from gchat_mirror.sync.daemon import SyncDaemon


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    dir_path = tmp_path / "data"
    db_path = dir_path / "sync" / "chat.db"
    run_migrations(db_path, Path(__file__).resolve().parents[2] / "migrations")
    return dir_path


def test_full_sync_process(data_dir: Path, httpx_mock, monkeypatch: pytest.MonkeyPatch) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://chat.googleapis.com/v1/spaces",
        json={
            "spaces": [
                {
                    "name": "spaces/AAAA1234",
                    "displayName": "Engineering",
                    "type": "SPACE",
                    "spaceThreadingState": "THREADED_MESSAGES",
                },
                {
                    "name": "spaces/BBBB5678",
                    "displayName": "Design",
                    "type": "SPACE",
                    "spaceThreadingState": "THREADED_MESSAGES",
                },
            ]
        },
    )

    httpx_mock.add_response(
        method="GET",
        url="https://chat.googleapis.com/v1/spaces/AAAA1234/messages?pageSize=100",
        json={
            "messages": [
                {
                    "name": "spaces/AAAA1234/messages/MSG001",
                    "text": "Hello everyone!",
                    "createTime": "2025-01-15T10:00:00Z",
                    "sender": {
                        "name": "users/USER001",
                        "displayName": "Alice",
                        "type": "HUMAN",
                        "email": "alice@example.com",
                    },
                    "thread": {"name": "spaces/AAAA1234/threads/THREAD001"},
                },
                {
                    "name": "spaces/AAAA1234/messages/MSG002",
                    "text": "Hi Alice!",
                    "createTime": "2025-01-15T10:05:00Z",
                    "sender": {
                        "name": "users/USER002",
                        "displayName": "Bob",
                        "type": "HUMAN",
                        "email": "bob@example.com",
                    },
                    "thread": {"name": "spaces/AAAA1234/threads/THREAD001"},
                },
            ]
        },
    )

    httpx_mock.add_response(
        method="GET",
        url="https://chat.googleapis.com/v1/spaces/BBBB5678/messages?pageSize=100",
        json={
            "messages": [
                {
                    "name": "spaces/BBBB5678/messages/MSG003",
                    "text": "Design review today",
                    "createTime": "2025-01-15T11:00:00Z",
                    "sender": {
                        "name": "users/USER001",
                        "displayName": "Alice",
                        "type": "HUMAN",
                        "email": "alice@example.com",
                    },
                }
            ]
        },
    )

    fake_creds = Mock(token="test-token", valid=True, expired=False)
    monkeypatch.setattr("gchat_mirror.sync.auth.authenticate", lambda key: fake_creds)
    monkeypatch.setattr("gchat_mirror.sync.daemon.authenticate", lambda key: fake_creds)

    daemon = SyncDaemon(data_dir, {"credential_key": "test-key"})
    daemon.start()

    db_path = data_dir / "sync" / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        spaces = conn.execute("SELECT id, display_name FROM spaces ORDER BY id").fetchall()
        assert len(spaces) == 2
        assert spaces[0][0] == "spaces/AAAA1234"
        assert spaces[1][0] == "spaces/BBBB5678"

        users = conn.execute("SELECT id, display_name FROM users ORDER BY id").fetchall()
        assert len(users) == 2
        assert users[0][1] == "Alice"
        assert users[1][1] == "Bob"

        messages = conn.execute("SELECT id, text, sender_id FROM messages ORDER BY id").fetchall()
        assert len(messages) == 3
        assert messages[0][1] == "Hello everyone!"
        assert messages[1][1] == "Hi Alice!"
        assert messages[2][1] == "Design review today"
        assert messages[2][2] == "users/USER001"
    finally:
        conn.close()
        daemon.stop()
