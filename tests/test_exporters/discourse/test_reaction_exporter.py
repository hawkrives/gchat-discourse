from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest

from gchat_mirror.exporters.discourse.reaction_exporter import ReactionExporter


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
    
    # Chat DB with reactions table
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.connect(chat_db_path)
    chat_conn.execute("""
        CREATE TABLE reactions (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            emoji_content TEXT NOT NULL,
            create_time TIMESTAMP NOT NULL
        )
    """)
    chat_conn.commit()
    
    return state_conn, chat_conn


def test_reaction_exporter_exports_reaction(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test exporting a reaction."""
    state_conn, chat_conn = setup_test_dbs
    
    # Setup test data
    chat_conn.execute("""
        INSERT INTO reactions
        (id, message_id, user_id, emoji_content, create_time)
        VALUES ('react1', 'msg1', 'user1', '👍', '2025-01-01 12:00:00')
    """)
    chat_conn.commit()
    
    # Message already exported
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('message', 'msg1', 'post', '456')
    """)
    state_conn.commit()
    
    client = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = ReactionExporter(
        client,
        state_conn,
        chat_conn,
        failed_manager
    )
    
    result = exporter.export_reaction('react1')
    
    assert result
    
    # Verify mapping stored
    cursor = state_conn.execute("""
        SELECT discourse_id FROM export_mappings
        WHERE source_type = 'reaction' AND source_id = 'react1'
    """)
    assert cursor.fetchone()[0] == '456'


def test_reaction_exporter_skips_already_exported(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that already exported reactions are skipped."""
    state_conn, chat_conn = setup_test_dbs
    
    # Reaction already exported
    state_conn.execute("""
        INSERT INTO export_mappings
        (source_type, source_id, discourse_type, discourse_id)
        VALUES ('reaction', 'react1', 'reaction', '456')
    """)
    state_conn.commit()
    
    client = Mock()
    failed_manager = Mock()
    
    exporter = ReactionExporter(
        client,
        state_conn,
        chat_conn,
        failed_manager
    )
    
    result = exporter.export_reaction('react1')
    
    assert result
    # Should not call Discourse API
    assert not client.called


def test_reaction_exporter_handles_blocked_reaction(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling of blocked reactions."""
    state_conn, chat_conn = setup_test_dbs
    
    client = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = True
    
    exporter = ReactionExporter(
        client,
        state_conn,
        chat_conn,
        failed_manager
    )
    
    result = exporter.export_reaction('react1')
    
    assert result is None


def test_reaction_exporter_handles_message_not_exported(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling when message is not yet exported."""
    state_conn, chat_conn = setup_test_dbs
    
    # Setup reaction but no message export
    chat_conn.execute("""
        INSERT INTO reactions
        (id, message_id, user_id, emoji_content, create_time)
        VALUES ('react1', 'msg1', 'user1', '👍', '2025-01-01 12:00:00')
    """)
    chat_conn.commit()
    
    client = Mock()
    failed_manager = Mock()
    failed_manager.is_blocked.return_value = False
    
    exporter = ReactionExporter(
        client,
        state_conn,
        chat_conn,
        failed_manager
    )
    
    result = exporter.export_reaction('react1')
    
    assert result is None
    # Should record failure
    failed_manager.record_failure.assert_called_once()
