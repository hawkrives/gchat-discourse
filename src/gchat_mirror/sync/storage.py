# ABOUTME: Data storage operations for sync daemon
# ABOUTME: Provides helpers to persist spaces, users, and messages

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()


class SyncStorage:
    """Handle storage operations for sync daemon."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_space(self, space_data: Dict[str, Any]) -> None:
        """Insert or update a space."""
        space_id = space_data.get("name")
        if not space_id:
            raise ValueError("Space data missing 'name'")

        threaded_state = space_data.get("spaceThreadingState")
        threaded = 1 if threaded_state == "THREADED_MESSAGES" else 0

        payload = {
            "id": space_id,
            "name": space_data.get("name"),
            "display_name": space_data.get("displayName"),
            "space_type": space_data.get("type"),
            "threaded": threaded,
            "raw_data": json.dumps(space_data),
        }

        self.conn.execute(
            """
            INSERT INTO spaces (id, name, display_name, space_type, threaded, raw_data)
            VALUES (:id, :name, :display_name, :space_type, :threaded, :raw_data)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                display_name=excluded.display_name,
                space_type=excluded.space_type,
                threaded=excluded.threaded,
                raw_data=excluded.raw_data,
                updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self.conn.commit()
        logger.info("space_upserted", space_id=space_id)

    def upsert_user(self, user_data: Dict[str, Any]) -> None:
        """Insert or update a user."""
        user_id = user_data.get("name")
        if not user_id:
            raise ValueError("User data missing 'name'")

        payload = {
            "id": user_id,
            "display_name": user_data.get("displayName"),
            "type": user_data.get("type"),
            "email": user_data.get("email"),
            "is_bot": 1 if user_data.get("type") == "BOT" else 0,
            "raw_data": json.dumps(user_data),
        }

        self.conn.execute(
            """
            INSERT INTO users (id, display_name, type, email, is_bot, raw_data)
            VALUES (:id, :display_name, :type, :email, :is_bot, :raw_data)
            ON CONFLICT(id) DO UPDATE SET
                display_name=excluded.display_name,
                type=excluded.type,
                email=excluded.email,
                is_bot=excluded.is_bot,
                raw_data=excluded.raw_data,
                updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self.conn.commit()
        logger.info("user_upserted", user_id=user_id)

    def insert_message(self, message_data: Dict[str, Any]) -> None:
        """Insert a message (does not update existing)."""
        message_id = message_data.get("name")
        if not message_id:
            raise ValueError("Message data missing 'name'")

        space_id = message_data.get("space", {}).get("name")
        if not space_id and "name" in message_data:
            parts = message_id.split("/")
            if len(parts) >= 2:
                space_id = "/".join(parts[:2])

        sender = message_data.get("sender", {})
        thread_id = message_data.get("thread", {}).get("name")

        payload = {
            "id": message_id,
            "space_id": space_id,
            "thread_id": thread_id,
            "sender_id": sender.get("name"),
            "text": message_data.get("text"),
            "create_time": message_data.get("createTime"),
            "update_time": message_data.get("updateTime"),
            "message_type": message_data.get("type"),
            "raw_data": json.dumps(message_data),
        }

        self.conn.execute(
            """
            INSERT OR IGNORE INTO messages (
                id, space_id, thread_id, sender_id, text, create_time,
                update_time, message_type, raw_data
            )
            VALUES (
                :id, :space_id, :thread_id, :sender_id, :text, :create_time,
                :update_time, :message_type, :raw_data
            )
            """,
            payload,
        )
        self.conn.commit()
        logger.info("message_inserted", message_id=message_id)

    def get_space_sync_cursor(self, space_id: str) -> Optional[str]:
        """Get the last sync cursor for a space."""
        cursor = self.conn.execute(
            "SELECT sync_cursor FROM spaces WHERE id = ?",
            (space_id,),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else None

    def update_space_sync_cursor(self, space_id: str, cursor: str) -> None:
        """Update sync cursor for a space."""
        self.conn.execute(
            """
            UPDATE spaces
            SET sync_cursor = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (cursor, space_id),
        )
        self.conn.commit()
        logger.info("space_cursor_updated", space_id=space_id)
