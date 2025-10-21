# ABOUTME: Converts Google Chat markdown to Discourse markdown
# ABOUTME: Handles formatting, mentions, and attachment embedding

from __future__ import annotations

import re
import sqlite3
from typing import Any

from gchat_mirror.exporters.discourse.user_mapper import UserMapper


class MarkdownConverter:
    """Converts Google Chat messages to Discourse markdown format."""
    
    def __init__(
        self,
        chat_conn: sqlite3.Connection,
        user_mapper: UserMapper,
        attachment_url_cache: dict[str, str]
    ):
        """Initialize the markdown converter.
        
        Args:
            chat_conn: Connection to chat database
            user_mapper: User mapper for mention resolution
            attachment_url_cache: Map of attachment IDs to Discourse URLs
        """
        self.chat_conn = chat_conn
        self.user_mapper = user_mapper
        self.attachment_url_cache = attachment_url_cache
        
    def convert_message(
        self,
        text: str | None,
        message_id: str,
        attachments: list[dict[str, Any]]
    ) -> str:
        """Convert a Google Chat message to Discourse markdown.
        
        Args:
            text: Message text (may be None)
            message_id: Message ID for context
            attachments: List of attachment metadata
            
        Returns:
            Converted markdown text
        """
        if not text:
            text = ""
            
        # Convert underlines (Google Chat uses _text_, Discourse uses <u>text</u>)
        # Must be done before mentions to avoid breaking <users/...>
        text = self._convert_underlines(text)
        
        # Convert mentions
        text = self._convert_mentions(text)
        
        # Add attachments at the end
        if attachments:
            attachment_text = self._format_attachments(attachments)
            if attachment_text:
                if text:
                    text += "\n\n"
                text += attachment_text
                
        return text
    
    def _convert_underlines(self, text: str) -> str:
        """Convert Google Chat underlines to HTML.
        
        Google Chat uses _text_ for underline.
        Discourse doesn't have markdown underline, so use HTML <u> tags.
        We need to be careful not to convert italic markdown (__text__).
        """
        # Match single underscores with non-underscore characters inside
        # This avoids matching double underscores or asterisks
        pattern = r'(?<!_)_([^_]+?)_(?!_)'
        return re.sub(pattern, r'<u>\1</u>', text)
    
    def _convert_mentions(self, text: str) -> str:
        """Convert Google Chat mentions to Discourse @mentions.
        
        Google Chat format: <users/USER_ID>
        Discourse format: @username
        """
        # Find all mentions
        mention_pattern = r'<users/([^>]+)>'
        
        def replace_mention(match: re.Match[str]) -> str:
            user_id = match.group(1)
            
            # Look up user display name
            cursor = self.chat_conn.execute(
                "SELECT display_name FROM users WHERE id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                # User not found, keep original
                return match.group(0)
                
            display_name = row[0]
            
            # Try to get Discourse username
            discourse_username = self.user_mapper.get_or_create_discourse_user(user_id)
            
            if discourse_username:
                return f"@{discourse_username}"
            else:
                # Fall back to display name
                return f"@{display_name}"
        
        return re.sub(mention_pattern, replace_mention, text)
    
    def _format_attachments(self, attachments: list[dict[str, Any]]) -> str:
        """Format attachments as markdown.
        
        Images: ![filename](url)
        Files: [filename](url)
        Missing: *[Attachment: filename]*
        """
        lines = []
        
        for attachment in attachments:
            attachment_id = attachment['id']
            name = attachment['name']
            mime_type = attachment['mime_type']
            
            # Look up URL in cache
            url = self.attachment_url_cache.get(attachment_id)
            
            if not url:
                # Attachment not uploaded yet
                lines.append(f"*[Attachment: {name}]*")
                continue
            
            # Format based on mime type
            if mime_type.startswith('image/'):
                lines.append(f"![{name}]({url})")
            else:
                lines.append(f"[{name}]({url})")
        
        return "\n".join(lines)
