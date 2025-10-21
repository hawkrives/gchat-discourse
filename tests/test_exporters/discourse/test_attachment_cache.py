import sqlite3
from unittest.mock import Mock

from pytest_httpx import HTTPXMock

from gchat_mirror.exporters.discourse.attachment_cache import AttachmentCache
from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient


def test_attachment_cache_uploads_new_attachment(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test uploading a new attachment."""
    state_conn, chat_conn = discourse_dbs

    # Add attachment metadata to chat DB
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
    """)
    chat_conn.execute("""
        INSERT INTO messages (id, space_id, text)
        VALUES ('msg1', 'space1', 'test message')
    """)
    chat_conn.execute("""
        INSERT INTO attachments (id, message_id, name, content_type, size_bytes, storage_type, downloaded)
        VALUES ('attach1', 'msg1', 'test.pdf', 'application/pdf', 11, 'inline', TRUE)
    """)
    chat_conn.commit()

    # Mock attachment storage
    storage = Mock()
    storage.retrieve_attachment.return_value = b"PDF content"

    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/uploads.json?type=composer",
        method="POST",
        json={"url": "https://discourse.example.com/uploads/test.pdf"},
    )

    client = DiscourseClient("https://discourse.example.com", "test_key")
    cache = AttachmentCache(client, state_conn, chat_conn, storage)

    url = cache.get_or_upload_attachment("attach1")

    assert url == "https://discourse.example.com/uploads/test.pdf"

    # Verify cached in database
    cursor = state_conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'attachment' AND source_id = 'attach1'
    """)
    assert cursor.fetchone()[0] == url


def test_attachment_cache_returns_cached_url(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    """Test that cached URLs are returned without upload."""
    state_conn, chat_conn = discourse_dbs

    # Pre-populate cache
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('attachment', 'attach1', 'attachment', 'https://example.com/cached.pdf')
    """)
    state_conn.commit()

    storage = Mock()
    client = Mock()
    cache = AttachmentCache(client, state_conn, chat_conn, storage)

    url = cache.get_or_upload_attachment("attach1")

    assert url == "https://example.com/cached.pdf"
    # Should not call upload
    assert not client.upload_file.called


def test_attachment_cache_preload(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
) -> None:
    """Test preloading attachment cache."""
    state_conn, chat_conn = discourse_dbs

    # Add multiple cached attachments
    state_conn.executemany(
        """
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('attachment', ?, 'attachment', ?)
    """,
        [
            ("attach1", "https://example.com/1.pdf"),
            ("attach2", "https://example.com/2.pdf"),
            ("attach3", "https://example.com/3.pdf"),
        ],
    )
    state_conn.commit()

    cache = AttachmentCache(Mock(), state_conn, chat_conn, Mock())

    cache.preload_cache(["attach1", "attach2", "attach3"])

    # All should be in memory cache
    assert cache._memory_cache["attach1"] == "https://example.com/1.pdf"
    assert cache._memory_cache["attach2"] == "https://example.com/2.pdf"
    assert cache._memory_cache["attach3"] == "https://example.com/3.pdf"
