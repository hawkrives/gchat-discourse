from datetime import datetime
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager
from gchat_mirror.exporters.discourse.retry_worker import RetryWorker


@pytest.fixture
def setup_test_dbs(tmp_path: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Set up test databases for state and chat."""
    # State DB with failed_exports table
    state_db_path = tmp_path / "state.db"
    state_conn = sqlite3.connect(state_db_path)
    state_conn.execute("""
        CREATE TABLE IF NOT EXISTS failed_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            
            error_message TEXT,
            error_count INTEGER DEFAULT 1,
            
            blocked_by TEXT,
            
            first_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            next_retry TIMESTAMP,
            
            UNIQUE(entity_type, entity_id, operation)
        )
    """)
    state_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_failed_retry
        ON failed_exports(next_retry)
    """)
    state_conn.commit()
    
    # Chat DB
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.Connection(chat_db_path)
    chat_conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            thread_id TEXT,
            sender_id TEXT,
            text TEXT
        )
    """)
    chat_conn.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            emoji_content TEXT NOT NULL,
            user_id TEXT NOT NULL
        )
    """)
    chat_conn.commit()
    
    return state_conn, chat_conn


def test_retry_worker_processes_retries(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that retry worker processes ready retries."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = FailedExportManager(state_conn, chat_conn)
    
    # Add a ready retry
    state_conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))
    state_conn.commit()
    
    # Mock exporter that succeeds
    mock_exporter = Mock(return_value={'success': True})
    
    worker = RetryWorker(
        state_conn,
        chat_conn,
        manager,
        {'thread': mock_exporter}
    )
    
    stats = worker.process_retries()
    
    assert stats['success'] == 1
    assert stats['failed'] == 0
    
    # Verify removed from failed exports
    cursor = state_conn.execute("""
        SELECT COUNT(*) FROM failed_exports
        WHERE entity_id = 'thread1'
    """)
    assert cursor.fetchone()[0] == 0


def test_retry_worker_handles_failure(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that retry worker handles failed retries."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = FailedExportManager(state_conn, chat_conn)
    
    # Add a ready retry
    state_conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))
    state_conn.commit()
    
    # Mock exporter that fails
    mock_exporter = Mock(side_effect=Exception("Still broken"))
    
    worker = RetryWorker(
        state_conn,
        chat_conn,
        manager,
        {'thread': mock_exporter}
    )
    
    stats = worker.process_retries()
    
    assert stats['success'] == 0
    assert stats['failed'] == 1
    
    # Verify error count incremented
    cursor = state_conn.execute("""
        SELECT error_count FROM failed_exports
        WHERE entity_id = 'thread1'
    """)
    assert cursor.fetchone()[0] == 2
