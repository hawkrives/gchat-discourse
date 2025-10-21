# ABOUTME: Add message revisions table for edit history
# ABOUTME: Stores previous versions of edited messages

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add message revisions table."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS message_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,

            -- legacy revision number for older migrations/tests
            revision_number INTEGER,

            -- canonical revision id used by newer code
            revision_id TEXT,

            text TEXT,
            formatted_text TEXT,

            -- legacy timestamp column
            last_update_time TIMESTAMP,

            -- canonical update time used by newer code
            update_time TIMESTAMP,

            raw_data TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,

            UNIQUE(message_id, revision_number),
            UNIQUE(message_id, revision_id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_revisions_message_number
        ON message_revisions(message_id, revision_number)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_revisions_message_id
        ON message_revisions(message_id, revision_id)
        """
    )

    # Add revision tracking to messages table
    conn.execute(
        """
        ALTER TABLE messages 
        ADD COLUMN revision_number INTEGER DEFAULT 0
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS message_revisions")
    # Can't remove column in SQLite without recreating table
    conn.commit()
