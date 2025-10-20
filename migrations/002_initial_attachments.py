# ABOUTME: Initial schema for attachments database
# ABOUTME: Creates tables for inline and chunked attachment storage

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create attachments.db schema."""

    # Small files stored whole
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attachment_inline (
            attachment_id TEXT PRIMARY KEY,
            data BLOB NOT NULL,
            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Large files stored in chunks
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attachment_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attachment_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,

            data BLOB NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256_hash TEXT,

            stored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(attachment_id, chunk_index)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chunks_attachment
        ON attachment_chunks(attachment_id, chunk_index)
        """
    )

    # Storage metadata
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Storage stats tracking
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            total_attachments INTEGER,
            inline_count INTEGER,
            chunked_count INTEGER,
            total_size_bytes INTEGER,
            db_size_bytes INTEGER
        )
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS attachment_inline")
    conn.execute("DROP TABLE IF EXISTS attachment_chunks")
    conn.execute("DROP TABLE IF EXISTS storage_metadata")
    conn.execute("DROP TABLE IF EXISTS storage_stats")
    conn.commit()
