# ABOUTME: Add avatar tracking tables with history
# ABOUTME: Stores avatar URLs and downloaded data with change tracking

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add user avatar tables."""

    # Avatar metadata in chat.db
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_avatars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            avatar_url TEXT NOT NULL,
            
            downloaded BOOLEAN DEFAULT FALSE,
            download_time TIMESTAMP,
            download_error TEXT,
            download_attempts INTEGER DEFAULT 0,
            
            storage_id TEXT,
            content_type TEXT,
            size_bytes INTEGER,
            sha256_hash TEXT,
            
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_current BOOLEAN DEFAULT TRUE,
            
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_avatars_user 
        ON user_avatars(user_id, is_current)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_avatars_download
        ON user_avatars(downloaded, download_attempts)
        """
    )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_avatars_unique
        ON user_avatars(user_id, avatar_url) 
        WHERE is_current = TRUE
        """
    )

    # Add avatar_id column to users table
    conn.execute(
        """
        ALTER TABLE users 
        ADD COLUMN current_avatar_id INTEGER 
        REFERENCES user_avatars(id)
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert this migration."""
    # SQLite doesn't support DROP COLUMN, would need to recreate table
    conn.execute("DROP TABLE IF EXISTS user_avatars")
    conn.commit()
