# ABOUTME: Tests for Google Chat message export to Discourse
# ABOUTME: Verifies post creation, content conversion, and state tracking

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest  # type: ignore
from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.message_exporter import MessageExporter


@pytest.fixture
def setup_test_dbs(tmp_path: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Set up test databases."""
    # State DB
    state_db_path = tmp_path / "state.db"
    state_conn = sqlite3.Connection(state_db_path)
    state_conn.execute("""
        CREATE TABLE export_mappings (
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            discourse_type TEXT NOT NULL,
            discourse_id TEXT NOT NULL,
            PRIMARY KEY (source_type, source_id)
        )
    """)
    state_conn.commit()
    
    # Chat DB
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.Connection(chat_db_path)
    chat_conn.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            space_id TEXT,
            sender_id TEXT,
            text TEXT,
            create_time TEXT,
            deleted INTEGER DEFAULT 0
        )
    """)
    chat_conn.execute("""
        CREATE TABLE attachments (
            id TEXT PRIMARY KEY,
            message_id TEXT,
            name TEXT,
            mime_type TEXT
        )
    """)
    chat_conn.commit()
    
    return state_conn, chat_conn


def test_message_exporter_already_exported(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that already exported messages return cached mapping."""
    state_conn, chat_conn = setup_test_dbs
    
    # Insert existing mapping
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('message', 'msg1', 'post', '456')
    """)
    state_conn.commit()
    
    exporter = MessageExporter(
        Mock(),  # discourse_client
        state_conn,
        chat_conn,
        Mock(),  # markdown_converter
        Mock()   # thread_exporter
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    assert result['discourse_id'] == '456'


def test_message_exporter_deleted_message(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that deleted messages are skipped."""
    state_conn, chat_conn = setup_test_dbs
    
    # Insert deleted message
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time, deleted)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'deleted text', '2024-01-01 10:00:00', 1)
    """)
    chat_conn.commit()
    
    exporter = MessageExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        Mock()
    )
    
    result = exporter.export_message('msg1')
    
    assert result is None


def test_message_exporter_message_not_found(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling of non-existent message."""
    state_conn, chat_conn = setup_test_dbs
    
    exporter = MessageExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        Mock()
    )
    
    result = exporter.export_message('nonexistent')
    
    assert result is None


def test_message_exporter_thread_export_fails(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that message export fails when thread export fails."""
    state_conn, chat_conn = setup_test_dbs
    
    # Insert message
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Hello', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Mock thread exporter that fails
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = None
    
    exporter = MessageExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        thread_exporter
    )
    
    result = exporter.export_message('msg1')
    
    assert result is None


def test_message_exporter_creates_reply_post(
    setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test exporting message as a reply post in a topic."""
    state_conn, chat_conn = setup_test_dbs
    
    # Insert message
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Hello world!', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Mock Discourse API response
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 123, "id": 456}
    )
    
    # Set up mocks
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    
    markdown_converter = Mock()
    markdown_converter.convert_message.return_value = "Hello world!"
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        thread_exporter
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    assert result['discourse_id'] == 456
    
    # Verify mapping was stored
    cursor = state_conn.execute("""
        SELECT discourse_type, discourse_id FROM export_mappings
        WHERE source_type = 'message' AND source_id = 'msg1'
    """)
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 'post'
    assert row[1] == '456'


def test_message_exporter_uses_markdown_converter(
    setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test that message exporter uses markdown converter."""
    state_conn, chat_conn = setup_test_dbs
    
    # Insert message with formatting
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', '**Bold** text', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Mock Discourse API response
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 123, "id": 456}
    )
    
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    
    markdown_converter = Mock()
    markdown_converter.convert_message.return_value = "**Bold** text"
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        thread_exporter
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    
    # Verify markdown converter was called
    markdown_converter.convert_message.assert_called_once()
    call_args = markdown_converter.convert_message.call_args
    assert call_args[0][0] == '**Bold** text'
    assert call_args[0][1] == 'msg1'


def test_message_exporter_handles_attachments(
    setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test that message exporter passes attachments to markdown converter."""
    state_conn, chat_conn = setup_test_dbs
    
    # Insert message with attachment
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Check this out', '2024-01-01 10:00:00')
    """)
    chat_conn.execute("""
        INSERT INTO attachments (id, message_id, name, mime_type)
        VALUES ('att1', 'msg1', 'photo.jpg', 'image/jpeg')
    """)
    chat_conn.commit()
    
    # Mock Discourse API response
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 123, "id": 456}
    )
    
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    
    markdown_converter = Mock()
    markdown_converter.convert_message.return_value = "Check this out\n\n![photo.jpg](url)"
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        thread_exporter
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    
    # Verify attachments were passed to markdown converter
    call_args = markdown_converter.convert_message.call_args
    attachments = call_args[0][2]
    assert len(attachments) == 1
    assert attachments[0]['id'] == 'att1'
    assert attachments[0]['name'] == 'photo.jpg'


def test_message_exporter_handles_empty_text(
    setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test that message exporter handles messages with no text (attachment-only)."""
    state_conn, chat_conn = setup_test_dbs
    
    # Insert message with no text
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', NULL, '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Mock Discourse API response
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 123, "id": 456}
    )
    
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    
    markdown_converter = Mock()
    markdown_converter.convert_message.return_value = ""
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        thread_exporter
    )
    
    result = exporter.export_message('msg1')
    
    # Should still export (Discourse allows empty posts with attachments)
    assert result is not None
