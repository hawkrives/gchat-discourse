# ABOUTME: Space mapping for different Discourse export modes
# ABOUTME: Handles chat/private_messages/hybrid mapping strategies

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Literal, Optional

import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient

logger = structlog.get_logger()

MappingMode = Literal["chat", "private_messages", "hybrid"]


class SpaceMapper:
    """Map Google Chat spaces to Discourse structures."""

    def __init__(
        self,
        discourse_client: DiscourseClient,
        state_conn: sqlite3.Connection,
        chat_conn: sqlite3.Connection,
        mapping_mode: MappingMode,
    ):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.mapping_mode = mapping_mode

    def get_or_create_space_mapping(self, space_id: str) -> Optional[Dict[str, Any]]:
        """
        Get or create Discourse mapping for a Google Chat space.

        Returns dict with:
        - type: 'chat_channel', 'category', or 'private_message'
        - id: Discourse entity ID
        - name: Discourse entity name (optional)
        - participants: List of user IDs (for private_message only)
        """
        # Check existing mapping
        cursor = self.state_conn.execute(
            """
            SELECT discourse_type, discourse_id FROM export_mappings
            WHERE source_type = 'space' AND source_id = ?
        """,
            (space_id,),
        )

        result = cursor.fetchone()
        if result:
            discourse_type, discourse_id = result
            mapping: Dict[str, Any] = {
                "type": discourse_type,
                "id": int(discourse_id) if discourse_id.isdigit() else 0,
            }

            # If it's a private_message, parse participants from discourse_id
            if discourse_type == "private_message":
                mapping["participants"] = discourse_id.split(",")

            return mapping

        # Get space data
        cursor = self.chat_conn.execute(
            """
            SELECT display_name, space_type, threaded 
            FROM spaces WHERE id = ?
        """,
            (space_id,),
        )

        space = cursor.fetchone()
        if not space:
            logger.error("space_not_found", space_id=space_id)
            return None

        display_name, space_type, threaded = space

        # Determine mapping based on mode and space type
        is_dm = space_type == "DM"

        if self.mapping_mode == "chat":
            # All spaces become chat channels
            return self._create_chat_channel(space_id, display_name)

        elif self.mapping_mode == "private_messages":
            if is_dm:
                # DMs become private messages
                return self._setup_private_message(space_id)
            else:
                # Regular spaces become categories
                return self._create_category(space_id, display_name)

        else:  # hybrid
            if is_dm:
                # DMs become private messages
                return self._setup_private_message(space_id)
            else:
                # Regular spaces become chat channels
                return self._create_chat_channel(space_id, display_name)

    def _create_chat_channel(self, space_id: str, display_name: str) -> Dict[str, Any]:
        """Create a Discourse chat channel."""
        try:
            channel = self.discourse.create_chat_channel(
                name=display_name, description=f"Mirrored from Google Chat space {space_id}"
            )

            # Store mapping
            self.state_conn.execute(
                """
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('space', ?, 'chat_channel', ?)
            """,
                (space_id, str(channel["id"])),
            )
            self.state_conn.commit()

            logger.info("chat_channel_created", space_id=space_id, channel_id=channel["id"])

            return {"type": "chat_channel", "id": channel["id"], "name": display_name}

        except Exception as e:
            logger.error("chat_channel_creation_failed", space_id=space_id, error=str(e))
            raise

    def _create_category(self, space_id: str, display_name: str) -> Dict[str, Any]:
        """Create a Discourse category."""
        try:
            category = self.discourse.create_category(name=display_name, color="0088CC")

            # Store mapping
            self.state_conn.execute(
                """
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('space', ?, 'category', ?)
            """,
                (space_id, str(category["id"])),
            )
            self.state_conn.commit()

            logger.info("category_created", space_id=space_id, category_id=category["id"])

            return {"type": "category", "id": category["id"], "name": display_name}

        except Exception as e:
            logger.error("category_creation_failed", space_id=space_id, error=str(e))
            raise

    def _setup_private_message(self, space_id: str) -> Dict[str, Any]:
        """
        Set up private message mapping for a DM space.

        For DMs, we don't create anything upfront - the mapping
        just indicates that threads in this space should become PMs.
        """
        # Get participants
        cursor = self.chat_conn.execute(
            """
            SELECT user_id FROM memberships WHERE space_id = ?
        """,
            (space_id,),
        )

        participants = [row[0] for row in cursor.fetchall()]

        # Store mapping with participant list
        self.state_conn.execute(
            """
            INSERT INTO export_mappings
            (source_type, source_id, discourse_type, discourse_id)
            VALUES ('space', ?, 'private_message', ?)
        """,
            (space_id, ",".join(participants)),
        )
        self.state_conn.commit()

        logger.info("private_message_setup", space_id=space_id, participants=len(participants))

        return {
            "type": "private_message",
            "id": 0,  # No Discourse ID yet
            "participants": participants,
        }
