# ABOUTME: Tests for export state management and progress tracking
# ABOUTME: Verifies progress tracking, space completion, and overall statistics

from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pytest  # type: ignore

from gchat_mirror.exporters.discourse.export_state import ExportStateManager


@pytest.fixture
def setup_test_dbs(tmp_path: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Set up test databases."""
    # State DB with export_progress table
    state_db_path = tmp_path / "state.db"
    state_conn = sqlite3.Connection(state_db_path)
    state_conn.execute("""
        CREATE TABLE export_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            space_id TEXT NOT NULL UNIQUE,
            threads_exported INTEGER DEFAULT 0,
            messages_exported INTEGER DEFAULT 0,
            attachments_exported INTEGER DEFAULT 0,
            reactions_exported INTEGER DEFAULT 0,
            last_exported_message_time TEXT,
            status TEXT DEFAULT 'pending',
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    state_conn.commit()
    
    # Chat DB (not used but required by interface)
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.Connection(chat_db_path)
    
    return state_conn, chat_conn


def test_export_state_manager_initializes_space_progress(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test initializing progress tracking for a space."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    manager.initialize_space_progress('space1')
    
    # Verify row created
    cursor = state_conn.execute("""
        SELECT space_id, status, threads_exported, messages_exported, started_at
        FROM export_progress
        WHERE space_id = 'space1'
    """)
    row = cursor.fetchone()
    
    assert row is not None
    assert row[0] == 'space1'
    assert row[1] == 'in_progress'
    assert row[2] == 0  # threads_exported
    assert row[3] == 0  # messages_exported
    assert row[4] is not None  # started_at


def test_export_state_manager_initializes_space_idempotent(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test that initializing same space twice doesn't error."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    manager.initialize_space_progress('space1')
    manager.initialize_space_progress('space1')  # Should not error
    
    # Verify only one row
    cursor = state_conn.execute("""
        SELECT COUNT(*) FROM export_progress WHERE space_id = 'space1'
    """)
    assert cursor.fetchone()[0] == 1


def test_export_state_manager_updates_progress(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test updating progress counters."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    manager.initialize_space_progress('space1')
    
    # Update multiple times (counters should accumulate)
    manager.update_progress('space1', threads=5, messages=50)
    manager.update_progress('space1', messages=25, reactions=10)
    manager.update_progress('space1', attachments=15)
    
    # Check accumulated values
    cursor = state_conn.execute("""
        SELECT threads_exported, messages_exported, attachments_exported, reactions_exported
        FROM export_progress
        WHERE space_id = 'space1'
    """)
    row = cursor.fetchone()
    
    assert row[0] == 5   # threads: 5
    assert row[1] == 75  # messages: 50 + 25
    assert row[2] == 15  # attachments: 15
    assert row[3] == 10  # reactions: 10


def test_export_state_manager_marks_space_complete(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test marking a space as complete."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    manager.initialize_space_progress('space1')
    manager.update_progress('space1', threads=10, messages=100)
    
    manager.mark_space_complete('space1')
    
    # Verify status and completed_at
    cursor = state_conn.execute("""
        SELECT status, completed_at
        FROM export_progress
        WHERE space_id = 'space1'
    """)
    row = cursor.fetchone()
    
    assert row[0] == 'completed'
    assert row[1] is not None


def test_export_state_manager_gets_space_progress(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test retrieving space progress."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    manager.initialize_space_progress('space1')
    manager.update_progress('space1', threads=5, messages=50, attachments=10, reactions=20)
    
    progress = manager.get_space_progress('space1')
    
    assert progress is not None
    assert progress['threads'] == 5
    assert progress['messages'] == 50
    assert progress['attachments'] == 10
    assert progress['reactions'] == 20
    assert progress['status'] == 'in_progress'
    assert progress['started_at'] is not None
    assert progress['completed_at'] is None


def test_export_state_manager_gets_nonexistent_space(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test retrieving progress for nonexistent space returns None."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    progress = manager.get_space_progress('nonexistent')
    
    assert progress is None


def test_export_state_manager_gets_overall_progress(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test retrieving overall progress across all spaces."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    
    # Setup multiple spaces
    manager.initialize_space_progress('space1')
    manager.update_progress('space1', threads=5, messages=50, attachments=10, reactions=20)
    manager.mark_space_complete('space1')
    
    manager.initialize_space_progress('space2')
    manager.update_progress('space2', threads=3, messages=30, attachments=5, reactions=10)
    
    manager.initialize_space_progress('space3')
    manager.update_progress('space3', threads=2, messages=20, attachments=3, reactions=5)
    manager.mark_space_complete('space3')
    
    # Get overall progress
    progress = manager.get_overall_progress()
    
    assert progress['total_spaces'] == 3
    assert progress['completed_spaces'] == 2
    assert progress['total_threads'] == 10  # 5 + 3 + 2
    assert progress['total_messages'] == 100  # 50 + 30 + 20
    assert progress['total_attachments'] == 18  # 10 + 5 + 3
    assert progress['total_reactions'] == 35  # 20 + 10 + 5


def test_export_state_manager_overall_progress_empty(setup_test_dbs: tuple[sqlite3.Connection, sqlite3.Connection]) -> None:
    """Test overall progress with no spaces returns zeros."""
    state_conn, chat_conn = setup_test_dbs
    
    manager = ExportStateManager(state_conn, chat_conn)
    progress = manager.get_overall_progress()
    
    assert progress['total_spaces'] == 0
    assert progress['completed_spaces'] == 0
    assert progress['total_threads'] == 0
    assert progress['total_messages'] == 0
    assert progress['total_attachments'] == 0
    assert progress['total_reactions'] == 0
