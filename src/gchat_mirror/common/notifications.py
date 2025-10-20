# ABOUTME: Notification queue management for export clients
# ABOUTME: Handles enqueueing changes and marking them processed

from __future__ import annotations

import json
import sqlite3
from typing import Any

import structlog  # type: ignore

logger = structlog.get_logger()


class NotificationManager:
    """Manage notification queue for export clients."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def enqueue(
        self,
        entity_type: str,
        entity_id: str,
        change_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """
        Add a notification to the queue.

        Args:
            entity_type: Type of entity (message, space, user, etc.)
            entity_id: ID of the entity
            change_type: Type of change (created, updated, deleted)
            data: Optional additional data
        """
        self.conn.execute(
            """
            INSERT INTO notification_queue 
            (entity_type, entity_id, change_type, data)
            VALUES (?, ?, ?, ?)
            """,
            (entity_type, entity_id, change_type, json.dumps(data) if data else None),
        )
        self.conn.commit()

        logger.debug(
            "notification_enqueued",
            entity_type=entity_type,
            entity_id=entity_id,
            change_type=change_type,
        )

    def get_pending(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get pending notifications."""
        cursor = self.conn.execute(
            """
            SELECT id, entity_type, entity_id, change_type, data, created_at
            FROM notification_queue
            WHERE processed_at IS NULL
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        )

        return [dict(row) for row in cursor.fetchall()]

    def mark_processed(self, notification_ids: list[int]) -> None:
        """Mark notifications as processed."""
        if not notification_ids:
            return

        placeholders = ",".join("?" * len(notification_ids))
        self.conn.execute(
            f"""
            UPDATE notification_queue
            SET processed_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            notification_ids,
        )
        self.conn.commit()

        logger.debug("notifications_processed", count=len(notification_ids))

    def cleanup_old(self, days: int = 30) -> None:
        """Remove processed notifications older than specified days."""
        self.conn.execute(
            """
            DELETE FROM notification_queue
            WHERE processed_at IS NOT NULL
              AND processed_at < datetime('now', '-' || ? || ' days')
            """,
            (days,),
        )
        self.conn.commit()
