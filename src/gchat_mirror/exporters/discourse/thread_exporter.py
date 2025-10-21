# ABOUTME: Export Google Chat threads to Discourse topics or private messages
# ABOUTME: Creates topics/PMs with generated titles from first messages

from __future__ import annotations

import sqlite3
from typing import Any, Optional

import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.space_mapper import SpaceMapper
from gchat_mirror.exporters.discourse.thread_title import ThreadTitleGenerator
from gchat_mirror.exporters.discourse.user_mapper import UserMapper

logger = structlog.get_logger()


class ThreadExporter:
    """Export Google Chat threads to Discourse topics or private messages."""

    def __init__(
        self,
        discourse_client: DiscourseClient,
        state_conn: sqlite3.Connection,
        chat_conn: sqlite3.Connection,
        user_mapper: UserMapper,
        space_mapper: SpaceMapper,
    ):
        """Initialize the thread exporter.

        Args:
            discourse_client: Discourse API client
            state_conn: Connection to state database
            chat_conn: Connection to chat database
            user_mapper: User mapping service
            space_mapper: Space mapping service
        """
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.user_mapper = user_mapper
        self.space_mapper = space_mapper
        self.title_generator = ThreadTitleGenerator()

    def export_thread(self, thread_id: str) -> Optional[dict[str, Any]]:
        """Export a Google Chat thread to Discourse.

        Args:
            thread_id: Google Chat thread ID

        Returns:
            Mapping data with discourse_type and discourse_id,
            or None if export fails
        """
        # Check if already exported
        cursor = self.state_conn.execute(
            """
            SELECT discourse_type, discourse_id FROM export_mappings
            WHERE source_type = 'thread' AND source_id = ?
        """,
            (thread_id,),
        )

        result = cursor.fetchone()
        if result:
            logger.debug("thread_already_exported", thread_id=thread_id)
            return {"discourse_type": result[0], "discourse_id": result[1]}

        # Get thread data
        cursor = self.chat_conn.execute(
            """
            SELECT space_id, reply_count
            FROM threads
            WHERE id = ?
        """,
            (thread_id,),
        )

        thread = cursor.fetchone()
        if not thread:
            logger.error("thread_not_found", thread_id=thread_id)
            return None

        space_id = thread[0]

        # Get space mapping
        space_mapping = self.space_mapper.get_or_create_space_mapping(space_id)
        if not space_mapping:
            logger.error("space_mapping_failed", space_id=space_id)
            return None

        # Get first message for title
        cursor = self.chat_conn.execute(
            """
            SELECT text FROM messages
            WHERE thread_id = ?
            ORDER BY create_time ASC
            LIMIT 1
        """,
            (thread_id,),
        )

        first_msg = cursor.fetchone()
        first_text = first_msg[0] if first_msg else None

        # Get space name
        cursor = self.chat_conn.execute(
            """
            SELECT display_name FROM spaces WHERE id = ?
        """,
            (space_id,),
        )
        space_name = cursor.fetchone()[0]

        # Generate title
        title = self.title_generator.generate_title(first_text, space_name, thread_id)

        # Export based on space mapping type
        if space_mapping["type"] == "chat_channel":
            # Discourse chat channels don't support threading
            # Messages will be exported as flat chat messages
            logger.warning(
                "thread_in_chat_channel", thread_id=thread_id, note="Will export as flat messages"
            )
            return {
                "discourse_type": "chat_thread",
                "discourse_id": 0,  # No actual thread object
            }

        elif space_mapping["type"] == "category":
            # Create topic in category
            return self._create_topic(thread_id, title, space_mapping["id"])

        elif space_mapping["type"] == "private_message":
            # Create private message thread
            return self._create_private_message(thread_id, title, space_mapping["participants"])

        else:
            logger.error("unknown_space_mapping_type", mapping_type=space_mapping["type"])
            return None

    def _create_topic(self, thread_id: str, title: str, category_id: int) -> dict[str, Any]:
        """Create a Discourse topic for a thread.

        Args:
            thread_id: Google Chat thread ID
            title: Topic title
            category_id: Discourse category ID

        Returns:
            Mapping data with discourse_type and discourse_id
        """
        try:
            # Create the topic with placeholder content
            # The actual first message will be updated by MessageExporter
            result = self.discourse.create_topic(
                title=title, raw="Loading messages...", category_id=category_id
            )

            # Store mapping
            self.state_conn.execute(
                """
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('thread', ?, 'topic', ?)
            """,
                (thread_id, str(result["topic_id"])),
            )
            self.state_conn.commit()

            logger.info("topic_created", thread_id=thread_id, topic_id=result["topic_id"])

            return {"discourse_type": "topic", "discourse_id": result["topic_id"]}

        except Exception as e:
            logger.error("topic_creation_failed", thread_id=thread_id, error=str(e))
            raise

    def _create_private_message(
        self, thread_id: str, title: str, participants: list[str]
    ) -> dict[str, Any]:
        """Create a Discourse private message for a thread.

        Args:
            thread_id: Google Chat thread ID
            title: PM title
            participants: List of Google Chat user IDs

        Returns:
            Mapping data with discourse_type and discourse_id
        """
        try:
            # Map participants to Discourse usernames
            usernames = []
            for user_id in participants:
                username = self.user_mapper.get_or_create_discourse_user(user_id)
                if username:
                    usernames.append(username)

            if not usernames:
                logger.error("no_valid_participants", thread_id=thread_id)
                raise ValueError("No valid participants for private message")

            # Create PM
            result = self.discourse.create_private_message(
                title=title, raw="Loading messages...", target_usernames=usernames
            )

            # Store mapping
            self.state_conn.execute(
                """
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('thread', ?, 'private_message', ?)
            """,
                (thread_id, str(result["topic_id"])),
            )
            self.state_conn.commit()

            logger.info("private_message_created", thread_id=thread_id, topic_id=result["topic_id"])

            return {"discourse_type": "private_message", "discourse_id": result["topic_id"]}

        except Exception as e:
            logger.error("private_message_creation_failed", thread_id=thread_id, error=str(e))
            raise
