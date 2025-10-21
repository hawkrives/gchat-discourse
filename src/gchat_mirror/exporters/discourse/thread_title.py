# ABOUTME: Thread title generation from Google Chat messages
# ABOUTME: Extracts meaningful titles for Discourse topics

from __future__ import annotations

import re
from typing import Optional

import structlog

logger = structlog.get_logger()


class ThreadTitleGenerator:
    """Generate Discourse topic titles from Google Chat threads."""

    MAX_TITLE_LENGTH = 255
    MIN_TITLE_LENGTH = 3
    DEFAULT_TITLE = "Chat Thread"

    def generate_title(self, message_text: Optional[str], space_name: str, thread_id: str) -> str:
        """
        Generate a topic title from the first message.

        Args:
            message_text: First message text (may be None for deleted messages)
            space_name: Name of the Google Chat space
            thread_id: Thread ID for fallback

        Returns:
            Suitable topic title
        """
        if not message_text or not message_text.strip():
            # No text - use space name + thread ID
            title = f"{space_name} - {thread_id[:8]}"
            logger.debug("thread_title_fallback", thread_id=thread_id)
            return self._truncate_title(title)

        # Extract first line/sentence BEFORE cleaning to preserve structure
        first_part = self._extract_first_sentence(message_text)

        # Then clean the extracted part
        cleaned = self._clean_text(first_part)

        if not cleaned:
            return self._truncate_title(f"{space_name} - {thread_id[:8]}")

        # Ensure reasonable length
        title = self._truncate_title(cleaned)
        if len(title) < self.MIN_TITLE_LENGTH:
            title = f"{space_name} - {title}"

        return self._truncate_title(title)

    def _clean_text(self, text: str) -> str:
        """
        Clean message text for title use.

        - Remove markdown formatting
        - Remove mentions
        - Remove URLs
        - Normalize whitespace
        """
        # Remove markdown formatting
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # Bold
        text = re.sub(r"\*(.+?)\*", r"\1", text)  # Italic
        text = re.sub(r"`(.+?)`", r"\1", text)  # Code
        text = re.sub(r"~~(.+?)~~", r"\1", text)  # Strikethrough

        # Remove mentions (@user)
        text = re.sub(r"<users/[^>]+>", "", text)

        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        text = text.strip()

        return text

    def _extract_first_sentence(self, text: str) -> str:
        """Extract first sentence or line from text.

        Args:
            text: Cleaned message text

        Returns:
            First sentence or line
        """
        # First, check for newlines
        if "\n" in text:
            return text.split("\n")[0].strip()

        # Then look for sentence-ending punctuation
        for punct in [". ", "? ", "! "]:
            if punct in text:
                return text.split(punct)[0] + punct.rstrip()

        # Return entire text if no sentence endings found
        return text

    def _truncate_title(self, title: str) -> str:
        """Truncate title to maximum length."""
        if len(title) <= self.MAX_TITLE_LENGTH:
            return title

        # Truncate at word boundary
        truncated = title[: self.MAX_TITLE_LENGTH - 3]
        last_space = truncated.rfind(" ")

        if last_space > self.MAX_TITLE_LENGTH // 2:
            truncated = truncated[:last_space]

        return truncated + "..."
