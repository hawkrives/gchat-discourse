# ABOUTME: Add threads table and modernize chat schema for exporters
# ABOUTME: Adds 'deleted' on messages, 'mime_type' on attachments, and
# ABOUTME: adds revision_id/update_time on message_revisions

from __future__ import annotations

import sqlite3
 


def upgrade(conn: sqlite3.Connection) -> None:
    """Bring chat.db schema to the shape expected by exporters/tests.

    This migration is intentionally additive: it creates the threads table
    and adds the columns used by newer code paths.
    """

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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_threads_space ON threads(space_id)")

    # Add deleted flag to messages if missing
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "deleted" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN deleted INTEGER DEFAULT 0")

    # Add revision_id to messages (to track current revision id)
    if "revision_id" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN revision_id TEXT")

    # Add mime_type to attachments
    cols_att = {r[1] for r in conn.execute("PRAGMA table_info(attachments)").fetchall()}
    if "mime_type" not in cols_att:
        conn.execute("ALTER TABLE attachments ADD COLUMN mime_type TEXT")

    # Add revision_id and update_time to message_revisions (non-destructive)
    rev_cols = {r[1] for r in conn.execute("PRAGMA table_info(message_revisions)").fetchall()} if any(
        r for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_revisions'")
    ) else set()
    # Add columns only if they don't exist (keeps migration idempotent)
    if "revision_id" not in rev_cols:
        conn.execute("ALTER TABLE message_revisions ADD COLUMN revision_id TEXT")
    if "update_time" not in rev_cols:
        conn.execute("ALTER TABLE message_revisions ADD COLUMN update_time TIMESTAMP")

    # Create supporting indexes if they don't exist
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_revisions_message_id ON message_revisions(message_id)"
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Downgrade is destructive and not implemented intentionally."""
    raise RuntimeError("downgrade not supported for 011_chat_schema_updates")
