# ABOUTME: Backfill manager for historical message retrieval
# ABOUTME: Handles fetching older messages beyond initial sync window

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import structlog
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from gchat_mirror.common.database import Database
from gchat_mirror.sync.auth import authenticate
from gchat_mirror.sync.google_client import GoogleChatClient
from gchat_mirror.sync.storage import SyncStorage

logger = structlog.get_logger()


class BackfillManager:
    """Manage backfilling historical messages."""

    def __init__(self, data_dir: Path, config: Dict[str, Any]):
        self.data_dir = Path(data_dir)
        self.config = config
        self.chat_db = Database(self.data_dir / "sync" / "chat.db")

    def backfill_all_spaces(self, days: int, batch_size: int = 100) -> None:
        """Backfill all active spaces."""
        self.chat_db.connect()

        if self.chat_db.conn is None:
            raise RuntimeError("Database connection failed")

        # Get all active spaces
        cursor = self.chat_db.conn.execute(
            """
            SELECT id, display_name 
            FROM spaces 
            WHERE sync_status = 'active'
            ORDER BY display_name
            """
        )
        spaces = cursor.fetchall()

        logger.info("backfill_starting", space_count=len(spaces), days=days)

        # Authenticate
        credential_key = (
            self.config.get("credential_key")
            or self.config.get("auth", {}).get("credential_key")
            or "gchat-sync"
        )
        creds = authenticate(credential_key)
        client = GoogleChatClient(creds)
        storage = SyncStorage(self.chat_db.conn)

        # Progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
        ) as progress:
            task = progress.add_task("Backfilling spaces...", total=len(spaces))

            for space_id, display_name in spaces:
                progress.update(task, description=f"Backfilling {display_name or space_id}")

                self._backfill_space_impl(client, storage, space_id, days, batch_size)

                progress.advance(task)

        client.close()
        self.chat_db.close()

        logger.info("backfill_complete")

    def backfill_space(self, space_id: str, days: int, batch_size: int = 100) -> None:
        """Backfill a single space."""
        self.chat_db.connect()

        if self.chat_db.conn is None:
            raise RuntimeError("Database connection failed")

        # Authenticate
        credential_key = (
            self.config.get("credential_key")
            or self.config.get("auth", {}).get("credential_key")
            or "gchat-sync"
        )
        creds = authenticate(credential_key)
        client = GoogleChatClient(creds)
        storage = SyncStorage(self.chat_db.conn)

        logger.info("backfill_space_starting", space_id=space_id, days=days)

        messages_fetched = self._backfill_space_impl(client, storage, space_id, days, batch_size)

        client.close()
        self.chat_db.close()

        logger.info("backfill_space_complete", space_id=space_id, messages=messages_fetched)

    def _backfill_space_impl(
        self,
        client: GoogleChatClient,
        storage: SyncStorage,
        space_id: str,
        days: int,
        batch_size: int,
    ) -> int:
        """Internal backfill implementation."""
        if self.chat_db.conn is None:
            raise RuntimeError("Database connection missing")

        # Calculate time window
        now = datetime.now(timezone.utc)
        end_time = now
        start_time = now - timedelta(days=days)

        # Get oldest message we have
        cursor = self.chat_db.conn.execute(
            """
            SELECT MIN(create_time) FROM messages WHERE space_id = ?
            """,
            (space_id,),
        )
        oldest = cursor.fetchone()[0]

        if oldest:
            # Only backfill before oldest message
            oldest_dt = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
            if oldest_dt <= start_time:
                logger.info("backfill_not_needed", space_id=space_id, oldest=oldest)
                return 0

            end_time = oldest_dt

        messages_fetched = 0
        page_token = None

        # Fetch messages in the time window
        while True:
            try:
                # Note: Google Chat API filter parameter may not be supported
                # If not, we'll fetch all messages and filter client-side
                response = client.list_messages(
                    space_id, page_token=page_token, page_size=batch_size
                )
            except Exception as e:
                logger.error("backfill_error", space_id=space_id, error=str(e))
                break

            messages = response.get("messages", [])
            if not messages:
                break

            for message in messages:
                # Check if we're past our start time
                create_time_str = message.get("createTime", "")
                if not create_time_str:
                    continue

                msg_time = datetime.fromisoformat(create_time_str.replace("Z", "+00:00"))

                # Skip messages newer than our end_time (already have them)
                if msg_time >= end_time:
                    continue

                # Stop if we've reached messages older than start_time
                if msg_time < start_time:
                    logger.info("backfill_reached_limit", space_id=space_id, start_time=start_time)
                    return messages_fetched

                # Process message (includes sender)
                sender = message.get("sender")
                if sender:
                    storage.upsert_user(sender)

                # Insert message (use insert not update for backfill)
                try:
                    storage.insert_message(message)
                    messages_fetched += 1
                except Exception:
                    # Message might already exist, skip
                    pass

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return messages_fetched
