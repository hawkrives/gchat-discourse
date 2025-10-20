# ABOUTME: Add reactions table for message reactions
# ABOUTME: Stores emoji reactions with user attribution and timestamps

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add reactions table."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reactions (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            
            emoji_content TEXT NOT NULL,
            emoji_unicode TEXT,
            emoji_custom_id TEXT,
            
            user_id TEXT NOT NULL,
            create_time TIMESTAMP NOT NULL,
            
            raw_data TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id),
            
            UNIQUE(message_id, emoji_content, user_id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reactions_message 
        ON reactions(message_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reactions_user 
        ON reactions(user_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reactions_emoji
        ON reactions(emoji_custom_id)
        """
    )

    conn.commit()


def downgrade(conn: sqlite3.Connection) -> None:
    """Revert this migration."""
    conn.execute("DROP TABLE IF EXISTS reactions")
    conn.commit()
