# ABOUTME: Tests for database integrity checker
# ABOUTME: Ensures IntegrityChecker detects various database problems

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest  # type: ignore

from gchat_mirror.common.database import Database
from gchat_mirror.common.integrity import IntegrityChecker
from gchat_mirror.common.migrations import run_migrations


@pytest.fixture
def db(tmp_path: Path):
    """Create test database with schema."""
    db_path = tmp_path / "test_integrity.db"

    # Apply migrations to create schema
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    run_migrations(db_path, migrations_dir)

    # Now connect to the migrated database
    db_manager = Database(db_path)
    db_manager.connect()
    return db_manager


def test_integrity_checker_passes_clean_db(db: Database) -> None:
    """Test integrity check on clean database with valid data."""
    # Add valid data
    assert db.conn is not None
    # Use SQL's datetime to avoid timezone comparison issues
    
    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'active', datetime('now'))
    """
    )
    db.conn.execute(
        """
        INSERT INTO users (id, display_name)
        VALUES ('user1', 'Test User')
    """
    )
    db.conn.execute(
        """
        INSERT INTO messages (id, space_id, text, sender_id, create_time)
        VALUES ('msg1', 'space1', 'test', 'user1', datetime('now'))
    """
    )
    db.conn.commit()

    checker = IntegrityChecker(db.conn)
    result = checker.check_all()
    # Debug: show what issues were found
    assert result is True, f"Unexpected issues found: {checker.issues}"
    assert len(checker.issues) == 0


def test_integrity_checker_detects_orphaned_messages(db: Database) -> None:
    """Test detection of orphaned messages."""
    assert db.conn is not None

    # Disable foreign keys temporarily to create orphaned record
    db.conn.execute("PRAGMA foreign_keys=OFF")

    # Create orphaned message (no parent space)
    db.conn.execute(
        """
        INSERT INTO messages (id, space_id, text, create_time)
        VALUES ('msg1', 'nonexistent_space', 'orphan', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.conn.commit()

    # Re-enable foreign keys for the check
    db.conn.execute("PRAGMA foreign_keys=ON")

    checker = IntegrityChecker(db.conn)
    assert checker.check_all() is False
    assert any(i["type"] == "orphaned_messages" for i in checker.issues)
    orphan_issue = next(i for i in checker.issues if i["type"] == "orphaned_messages")
    assert orphan_issue["count"] == 1


def test_integrity_checker_detects_orphaned_reactions(db: Database) -> None:
    """Test detection of orphaned reactions."""
    assert db.conn is not None

    # Create space first
    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'active', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.conn.commit()

    # Disable foreign keys to create orphan
    db.conn.execute("PRAGMA foreign_keys=OFF")
    db.conn.commit()
    
    db.conn.execute(
        """
        INSERT INTO reactions (id, message_id, emoji_content, user_id, create_time)
        VALUES ('reaction1', 'nonexistent_msg', '👍', 'user1', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.conn.commit()
    db.conn.execute("PRAGMA foreign_keys=ON")

    checker = IntegrityChecker(db.conn)
    assert checker.check_all() is False
    assert any(i["type"] == "orphaned_reactions" for i in checker.issues)


def test_integrity_checker_detects_orphaned_attachments(db: Database) -> None:
    """Test detection of orphaned attachments."""
    assert db.conn is not None

    # Create space first
    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'active', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.conn.commit()

    # Disable foreign keys to create orphan
    db.conn.execute("PRAGMA foreign_keys=OFF")
    db.conn.commit()
    
    db.conn.execute(
        """
        INSERT INTO attachments (id, message_id, name, content_type, source_url)
        VALUES ('attach1', 'nonexistent_msg', 'file.pdf', 'application/pdf', 'http://example.com')
    """
    )
    db.conn.commit()
    db.conn.execute("PRAGMA foreign_keys=ON")

    checker = IntegrityChecker(db.conn)
    assert checker.check_all() is False
    assert any(i["type"] == "orphaned_attachments" for i in checker.issues)


def test_integrity_checker_detects_invalid_sync_status(db: Database) -> None:
    """Test detection of invalid sync_status values."""
    assert db.conn is not None

    # Create space with invalid sync_status
    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'invalid_status', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.conn.commit()

    checker = IntegrityChecker(db.conn)
    assert checker.check_all() is False
    assert any(i["type"] == "invalid_sync_status" for i in checker.issues)


def test_integrity_checker_detects_future_timestamps(db: Database) -> None:
    """Test detection of messages with future timestamps."""
    assert db.conn is not None

    # Create space
    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'active', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )

    # Create message with future timestamp
    future_time = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    db.conn.execute(
        """
        INSERT INTO messages (id, space_id, text, create_time)
        VALUES ('msg1', 'space1', 'future message', ?)
    """,
        (future_time,),
    )
    db.conn.commit()

    checker = IntegrityChecker(db.conn)
    assert checker.check_all() is False
    assert any(i["type"] == "future_timestamps" for i in checker.issues)


def test_integrity_checker_multiple_issues(db: Database) -> None:
    """Test that multiple issues are detected."""
    assert db.conn is not None

    # Disable foreign keys
    db.conn.execute("PRAGMA foreign_keys=OFF")

    # Create multiple issues
    # 1. Orphaned message
    db.conn.execute(
        """
        INSERT INTO messages (id, space_id, text, create_time)
        VALUES ('msg1', 'nonexistent', 'orphan', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )

    # 2. Invalid sync_status
    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'bad_status', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.conn.commit()

    # Re-enable foreign keys
    db.conn.execute("PRAGMA foreign_keys=ON")

    checker = IntegrityChecker(db.conn)
    assert checker.check_all() is False
    assert len(checker.issues) >= 2
    assert any(i["type"] == "orphaned_messages" for i in checker.issues)
    assert any(i["type"] == "invalid_sync_status" for i in checker.issues)


def test_sqlite_integrity_check(db: Database) -> None:
    """Test that SQLite's built-in integrity check works."""
    assert db.conn is not None

    # Add valid data
    db.conn.execute(
        """
        INSERT INTO spaces (id, name, sync_status, created_at)
        VALUES ('space1', 'Test', 'active', ?)
    """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.conn.commit()

    checker = IntegrityChecker(db.conn)
    checker._check_sqlite_integrity()

    # Should have no issues on a clean database
    assert not any(i["type"] == "sqlite_integrity" for i in checker.issues)
