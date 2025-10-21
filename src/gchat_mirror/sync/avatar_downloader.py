# ABOUTME: Avatar download management with history tracking
# ABOUTME: Handles downloading user avatars and tracking URL changes

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from typing import Any

import httpx  # type: ignore
import structlog  # type: ignore

from gchat_mirror.sync.attachment_storage import AttachmentStorage

logger = structlog.get_logger()


class AvatarDownloader:
    """Download and track user avatars."""

    def __init__(self, storage: AttachmentStorage, chat_conn: sqlite3.Connection) -> None:
        self.storage = storage
        self.chat_conn = chat_conn

    def update_user_avatar(self, user_id: str, avatar_url: str | None) -> None:
        """
        Update user's avatar URL, creating history entry if changed.

        Args:
            user_id: User ID
            avatar_url: New avatar URL (or None if no avatar)
        """
        if not avatar_url:
            return

        # Check if this URL is already current
        cursor = self.chat_conn.execute(
            """
            SELECT id FROM user_avatars 
            WHERE user_id = ? AND avatar_url = ? AND is_current = TRUE
            """,
            (user_id, avatar_url),
        )

        if cursor.fetchone():
            # URL unchanged, just update last_seen
            self.chat_conn.execute(
                """
                UPDATE user_avatars 
                SET last_seen = CURRENT_TIMESTAMP
                WHERE user_id = ? AND avatar_url = ? AND is_current = TRUE
                """,
                (user_id, avatar_url),
            )
            self.chat_conn.commit()
            return

        # Mark old avatars as not current
        self.chat_conn.execute(
            """
            UPDATE user_avatars 
            SET is_current = FALSE
            WHERE user_id = ? AND is_current = TRUE
            """,
            (user_id,),
        )

        # Insert new avatar record
        self.chat_conn.execute(
            """
            INSERT INTO user_avatars 
            (user_id, avatar_url, is_current)
            VALUES (?, ?, TRUE)
            """,
            (user_id, avatar_url),
        )

        self.chat_conn.commit()

        logger.info("avatar_updated", user_id=user_id, url=avatar_url)

    async def download_pending_avatars(self, batch_size: int = 50) -> None:
        """Download pending avatars."""
        pending = self._get_pending_avatars(batch_size)

        if not pending:
            logger.info("no_pending_avatars")
            return

        logger.info("downloading_avatars", count=len(pending))

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as session:
            tasks = [self._download_avatar(session, avatar) for avatar in pending]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            success = sum(1 for r in results if r is True)
            failed = sum(1 for r in results if r is not True)

            logger.info("avatar_download_complete", success=success, failed=failed)

    def _get_pending_avatars(self, limit: int) -> list[dict[str, Any]]:
        """Get pending avatar downloads."""
        cursor = self.chat_conn.execute(
            """
            SELECT id, user_id, avatar_url, download_attempts
            FROM user_avatars
            WHERE downloaded = FALSE
              AND download_attempts < 5
              AND is_current = TRUE
            ORDER BY first_seen DESC
            LIMIT ?
            """,
            (limit,),
        )

        return [dict(row) for row in cursor.fetchall()]

    async def _download_avatar(self, session: httpx.AsyncClient, avatar: dict[str, Any]) -> bool:
        """Download a single avatar."""
        try:
            response = await session.get(avatar["avatar_url"])

            if response.status_code != 200:
                logger.error(
                    "avatar_download_failed",
                    status=response.status_code,
                    user_id=avatar["user_id"],
                )
                self._mark_download_failed(avatar["id"], f"HTTP {response.status_code}")
                return False

            data = response.content
            content_type = response.headers.get("Content-Type", "image/jpeg")
            sha256 = hashlib.sha256(data).hexdigest()

            # Store in attachments.db using inline storage
            # (avatars are typically small)
            storage_id = f"avatar_{avatar['user_id']}_{avatar['id']}"

            self.storage.attachments_conn.execute(
                """
                INSERT INTO attachment_inline (attachment_id, data)
                VALUES (?, ?)
                """,
                (storage_id, data),
            )

            # Update avatar record
            self.chat_conn.execute(
                """
                UPDATE user_avatars
                SET downloaded = TRUE,
                    download_time = CURRENT_TIMESTAMP,
                    storage_id = ?,
                    content_type = ?,
                    size_bytes = ?,
                    sha256_hash = ?
                WHERE id = ?
                """,
                (storage_id, content_type, len(data), sha256, avatar["id"]),
            )

            self.storage.attachments_conn.commit()
            self.chat_conn.commit()

            logger.info(
                "avatar_downloaded",
                user_id=avatar["user_id"],
                size_kb=len(data) / 1024,
            )

            return True

        except Exception as e:
            logger.error("avatar_download_error", user_id=avatar["user_id"], error=str(e))
            self._mark_download_failed(avatar["id"], str(e))
            return False

    def _mark_download_failed(self, avatar_id: int, error: str) -> None:
        """Mark avatar download as failed."""
        self.chat_conn.execute(
            """
            UPDATE user_avatars
            SET download_error = ?,
                download_attempts = download_attempts + 1
            WHERE id = ?
            """,
            (error, avatar_id),
        )
        self.chat_conn.commit()
