# ABOUTME: Export progress tracking and state management
# ABOUTME: Monitors export completion per space with incremental counters

import sqlite3
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


class ExportStateManager:
    """Manage export state and progress tracking.

    Tracks export progress per space with incremental counters for:
    - Threads exported
    - Messages exported
    - Attachments exported
    - Reactions exported

    Also tracks overall progress across all spaces.
    """

    def __init__(self, state_conn: sqlite3.Connection, chat_conn: sqlite3.Connection):
        """Initialize the export state manager.

        Args:
            state_conn: Connection to state database
            chat_conn: Connection to chat database
        """
        self.state_conn = state_conn
        self.chat_conn = chat_conn

    def initialize_space_progress(self, space_id: str) -> None:
        """Initialize progress tracking for a space.

        Idempotent - safe to call multiple times for same space.

        Args:
            space_id: Space ID to initialize
        """
        now = datetime.now(timezone.utc).isoformat()

        self.state_conn.execute(
            """
            INSERT OR IGNORE INTO export_progress
            (space_id, status, started_at, updated_at)
            VALUES (?, 'in_progress', ?, ?)
        """,
            (space_id, now, now),
        )
        self.state_conn.commit()

        logger.debug("space_progress_initialized", space_id=space_id)

    def update_progress(
        self,
        space_id: str,
        threads: int = 0,
        messages: int = 0,
        attachments: int = 0,
        reactions: int = 0,
    ) -> None:
        """Increment export progress counters.

        All counters are incremental - they add to existing values.

        Args:
            space_id: Space ID
            threads: Number of threads to add to counter
            messages: Number of messages to add to counter
            attachments: Number of attachments to add to counter
            reactions: Number of reactions to add to counter
        """
        now = datetime.now(timezone.utc).isoformat()

        self.state_conn.execute(
            """
            UPDATE export_progress
            SET threads_exported = threads_exported + ?,
                messages_exported = messages_exported + ?,
                attachments_exported = attachments_exported + ?,
                reactions_exported = reactions_exported + ?,
                updated_at = ?
            WHERE space_id = ?
        """,
            (threads, messages, attachments, reactions, now, space_id),
        )
        self.state_conn.commit()

        logger.debug(
            "progress_updated",
            space_id=space_id,
            threads=threads,
            messages=messages,
            attachments=attachments,
            reactions=reactions,
        )

    def mark_space_complete(self, space_id: str) -> None:
        """Mark a space as fully exported.

        Args:
            space_id: Space ID to mark complete
        """
        now = datetime.now(timezone.utc).isoformat()

        self.state_conn.execute(
            """
            UPDATE export_progress
            SET status = 'completed',
                completed_at = ?,
                updated_at = ?
            WHERE space_id = ?
        """,
            (now, now, space_id),
        )
        self.state_conn.commit()

        logger.info("space_export_complete", space_id=space_id)

    def get_space_progress(self, space_id: str) -> Optional[Dict[str, Any]]:
        """Get export progress for a space.

        Args:
            space_id: Space ID

        Returns:
            Dictionary with progress data, or None if space not found
        """
        cursor = self.state_conn.execute(
            """
            SELECT 
                threads_exported,
                messages_exported,
                attachments_exported,
                reactions_exported,
                status,
                started_at,
                completed_at
            FROM export_progress
            WHERE space_id = ?
        """,
            (space_id,),
        )

        row = cursor.fetchone()
        if not row:
            return None

        return {
            "threads": row[0],
            "messages": row[1],
            "attachments": row[2],
            "reactions": row[3],
            "status": row[4],
            "started_at": row[5],
            "completed_at": row[6],
        }

    def get_overall_progress(self) -> Dict[str, Any]:
        """Get overall export progress across all spaces.

        Returns:
            Dictionary with aggregated progress data
        """
        cursor = self.state_conn.execute("""
            SELECT 
                COUNT(*) as total_spaces,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_spaces,
                SUM(threads_exported) as total_threads,
                SUM(messages_exported) as total_messages,
                SUM(attachments_exported) as total_attachments,
                SUM(reactions_exported) as total_reactions
            FROM export_progress
        """)

        row = cursor.fetchone()

        return {
            "total_spaces": row[0] or 0,
            "completed_spaces": row[1] or 0,
            "total_threads": row[2] or 0,
            "total_messages": row[3] or 0,
            "total_attachments": row[4] or 0,
            "total_reactions": row[5] or 0,
        }
