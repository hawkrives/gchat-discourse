# ABOUTME: Tests for Google Chat thread export to Discourse
# ABOUTME: Verifies topic/PM creation, mappings, and title generation

from __future__ import annotations

import sqlite3
from unittest.mock import Mock

from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.thread_exporter import ThreadExporter


def test_thread_exporter_already_exported(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that already exported threads return cached mapping."""
    state_conn, chat_conn = discourse_dbs
    
    # Insert existing mapping
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('thread', 'thread1', 'topic', '123')
    """)
    state_conn.commit()
    
    exporter = ThreadExporter(
        Mock(),  # discourse_client
        state_conn,
        chat_conn,
        Mock(),  # user_mapper
        Mock()   # space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    assert result is not None
    assert result['discourse_type'] == 'topic'
    assert result['discourse_id'] == '123'


def test_thread_exporter_creates_topic(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test exporting thread as category topic."""
    state_conn, chat_conn = discourse_dbs
    
    # Set up test data
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'Engineering', 'SPACE')
    """)
    chat_conn.execute("""
        INSERT INTO threads (id, space_id, reply_count)
        VALUES ('thread1', 'space1', 5)
    """)
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'Hello everyone!', '2024-01-01 10:00:00')
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
    
    user_mapper = Mock()
    
    space_mapper = Mock()
    space_mapper.get_or_create_space_mapping.return_value = {
        'type': 'category',
        'id': 42
    }
    
    exporter = ThreadExporter(
        discourse_client,
        state_conn,
        chat_conn,
        user_mapper,
        space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    assert result is not None
    assert result['discourse_type'] == 'topic'
    assert result['discourse_id'] == 123
    
    # Verify mapping was stored
    cursor = state_conn.execute("""
        SELECT discourse_type, discourse_id FROM export_mappings
        WHERE source_type = 'thread' AND source_id = 'thread1'
    """)
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 'topic'
    assert row[1] == '123'


def test_thread_exporter_creates_private_message(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test exporting thread as private message."""
    state_conn, chat_conn = discourse_dbs
    
    # Set up test data
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'DM with Alice', 'DM')
    """)
    chat_conn.execute("""
        INSERT INTO threads (id, space_id, reply_count)
        VALUES ('thread1', 'space1', 3)
    """)
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'Hey there', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Mock Discourse API response
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 789, "id": 890}
    )
    
    # Set up mocks
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    
    user_mapper = Mock()
    user_mapper.get_or_create_discourse_user.return_value = "alice"
    
    space_mapper = Mock()
    space_mapper.get_or_create_space_mapping.return_value = {
        'type': 'private_message',
        'participants': ['user1', 'user2']
    }
    
    exporter = ThreadExporter(
        discourse_client,
        state_conn,
        chat_conn,
        user_mapper,
        space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    assert result is not None
    assert result['discourse_type'] == 'private_message'
    assert result['discourse_id'] == 789


def test_thread_exporter_chat_channel_handling(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that threads in chat channels are handled appropriately."""
    state_conn, chat_conn = discourse_dbs
    
    # Set up test data
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'General', 'SPACE')
    """)
    chat_conn.execute("""
        INSERT INTO threads (id, space_id, reply_count)
        VALUES ('thread1', 'space1', 2)
    """)
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', 'Quick question', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Set up mocks
    space_mapper = Mock()
    space_mapper.get_or_create_space_mapping.return_value = {
        'type': 'chat_channel',
        'id': 5
    }
    
    exporter = ThreadExporter(
        Mock(),  # discourse_client
        state_conn,
        chat_conn,
        Mock(),  # user_mapper
        space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    # Chat channels don't support threading, so we return a special marker
    assert result is not None
    assert result['discourse_type'] == 'chat_thread'
    assert result['discourse_id'] == 0


def test_thread_exporter_thread_not_found(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling of non-existent thread."""
    state_conn, chat_conn = discourse_dbs
    
    exporter = ThreadExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        Mock()
    )
    
    result = exporter.export_thread('nonexistent')
    
    assert result is None


def test_thread_exporter_space_mapping_failure(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling when space mapping fails."""
    state_conn, chat_conn = discourse_dbs
    
    # Set up test data
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'Engineering', 'SPACE')
    """)
    chat_conn.execute("""
        INSERT INTO threads (id, space_id, reply_count)
        VALUES ('thread1', 'space1', 5)
    """)
    chat_conn.commit()
    
    # Space mapper returns None
    space_mapper = Mock()
    space_mapper.get_or_create_space_mapping.return_value = None
    
    exporter = ThreadExporter(
        Mock(),
        state_conn,
        chat_conn,
        Mock(),
        space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    assert result is None


def test_thread_exporter_uses_title_generator(
    discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection],
    httpx_mock: HTTPXMock
) -> None:
    """Test that thread exporter uses title generator for topic titles."""
    state_conn, chat_conn = discourse_dbs
    
    # Set up test data with a message that should be cleaned
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type)
        VALUES ('space1', 'Engineering', 'SPACE')
    """)
    chat_conn.execute("""
        INSERT INTO threads (id, space_id, reply_count)
        VALUES ('thread1', 'space1', 5)
    """)
    chat_conn.execute("""
        INSERT INTO messages (id, thread_id, space_id, text, create_time)
        VALUES ('msg1', 'thread1', 'space1', '**Can anyone help?** https://example.com', '2024-01-01 10:00:00')
    """)
    chat_conn.commit()
    
    # Capture the title sent to Discourse
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"topic_id": 123, "id": 456}
    )
    
    discourse_client = DiscourseClient("https://discourse.example.com", "test-key")
    
    space_mapper = Mock()
    space_mapper.get_or_create_space_mapping.return_value = {
        'type': 'category',
        'id': 42
    }
    
    exporter = ThreadExporter(
        discourse_client,
        state_conn,
        chat_conn,
        Mock(),
        space_mapper
    )
    
    result = exporter.export_thread('thread1')
    
    assert result is not None
    
    # Verify the request was made with a cleaned title
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    # Title should have markdown and URL removed
    assert "**" not in str(requests[0].content)
    assert "https://example.com" not in str(requests[0].content)
