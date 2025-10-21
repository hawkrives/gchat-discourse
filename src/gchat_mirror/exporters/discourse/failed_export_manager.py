# ABOUTME: Failed export tracking with dependency management
# ABOUTME: Handles retry scheduling and dependency blocking

import sqlite3
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import structlog

from gchat_mirror.exporters.discourse.retry_config import RetryConfig

logger = structlog.get_logger()


class FailedExportManager:
    """Manage failed exports and retry logic."""

    def __init__(
        self,
        state_conn: sqlite3.Connection,
        chat_conn: sqlite3.Connection,
        retry_config: Optional[RetryConfig] = None,
    ):
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.retry_config = retry_config or RetryConfig()

    def record_failure(
        self,
        entity_type: str,
        entity_id: str,
        operation: str,
        error_message: str,
        blocked_by: Optional[str] = None,
    ) -> bool:
        """
        Record a failed export.

        Args:
            entity_type: Type of entity ('thread', 'message', 'reaction', etc.)
            entity_id: Entity ID
            operation: Operation that failed ('export', 'update', etc.)
            error_message: Error message
            blocked_by: Entity ID that blocks this one (e.g., thread blocks message)

        Returns:
            True if should retry, False if permanent failure
        """
        # Check if this is a permanent failure
        if self.retry_config.is_permanent_failure(error_message):
            logger.error(
                "permanent_failure",
                entity_type=entity_type,
                entity_id=entity_id,
                error=error_message,
            )

            # Don't add to retry queue
            return False

        # Get or create failed export record
        cursor = self.state_conn.execute(
            """
            SELECT error_count, first_attempt
            FROM failed_exports
            WHERE entity_type = ? AND entity_id = ? AND operation = ?
        """,
            (entity_type, entity_id, operation),
        )

        existing = cursor.fetchone()

        if existing:
            error_count, first_attempt = existing
            error_count += 1
        else:
            error_count = 1
            first_attempt = datetime.now(timezone.utc)

        # Check if we should still retry
        if not self.retry_config.should_retry(error_count):
            logger.error(
                "max_retries_exceeded",
                entity_type=entity_type,
                entity_id=entity_id,
                error_count=error_count,
            )
            return False

        # Calculate next retry time
        next_retry = self.retry_config.calculate_next_retry(error_count)

        # Insert or update failed export
        self.state_conn.execute(
            """
            INSERT INTO failed_exports
            (entity_type, entity_id, operation, error_message, error_count,
             blocked_by, first_attempt, last_attempt, next_retry)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_id, operation)
            DO UPDATE SET
                error_message = excluded.error_message,
                error_count = excluded.error_count,
                blocked_by = excluded.blocked_by,
                last_attempt = excluded.last_attempt,
                next_retry = excluded.next_retry
        """,
            (
                entity_type,
                entity_id,
                operation,
                error_message,
                error_count,
                blocked_by,
                first_attempt,
                datetime.now(timezone.utc),
                next_retry,
            ),
        )

        self.state_conn.commit()

        logger.warning(
            "export_failure_recorded",
            entity_type=entity_type,
            entity_id=entity_id,
            error_count=error_count,
            next_retry=next_retry.isoformat(),
        )

        return True

    def get_ready_retries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get failed exports ready for retry.

        Returns exports where:
        - next_retry is in the past
        - not blocked by another failed export

        Args:
            limit: Maximum number of retries to return

        Returns:
            List of failed export records
        """
        cursor = self.state_conn.execute(
            """
            SELECT 
                id,
                entity_type,
                entity_id,
                operation,
                error_message,
                error_count,
                blocked_by,
                first_attempt,
                last_attempt
            FROM failed_exports
            WHERE next_retry <= ?
            AND (
                blocked_by IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM failed_exports f2
                    WHERE f2.entity_id = failed_exports.blocked_by
                )
            )
            ORDER BY next_retry ASC
            LIMIT ?
        """,
            (datetime.now(timezone.utc), limit),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "id": row[0],
                    "entity_type": row[1],
                    "entity_id": row[2],
                    "operation": row[3],
                    "error_message": row[4],
                    "error_count": row[5],
                    "blocked_by": row[6],
                    "first_attempt": row[7],
                    "last_attempt": row[8],
                }
            )

        return results

    def mark_success(self, entity_type: str, entity_id: str, operation: str):
        """
        Mark a previously failed export as successful.

        This removes it from the failed exports table and unblocks
        any dependent exports.
        """
        self.state_conn.execute(
            """
            DELETE FROM failed_exports
            WHERE entity_type = ? AND entity_id = ? AND operation = ?
        """,
            (entity_type, entity_id, operation),
        )

        self.state_conn.commit()

        logger.info("export_success", entity_type=entity_type, entity_id=entity_id)

        # Log any exports that are now unblocked
        cursor = self.state_conn.execute(
            """
            SELECT COUNT(*) FROM failed_exports
            WHERE blocked_by = ?
        """,
            (entity_id,),
        )

        unblocked_count = cursor.fetchone()[0]
        if unblocked_count > 0:
            logger.info("exports_unblocked", blocker_id=entity_id, unblocked_count=unblocked_count)

    def is_blocked(self, entity_type: str, entity_id: str) -> bool:
        """
        Check if an entity's export is blocked by a failed dependency.

        Args:
            entity_type: Type of entity
            entity_id: Entity ID

        Returns:
            True if blocked, False otherwise
        """
        # Get the blocker entity ID based on type
        blocker_id = None
        blocker_type = None

        if entity_type == "message":
            # Messages are blocked by failed thread export
            cursor = self.chat_conn.execute(
                """
                SELECT thread_id FROM messages WHERE id = ?
            """,
                (entity_id,),
            )
            result = cursor.fetchone()
            if result:
                blocker_id = result[0]
                blocker_type = "thread"

        elif entity_type == "reaction":
            # Reactions are blocked by failed message export
            cursor = self.chat_conn.execute(
                """
                SELECT message_id FROM reactions WHERE id = ?
            """,
                (entity_id,),
            )
            result = cursor.fetchone()
            if result:
                blocker_id = result[0]
                blocker_type = "message"

        else:
            # No blockers for threads, spaces, users
            return False

        if not blocker_id or not blocker_type:
            return False

        # Check if blocker is in failed exports
        cursor = self.state_conn.execute(
            """
            SELECT 1 FROM failed_exports
            WHERE entity_type = ? AND entity_id = ?
        """,
            (blocker_type, blocker_id),
        )

        is_blocked = cursor.fetchone() is not None

        if is_blocked:
            logger.debug(
                "export_blocked",
                entity_type=entity_type,
                entity_id=entity_id,
                blocked_by_type=blocker_type,
                blocked_by_id=blocker_id,
            )

        return is_blocked

    def get_blocked_exports(self) -> List[Dict[str, Any]]:
        """
        Get all failed exports that are blocked by dependencies.

        Returns:
            List of blocked export records with blocker info
        """
        cursor = self.state_conn.execute("""
            SELECT 
                f1.entity_type,
                f1.entity_id,
                f1.operation,
                f1.error_message,
                f1.blocked_by,
                f2.entity_type as blocker_type,
                f2.error_message as blocker_error
            FROM failed_exports f1
            JOIN failed_exports f2 ON f1.blocked_by = f2.entity_id
            WHERE f1.blocked_by IS NOT NULL
            ORDER BY f1.first_attempt
        """)

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "entity_type": row[0],
                    "entity_id": row[1],
                    "operation": row[2],
                    "error_message": row[3],
                    "blocked_by_id": row[4],
                    "blocked_by_type": row[5],
                    "blocker_error": row[6],
                }
            )

        return results

    def clear_all_failures(self):
        """Clear all failed exports (for testing or manual intervention)."""
        self.state_conn.execute("DELETE FROM failed_exports")
        self.state_conn.commit()
        logger.warning("all_failures_cleared")

    def force_retry(self, entity_type: str, entity_id: str) -> bool:
        """
        Force immediate retry of a failed export.

        Sets next_retry to now and resets error_count.

        Returns:
            True if a row was updated, False otherwise
        """
        cursor = self.state_conn.execute(
            """
            UPDATE failed_exports
            SET next_retry = ?,
                error_count = 1
            WHERE entity_type = ? AND entity_id = ?
        """,
            (datetime.now(timezone.utc), entity_type, entity_id),
        )

        self.state_conn.commit()

        success = cursor.rowcount > 0

        if success:
            logger.info("retry_forced", entity_type=entity_type, entity_id=entity_id)

        return success
