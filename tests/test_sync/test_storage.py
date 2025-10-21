# ABOUTME: Tests for sync storage helpers
# ABOUTME: Confirms SQLite operations for spaces, users, and messages

from __future__ import annotations

import json

import pytest  # type: ignore

from gchat_mirror.sync.storage import SyncStorage


@pytest.fixture
def storage(db) -> SyncStorage:
    """Return a SyncStorage backed by the shared `db` fixture."""
    assert db.conn is not None
    return SyncStorage(db.conn)


def test_upsert_space_updates_existing(storage: SyncStorage) -> None:
    space_payload = {
        "name": "spaces/TEST",
        "displayName": "Test Space",
        "type": "SPACE",
        "spaceThreadingState": "THREADED_MESSAGES",
    }

    storage.upsert_space(space_payload)

    storage.upsert_space({**space_payload, "displayName": "Updated"})

    cursor = storage.conn.execute(
        "SELECT display_name, threaded FROM spaces WHERE id=?", ("spaces/TEST",)
    )
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

    cursor = storage.conn.execute(
        "SELECT display_name, email FROM users WHERE id=?", ("users/USER1",)
    )
    row = cursor.fetchone()

    assert row["display_name"] == "Alice"
    assert row["email"] == "alice@example.com"


def test_insert_message_stores_payload(storage: SyncStorage) -> None:
    storage.upsert_space(
        {
            "name": "spaces/TEST",
            "displayName": "Test Space",
            "type": "SPACE",
        }
    )
    storage.upsert_user(
        {
            "name": "users/USER1",
            "displayName": "Alice",
            "type": "HUMAN",
        }
    )

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

    cursor = storage.conn.execute(
        "SELECT text, thread_id, raw_data FROM messages WHERE id=?", ("spaces/TEST/messages/MSG1",)
    )
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


def test_store_reaction(storage: SyncStorage) -> None:
    """Test storing reactions."""
    # Create prerequisite records
    storage.conn.execute("INSERT INTO spaces (id, name) VALUES ('space1', 'Test Space')")
    storage.conn.execute("INSERT INTO messages (id, space_id) VALUES ('msg1', 'space1')")
    storage.conn.execute("INSERT INTO users (id) VALUES ('user1')")
    storage.conn.commit()

    reaction_data = {
        "name": "spaces/SPACE/messages/MSG/reactions/REACT",
        "message_id": "msg1",
        "emoji": {"content": "👍", "unicode": "U+1F44D"},
        "user": {"name": "user1"},
        "createTime": "2025-01-15T10:00:00Z",
    }

    storage.upsert_reaction(reaction_data)

    # Verify
    cursor = storage.conn.execute(
        """
        SELECT emoji_content, user_id FROM reactions WHERE id = ?
        """,
        (reaction_data["name"],),
    )
    row = cursor.fetchone()
    assert row["emoji_content"] == "👍"
    assert row["user_id"] == "user1"


def test_delete_reaction(storage: SyncStorage) -> None:
    """Test deleting reactions."""
    # Create prerequisite records
    storage.conn.execute("INSERT INTO spaces (id, name) VALUES ('space1', 'Test Space')")
    storage.conn.execute("INSERT INTO messages (id, space_id) VALUES ('msg1', 'space1')")
    storage.conn.execute("INSERT INTO users (id) VALUES ('user1')")
    storage.conn.execute(
        """
        INSERT INTO reactions (id, message_id, emoji_content, user_id, create_time)
        VALUES ('react1', 'msg1', '👍', 'user1', '2025-01-15T10:00:00Z')
        """
    )
    storage.conn.commit()

    # Delete
    storage.delete_reaction("react1")

    # Verify deleted
    cursor = storage.conn.execute("SELECT COUNT(*) FROM reactions WHERE id = 'react1'")
    assert cursor.fetchone()[0] == 0


def test_upsert_custom_emoji(storage: SyncStorage) -> None:
    """Test storing custom emoji."""
    emoji_data = {
        "customEmoji": {
            "uid": "emoji1",
            "name": "partyparrot",
            "url": "https://example.com/parrot.gif",
        }
    }

    storage.upsert_custom_emoji(emoji_data)

    # Verify
    cursor = storage.conn.execute(
        """
        SELECT name, source_url FROM custom_emoji WHERE id = ?
        """,
        ("emoji1",),
    )
    row = cursor.fetchone()
    assert row["name"] == "partyparrot"
    assert row["source_url"] == "https://example.com/parrot.gif"

    # Update
    emoji_data["customEmoji"]["name"] = "updated_parrot"
    storage.upsert_custom_emoji(emoji_data)

    cursor = storage.conn.execute("SELECT name FROM custom_emoji WHERE id = 'emoji1'")
    row = cursor.fetchone()
    assert row["name"] == "updated_parrot"


def test_message_edit_creates_revision(storage: SyncStorage) -> None:
    """Test that editing a message creates a revision."""
    # Create initial message
    storage.upsert_space({"name": "spaces/TEST", "displayName": "Test Space", "type": "SPACE"})
    storage.upsert_user({"name": "users/USER1", "displayName": "Alice", "type": "HUMAN"})

    original = {
        "name": "spaces/TEST/messages/MSG1",
        "text": "original text",
        "updateTime": "2025-01-15T10:00:00Z",
        "sender": {"name": "users/USER1"},
        "space": {"name": "spaces/TEST"},
    }
    storage.insert_message(original)

    # Edit the message
    edited = {
        "name": "spaces/TEST/messages/MSG1",
        "text": "edited text",
        "updateTime": "2025-01-15T10:01:00Z",
        "sender": {"name": "users/USER1"},
        "space": {"name": "spaces/TEST"},
    }
    storage.update_message(edited)

    # Verify current version
    cursor = storage.conn.execute(
        """
        SELECT text, revision_number FROM messages WHERE id = ?
        """,
        ("spaces/TEST/messages/MSG1",),
    )
    row = cursor.fetchone()
    assert row["text"] == "edited text"
    assert row["revision_number"] == 1

    # Verify revision exists
    cursor = storage.conn.execute(
        """
        SELECT text, revision_number FROM message_revisions 
        WHERE message_id = ?
        """,
        ("spaces/TEST/messages/MSG1",),
    )
    row = cursor.fetchone()
    assert row["text"] == "original text"
    assert row["revision_number"] == 0


def test_update_message_inserts_if_not_exists(storage: SyncStorage) -> None:
    """Test that update_message inserts the message if it doesn't exist."""
    storage.upsert_space({"name": "spaces/TEST", "displayName": "Test Space", "type": "SPACE"})
    storage.upsert_user({"name": "users/USER1", "displayName": "Alice", "type": "HUMAN"})

    message = {
        "name": "spaces/TEST/messages/MSG1",
        "text": "new message",
        "updateTime": "2025-01-15T10:00:00Z",
        "sender": {"name": "users/USER1"},
        "space": {"name": "spaces/TEST"},
    }

    # Should insert since message doesn't exist
    storage.update_message(message)

    cursor = storage.conn.execute(
        """
        SELECT text, revision_number FROM messages WHERE id = ?
        """,
        ("spaces/TEST/messages/MSG1",),
    )
    row = cursor.fetchone()
    assert row["text"] == "new message"
    assert row["revision_number"] == 0

    # Should not create a revision
    cursor = storage.conn.execute(
        """
        SELECT COUNT(*) FROM message_revisions WHERE message_id = ?
        """,
        ("spaces/TEST/messages/MSG1",),
    )
    assert cursor.fetchone()[0] == 0


def test_update_message_skips_if_text_unchanged(storage: SyncStorage) -> None:
    """Test that update_message skips if text hasn't changed."""
    storage.upsert_space({"name": "spaces/TEST", "displayName": "Test Space", "type": "SPACE"})
    storage.upsert_user({"name": "users/USER1", "displayName": "Alice", "type": "HUMAN"})

    original = {
        "name": "spaces/TEST/messages/MSG1",
        "text": "same text",
        "updateTime": "2025-01-15T10:00:00Z",
        "sender": {"name": "users/USER1"},
        "space": {"name": "spaces/TEST"},
    }
    storage.insert_message(original)

    # Update with same text
    storage.update_message(original)

    # Should not create a revision
    cursor = storage.conn.execute(
        """
        SELECT COUNT(*) FROM message_revisions WHERE message_id = ?
        """,
        ("spaces/TEST/messages/MSG1",),
    )
    assert cursor.fetchone()[0] == 0

    # Revision number should still be 0
    cursor = storage.conn.execute(
        """
        SELECT revision_number FROM messages WHERE id = ?
        """,
        ("spaces/TEST/messages/MSG1",),
    )
    assert cursor.fetchone()["revision_number"] == 0
