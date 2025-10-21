# ABOUTME: Export Google Chat messages to Discourse posts with full fidelity
# ABOUTME: Handles attachments, edit history, dependencies, and batch processing

from __future__ import annotations

import sqlite3
from typing import Any, Optional

import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.markdown_converter import MarkdownConverter
from gchat_mirror.exporters.discourse.thread_exporter import ThreadExporter
from gchat_mirror.exporters.discourse.attachment_cache import AttachmentCache
from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager

logger = structlog.get_logger()


class MessageExporter:
    """Export Google Chat messages to Discourse posts.

    Enhanced implementation with attachment caching, edit history,
    dependency blocking, and sequential batch processing.
    """

    def __init__(
        self,
        discourse_client: DiscourseClient,
        state_conn: sqlite3.Connection,
        chat_conn: sqlite3.Connection,
        markdown_converter: MarkdownConverter,
        attachment_cache: AttachmentCache,
        thread_exporter: ThreadExporter,
        failed_manager: FailedExportManager,
    ):
        """Initialize the message exporter.

        Args:
            discourse_client: Discourse API client
            state_conn: Connection to state database
            chat_conn: Connection to chat database
            markdown_converter: Markdown conversion service
            attachment_cache: Attachment URL cache
            thread_exporter: Thread export service
            failed_manager: Failed export tracking
        """
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.markdown = markdown_converter
        self.attachment_cache = attachment_cache
        self.thread_exporter = thread_exporter
        self.failed_manager = failed_manager

    def export_message(self, message_id: str) -> Optional[dict[str, Any]]:
        """Export a Google Chat message to Discourse.

        Args:
            message_id: Google Chat message ID

        Returns:
            Mapping data with discourse_id, or None if export fails
        """
        # Check if blocked by failed dependency
        if self.failed_manager.is_blocked("message", message_id):
            logger.debug("message_export_blocked", message_id=message_id)
            return None

        # Check if already exported
        cursor = self.state_conn.execute(
            """
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'message' AND source_id = ?
        """,
            (message_id,),
        )

        result = cursor.fetchone()
        if result:
            logger.debug("message_already_exported", message_id=message_id)
            return {"discourse_id": result[0]}

        # Get message data
        cursor = self.chat_conn.execute(
            """
            SELECT 
                thread_id,
                space_id,
                sender_id,
                text,
                create_time,
                deleted
            FROM messages
            WHERE id = ?
        """,
            (message_id,),
        )

        msg = cursor.fetchone()
        if not msg:
            logger.error("message_not_found", message_id=message_id)
            return None

        thread_id, space_id, sender_id, text, create_time, deleted = msg

        # Skip deleted messages
        if deleted:
            logger.info("message_deleted_skipping", message_id=message_id)
            return None

        # Ensure thread is exported first
        thread_mapping = self.thread_exporter.export_thread(thread_id)
        if not thread_mapping:
            logger.error("thread_export_failed", message_id=message_id, thread_id=thread_id)
            # Record failure blocked by thread
            self.failed_manager.record_failure(
                "message", message_id, "export", "Thread export failed", blocked_by=thread_id
            )
            return None

        # Get attachments and upload to get URLs
        cursor = self.chat_conn.execute(
            """
            SELECT id, name, content_type
            FROM attachments
            WHERE message_id = ?
        """,
            (message_id,),
        )

        attachments = []
        for row in cursor.fetchall():
            att_id, name, content_type = row
            # Get or upload attachment to get Discourse URL
            url = self.attachment_cache.get_or_upload_attachment(att_id)
            attachments.append(
                {"id": att_id, "name": name, "content_type": content_type, "url": url}
            )

        # Convert message to markdown
        markdown_text = self.markdown.convert_message(text or "", message_id, attachments)

        # Export based on thread mapping type
        try:
            if thread_mapping["discourse_type"] in ["topic", "private_message"]:
                # Create a reply post in the topic/PM
                post_id = self._create_post(thread_mapping["discourse_id"], markdown_text)
            else:
                # Chat channels or other types not yet supported
                logger.warning(
                    "unsupported_thread_type",
                    message_id=message_id,
                    thread_type=thread_mapping["discourse_type"],
                )
                return None

            if not post_id:
                return None

            # Store mapping
            self.state_conn.execute(
                """
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('message', ?, 'post', ?)
            """,
                (message_id, str(post_id)),
            )
            self.state_conn.commit()

            # Export edit history if exists
            self._export_edits(message_id, post_id)

            logger.info("message_exported", message_id=message_id, post_id=post_id)

            return {"discourse_id": post_id}

        except Exception as e:
            logger.error("message_export_failed", message_id=message_id, error=str(e))
            raise

    def _create_post(self, topic_id: int, markdown_text: str) -> int:
        """Create a post in a Discourse topic.

        Args:
            topic_id: Discourse topic ID
            markdown_text: Post content in markdown

        Returns:
            Discourse post ID
        """
        result = self.discourse.create_post(topic_id=topic_id, raw=markdown_text)
        return result["id"]

    def _export_edits(self, message_id: str, post_id: int) -> None:
        """Export edit history for a message.

        Args:
            message_id: Google Chat message ID
            post_id: Discourse post ID
        """
        # Get revisions ordered by time
        cursor = self.chat_conn.execute(
            """
            SELECT revision_id, text, update_time
            FROM message_revisions
            WHERE message_id = ?
            ORDER BY update_time ASC
        """,
            (message_id,),
        )

        revisions = cursor.fetchall()
        if not revisions:
            return

        # Get attachments for markdown conversion
        cursor = self.chat_conn.execute(
            """
            SELECT id, name, content_type
            FROM attachments
            WHERE message_id = ?
        """,
            (message_id,),
        )

        attachments = []
        for row in cursor.fetchall():
            att_id, name, content_type = row
            url = self.attachment_cache.get_or_upload_attachment(att_id)
            attachments.append(
                {"id": att_id, "name": name, "content_type": content_type, "url": url}
            )

        # Apply each revision as an edit
        for revision_id, text, update_time in revisions:
            markdown_text = self.markdown.convert_message(text or "", message_id, attachments)

            try:
                self.discourse.update_post(post_id, markdown_text)
                logger.debug(
                    "revision_exported",
                    message_id=message_id,
                    revision_id=revision_id,
                    post_id=post_id,
                )
            except Exception as e:
                logger.warning(
                    "revision_export_failed",
                    message_id=message_id,
                    revision_id=revision_id,
                    error=str(e),
                )

    def export_messages_batch(
        self, message_ids: list[str], max_workers: int = 4
    ) -> list[dict[str, Any]]:
        """Export multiple messages sequentially.

        Note: Processes messages one at a time due to SQLite's single-writer
        limitation. The max_workers parameter is ignored but kept for API
        compatibility.

        Args:
            message_ids: List of message IDs to export
            max_workers: Ignored (kept for API compatibility)

        Returns:
            List of results with 'success' and 'result' or 'error' keys
        """
        results = []

        for msg_id in message_ids:
            try:
                result = self.export_message(msg_id)
                results.append(
                    {"message_id": msg_id, "success": result is not None, "result": result}
                )
            except Exception as e:
                logger.error("batch_export_error", message_id=msg_id, error=str(e))
                results.append({"message_id": msg_id, "success": False, "error": str(e)})

        return results
