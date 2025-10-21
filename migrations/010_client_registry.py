# ABOUTME: Add client registry table for export client tracking
# ABOUTME: Tracks registered export clients with heartbeat monitoring

from __future__ import annotations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Add client registry table."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS export_clients (
            id TEXT PRIMARY KEY,
            client_type TEXT NOT NULL,
            
            status TEXT DEFAULT 'active',
            
            last_heartbeat TIMESTAMP,
            last_processed_notification INTEGER,
            
            config TEXT,
            
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_export_clients_status
        ON export_clients(status, last_heartbeat)
        """
    )

    conn.commit()
