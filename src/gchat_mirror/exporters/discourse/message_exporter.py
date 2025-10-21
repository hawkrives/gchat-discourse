# ABOUTME: Export Google Chat messages to Discourse posts
# ABOUTME: Basic message export with markdown conversion and attachment handling

from __future__ import annotations

import sqlite3
from typing import Any, Optional

import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.markdown_converter import MarkdownConverter
from gchat_mirror.exporters.discourse.thread_exporter import ThreadExporter

logger = structlog.get_logger()


class MessageExporter:
    """Export Google Chat messages to Discourse posts.
    
    This is a basic implementation for Phase 4.5. Advanced features like
    edit history, reactions, and parallel processing will be added in Phase 4.7.
    """
    
    def __init__(
        self,
        discourse_client: DiscourseClient,
        state_conn: sqlite3.Connection,
        chat_conn: sqlite3.Connection,
        markdown_converter: MarkdownConverter,
        thread_exporter: ThreadExporter
    ):
        """Initialize the message exporter.
        
        Args:
            discourse_client: Discourse API client
            state_conn: Connection to state database
            chat_conn: Connection to chat database
            markdown_converter: Markdown conversion service
            thread_exporter: Thread export service
        """
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.markdown = markdown_converter
        self.thread_exporter = thread_exporter
    
    def export_message(self, message_id: str) -> Optional[dict[str, Any]]:
        """Export a Google Chat message to Discourse.
        
        Args:
            message_id: Google Chat message ID
        
        Returns:
            Mapping data with discourse_id, or None if export fails
        """
        # Check if already exported
        cursor = self.state_conn.execute("""
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'message' AND source_id = ?
        """, (message_id,))
        
        result = cursor.fetchone()
        if result:
            logger.debug("message_already_exported", message_id=message_id)
            return {'discourse_id': result[0]}
        
        # Get message data
        cursor = self.chat_conn.execute("""
            SELECT 
                thread_id,
                space_id,
                sender_id,
                text,
                create_time,
                deleted
            FROM messages
            WHERE id = ?
        """, (message_id,))
        
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
            logger.error("thread_export_failed",
                        message_id=message_id,
                        thread_id=thread_id)
            return None
        
        # Get attachments
        cursor = self.chat_conn.execute("""
            SELECT id, name, mime_type
            FROM attachments
            WHERE message_id = ?
        """, (message_id,))
        
        attachments = [
            {'id': row[0], 'name': row[1], 'mime_type': row[2]}
            for row in cursor.fetchall()
        ]
        
        # Convert message to markdown
        markdown_text = self.markdown.convert_message(
            text or "",
            message_id,
            attachments
        )
        
        # Export based on thread mapping type
        try:
            if thread_mapping['discourse_type'] in ['topic', 'private_message']:
                # Create a reply post in the topic/PM
                post_id = self._create_post(
                    thread_mapping['discourse_id'],
                    markdown_text
                )
            else:
                # Chat channels or other types not yet supported in basic version
                logger.warning("unsupported_thread_type",
                             message_id=message_id,
                             thread_type=thread_mapping['discourse_type'])
                return None
            
            if not post_id:
                return None
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('message', ?, 'post', ?)
            """, (message_id, str(post_id)))
            self.state_conn.commit()
            
            logger.info("message_exported",
                       message_id=message_id,
                       post_id=post_id)
            
            return {'discourse_id': post_id}
        
        except Exception as e:
            logger.error("message_export_failed",
                        message_id=message_id,
                        error=str(e))
            raise
    
    def _create_post(self, topic_id: int, markdown_text: str) -> int:
        """Create a post in a Discourse topic.
        
        Args:
            topic_id: Discourse topic ID
            markdown_text: Post content in markdown
        
        Returns:
            Discourse post ID
        """
        result = self.discourse.create_post(
            topic_id=topic_id,
            raw=markdown_text
        )
        return result['id']
