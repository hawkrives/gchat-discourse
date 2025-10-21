from datetime import datetime, timezone
import sqlite3
from pathlib import Path

import pytest

from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager
from gchat_mirror.exporters.discourse.retry_config import RetryConfig


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
    
    # Chat DB with messages and reactions tables
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.Connection(chat_db_path)
    chat_conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            thread_id TEXT,
            sender_id TEXT,
            text TEXT,
            create_time TIMESTAMP,
            update_time TIMESTAMP
        )
    """)
    chat_conn.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            emoji_content TEXT NOT NULL,
            user_id TEXT NOT NULL,
            create_time TIMESTAMP NOT NULL
        )
    """)
    chat_conn.commit()
    
    return state_conn, chat_conn


def test_failed_export_manager_records_failure(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test recording a failed export."""
    state_conn, chat_conn = setup_test_dbs
    manager = FailedExportManager(state_conn, chat_conn)
    
    should_retry = manager.record_failure(
        entity_type='thread',
        entity_id='thread1',
        operation='export',
        error_message='Connection timeout'
    )
    
    assert should_retry
    
    # Verify record in database
    cursor = state_conn.execute("""
        SELECT error_count, error_message FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    row = cursor.fetchone()
    assert row[0] == 1
    assert 'timeout' in row[1]


def test_failed_export_manager_increments_error_count(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that repeated failures increment error count."""
    state_conn, chat_conn = setup_test_dbs
    manager = FailedExportManager(state_conn, chat_conn)
    
    # First failure
    manager.record_failure('thread', 'thread1', 'export', 'Error 1')
    
    # Second failure
    manager.record_failure('thread', 'thread1', 'export', 'Error 2')
    
    # Third failure
    manager.record_failure('thread', 'thread1', 'export', 'Error 3')
    
    cursor = state_conn.execute("""
        SELECT error_count FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    assert cursor.fetchone()[0] == 3


def test_failed_export_manager_permanent_failure(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that permanent failures are not retried."""
    state_conn, chat_conn = setup_test_dbs
    manager = FailedExportManager(state_conn, chat_conn)
    
    should_retry = manager.record_failure(
        entity_type='thread',
        entity_id='thread1',
        operation='export',
        error_message='404 Not Found'
    )
    
    assert not should_retry
    
    # Should not be in failed exports table
    cursor = state_conn.execute("""
        SELECT COUNT(*) FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    assert cursor.fetchone()[0] == 0


def test_failed_export_manager_max_retries(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that max retries stops retry attempts."""
    state_conn, chat_conn = setup_test_dbs
    config = RetryConfig(max_attempts=3)
    manager = FailedExportManager(state_conn, chat_conn, config)
    
    # First 3 attempts should allow retry
    assert manager.record_failure('thread', 'thread1', 'export', 'Error')
    assert manager.record_failure('thread', 'thread1', 'export', 'Error')
    assert not manager.record_failure('thread', 'thread1', 'export', 'Error')


def test_failed_export_manager_get_ready_retries(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test getting exports ready for retry."""
    state_conn, chat_conn = setup_test_dbs
    manager = FailedExportManager(state_conn, chat_conn)
    
    # Add a failed export with past retry time
    state_conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))  # Past date
    
    state_conn.commit()
    
    retries = manager.get_ready_retries()
    
    assert len(retries) == 1
    assert retries[0]['entity_id'] == 'thread1'


def test_failed_export_manager_blocked_exports(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that blocked exports are not returned for retry."""
    state_conn, chat_conn = setup_test_dbs
    manager = FailedExportManager(state_conn, chat_conn)
    
    # Failed thread (blocker)
    state_conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 1, ?)
    """, (datetime(2020, 1, 1),))
    
    # Failed message blocked by thread
    state_conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, 
         next_retry, blocked_by)
        VALUES ('message', 'msg1', 'export', 'Error', 1, ?, 'thread1')
    """, (datetime(2020, 1, 1),))
    
    state_conn.commit()
    
    retries = manager.get_ready_retries()
    
    # Only thread should be ready, message is blocked
    assert len(retries) == 1
    assert retries[0]['entity_type'] == 'thread'


def test_failed_export_manager_mark_success(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test marking a failed export as successful."""
    state_conn, chat_conn = setup_test_dbs
    manager = FailedExportManager(state_conn, chat_conn)
    
    manager.record_failure('thread', 'thread1', 'export', 'Error')
    
    manager.mark_success('thread', 'thread1', 'export')
    
    # Should be removed from failed exports
    cursor = state_conn.execute("""
        SELECT COUNT(*) FROM failed_exports
        WHERE entity_type = 'thread' AND entity_id = 'thread1'
    """)
    
    assert cursor.fetchone()[0] == 0


def test_failed_export_manager_force_retry(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test forcing immediate retry."""
    state_conn, chat_conn = setup_test_dbs
    manager = FailedExportManager(state_conn, chat_conn)
    
    # Create a failed export with future retry time
    state_conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry)
        VALUES ('thread', 'thread1', 'export', 'Error', 5, ?)
    """, (datetime(2099, 1, 1),))  # Far future
    
    state_conn.commit()
    
    # Force retry
    manager.force_retry('thread', 'thread1')
    
    # Should now be ready for retry
    retries = manager.get_ready_retries()
    assert len(retries) == 1
    assert retries[0]['error_count'] == 1  # Reset to 1
