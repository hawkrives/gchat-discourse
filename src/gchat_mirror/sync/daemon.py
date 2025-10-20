# ABOUTME: Main sync daemon coordinating Google Chat polling
# ABOUTME: Orchestrates authentication, API calls, and database storage

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from gchat_mirror.common.database import Database
from gchat_mirror.common.migrations import run_migrations
from gchat_mirror.sync.auth import authenticate
from gchat_mirror.sync.google_client import GoogleChatClient
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

        self.running = True
        self.initial_sync()
        logger.info("sync_daemon_started")

    def stop(self) -> None:
        """Stop the sync daemon."""
        logger.info("sync_daemon_stopping")
        self.running = False

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
        """Sync a single space."""
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

        while True:
            response = self.client.list_messages(space_id, page_token=page_token)
            messages = response.get("messages", [])

            for message in messages:
                self._process_message(message)
                message_count += 1

            next_token = response.get("nextPageToken")
            if not next_token:
                break

            self.storage.update_space_sync_cursor(space_id, next_token)
            page_token = next_token

        logger.info("space_sync_complete", space_id=space_id, messages=message_count)

    def _process_message(self, message: Dict[str, Any]) -> None:
        """Process a single message payload."""
        if self.storage is None:
            raise RuntimeError("Storage not initialised")

        sender = message.get("sender")
        if sender:
            self.storage.upsert_user(sender)

        self.storage.insert_message(message)
        logger.debug("message_processed", message_id=message.get("name"))
