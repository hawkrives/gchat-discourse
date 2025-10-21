import sqlite3
from unittest.mock import Mock


from gchat_mirror.exporters.discourse.reaction_exporter import ReactionExporter


def test_reaction_exporter_exports_reaction(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test exporting a reaction."""
    state_conn, chat_conn = discourse_dbs
    
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


def test_reaction_exporter_skips_already_exported(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that already exported reactions are skipped."""
    state_conn, chat_conn = discourse_dbs
    
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


def test_reaction_exporter_handles_blocked_reaction(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling of blocked reactions."""
    state_conn, chat_conn = discourse_dbs
    
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


def test_reaction_exporter_handles_message_not_exported(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test handling when message is not yet exported."""
    state_conn, chat_conn = discourse_dbs
    
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
