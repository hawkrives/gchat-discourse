from datetime import datetime
import sqlite3
from unittest.mock import Mock


from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager
from gchat_mirror.exporters.discourse.retry_worker import RetryWorker


def test_retry_worker_processes_retries(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that retry worker processes ready retries."""
    state_conn, chat_conn = discourse_dbs
    
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


def test_retry_worker_handles_failure(discourse_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that retry worker handles failed retries."""
    state_conn, chat_conn = discourse_dbs
    
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
