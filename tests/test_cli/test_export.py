# ABOUTME: Tests for export CLI commands
# ABOUTME: Verifies export status and retry functionality

from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from gchat_mirror.cli.main import cli


def test_discourse_start_placeholder(tmp_path: Path) -> None:
    """Test that start command shows placeholder message."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "start",
        ],
    )

    assert result.exit_code == 0
    assert "daemon not yet implemented" in result.output


def test_discourse_status_no_database(tmp_path: Path) -> None:
    """Test status command when no database exists."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "status",
        ],
    )

    assert result.exit_code == 0
    assert "No Discourse state database found" in result.output


def test_discourse_status_with_data(tmp_path: Path) -> None:
    """Test status command with export data."""
    # Create database structure
    data_dir = tmp_path / "data"
    discourse_dir = data_dir / "discourse"
    sync_dir = data_dir / "sync"
    discourse_dir.mkdir(parents=True)
    sync_dir.mkdir(parents=True)
    
    # Create state database with export_progress
    state_db_path = discourse_dir / "state.db"
    state_conn = sqlite3.connect(state_db_path)
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
    state_conn.execute("""
        INSERT INTO export_progress
        (space_id, status, threads_exported, messages_exported, attachments_exported, reactions_exported, started_at)
        VALUES ('space1', 'completed', 5, 50, 10, 20, '2024-01-01 10:00:00')
    """)
    state_conn.commit()
    state_conn.close()
    
    # Create chat database
    chat_db_path = sync_dir / "chat.db"
    chat_conn = sqlite3.connect(chat_db_path)
    chat_conn.execute("CREATE TABLE spaces (id TEXT PRIMARY KEY)")
    chat_conn.commit()
    chat_conn.close()
    
    # Run status command
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(data_dir),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "status",
        ],
    )

    assert result.exit_code == 0
    assert "Discourse Export Progress" in result.output
    assert "Spaces: 1/1 completed" in result.output
    assert "Threads: 5" in result.output
    assert "Messages: 50" in result.output


def test_discourse_retry_no_database(tmp_path: Path) -> None:
    """Test retry command when no database exists."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "retry",
            "message",
            "msg123",
        ],
    )

    assert result.exit_code == 0
    assert "No Discourse state database found" in result.output


def test_discourse_retry_not_found(tmp_path: Path) -> None:
    """Test retry command when entity not in failed exports."""
    # Create database structure
    data_dir = tmp_path / "data"
    discourse_dir = data_dir / "discourse"
    sync_dir = data_dir / "sync"
    discourse_dir.mkdir(parents=True)
    sync_dir.mkdir(parents=True)
    
    # Create state database
    state_db_path = discourse_dir / "state.db"
    state_conn = sqlite3.connect(state_db_path)
    state_conn.execute("""
        CREATE TABLE failed_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            error_message TEXT,
            error_count INTEGER DEFAULT 1,
            blocked_by TEXT,
            first_attempt TEXT DEFAULT CURRENT_TIMESTAMP,
            last_attempt TEXT DEFAULT CURRENT_TIMESTAMP,
            next_retry TEXT,
            UNIQUE(entity_type, entity_id, operation)
        )
    """)
    state_conn.commit()
    state_conn.close()
    
    # Create chat database
    chat_db_path = sync_dir / "chat.db"
    chat_conn = sqlite3.connect(chat_db_path)
    chat_conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    chat_conn.commit()
    chat_conn.close()
    
    # Run retry command
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(data_dir),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "retry",
            "message",
            "msg123",
        ],
    )

    assert result.exit_code == 0
    assert "No failed exports found" in result.output


def test_discourse_retry_success(tmp_path: Path) -> None:
    """Test successful retry of failed export."""
    # Create database structure
    data_dir = tmp_path / "data"
    discourse_dir = data_dir / "discourse"
    sync_dir = data_dir / "sync"
    discourse_dir.mkdir(parents=True)
    sync_dir.mkdir(parents=True)
    
    # Create state database with failed export
    state_db_path = discourse_dir / "state.db"
    state_conn = sqlite3.connect(state_db_path)
    state_conn.execute("""
        CREATE TABLE failed_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            error_message TEXT,
            error_count INTEGER DEFAULT 1,
            blocked_by TEXT,
            first_attempt TEXT DEFAULT CURRENT_TIMESTAMP,
            last_attempt TEXT DEFAULT CURRENT_TIMESTAMP,
            next_retry TEXT,
            UNIQUE(entity_type, entity_id, operation)
        )
    """)
    state_conn.execute("""
        INSERT INTO failed_exports
        (entity_type, entity_id, operation, error_message, error_count, next_retry, first_attempt, last_attempt)
        VALUES ('message', 'msg123', 'export', 'Test error', 1, '2024-01-01 10:00:00', '2024-01-01 09:00:00', '2024-01-01 09:00:00')
    """)
    state_conn.commit()
    state_conn.close()
    
    chat_db_path = sync_dir / "chat.db"
    chat_conn = sqlite3.connect(chat_db_path)
    chat_conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
    chat_conn.commit()
    chat_conn.close()
    
    # Run retry command
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(data_dir),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "retry",
            "message",
            "msg123",
        ],
    )

    assert result.exit_code == 0
    assert "Forced retry for message msg123" in result.output
