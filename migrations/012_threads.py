# ABOUTME: Add threads table and modernize chat schema for exporters
from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Creates the threads table"""

    # Create threads table
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            reply_count INTEGER DEFAULT 0,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(space_id) REFERENCES spaces(id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_threads_space
        ON threads(space_id)
        """
    )
