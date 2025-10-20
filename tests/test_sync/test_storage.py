# ABOUTME: Tests for sync storage helpers
# ABOUTME: Confirms SQLite operations for spaces, users, and messages

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest  # type: ignore

from gchat_mirror.common.migrations import run_migrations
from gchat_mirror.sync.storage import SyncStorage


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[SyncStorage]:
    db_path = tmp_path / "chat.db"
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    run_migrations(db_path, migrations_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    store = SyncStorage(conn)
    try:
        yield store
    finally:
        conn.close()


def test_upsert_space_updates_existing(storage: SyncStorage) -> None:
    space_payload = {
        "name": "spaces/TEST",
        "displayName": "Test Space",
        "type": "SPACE",
        "spaceThreadingState": "THREADED_MESSAGES",
    }

    storage.upsert_space(space_payload)

    storage.upsert_space({**space_payload, "displayName": "Updated"})

    cursor = storage.conn.execute("SELECT display_name, threaded FROM spaces WHERE id=?", ("spaces/TEST",))
    row = cursor.fetchone()

    assert row["display_name"] == "Updated"
    assert row["threaded"] == 1


def test_user_upsert_writes_row(storage: SyncStorage) -> None:
    user_payload = {
        "name": "users/USER1",
        "displayName": "Alice",
        "type": "HUMAN",
        "email": "alice@example.com",
    }

    storage.upsert_user(user_payload)

    cursor = storage.conn.execute("SELECT display_name, email FROM users WHERE id=?", ("users/USER1",))
    row = cursor.fetchone()

    assert row["display_name"] == "Alice"
    assert row["email"] == "alice@example.com"


def test_insert_message_stores_payload(storage: SyncStorage) -> None:
    storage.upsert_space({
        "name": "spaces/TEST",
        "displayName": "Test Space",
        "type": "SPACE",
    })
    storage.upsert_user({
        "name": "users/USER1",
        "displayName": "Alice",
        "type": "HUMAN",
    })

    message_payload = {
        "name": "spaces/TEST/messages/MSG1",
        "text": "Hello",
        "createTime": "2025-01-01T00:00:00Z",
        "sender": {"name": "users/USER1"},
        "thread": {"name": "spaces/TEST/threads/THREAD1"},
        "space": {"name": "spaces/TEST"},
    }

    storage.insert_message(message_payload)
    storage.insert_message(message_payload)

    cursor = storage.conn.execute("SELECT text, thread_id, raw_data FROM messages WHERE id=?", ("spaces/TEST/messages/MSG1",))
    row = cursor.fetchone()

    assert row["text"] == "Hello"
    assert row["thread_id"] == "spaces/TEST/threads/THREAD1"
    assert json.loads(row["raw_data"]) == message_payload

    cursor = storage.conn.execute("SELECT COUNT(*) FROM messages")
    assert cursor.fetchone()[0] == 1


def test_sync_cursor_helpers(storage: SyncStorage) -> None:
    storage.upsert_space({"name": "spaces/TEST"})

    assert storage.get_space_sync_cursor("spaces/TEST") is None
    storage.update_space_sync_cursor("spaces/TEST", "cursor123")
    assert storage.get_space_sync_cursor("spaces/TEST") == "cursor123"
