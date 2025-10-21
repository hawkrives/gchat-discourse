# ABOUTME: Tests for Google Chat message export to Discourse
# ABOUTME: Verifies post creation, content conversion, and state tracking

from __future__ import annotations

import sqlite3
from unittest.mock import Mock

from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.message_exporter import MessageExporter


def test_message_exporter_already_exported(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that already exported messages return cached mapping."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert existing mapping
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('message', 'msg1', 'post', '456')
    """)
    state_conn.commit()
    
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        Mock(),  # discourse_client
        state_conn,
        chat_conn,
        Mock(),  # markdown_converter
        Mock(),  # attachment_cache
        Mock(),  # thread_exporter
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    assert result['discourse_id'] == '456'


def test_message_exporter_deleted_message(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that deleted messages are skipped."""
    state_conn, chat_conn = discourse_dbs
    
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
        Mock(),
        Mock(),
        Mock()
    )
    
    result = exporter.export_message('msg1')
    
    assert result is None


def test_message_exporter_message_not_found(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling of non-existent message."""
    state_conn, chat_conn = discourse_dbs
    
    exporter = MessageExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        Mock(),
        Mock(),
        Mock()
    )
    
    result = exporter.export_message('nonexistent')
    
    assert result is None


def test_message_exporter_thread_export_fails(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that message export fails when thread export fails."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert message
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Hello', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Mock thread exporter that fails
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = None
    
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        Mock(),
        thread_exporter,
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is None


def test_message_exporter_creates_reply_post(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test exporting message as a reply post in a topic."""
    state_conn, chat_conn = discourse_dbs
    
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
    
    attachment_cache = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        attachment_cache,
        thread_exporter,
        failed_manager
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
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test that message exporter uses markdown converter."""
    state_conn, chat_conn = discourse_dbs
    
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
    
    attachment_cache = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        attachment_cache,
        thread_exporter,
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    
    # Verify markdown converter was called
    markdown_converter.convert_message.assert_called_once()
    call_args = markdown_converter.convert_message.call_args
    assert call_args[0][0] == '**Bold** text'
    assert call_args[0][1] == 'msg1'


def test_message_exporter_handles_attachments(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test that message exporter passes attachments to markdown converter."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert message with attachment
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Check this out', '2024-01-01 10:00:00')
    """)
    chat_conn.execute("""
        INSERT INTO attachments (id, message_id, name, content_type)
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
    
    attachment_cache = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        attachment_cache,
        thread_exporter,
        failed_manager
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
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test that message exporter handles messages with no text (attachment-only)."""
    state_conn, chat_conn = discourse_dbs
    
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
    
    attachment_cache = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        attachment_cache,
        thread_exporter,
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    # Should still export (Discourse allows empty posts with attachments)
    assert result is not None


def test_message_exporter_with_attachment_cache(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test message export with attachment cache integration."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert message and attachment
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Check attachment', '2024-01-01 10:00:00')
    """)
    chat_conn.execute("""
        INSERT INTO attachments (id, message_id, name, content_type)
        VALUES ('att1', 'msg1', 'file.pdf', 'application/pdf')
    """)
    chat_conn.commit()
    
    # Thread already exported
    state_conn.execute("""
        INSERT INTO export_mappings (source_type, source_id, discourse_type, discourse_id)
        VALUES ('thread', 'thread1', 'topic', '123')
    """)
    state_conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={'id': 456}
    )
    
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    markdown_converter = Mock()
    markdown_converter.convert_message.return_value = "Check attachment"
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    
    attachment_cache = Mock()
    attachment_cache.get_or_upload_attachment.return_value = 'https://example.com/file.pdf'
    
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        attachment_cache,
        thread_exporter,
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    assert result['discourse_id'] == 456
    
    # Verify attachment was processed
    attachment_cache.get_or_upload_attachment.assert_called_once_with('att1')


def test_message_exporter_handles_blocked_message(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that blocked messages are not exported."""
    state_conn, chat_conn = discourse_dbs
    
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = True
    
    exporter = MessageExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        Mock(),
        Mock(),
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is None


def test_message_exporter_records_failure_on_thread_export_fail(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that thread export failure is recorded."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert message
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Hello', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = None  # Thread export failed
    
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        Mock(),
        thread_exporter,
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is None
    # Verify failure was recorded
    failed_manager.record_failure.assert_called_once()
    call_args = failed_manager.record_failure.call_args
    assert call_args[0][0] == 'message'
    assert call_args[0][1] == 'msg1'
    assert call_args[1]['blocked_by'] == 'thread1'


def test_message_exporter_exports_edit_history(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test message export with edit history."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert message with edits
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time, update_time)
        VALUES ('msg1', 'thread1', 'space1', 'user1', 'Final text', '2024-01-01 10:00:00', '2024-01-01 10:30:00')
    """)
    chat_conn.execute("""
        INSERT INTO message_revisions (message_id, revision_id, text, update_time)
        VALUES 
            ('msg1', 'rev1', 'Original text', '2024-01-01 10:00:00'),
            ('msg1', 'rev2', 'Edited text', '2024-01-01 10:15:00')
    """)
    chat_conn.commit()
    
    # Thread already exported
    state_conn.execute("""
        INSERT INTO export_mappings (source_type, source_id, discourse_type, discourse_id)
        VALUES ('thread', 'thread1', 'topic', '123')
    """)
    state_conn.commit()
    
    # Mock Discourse API - initial post + 2 edits
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={'id': 456}
    )
    httpx_mock.add_response(
        url="https://discourse.example.com/posts/456.json",
        method="PUT",
        json={'post': {'id': 456}}
    )
    httpx_mock.add_response(
        url="https://discourse.example.com/posts/456.json",
        method="PUT",
        json={'post': {'id': 456}}
    )
    
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    markdown_converter = Mock()
    markdown_converter.convert_message.side_effect = ["Original text", "Edited text", "Final text"]
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    
    attachment_cache = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        attachment_cache,
        thread_exporter,
        failed_manager
    )
    
    result = exporter.export_message('msg1')
    
    assert result is not None
    assert result['discourse_id'] == 456
    
    # Verify markdown converter called 3 times (original + 2 edits)
    assert markdown_converter.convert_message.call_count == 3


def test_message_exporter_batch_export(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test batch message export with sequential processing."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert multiple messages
    for i in range(5):
        chat_conn.execute("""
            INSERT INTO messages (id, thread_id, space_id, sender_id, text, create_time)
            VALUES (?, 'thread1', 'space1', 'user1', ?, '2024-01-01 10:00:00')
        """, (f'msg{i}', f'Text {i}'))
    chat_conn.commit()
    
    # Thread already exported
    state_conn.execute("""
        INSERT INTO export_mappings (source_type, source_id, discourse_type, discourse_id)
        VALUES ('thread', 'thread1', 'topic', '123')
    """)
    state_conn.commit()
    
    # Mock Discourse API responses
    for i in range(5):
        httpx_mock.add_response(
            url="https://discourse.example.com/posts.json",
            method="POST",
            json={'id': 400 + i}
        )
    
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    markdown_converter = Mock()
    markdown_converter.convert_message.side_effect = [f'Text {i}' for i in range(5)]
    
    thread_exporter = Mock()
    thread_exporter.export_thread.return_value = {
        'discourse_type': 'topic',
        'discourse_id': 123
    }
    
    attachment_cache = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = MessageExporter(
        discourse_client,
        state_conn,
        chat_conn,
        markdown_converter,
        attachment_cache,
        thread_exporter,
        failed_manager
    )
    
    message_ids = [f'msg{i}' for i in range(5)]
    results = exporter.export_messages_batch(message_ids, max_workers=2)
    
    # All messages should be exported
    assert len(results) == 5
    successful = [r for r in results if r['success']]
    assert len(successful) == 5
    
    # Verify all Discourse IDs are present
    discourse_ids = {r['result']['discourse_id'] for r in successful}
    assert discourse_ids == {400, 401, 402, 403, 404}

