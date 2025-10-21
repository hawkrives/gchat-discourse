# ABOUTME: Main sync daemon coordinating Google Chat polling
# ABOUTME: Orchestrates authentication, API calls, and database storage

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import structlog

from gchat_mirror.common.database import Database
from gchat_mirror.common.migrations import run_migrations
from gchat_mirror.sync.activity_tracker import ActivityTracker
from gchat_mirror.sync.auth import authenticate
from gchat_mirror.sync.google_client import GoogleChatClient
from gchat_mirror.sync.health_server import HealthCheckServer
from gchat_mirror.sync.storage import SyncStorage

logger = structlog.get_logger()


class SyncDaemon:
    """Main sync daemon for Google Chat."""

    def __init__(self, data_dir: Path, config: Dict[str, Any]):
        self.data_dir = Path(data_dir)
        self.config = config
        self.chat_db = Database(self.data_dir / "sync" / "chat.db")
        self.running = False
        self.client: Optional[GoogleChatClient] = None
        self.storage: Optional[SyncStorage] = None
        self.activity_tracker: Optional[ActivityTracker] = None
        self.health_server: Optional[HealthCheckServer] = None

    def start(self) -> None:
        """Start the sync daemon."""
        logger.info("sync_daemon_starting")

        db_path = self.chat_db.db_path
        migrations_dir = Path(__file__).resolve().parents[3] / "migrations"
        run_migrations(db_path, migrations_dir)

        self.chat_db.connect()

        if not self.chat_db.integrity_check():
            self.chat_db.close()
            raise RuntimeError("Database integrity check failed")

        credential_key = (
            self.config.get("credential_key")
            or self.config.get("auth", {}).get("credential_key")
            or "gchat-sync"
        )
        creds = authenticate(credential_key)

        self.client = GoogleChatClient(creds)
        if self.chat_db.conn is None:
            raise RuntimeError("Database connection missing after connect")
        self.storage = SyncStorage(self.chat_db.conn)
        self.activity_tracker = ActivityTracker(self.chat_db.conn, self.config)

        # Start health check server
        port = self.config.get("monitoring", {}).get("health_check_port", 4981)
        self.health_server = HealthCheckServer(self, port)
        self.health_server.start()

        self.running = True
        self.initial_sync()
        logger.info("sync_daemon_started")

    def stop(self) -> None:
        """Stop the sync daemon."""
        logger.info("sync_daemon_stopping")
        self.running = False

        if self.health_server is not None:
            self.health_server.stop()

        if self.client is not None:
            self.client.close()

        self.chat_db.close()
        logger.info("sync_daemon_stopped")

    def initial_sync(self) -> None:
        """Run initial sync for all spaces."""
        if self.client is None or self.storage is None:
            raise RuntimeError("Sync daemon must be started before initial_sync")

        spaces = self.client.list_spaces()
        logger.info("initial_sync_spaces", count=len(spaces))

        for space in spaces:
            self.sync_space(space)

    def sync_space(self, space: Dict[str, Any]) -> None:
        """Sync a single space with error handling."""
        if self.client is None or self.storage is None:
            raise RuntimeError("Sync daemon must be started before syncing spaces")

        space_id = space.get("name")
        if not space_id:
            logger.warning("space_missing_id", space=space)
            return

        logger.info("space_sync_start", space_id=space_id)
        self.storage.upsert_space(space)

        page_token = self.storage.get_space_sync_cursor(space_id)
        message_count = 0

        try:
            while True:
                try:
                    response = self.client.list_messages(space_id, page_token=page_token)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 403:
                        # Access denied - mark space
                        self._mark_space_access_denied(space_id, "Access denied by Google Chat API")
                        logger.warning("space_access_denied", space_id=space_id)
                        return
                    elif e.response.status_code == 404:
                        # Space not found - might be deleted
                        self._mark_space_access_denied(
                            space_id, "Space not found (possibly deleted)"
                        )
                        logger.warning("space_not_found", space_id=space_id)
                        return
                    else:
                        # Other HTTP error - re-raise for retry logic
                        raise

                messages = response.get("messages", [])

                for message in messages:
                    self._process_message(message)
                    message_count += 1

                next_token = response.get("nextPageToken")
                if not next_token:
                    break

                self.storage.update_space_sync_cursor(space_id, next_token)
                page_token = next_token

            # Update sync timestamp and last message time
            if self.chat_db.conn is not None:
                self.chat_db.conn.execute(
                    """
                    UPDATE spaces
                    SET last_synced_at = CURRENT_TIMESTAMP,
                        last_message_time = (
                            SELECT MAX(create_time) FROM messages 
                            WHERE space_id = ?
                        )
                    WHERE id = ?
                    """,
                    (space_id, space_id),
                )
                self.chat_db.conn.commit()

            logger.info("space_sync_complete", space_id=space_id, messages=message_count)

        except Exception as e:
            logger.error("space_sync_error", space_id=space_id, error=str(e), exc_info=True)
            # Don't mark as access_denied for other errors
            raise

    def _process_message(self, message: Dict[str, Any]) -> None:
        """Process a single message payload."""
        if self.storage is None:
            raise RuntimeError("Storage not initialised")

        sender = message.get("sender")
        if sender:
            self.storage.upsert_user(sender)

        self.storage.insert_message(message)
        logger.debug("message_processed", message_id=message.get("name"))

    def _mark_space_access_denied(self, space_id: str, reason: str) -> None:
        """Mark a space as access denied."""
        if self.chat_db.conn is None:
            raise RuntimeError("Database connection missing")

        self.chat_db.conn.execute(
            """
            UPDATE spaces
            SET sync_status = 'access_denied',
                access_denied_at = CURRENT_TIMESTAMP,
                access_denied_reason = ?
            WHERE id = ?
            """,
            (reason, space_id),
        )
        self.chat_db.conn.commit()

    def discover_spaces(self) -> list[Dict[str, Any]]:
        """Discover all accessible spaces from Google Chat."""
        if self.client is None or self.storage is None:
            raise RuntimeError("Sync daemon must be started before discovering spaces")

        try:
            spaces = self.client.list_spaces()
            logger.info("spaces_discovered", count=len(spaces))

            # Update database with discovered spaces
            for space in spaces:
                self.storage.upsert_space(space)

            return spaces

        except Exception as e:
            logger.error("space_discovery_error", error=str(e), exc_info=True)
            raise

    async def poll_loop(self) -> None:
        """
        Continuous polling loop with adaptive intervals.

        Uses asyncio to poll multiple spaces concurrently, improving
        throughput when syncing many active spaces.
        """
        if self.activity_tracker is None:
            raise RuntimeError("Activity tracker not initialized")

        logger.info("poll_loop_started")

        while self.running:
            try:
                # Get spaces that need polling
                spaces_to_poll = self.activity_tracker.get_spaces_to_poll()

                if spaces_to_poll:
                    logger.info("polling_spaces", count=len(spaces_to_poll))

                    # Poll spaces concurrently using asyncio
                    tasks = []
                    for space_id in spaces_to_poll:
                        if not self.running:
                            break
                        tasks.append(self.sync_space_async(space_id))

                    # Wait for all syncs to complete
                    await asyncio.gather(*tasks, return_exceptions=True)

                    # Update activity metrics for all spaces
                    for space_id in spaces_to_poll:
                        self.activity_tracker.update_space_activity(space_id)

                # Sleep briefly before checking again
                await asyncio.sleep(1)

            except KeyboardInterrupt:
                logger.info("interrupt_received")
                break
            except Exception as e:
                logger.error("poll_loop_error", error=str(e), exc_info=True)
                await asyncio.sleep(5)  # Back off on error

    async def sync_space_async(self, space_id: str) -> None:
        """
        Sync a single space asynchronously.

        Wraps the synchronous sync_space method to allow concurrent execution.
        """
        if self.chat_db.conn is None:
            raise RuntimeError("Database connection missing")

        try:
            # Fetch space data
            cursor = self.chat_db.conn.execute(
                """
                SELECT * FROM spaces WHERE id = ?
                """,
                (space_id,),
            )
            row = cursor.fetchone()
            if not row:
                logger.warning("space_not_found_in_db", space_id=space_id)
                return

            # Convert row to dict
            space = dict(row)

            # Sync the space (run in executor to avoid blocking)
            await asyncio.get_event_loop().run_in_executor(None, self.sync_space, space)
        except Exception as e:
            logger.error("sync_space_async_error", space_id=space_id, error=str(e))

    def get_space_count(self) -> int:
        """Get the total number of spaces being tracked."""
        if self.chat_db.conn is None:
            return 0

        cursor = self.chat_db.conn.execute("SELECT COUNT(*) FROM spaces")
        result = cursor.fetchone()
        return result[0] if result else 0

    def get_message_count(self) -> int:
        """Get the total number of messages stored."""
        if self.chat_db.conn is None:
            return 0

        cursor = self.chat_db.conn.execute("SELECT COUNT(*) FROM messages")
        result = cursor.fetchone()
        return result[0] if result else 0

    def get_last_sync_time(self) -> str:
        """Get the timestamp of the most recent sync, or 'never'."""
        if self.chat_db.conn is None:
            return "never"

        cursor = self.chat_db.conn.execute(
            "SELECT MAX(last_synced_at) FROM spaces WHERE last_synced_at IS NOT NULL"
        )
        result = cursor.fetchone()
        return result[0] if result and result[0] else "never"
