# ABOUTME: Initial database schema for Google Chat mirroring
# ABOUTME: Creates core tables for spaces, users, memberships, and messages

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS spaces (
            id TEXT PRIMARY KEY,
            name TEXT,
            display_name TEXT,
            space_type TEXT,
            threaded INTEGER,
            last_synced_at TIMESTAMP,
            last_message_time TIMESTAMP,
            sync_cursor TEXT,
            sync_status TEXT DEFAULT 'active',
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            type TEXT,
            email TEXT,
            is_bot INTEGER,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memberships (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(space_id) REFERENCES spaces(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            thread_id TEXT,
            sender_id TEXT,
            text TEXT,
            create_time TIMESTAMP,
            update_time TIMESTAMP,
            message_type TEXT,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(space_id) REFERENCES spaces(id),
            FOREIGN KEY(sender_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_space_time ON messages(space_id, create_time)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memberships_space ON memberships(space_id)")

    conn.commit()
