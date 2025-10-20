# ABOUTME: Add notification queue table for export client notifications
# ABOUTME: Tracks data changes that need to be exported to clients

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add notification queue table."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            
            data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notification_queue_pending 
        ON notification_queue(processed_at, created_at)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_notification_queue_entity
        ON notification_queue(entity_type, entity_id)
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS notification_queue")
    conn.commit()
