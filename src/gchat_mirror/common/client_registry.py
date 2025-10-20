# ABOUTME: Export client registry management
# ABOUTME: Handles client registration, heartbeats, and status tracking

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

import structlog  # type: ignore

logger = structlog.get_logger()


class ClientRegistry:
    """Manage export client registration and heartbeats."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def register(
        self, client_id: str, client_type: str, config: dict[str, Any] | None = None
    ) -> str:
        """
        Register an export client.

        Returns:
            The client_id
        """
        self.conn.execute(
            """
            INSERT INTO export_clients 
            (id, client_type, config, last_heartbeat)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                status = 'active',
                last_heartbeat = CURRENT_TIMESTAMP,
                config = excluded.config,
                updated_at = CURRENT_TIMESTAMP
            """,
            (client_id, client_type, json.dumps(config) if config else None),
        )
        self.conn.commit()

        logger.info("client_registered", client_id=client_id, client_type=client_type)

        return client_id

    def heartbeat(
        self, client_id: str, last_processed_notification: int | None = None
    ) -> None:
        """Update client heartbeat."""
        if last_processed_notification is not None:
            self.conn.execute(
                """
                UPDATE export_clients
                SET last_heartbeat = CURRENT_TIMESTAMP,
                    last_processed_notification = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (last_processed_notification, client_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE export_clients
                SET last_heartbeat = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (client_id,),
            )

        self.conn.commit()

    def unregister(self, client_id: str) -> None:
        """Unregister a client."""
        self.conn.execute(
            """
            UPDATE export_clients
            SET status = 'inactive',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (client_id,),
        )
        self.conn.commit()

        logger.info("client_unregistered", client_id=client_id)

    def list_clients(self) -> list[dict[str, Any]]:
        """List all registered clients."""
        cursor = self.conn.execute(
            """
            SELECT id, client_type, status, last_heartbeat,
                   last_processed_notification, registered_at
            FROM export_clients
            ORDER BY registered_at DESC
            """
        )

        return [dict(row) for row in cursor.fetchall()]

    def cleanup_stale(self, timeout_minutes: int = 10) -> int:
        """Mark clients as stale if no heartbeat received."""
        cutoff = datetime.now() - timedelta(minutes=timeout_minutes)

        cursor = self.conn.execute(
            """
            UPDATE export_clients
            SET status = 'stale'
            WHERE status = 'active'
              AND last_heartbeat < ?
            """,
            (cutoff,),
        )

        stale_count = cursor.rowcount
        self.conn.commit()

        if stale_count > 0:
            logger.warning("clients_marked_stale", count=stale_count)

        return stale_count
