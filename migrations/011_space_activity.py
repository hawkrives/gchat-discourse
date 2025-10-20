# ABOUTME: Add space activity tracking for adaptive polling
# ABOUTME: Stores message counts and timestamps to determine activity levels

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add activity tracking fields to spaces table."""

    # Add activity tracking columns
    conn.execute(
        """
        ALTER TABLE spaces 
        ADD COLUMN message_count_24h INTEGER DEFAULT 0
        """
    )

    conn.execute(
        """
        ALTER TABLE spaces 
        ADD COLUMN message_count_7d INTEGER DEFAULT 0
        """
    )

    conn.execute(
        """
        ALTER TABLE spaces 
        ADD COLUMN poll_interval_seconds INTEGER DEFAULT 300
        """
    )

    conn.execute(
        """
        ALTER TABLE spaces
        ADD COLUMN last_activity_check TIMESTAMP
        """
    )

    # Create activity log table for trend analysis
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS space_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            space_id TEXT NOT NULL,
            
            message_count INTEGER DEFAULT 0,
            
            window_start TIMESTAMP NOT NULL,
            window_end TIMESTAMP NOT NULL,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (space_id) REFERENCES spaces(id) ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_log_space
        ON space_activity_log(space_id, window_start)
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """
    Revert this migration.
    
    NOTE: This is a no-op. We use forward-only migrations.
    SQLite doesn't support dropping columns without recreating the entire table,
    and we don't rollback migrations in production.
    """
    pass
