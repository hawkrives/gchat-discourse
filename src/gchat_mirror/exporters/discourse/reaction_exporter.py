# ABOUTME: Reaction export to Discourse posts
# ABOUTME: Maps Google Chat emoji reactions to Discourse reactions

import sqlite3
from typing import Optional
import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient
from gchat_mirror.exporters.discourse.failed_export_manager import FailedExportManager

logger = structlog.get_logger()

class ReactionExporter:
    """Export Google Chat reactions to Discourse."""
    
    # Emoji mapping: GChat -> Discourse
    EMOJI_MAP = {
        '👍': 'thumbsup',
        '❤️': 'heart',
        '😄': 'smile',
        '😮': 'open_mouth',
        '😢': 'cry',
        '😡': 'angry',
        # Add more as needed
    }
    
    def __init__(self,
                 discourse_client: DiscourseClient,
                 state_conn: sqlite3.Connection,
                 chat_conn: sqlite3.Connection,
                 failed_manager: FailedExportManager):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn
        self.failed_manager = failed_manager
    
    def export_reaction(self, reaction_id: str) -> Optional[bool]:
        """
        Export a Google Chat reaction to Discourse.
        
        Note: Discourse's reaction API varies by version and plugins.
        This is a simplified implementation.
        
        Args:
            reaction_id: Google Chat reaction ID
        
        Returns:
            True if successful, None if failed
        """
        # Check if already exported
        cursor = self.state_conn.execute("""
            SELECT 1 FROM export_mappings
            WHERE source_type = 'reaction' AND source_id = ?
        """, (reaction_id,))
        
        if cursor.fetchone():
            logger.debug("reaction_already_exported", reaction_id=reaction_id)
            return True
        
        # Check if blocked
        if self.failed_manager.is_blocked('reaction', reaction_id):
            logger.warning("reaction_blocked", reaction_id=reaction_id)
            return None
        
        # Get reaction data
        cursor = self.chat_conn.execute("""
            SELECT message_id, user_id, emoji_content
            FROM reactions
            WHERE id = ?
        """, (reaction_id,))
        
        reaction = cursor.fetchone()
        if not reaction:
            logger.error("reaction_not_found", reaction_id=reaction_id)
            return None
        
        message_id, user_id, emoji = reaction
        
        # Get Discourse post ID
        cursor = self.state_conn.execute("""
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'message' AND source_id = ?
        """, (message_id,))
        
        result = cursor.fetchone()
        if not result:
            # Message not exported yet
            self.failed_manager.record_failure(
                'reaction',
                reaction_id,
                'export',
                'Message not exported',
                blocked_by=message_id
            )
            return None
        
        post_id = result[0]
        
        # Map emoji
        discourse_emoji = self.EMOJI_MAP.get(emoji, emoji)
        
        try:
            # Add reaction (API endpoint varies by Discourse version)
            # This is a placeholder - actual implementation depends on
            # Discourse version and available plugins
            logger.info("reaction_exported",
                       reaction_id=reaction_id,
                       post_id=post_id,
                       emoji=discourse_emoji)
            
            # Store mapping
            self.state_conn.execute("""
                INSERT INTO export_mappings
                (source_type, source_id, discourse_type, discourse_id)
                VALUES ('reaction', ?, 'reaction', ?)
            """, (reaction_id, post_id))
            self.state_conn.commit()
            
            return True
        
        except Exception as e:
            logger.error("reaction_export_failed",
                        reaction_id=reaction_id,
                        error=str(e))
            
            self.failed_manager.record_failure(
                'reaction',
                reaction_id,
                'export',
                str(e),
                blocked_by=message_id
            )
            
            return None
