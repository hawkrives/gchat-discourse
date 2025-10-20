# ABOUTME: Add read receipts table for message read tracking
# ABOUTME: Stores who has read which messages and when

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add read receipts table."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS read_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            read_time TIMESTAMP NOT NULL,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id),
            
            UNIQUE(message_id, user_id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_read_receipts_message 
        ON read_receipts(message_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_read_receipts_user 
        ON read_receipts(user_id)
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS read_receipts")
    conn.commit()
