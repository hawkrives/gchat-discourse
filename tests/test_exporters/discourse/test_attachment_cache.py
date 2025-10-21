from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest
from pytest_httpx import HTTPXMock

from gchat_mirror.exporters.discourse.attachment_cache import AttachmentCache
from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient


@pytest.fixture
def setup_test_dbs(tmp_path: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Set up test databases for state and chat."""
    # State DB with export_mappings table
    state_db_path = tmp_path / "state.db"
    state_conn = sqlite3.connect(state_db_path)
    state_conn.execute("""
        CREATE TABLE export_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            discourse_type TEXT NOT NULL,
            discourse_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_type, source_id)
        )
    """)
    state_conn.commit()
    
    # Chat DB with attachments table
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.connect(chat_db_path)
    chat_conn.execute("""
        CREATE TABLE attachments (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            name TEXT,
            content_type TEXT,
            size_bytes INTEGER,
            storage_type TEXT,
            downloaded BOOLEAN,
            sha256_hash TEXT
        )
    """)
    chat_conn.commit()
    
    return state_conn, chat_conn


def test_attachment_cache_uploads_new_attachment(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test uploading a new attachment."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add attachment metadata to chat DB
    chat_conn.execute("""
        INSERT INTO attachments (id, message_id, name, content_type, size_bytes, storage_type, downloaded)
        VALUES ('attach1', 'msg1', 'test.pdf', 'application/pdf', 11, 'inline', TRUE)
    """)
    chat_conn.commit()
    
    # Mock attachment storage
    storage = Mock()
    storage.retrieve_attachment.return_value = b'PDF content'
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/uploads.json?type=composer",
        method="POST",
        json={'url': 'https://discourse.example.com/uploads/test.pdf'}
    )
    
    client = DiscourseClient("https://discourse.example.com", "test_key")
    cache = AttachmentCache(client, state_conn, chat_conn, storage)
    
    url = cache.get_or_upload_attachment('attach1')
    
    assert url == 'https://discourse.example.com/uploads/test.pdf'
    
    # Verify cached in database
    cursor = state_conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'attachment' AND source_id = 'attach1'
    """)
    assert cursor.fetchone()[0] == url


def test_attachment_cache_returns_cached_url(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that cached URLs are returned without upload."""
    state_conn, chat_conn = setup_test_dbs
    
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
    
    url = cache.get_or_upload_attachment('attach1')
    
    assert url == 'https://example.com/cached.pdf'
    # Should not call upload
    assert not client.upload_file.called


def test_attachment_cache_preload(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test preloading attachment cache."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add multiple cached attachments
    state_conn.executemany("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('attachment', ?, 'attachment', ?)
    """, [
        ('attach1', 'https://example.com/1.pdf'),
        ('attach2', 'https://example.com/2.pdf'),
        ('attach3', 'https://example.com/3.pdf'),
    ])
    state_conn.commit()
    
    cache = AttachmentCache(Mock(), state_conn, chat_conn, Mock())
    
    cache.preload_cache(['attach1', 'attach2', 'attach3'])
    
    # All should be in memory cache
    assert cache._memory_cache['attach1'] == 'https://example.com/1.pdf'
    assert cache._memory_cache['attach2'] == 'https://example.com/2.pdf'
    assert cache._memory_cache['attach3'] == 'https://example.com/3.pdf'
