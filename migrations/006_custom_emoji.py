# ABOUTME: Add custom emoji table for workspace custom emoji
# ABOUTME: Stores custom emoji metadata and download tracking

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add custom emoji table."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_emoji (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            
            source_url TEXT,
            
            downloaded BOOLEAN DEFAULT FALSE,
            download_time TIMESTAMP,
            download_error TEXT,
            download_attempts INTEGER DEFAULT 0,
            
            storage_id TEXT,
            content_type TEXT,
            size_bytes INTEGER,
            sha256_hash TEXT,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_custom_emoji_name 
        ON custom_emoji(name)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_custom_emoji_download
        ON custom_emoji(downloaded, download_attempts)
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS custom_emoji")
    conn.commit()
