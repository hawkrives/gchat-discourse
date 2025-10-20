# ABOUTME: Tests for attachment database migrations (002 and 003)
# ABOUTME: Verifies attachments.db and chat.db attachment schema creation

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest  # type: ignore

from gchat_mirror.common.migrations import apply_migration


@pytest.fixture
def empty_attachments_db(tmp_path: Path) -> sqlite3.Connection:
    """Create an empty attachments.db connection."""
    db_path = tmp_path / "attachments.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def chat_db_with_messages(tmp_path: Path) -> sqlite3.Connection:
    """Create a chat.db with messages table for testing attachments FK."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create messages table (dependency for attachments)
    conn.execute(
        """
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            text TEXT
        )
        """
    )
    conn.commit()
    return conn


def test_attachments_db_migration_creates_tables(empty_attachments_db: sqlite3.Connection) -> None:
    """Test that migration 002 creates all required tables."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "002_initial_attachments.py"
    apply_migration(empty_attachments_db, migration_path)

    # Verify tables exist
    cursor = empty_attachments_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}

    assert "attachment_inline" in tables
    assert "attachment_chunks" in tables
    assert "storage_metadata" in tables
    assert "storage_stats" in tables


def test_attachment_inline_table_stores_data(empty_attachments_db: sqlite3.Connection) -> None:
    """Test that attachment_inline table can store binary data."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "002_initial_attachments.py"
    apply_migration(empty_attachments_db, migration_path)

    # Insert test data
    test_data = b"This is test binary data"
    empty_attachments_db.execute(
        """
        INSERT INTO attachment_inline (attachment_id, data)
        VALUES (?, ?)
        """,
        ("att1", test_data),
    )
    empty_attachments_db.commit()

    # Verify
    cursor = empty_attachments_db.execute(
        "SELECT attachment_id, data FROM attachment_inline WHERE attachment_id = ?",
        ("att1",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "att1"
    assert row[1] == test_data


def test_attachment_chunks_table_stores_chunks(empty_attachments_db: sqlite3.Connection) -> None:
    """Test that attachment_chunks table can store file chunks."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "002_initial_attachments.py"
    apply_migration(empty_attachments_db, migration_path)

    # Insert test chunks
    chunk1_data = b"chunk1" * 100
    chunk2_data = b"chunk2" * 100

    empty_attachments_db.execute(
        """
        INSERT INTO attachment_chunks
        (attachment_id, chunk_index, data, size_bytes, sha256_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("att2", 0, chunk1_data, len(chunk1_data), "hash1"),
    )

    empty_attachments_db.execute(
        """
        INSERT INTO attachment_chunks
        (attachment_id, chunk_index, data, size_bytes, sha256_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("att2", 1, chunk2_data, len(chunk2_data), "hash2"),
    )
    empty_attachments_db.commit()

    # Verify chunks are ordered correctly
    cursor = empty_attachments_db.execute(
        """
        SELECT chunk_index, size_bytes, sha256_hash
        FROM attachment_chunks
        WHERE attachment_id = ?
        ORDER BY chunk_index
        """,
        ("att2",),
    )
    chunks = cursor.fetchall()
    assert len(chunks) == 2
    assert chunks[0][0] == 0  # chunk_index
    assert chunks[0][1] == len(chunk1_data)  # size_bytes
    assert chunks[0][2] == "hash1"  # sha256_hash
    assert chunks[1][0] == 1
    assert chunks[1][1] == len(chunk2_data)
    assert chunks[1][2] == "hash2"


def test_attachment_chunks_unique_constraint(empty_attachments_db: sqlite3.Connection) -> None:
    """Test that duplicate attachment_id/chunk_index combinations are rejected."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "002_initial_attachments.py"
    apply_migration(empty_attachments_db, migration_path)

    # Insert first chunk
    empty_attachments_db.execute(
        """
        INSERT INTO attachment_chunks
        (attachment_id, chunk_index, data, size_bytes)
        VALUES (?, ?, ?, ?)
        """,
        ("att3", 0, b"data", 4),
    )
    empty_attachments_db.commit()

    # Try to insert duplicate
    with pytest.raises(sqlite3.IntegrityError):
        empty_attachments_db.execute(
            """
            INSERT INTO attachment_chunks
            (attachment_id, chunk_index, data, size_bytes)
            VALUES (?, ?, ?, ?)
            """,
            ("att3", 0, b"other_data", 10),
        )


def test_attachments_metadata_table_creation(chat_db_with_messages: sqlite3.Connection) -> None:
    """Test that migration 003 creates attachments metadata table."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "003_add_attachments.py"
    apply_migration(chat_db_with_messages, migration_path)

    # Verify table exists
    cursor = chat_db_with_messages.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='attachments'"
    )
    assert cursor.fetchone() is not None


def test_attachments_metadata_stores_data(chat_db_with_messages: sqlite3.Connection) -> None:
    """Test that attachments metadata table can store attachment info."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "003_add_attachments.py"
    apply_migration(chat_db_with_messages, migration_path)

    # Insert a message first
    chat_db_with_messages.execute(
        """
        INSERT INTO messages (id, text) VALUES ('msg1', 'test message')
        """
    )

    # Insert attachment metadata
    chat_db_with_messages.execute(
        """
        INSERT INTO attachments (id, message_id, name, size_bytes, content_type)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("att1", "msg1", "test.pdf", 1024, "application/pdf"),
    )
    chat_db_with_messages.commit()

    # Verify
    cursor = chat_db_with_messages.execute(
        "SELECT name, size_bytes, content_type FROM attachments WHERE id = ?",
        ("att1",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "test.pdf"
    assert row[1] == 1024
    assert row[2] == "application/pdf"


def test_attachments_foreign_key_constraint(chat_db_with_messages: sqlite3.Connection) -> None:
    """Test that foreign key constraint to messages table works."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "003_add_attachments.py"
    apply_migration(chat_db_with_messages, migration_path)

    # Enable foreign key constraints
    chat_db_with_messages.execute("PRAGMA foreign_keys = ON")

    # Try to insert attachment without parent message
    with pytest.raises(sqlite3.IntegrityError):
        chat_db_with_messages.execute(
            """
            INSERT INTO attachments (id, message_id, name)
            VALUES (?, ?, ?)
            """,
            ("att_orphan", "nonexistent_msg", "orphan.txt"),
        )


def test_attachments_cascade_delete(chat_db_with_messages: sqlite3.Connection) -> None:
    """Test that deleting a message cascades to delete attachments."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "003_add_attachments.py"
    apply_migration(chat_db_with_messages, migration_path)

    # Enable foreign key constraints
    chat_db_with_messages.execute("PRAGMA foreign_keys = ON")

    # Insert message and attachment
    chat_db_with_messages.execute(
        """
        INSERT INTO messages (id, text) VALUES ('msg2', 'message with attachment')
        """
    )
    chat_db_with_messages.execute(
        """
        INSERT INTO attachments (id, message_id, name)
        VALUES (?, ?, ?)
        """,
        ("att2", "msg2", "file.txt"),
    )
    chat_db_with_messages.commit()

    # Verify attachment exists
    cursor = chat_db_with_messages.execute(
        "SELECT COUNT(*) FROM attachments WHERE id = ?", ("att2",)
    )
    assert cursor.fetchone()[0] == 1

    # Delete message
    chat_db_with_messages.execute("DELETE FROM messages WHERE id = ?", ("msg2",))
    chat_db_with_messages.commit()

    # Verify attachment was cascade deleted
    cursor = chat_db_with_messages.execute(
        "SELECT COUNT(*) FROM attachments WHERE id = ?", ("att2",)
    )
    assert cursor.fetchone()[0] == 0


def test_attachments_indexes_created(chat_db_with_messages: sqlite3.Connection) -> None:
    """Test that all required indexes are created."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "003_add_attachments.py"
    apply_migration(chat_db_with_messages, migration_path)

    # Check indexes
    cursor = chat_db_with_messages.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='attachments' ORDER BY name"
    )
    indexes = {row[0] for row in cursor.fetchall()}

    # Should have at least the named indexes (SQLite also creates implicit indexes)
    assert "idx_attachments_message" in indexes
    assert "idx_attachments_downloaded" in indexes
    assert "idx_attachments_hash" in indexes
    assert "idx_attachments_download_pending" in indexes


def test_attachments_download_tracking(chat_db_with_messages: sqlite3.Connection) -> None:
    """Test that download tracking fields work correctly."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "003_add_attachments.py"
    apply_migration(chat_db_with_messages, migration_path)

    # Insert message
    chat_db_with_messages.execute(
        """
        INSERT INTO messages (id, text) VALUES ('msg3', 'test')
        """
    )

    # Insert attachment with download tracking
    chat_db_with_messages.execute(
        """
        INSERT INTO attachments
        (id, message_id, name, downloaded, download_attempts, download_error)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("att3", "msg3", "file.pdf", False, 2, "Connection timeout"),
    )
    chat_db_with_messages.commit()

    # Verify tracking data
    cursor = chat_db_with_messages.execute(
        """
        SELECT downloaded, download_attempts, download_error
        FROM attachments WHERE id = ?
        """,
        ("att3",),
    )
    row = cursor.fetchone()
    assert row[0] == 0  # False in SQLite
    assert row[1] == 2
    assert row[2] == "Connection timeout"


def test_attachments_storage_type_fields(chat_db_with_messages: sqlite3.Connection) -> None:
    """Test that storage type fields work correctly."""
    migration_path = Path(__file__).parent.parent.parent / "migrations" / "003_add_attachments.py"
    apply_migration(chat_db_with_messages, migration_path)

    # Insert message
    chat_db_with_messages.execute(
        """
        INSERT INTO messages (id, text) VALUES ('msg4', 'test')
        """
    )

    # Insert attachment with storage info
    chat_db_with_messages.execute(
        """
        INSERT INTO attachments
        (id, message_id, name, storage_type, chunk_size, total_chunks)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("att4", "msg4", "large.zip", "chunked", 10485760, 5),
    )
    chat_db_with_messages.commit()

    # Verify storage info
    cursor = chat_db_with_messages.execute(
        """
        SELECT storage_type, chunk_size, total_chunks
        FROM attachments WHERE id = ?
        """,
        ("att4",),
    )
    row = cursor.fetchone()
    assert row[0] == "chunked"
    assert row[1] == 10485760  # 10MB
    assert row[2] == 5


def test_user_avatars_migration_creates_tables(tmp_path: Path) -> None:
    """Test that migration 004 creates user_avatars table."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create users table first (dependency)
    conn.execute(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            display_name TEXT
        )
        """
    )
    conn.commit()

    migration_path = Path(__file__).parent.parent.parent / "migrations" / "004_user_avatars.py"
    apply_migration(conn, migration_path)

    # Verify table exists
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='user_avatars'
        """
    )
    assert cursor.fetchone() is not None

    # Test inserting avatar
    conn.execute("INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')")
    conn.execute(
        """
        INSERT INTO user_avatars (user_id, avatar_url, is_current)
        VALUES ('user1', 'https://example.com/avatar.jpg', TRUE)
        """
    )
    conn.commit()

    # Verify foreign key works
    cursor = conn.execute(
        """
        SELECT avatar_url FROM user_avatars WHERE user_id = ?
        """,
        ("user1",),
    )
    assert cursor.fetchone()[0] == "https://example.com/avatar.jpg"

    # Verify current_avatar_id column was added to users
    cursor = conn.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "current_avatar_id" in columns

    conn.close()


def test_reactions_migration_creates_table(tmp_path: Path) -> None:
    """Test that migration 005 creates reactions table."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create prerequisite tables
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    conn.commit()

    migration_path = Path(__file__).parent.parent.parent / "migrations" / "005_reactions.py"
    apply_migration(conn, migration_path)

    # Insert test reaction
    conn.execute("INSERT INTO messages (id) VALUES ('msg1')")
    conn.execute("INSERT INTO users (id) VALUES ('user1')")
    conn.execute(
        """
        INSERT INTO reactions 
        (id, message_id, emoji_content, user_id, create_time)
        VALUES ('react1', 'msg1', '👍', 'user1', '2025-01-15T10:00:00Z')
        """
    )
    conn.commit()

    # Verify unique constraint (same user can't react with same emoji twice)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO reactions 
            (id, message_id, emoji_content, user_id, create_time)
            VALUES ('react2', 'msg1', '👍', 'user1', '2025-01-15T10:01:00Z')
            """
        )

    # Verify indexes exist
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='reactions'
        """
    )
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_reactions_message" in indexes
    assert "idx_reactions_user" in indexes
    assert "idx_reactions_emoji" in indexes

    conn.close()


def test_custom_emoji_migration_creates_table(tmp_path: Path) -> None:
    """Test that migration 006 creates custom_emoji table."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    migration_path = Path(__file__).parent.parent.parent / "migrations" / "006_custom_emoji.py"
    apply_migration(conn, migration_path)

    # Insert test emoji
    conn.execute(
        """
        INSERT INTO custom_emoji (id, name, source_url)
        VALUES ('emoji1', 'partyparrot', 'https://example.com/parrot.gif')
        """
    )
    conn.commit()

    cursor = conn.execute(
        """
        SELECT name FROM custom_emoji WHERE id = 'emoji1'
        """
    )
    assert cursor.fetchone()[0] == "partyparrot"

    # Verify indexes exist
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='custom_emoji'
        """
    )
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_custom_emoji_name" in indexes
    assert "idx_custom_emoji_download" in indexes

    conn.close()


def test_message_revisions_migration_creates_table(tmp_path: Path) -> None:
    """Test that migration 007 creates message_revisions table."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create messages table
    conn.execute(
        """
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            text TEXT,
            last_update_time TIMESTAMP
        )
        """
    )
    conn.commit()

    migration_path = Path(__file__).parent.parent.parent / "migrations" / "007_message_revisions.py"
    apply_migration(conn, migration_path)

    # Create message with revisions
    conn.execute(
        """
        INSERT INTO messages (id, text, last_update_time, revision_number)
        VALUES ('msg1', 'edited text', '2025-01-15T10:01:00Z', 1)
        """
    )

    conn.execute(
        """
        INSERT INTO message_revisions 
        (message_id, revision_number, text, last_update_time)
        VALUES ('msg1', 0, 'original text', '2025-01-15T10:00:00Z')
        """
    )
    conn.commit()

    # Verify
    cursor = conn.execute(
        """
        SELECT text FROM message_revisions WHERE message_id = 'msg1'
        """
    )
    assert cursor.fetchone()[0] == "original text"

    # Verify unique constraint on (message_id, revision_number)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO message_revisions 
            (message_id, revision_number, text, last_update_time)
            VALUES ('msg1', 0, 'duplicate', '2025-01-15T10:02:00Z')
            """
        )

    # Verify revision_number column was added to messages
    cursor = conn.execute("PRAGMA table_info(messages)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "revision_number" in columns

    conn.close()


def test_read_receipts_migration_creates_table(tmp_path: Path) -> None:
    """Test that migration 008 creates read_receipts table."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create prerequisites
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    conn.commit()

    migration_path = Path(__file__).parent.parent.parent / "migrations" / "008_read_receipts.py"
    apply_migration(conn, migration_path)

    # Insert test read receipt
    conn.execute("INSERT INTO messages (id) VALUES ('msg1')")
    conn.execute("INSERT INTO users (id) VALUES ('user1')")
    conn.execute(
        """
        INSERT INTO read_receipts (message_id, user_id, read_time)
        VALUES ('msg1', 'user1', '2025-01-15T10:00:00Z')
        """
    )
    conn.commit()

    # Verify unique constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO read_receipts (message_id, user_id, read_time)
            VALUES ('msg1', 'user1', '2025-01-15T10:01:00Z')
            """
        )

    # Verify indexes
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='read_receipts'
        """
    )
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_read_receipts_message" in indexes
    assert "idx_read_receipts_user" in indexes

    conn.close()


def test_notification_queue_migration_creates_table(tmp_path: Path) -> None:
    """Test that migration 009 creates notification_queue table."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    migration_path = Path(__file__).parent.parent.parent / "migrations" / "009_notification_queue.py"
    apply_migration(conn, migration_path)

    # Insert test notification
    conn.execute(
        """
        INSERT INTO notification_queue 
        (entity_type, entity_id, change_type, data)
        VALUES ('message', 'msg1', 'created', '{"text": "test"}')
        """
    )
    conn.commit()

    # Query pending
    cursor = conn.execute(
        """
        SELECT entity_type, entity_id, change_type
        FROM notification_queue
        WHERE processed_at IS NULL
        """
    )
    row = cursor.fetchone()
    assert row[0] == "message"
    assert row[1] == "msg1"
    assert row[2] == "created"

    # Verify indexes
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='notification_queue'
        """
    )
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_notification_queue_pending" in indexes
    assert "idx_notification_queue_entity" in indexes

    conn.close()


def test_client_registry_migration_creates_table(tmp_path: Path) -> None:
    """Test that migration 010 creates export_clients table."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    migration_path = Path(__file__).parent.parent.parent / "migrations" / "010_client_registry.py"
    apply_migration(conn, migration_path)

    # Register client
    conn.execute(
        """
        INSERT INTO export_clients (id, client_type)
        VALUES ('discourse-1', 'discourse')
        """
    )
    conn.commit()

    cursor = conn.execute(
        """
        SELECT client_type, status FROM export_clients WHERE id = 'discourse-1'
        """
    )
    row = cursor.fetchone()
    assert row[0] == "discourse"
    assert row[1] == "active"

    # Verify index
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master 
        WHERE type='index' AND tbl_name='export_clients'
        """
    )
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_export_clients_status" in indexes

    conn.close()
