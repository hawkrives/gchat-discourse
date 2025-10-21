# ABOUTME: Space activity tracking and adaptive polling
# ABOUTME: Calculates poll intervals based on message frequency

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import List

import structlog

logger = structlog.get_logger()


class ActivityTracker:
    """Track space activity and adjust poll intervals."""

    def __init__(self, conn: sqlite3.Connection, config: dict | None = None):
        self.conn = conn

        # Load thresholds from config or use defaults
        if config is None:
            config = {}

        polling_config = config.get("polling", {})

        # Activity thresholds (configurable)
        self.active_threshold = polling_config.get("active_threshold", 10)  # messages per 24h
        self.active_poll_interval = polling_config.get("active_interval", 10)  # seconds
        self.quiet_poll_interval = polling_config.get("quiet_interval", 300)  # 5 minutes

        logger.info(
            "activity_tracker_initialized",
            active_threshold=self.active_threshold,
            active_interval=self.active_poll_interval,
            quiet_interval=self.quiet_poll_interval,
        )

    def update_space_activity(self, space_id: str) -> int:
        """
        Update activity metrics for a space.

        Calculates message counts for 24h and 7d windows,
        then adjusts poll interval accordingly.

        Returns:
            The new poll interval in seconds.
        """
        # Count messages in last 24 hours
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE space_id = ?
              AND create_time > datetime('now', '-24 hours')
            """,
            (space_id,),
        )
        count_24h = cursor.fetchone()[0]

        # Count messages in last 7 days
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE space_id = ?
              AND create_time > datetime('now', '-7 days')
            """,
            (space_id,),
        )
        count_7d = cursor.fetchone()[0]

        # Determine poll interval
        if count_24h >= self.active_threshold:
            poll_interval = self.active_poll_interval
            activity_level = "active"
        else:
            poll_interval = self.quiet_poll_interval
            activity_level = "quiet"

        # Update space record
        self.conn.execute(
            """
            UPDATE spaces
            SET message_count_24h = ?,
                message_count_7d = ?,
                poll_interval_seconds = ?,
                last_activity_check = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (count_24h, count_7d, poll_interval, space_id),
        )

        self.conn.commit()

        logger.debug(
            "activity_updated",
            space_id=space_id,
            count_24h=count_24h,
            level=activity_level,
            poll_interval=poll_interval,
        )

        return poll_interval

    def get_spaces_to_poll(self) -> List[str]:
        """
        Get spaces that need polling based on their intervals.

        Returns list of space IDs that should be polled now.
        """
        cursor = self.conn.execute(
            """
            SELECT id, poll_interval_seconds, last_synced_at
            FROM spaces
            WHERE sync_status = 'active'
              AND (
                  last_synced_at IS NULL
                  OR datetime(last_synced_at, 
                      '+' || poll_interval_seconds || ' seconds') 
                      <= datetime('now')
              )
            ORDER BY last_synced_at ASC NULLS FIRST
            """
        )

        return [row[0] for row in cursor.fetchall()]

    def log_activity_window(
        self, space_id: str, window_start: datetime, window_end: datetime
    ) -> None:
        """Log activity for a time window (for trend analysis)."""
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE space_id = ?
              AND create_time >= ?
              AND create_time < ?
            """,
            (space_id, window_start.isoformat(), window_end.isoformat()),
        )

        message_count = cursor.fetchone()[0]

        self.conn.execute(
            """
            INSERT INTO space_activity_log
            (space_id, message_count, window_start, window_end)
            VALUES (?, ?, ?, ?)
            """,
            (space_id, message_count, window_start.isoformat(), window_end.isoformat()),
        )

        self.conn.commit()
