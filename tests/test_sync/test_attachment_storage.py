# ABOUTME: Tests for attachment storage operations
# ABOUTME: Verifies inline and chunked storage strategies work correctly

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest  # type: ignore

from gchat_mirror.common.migrations import apply_migration
from gchat_mirror.sync.attachment_storage import AttachmentStorage


@pytest.fixture
def test_databases(tmp_path: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Create test chat.db and attachments.db with proper schemas."""
    # Setup chat.db
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.connect(chat_db_path)
    chat_conn.row_factory = sqlite3.Row

    # Apply chat migrations
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    apply_migration(chat_conn, migrations_dir / "001_initial_chat.py")
    apply_migration(chat_conn, migrations_dir / "003_add_attachments.py")

    # Add a test message (required for FK)
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, text)
        VALUES ('msg1', 'space1', 'test message')
    """
    )
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, text)
        VALUES ('msg2', 'space1', 'test message 2')
    """
    )
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, text)
        VALUES ('msg3', 'space1', 'test message 3')
    """
    )
    chat_conn.commit()

    # Setup attachments.db
    att_db_path = tmp_path / "attachments.db"
    att_conn = sqlite3.connect(att_db_path)
    att_conn.row_factory = sqlite3.Row

    # Apply attachments migration
    apply_migration(att_conn, migrations_dir / "002_initial_attachments.py")

    return chat_conn, att_conn


def test_store_and_retrieve_small_attachment(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test inline storage for small files."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Create small test file (< 1MB)
    test_data = b"Hello world! " * 100
    metadata = {
        "name": "small.txt",
        "content_type": "text/plain",
        "source_url": "https://example.com/file",
    }

    # Store
    storage.store_attachment("att1", "msg1", metadata, test_data)

    # Retrieve
    retrieved = storage.retrieve_attachment("att1")

    assert retrieved == test_data

    # Verify metadata
    cursor = chat_conn.execute(
        """
        SELECT storage_type, size_bytes, downloaded
        FROM attachments WHERE id = ?
    """,
        ("att1",),
    )
    row = cursor.fetchone()
    assert row["storage_type"] == "inline"
    assert row["size_bytes"] == len(test_data)
    assert row["downloaded"] == 1


def test_store_and_retrieve_large_attachment(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test chunked storage for large files."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Create large test file (15MB)
    test_data = b"X" * (15 * 1024 * 1024)
    metadata = {
        "name": "large.bin",
        "content_type": "application/octet-stream",
        "source_url": "https://example.com/largefile",
    }

    # Store
    storage.store_attachment("att2", "msg2", metadata, test_data)

    # Retrieve
    retrieved = storage.retrieve_attachment("att2")

    assert retrieved == test_data

    # Verify it was chunked
    cursor = chat_conn.execute(
        """
        SELECT storage_type, total_chunks
        FROM attachments WHERE id = ?
    """,
        ("att2",),
    )
    row = cursor.fetchone()
    assert row["storage_type"] == "chunked"
    assert row["total_chunks"] == 2  # 15MB / 10MB = 2 chunks


def test_attachment_integrity_check(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that corrupted data is detected."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Store attachment
    test_data = b"test data"
    metadata = {"name": "test.txt"}
    storage.store_attachment("att3", "msg3", metadata, test_data)

    # Corrupt the data
    att_conn.execute(
        """
        UPDATE attachment_inline
        SET data = ?
        WHERE attachment_id = ?
    """,
        (b"corrupted", "att3"),
    )
    att_conn.commit()

    # Try to retrieve - should fail hash check
    with pytest.raises(ValueError, match="Hash mismatch"):
        storage.retrieve_attachment("att3")


def test_retrieve_nonexistent_attachment(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that retrieving non-existent attachment raises error."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    with pytest.raises(ValueError, match="not found"):
        storage.retrieve_attachment("nonexistent")


def test_retrieve_not_downloaded_attachment(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that retrieving not-yet-downloaded attachment raises error."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Insert attachment metadata without actually storing data
    chat_conn.execute(
        """
        INSERT INTO attachments (id, message_id, name, downloaded)
        VALUES (?, ?, ?, ?)
    """,
        ("att_pending", "msg1", "pending.txt", False),
    )
    chat_conn.commit()

    with pytest.raises(ValueError, match="not yet downloaded"):
        storage.retrieve_attachment("att_pending")


def test_chunked_attachment_multiple_chunks(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that large files are properly split into multiple chunks."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Create 25MB file (should be 3 chunks: 10MB + 10MB + 5MB)
    test_data = b"Y" * (25 * 1024 * 1024)
    metadata = {"name": "huge.dat", "content_type": "application/octet-stream"}

    storage.store_attachment("att_huge", "msg1", metadata, test_data)

    # Verify chunk count
    cursor = att_conn.execute(
        """
        SELECT COUNT(*) FROM attachment_chunks WHERE attachment_id = ?
    """,
        ("att_huge",),
    )
    assert cursor.fetchone()[0] == 3

    # Verify chunks are in correct order and have correct sizes
    cursor = att_conn.execute(
        """
        SELECT chunk_index, size_bytes
        FROM attachment_chunks
        WHERE attachment_id = ?
        ORDER BY chunk_index
    """,
        ("att_huge",),
    )
    chunks = cursor.fetchall()
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["size_bytes"] == 10 * 1024 * 1024
    assert chunks[1]["chunk_index"] == 1
    assert chunks[1]["size_bytes"] == 10 * 1024 * 1024
    assert chunks[2]["chunk_index"] == 2
    assert chunks[2]["size_bytes"] == 5 * 1024 * 1024

    # Retrieve and verify data is intact
    retrieved = storage.retrieve_attachment("att_huge")
    assert retrieved == test_data


def test_inline_threshold_boundary(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test storage type selection at the 1MB threshold."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Just under 1MB - should be inline
    data_inline = b"Z" * (1024 * 1024 - 1)
    storage.store_attachment("att_inline", "msg1", {"name": "inline.bin"}, data_inline)

    cursor = chat_conn.execute(
        "SELECT storage_type FROM attachments WHERE id = ?", ("att_inline",)
    )
    assert cursor.fetchone()["storage_type"] == "inline"

    # Exactly 1MB - should be chunked
    data_chunked = b"A" * (1024 * 1024)
    storage.store_attachment(
        "att_chunked", "msg2", {"name": "chunked.bin"}, data_chunked
    )

    cursor = chat_conn.execute(
        "SELECT storage_type FROM attachments WHERE id = ?", ("att_chunked",)
    )
    assert cursor.fetchone()["storage_type"] == "chunked"


def test_attachment_metadata_fields(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that all metadata fields are properly stored."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    metadata = {
        "name": "document.pdf",
        "content_type": "application/pdf",
        "source_url": "https://example.com/doc.pdf",
        "raw_data": '{"extra": "field"}',
    }

    test_data = b"PDF content"
    storage.store_attachment("att_meta", "msg1", metadata, test_data)

    # Verify all metadata fields
    cursor = chat_conn.execute(
        """
        SELECT name, content_type, source_url, raw_data, sha256_hash
        FROM attachments WHERE id = ?
    """,
        ("att_meta",),
    )
    row = cursor.fetchone()
    assert row["name"] == "document.pdf"
    assert row["content_type"] == "application/pdf"
    assert row["source_url"] == "https://example.com/doc.pdf"
    assert row["raw_data"] == '{"extra": "field"}'
    assert row["sha256_hash"] is not None
    assert len(row["sha256_hash"]) == 64  # SHA256 hex digest length


def test_empty_file_storage(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that empty files can be stored and retrieved."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    empty_data = b""
    storage.store_attachment("att_empty", "msg1", {"name": "empty.txt"}, empty_data)

    retrieved = storage.retrieve_attachment("att_empty")
    assert retrieved == empty_data

    # Verify it's stored inline (0 bytes < 1MB)
    cursor = chat_conn.execute(
        "SELECT storage_type, size_bytes FROM attachments WHERE id = ?",
        ("att_empty",),
    )
    row = cursor.fetchone()
    assert row["storage_type"] == "inline"
    assert row["size_bytes"] == 0
