# ABOUTME: Add attachments metadata table to chat.db
# ABOUTME: Stores attachment metadata with download tracking

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add attachments table to chat.db."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,

            name TEXT,
            content_type TEXT,
            size_bytes INTEGER,

            source_url TEXT,
            thumbnail_url TEXT,

            downloaded BOOLEAN DEFAULT FALSE,
            download_time TIMESTAMP,
            download_error TEXT,
            download_attempts INTEGER DEFAULT 0,

            storage_type TEXT DEFAULT 'chunked',
            chunk_size INTEGER,
            total_chunks INTEGER,

            sha256_hash TEXT,

            raw_data TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attachments_message
        ON attachments(message_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attachments_downloaded
        ON attachments(downloaded)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attachments_hash
        ON attachments(sha256_hash)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attachments_download_pending
        ON attachments(downloaded, download_attempts)
        """
    )

    conn.commit()
