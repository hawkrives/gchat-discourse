# ABOUTME: Database integrity checking and repair
# ABOUTME: Validates foreign keys, orphaned records, and data consistency

from __future__ import annotations

import sqlite3
from typing import Any

import structlog

logger = structlog.get_logger()


class IntegrityChecker:
    """Check database integrity."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.issues: list[dict[str, Any]] = []

    def check_all(self) -> bool:
        """
        Run all integrity checks.

        Returns:
            True if all checks pass, False if issues found
        """
        self.issues = []

        # SQLite's built-in integrity check
        self._check_sqlite_integrity()

        # Foreign key violations
        self._check_foreign_keys()

        # Orphaned records
        self._check_orphans()

        # Data consistency
        self._check_data_consistency()

        if self.issues:
            for issue in self.issues:
                logger.warning("integrity_issue", **issue)
            return False

        logger.info("integrity_check_passed")
        return True

    def _check_sqlite_integrity(self) -> None:
        """Run SQLite's PRAGMA integrity_check."""
        cursor = self.conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        if not result:
            return

        result_str = result[0]
        if result_str != "ok":
            self.issues.append({"type": "sqlite_integrity", "message": result_str})

    def _check_foreign_keys(self) -> None:
        """Check for foreign key violations."""
        cursor = self.conn.execute("PRAGMA foreign_key_check")
        violations = cursor.fetchall()

        for violation in violations:
            self.issues.append(
                {
                    "type": "foreign_key_violation",
                    "table": violation[0],
                    "rowid": violation[1],
                    "parent": violation[2],
                    "fkid": violation[3],
                }
            )

    def _check_orphans(self) -> None:
        """Check for orphaned records."""
        # Messages without spaces
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM messages m
            WHERE NOT EXISTS (
                SELECT 1 FROM spaces s WHERE s.id = m.space_id
            )
        """
        )
        result = cursor.fetchone()
        orphan_messages = result[0] if result else 0
        if orphan_messages > 0:
            self.issues.append({"type": "orphaned_messages", "count": orphan_messages})

        # Reactions without messages
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM reactions r
            WHERE NOT EXISTS (
                SELECT 1 FROM messages m WHERE m.id = r.message_id
            )
        """
        )
        result = cursor.fetchone()
        orphan_reactions = result[0] if result else 0
        if orphan_reactions > 0:
            self.issues.append({"type": "orphaned_reactions", "count": orphan_reactions})

        # Attachments without messages
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM attachments a
            WHERE NOT EXISTS (
                SELECT 1 FROM messages m WHERE m.id = a.message_id
            )
        """
        )
        result = cursor.fetchone()
        orphan_attachments = result[0] if result else 0
        if orphan_attachments > 0:
            self.issues.append({"type": "orphaned_attachments", "count": orphan_attachments})

    def _check_data_consistency(self) -> None:
        """Check data consistency rules."""
        # Spaces with invalid sync_status
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM spaces
            WHERE sync_status NOT IN ('active', 'access_denied', 'paused')
        """
        )
        result = cursor.fetchone()
        invalid_status = result[0] if result else 0
        if invalid_status > 0:
            self.issues.append({"type": "invalid_sync_status", "count": invalid_status})

        # Messages with future timestamps (comparing ISO timestamps)
        # Use strftime to compare, and add a 1-minute tolerance for clock skew
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE create_time > datetime('now', '+1 minute')
        """
        )
        result = cursor.fetchone()
        future_messages = result[0] if result else 0
        if future_messages > 0:
            self.issues.append({"type": "future_timestamps", "count": future_messages})
