# ABOUTME: Tests for Discourse user mapping and auto-creation
# ABOUTME: Verifies username generation, caching, and uniqueness handling

from __future__ import annotations

import sqlite3
from unittest.mock import Mock

from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.exporters.discourse.user_mapper import UserMapper


def test_user_mapper_creates_new_user(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test creating a new Discourse user."""
    state_conn, chat_conn = discourse_dbs
    
    # Add Google Chat user
    chat_conn.execute("""
        INSERT INTO users (id, display_name, email)
        VALUES ('user1', 'Alice Smith', 'alice@example.com')
    """)
    chat_conn.commit()
    
    # Mock Discourse API - user doesn't exist
    httpx_mock.add_response(
        url="https://discourse.example.com/users/alice_smith.json",
        method="GET",
        status_code=404
    )
    # Mock user creation
    httpx_mock.add_response(
        url="https://discourse.example.com/users.json",
        method="POST",
        json={"user_id": 123, "username": "alice_smith"}
    )
    
    from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
    client = DiscourseClient("https://discourse.example.com", "test_key")
    mapper = UserMapper(client, state_conn, chat_conn)
    
    username = mapper.get_or_create_discourse_user('user1')
    
    assert username == 'alice_smith'
    
    # Verify mapping stored
    cursor = state_conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'user' AND source_id = 'user1'
    """)
    result = cursor.fetchone()
    assert result is not None
    assert result[0] == 'alice_smith'


def test_user_mapper_handles_existing_user(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that existing mappings are reused."""
    state_conn, chat_conn = discourse_dbs
    
    # Pre-populate mapping
    state_conn.execute("""
        INSERT INTO export_mappings 
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('user', 'user1', 'user', 'existing_user')
    """)
    state_conn.commit()
    
    client = Mock()
    mapper = UserMapper(client, state_conn, chat_conn)
    
    username = mapper.get_or_create_discourse_user('user1')
    
    assert username == 'existing_user'
    # Should not call Discourse API
    assert not client.create_user.called
    assert not client.get_user_by_username.called


def test_username_generation(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test username generation rules."""
    state_conn, chat_conn = discourse_dbs
    
    client = Mock()
    mapper = UserMapper(client, state_conn, chat_conn)
    
    # Normal case
    assert mapper._generate_username("Alice Smith", "alice@example.com") == "alice_smith"
    
    # Special characters
    assert mapper._generate_username("Bob O'Neill", "bob@example.com") == "bob_oneill"
    
    # Non-ASCII
    username = mapper._generate_username("José García", "jose@example.com")
    assert username == "jos_garca"
    
    # Multiple spaces
    assert mapper._generate_username("Alice  Bob   Smith", "alice@example.com") == "alice_bob_smith"
    
    # Consecutive underscores should be removed
    username = mapper._generate_username("Alice___Smith", "alice@example.com")
    assert username == "alice_smith"


def test_username_generation_short_names(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test username generation for very short names."""
    state_conn, chat_conn = discourse_dbs
    
    client = Mock()
    mapper = UserMapper(client, state_conn, chat_conn)
    
    # Too short - should use email fallback
    username = mapper._generate_username("A", "alice@example.com")
    assert len(username) >= 3
    assert "alice" in username
    
    # Two characters - should use email fallback
    username = mapper._generate_username("AB", "ab@example.com")
    assert len(username) >= 3


def test_username_uniqueness(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that duplicate usernames get unique suffixes."""
    state_conn, chat_conn = discourse_dbs
    
    # Add existing mapping
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('user', 'user1', 'user', 'alice_smith')
    """)
    state_conn.commit()
    
    client = Mock()
    mapper = UserMapper(client, state_conn, chat_conn)
    
    # Should generate alice_smith_1 since alice_smith exists
    username = mapper._generate_username("Alice Smith", "alice@example.com")
    assert username == "alice_smith_1"
    
    # Add another mapping
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('user', 'user2', 'user', 'alice_smith_1')
    """)
    state_conn.commit()
    
    # Should generate alice_smith_2
    username = mapper._generate_username("Alice Smith", "alice@example.com")
    assert username == "alice_smith_2"


def test_username_truncation(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that long usernames are truncated."""
    state_conn, chat_conn = discourse_dbs
    
    client = Mock()
    mapper = UserMapper(client, state_conn, chat_conn)
    
    # Very long name
    long_name = "A" * 50 + " " + "B" * 50
    username = mapper._generate_username(long_name, "test@example.com")
    
    assert len(username) <= 20


def test_user_mapper_handles_missing_user(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling when Google Chat user doesn't exist."""
    state_conn, chat_conn = discourse_dbs
    
    client = Mock()
    mapper = UserMapper(client, state_conn, chat_conn)
    
    username = mapper.get_or_create_discourse_user('nonexistent_user')
    
    assert username is None


def test_user_mapper_handles_creation_failure(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock) -> None:
    """Test handling when user creation fails."""
    state_conn, chat_conn = discourse_dbs
    
    # Add Google Chat user
    chat_conn.execute("""
        INSERT INTO users (id, display_name, email)
        VALUES ('user1', 'Alice Smith', 'alice@example.com')
    """)
    chat_conn.commit()
    
    # Mock Discourse API - user doesn't exist
    httpx_mock.add_response(
        url="https://discourse.example.com/users/alice_smith.json",
        method="GET",
        status_code=404
    )
    # Mock user creation failure
    httpx_mock.add_response(
        url="https://discourse.example.com/users.json",
        method="POST",
        status_code=422,  # Validation error
        json={"errors": ["Username already taken"]}
    )
    
    from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
    client = DiscourseClient("https://discourse.example.com", "test_key")
    mapper = UserMapper(client, state_conn, chat_conn)
    
    username = mapper.get_or_create_discourse_user('user1')
    
    assert username is None
