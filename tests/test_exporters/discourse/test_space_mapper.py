# ABOUTME: Tests for space mapping to Discourse structures
# ABOUTME: Verifies chat, private_messages, and hybrid mapping modes

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest  # type: ignore
from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.exporters.discourse.space_mapper import SpaceMapper


@pytest.fixture
def setup_test_dbs(tmp_path: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Set up test databases for state and chat."""
    # State DB
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
    
    # Chat DB
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.connect(chat_db_path)
    chat_conn.execute("""
        CREATE TABLE spaces (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            space_type TEXT,
            threaded INTEGER
        )
    """)
    chat_conn.execute("""
        CREATE TABLE memberships (
            space_id TEXT,
            user_id TEXT,
            PRIMARY KEY (space_id, user_id)
        )
    """)
    chat_conn.commit()
    
    return state_conn, chat_conn


def test_space_mapper_chat_mode(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test space mapping in chat mode."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add regular space
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type, threaded)
        VALUES ('space1', 'Engineering', 'SPACE', 1)
    """)
    chat_conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/chat/api/channels.json",
        method="POST",
        json={"channel": {"id": 42, "name": "Engineering"}}
    )
    
    from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
    client = DiscourseClient("https://discourse.example.com", "test_key")
    mapper = SpaceMapper(client, state_conn, chat_conn, "chat")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result is not None
    assert result['type'] == 'chat_channel'
    assert result['id'] == 42


def test_space_mapper_private_messages_mode_regular_space(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test regular space mapping in private_messages mode."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add regular space
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type, threaded)
        VALUES ('space1', 'Engineering', 'SPACE', 1)
    """)
    chat_conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/categories.json",
        method="POST",
        json={"category": {"id": 99, "name": "Engineering"}}
    )
    
    from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
    client = DiscourseClient("https://discourse.example.com", "test_key")
    mapper = SpaceMapper(client, state_conn, chat_conn, "private_messages")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result is not None
    assert result['type'] == 'category'
    assert result['id'] == 99


def test_space_mapper_private_messages_mode_dm(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test DM mapping in private_messages mode."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add DM space
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type, threaded)
        VALUES ('dm1', 'DM with Bob', 'DM', 0)
    """)
    chat_conn.execute("""
        INSERT INTO memberships (space_id, user_id)
        VALUES ('dm1', 'user1'), ('dm1', 'user2')
    """)
    chat_conn.commit()
    
    client = Mock()
    mapper = SpaceMapper(client, state_conn, chat_conn, "private_messages")
    
    result = mapper.get_or_create_space_mapping('dm1')
    
    assert result is not None
    assert result['type'] == 'private_message'
    assert result['id'] == 0  # No Discourse ID yet
    assert len(result['participants']) == 2
    assert 'user1' in result['participants']
    assert 'user2' in result['participants']


def test_space_mapper_hybrid_mode_dm(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test DM mapping in hybrid mode."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add DM space
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type, threaded)
        VALUES ('dm1', 'DM with Bob', 'DM', 0)
    """)
    chat_conn.execute("""
        INSERT INTO memberships (space_id, user_id)
        VALUES ('dm1', 'user1'), ('dm1', 'user2')
    """)
    chat_conn.commit()
    
    client = Mock()
    mapper = SpaceMapper(client, state_conn, chat_conn, "hybrid")
    
    result = mapper.get_or_create_space_mapping('dm1')
    
    assert result is not None
    assert result['type'] == 'private_message'
    assert len(result['participants']) == 2


def test_space_mapper_hybrid_mode_regular_space(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test regular space mapping in hybrid mode."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add regular space
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type, threaded)
        VALUES ('space1', 'Engineering', 'SPACE', 1)
    """)
    chat_conn.commit()
    
    # Mock Discourse API
    httpx_mock.add_response(
        url="https://discourse.example.com/chat/api/channels.json",
        method="POST",
        json={"channel": {"id": 42, "name": "Engineering"}}
    )
    
    from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
    client = DiscourseClient("https://discourse.example.com", "test_key")
    mapper = SpaceMapper(client, state_conn, chat_conn, "hybrid")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result is not None
    assert result['type'] == 'chat_channel'
    assert result['id'] == 42


def test_space_mapper_caches_mappings(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that mappings are cached and reused."""
    state_conn, chat_conn = setup_test_dbs
    
    # Pre-populate mapping
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('space', 'space1', 'chat_channel', '42')
    """)
    state_conn.commit()
    
    client = Mock()
    mapper = SpaceMapper(client, state_conn, chat_conn, "chat")
    
    result = mapper.get_or_create_space_mapping('space1')
    
    assert result is not None
    assert result['type'] == 'chat_channel'
    assert result['id'] == 42
    # Should not call Discourse API
    assert not client.create_chat_channel.called


def test_space_mapper_handles_missing_space(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling when space doesn't exist."""
    state_conn, chat_conn = setup_test_dbs
    
    client = Mock()
    mapper = SpaceMapper(client, state_conn, chat_conn, "chat")
    
    result = mapper.get_or_create_space_mapping('nonexistent')
    
    assert result is None


def test_space_mapper_stores_participant_list(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that DM participant list is stored in mapping."""
    state_conn, chat_conn = setup_test_dbs
    
    # Add DM space
    chat_conn.execute("""
        INSERT INTO spaces (id, display_name, space_type, threaded)
        VALUES ('dm1', 'DM', 'DM', 0)
    """)
    chat_conn.execute("""
        INSERT INTO memberships (space_id, user_id)
        VALUES ('dm1', 'user1'), ('dm1', 'user2'), ('dm1', 'user3')
    """)
    chat_conn.commit()
    
    client = Mock()
    mapper = SpaceMapper(client, state_conn, chat_conn, "hybrid")
    
    result = mapper.get_or_create_space_mapping('dm1')
    
    assert result is not None
    
    # Verify mapping stored in database
    cursor = state_conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'space' AND source_id = 'dm1'
    """)
    mapping_data = cursor.fetchone()
    assert mapping_data is not None
    # discourse_id should contain comma-separated participant list
    assert 'user1' in mapping_data[0]
    assert 'user2' in mapping_data[0]
    assert 'user3' in mapping_data[0]
