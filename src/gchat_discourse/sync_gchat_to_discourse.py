"""
Sync logic for Google Chat to Discourse direction.
"""

import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime

from gchat_discourse.google_chat_client import GoogleChatClient
from gchat_discourse.discourse_client import (
    DiscourseClient,
    CreateTopicResponse,
    PostDetailsResponse,
)
from gchat_discourse.db import SyncDatabase

logger = logging.getLogger(__name__)


def _format_response(result: object, context: Optional[str] = None, max_len: int = 1000) -> str:
    """Pretty-print a response object, truncate if too long, and log full at DEBUG.

    Prefers `result.raw` when available, falls back to dict or repr(result).
    """
    raw = getattr(result, "raw", None)
    if raw is None and isinstance(result, dict):
        raw = result
    if raw is None:
        s = repr(result)
    else:
        try:
            s = json.dumps(raw, indent=2, ensure_ascii=False)
        except Exception:
            try:
                s = str(raw)
            except Exception:
                s = repr(raw)

    if len(s) > max_len:
        # Log the full payload at DEBUG for deeper inspection
        if logger.isEnabledFor(logging.DEBUG):
            try:
                logger.debug("Full response%s: %s", f" ({context})" if context else "", s)
            except Exception:
                logger.debug("Full response (unable to format)")
        return s[:max_len] + "... (truncated)"

    return s


def make_title_and_body(text: str, max_title_len: int = 255) -> tuple[str, str]:
    """Return (title, body) for a Discourse topic based on chat text.

    Title is the first non-empty line of `text`. If that line exceeds
    `max_title_len`, it is truncated to (max_title_len - 3) and "..." is appended.
    The body contains the (possibly trimmed) title followed by two newlines and
    the full original `text` so the complete chat message is preserved.
    """
    if not text:
        return ("", "")

    # Find first non-empty line
    first_line = ""
    for line in text.splitlines():
        if line.strip():
            first_line = line
            break
    if not first_line:
        # fallback to the first line or full text
        lines = text.splitlines()
        first_line = lines[0] if lines else text

    if len(first_line) <= max_title_len:
        title = first_line
    else:
        title = first_line[: max_title_len - 3] + "..."

    body = f"{title}\n\n{text}"
    return title, body


class GChatToDiscourseSync:
    """Handles synchronization from Google Chat to Discourse."""

    def __init__(self, gchat_client: GoogleChatClient, 
                 discourse_client: DiscourseClient,
                 db: SyncDatabase):
        """
        Initialize the sync handler.

        Args:
            gchat_client: Google Chat API client
            discourse_client: Discourse API client
            db: Database for state management
        """
        self.gchat = gchat_client
        self.discourse = discourse_client
        self.db = db

    def sync_space_to_category(self, space_id: str, 
                               category_id: Optional[int] = None,
                               parent_category_id: Optional[int] = None) -> Optional[int]:
        """
        Sync a Google Chat space to a Discourse category.

        Args:
            space_id: Google Chat space ID
            category_id: Existing Discourse category ID (optional)
            parent_category_id: Parent category ID for creating sub-category

        Returns:
            The Discourse category ID or None if error
        """
        # Get space details from Google Chat
        space = self.gchat.get_space(space_id)
        if not space:
            logger.error(f"Could not fetch space {space_id}")
            return None

        space_name = space.get('displayName', 'Unnamed Space')

        # Check if mapping already exists
        existing_category_id = self.db.get_category_id(space_id)
        if existing_category_id:
            logger.info(f"Space {space_id} already mapped to category {existing_category_id}")
            return existing_category_id

        # Create or verify category
        if category_id:
            # Use existing category
            category = self.discourse.get_category(category_id)
            if not category:
                logger.error(f"Category {category_id} not found in Discourse")
                return None
            final_category_id = category_id
        else:
            # Create new category (possibly as sub-category)
            result = self.discourse.create_category(
                name=space_name,
                parent_category_id=parent_category_id,
            )
            if not result:
                logger.error(f"Failed to create category for space {space_id}")
                return None
            # CreateCategoryResponse contains .category
            category_obj = getattr(result, "category", None)
            if not category_obj or getattr(category_obj, "id", None) is None:
                # Log full response for debugging (raw dict if available)
                resp_repr = _format_response(result, context=f"create_category {space_id}")
                logger.error(
                    "Create category returned unexpected response for space %s: %s",
                    space_id,
                    resp_repr,
                )
                return None
            final_category_id = category_obj.id

        # Store mapping
        self.db.add_space_category_mapping(space_id, final_category_id)
        logger.info(f"Synced space {space_id} to category {final_category_id}")
        
        return final_category_id

    def sync_messages_to_posts(self, space_id: str, 
                              since_timestamp: Optional[str] = None) -> int:
        """
        Sync messages from a Google Chat space to Discourse.

        Args:
            space_id: Google Chat space ID
            since_timestamp: Only sync messages after this timestamp

        Returns:
            Number of messages synced
        """
        # Get the category ID for this space
        category_id = self.db.get_category_id(space_id)
        if not category_id:
            logger.error(f"No category mapping found for space {space_id}")
            return 0

        synced_count = 0
        page_token = None

        # Fetch messages from Google Chat
        while True:
            response = self.gchat.list_messages(space_id, page_token=page_token)
            messages = response.get('messages', [])

            for message in messages:
                if self._sync_message_to_post(message, space_id, category_id):
                    synced_count += 1

            page_token = response.get('nextPageToken')
            if not page_token:
                break

        # Update last sync timestamp
        if synced_count > 0:
            current_time = datetime.utcnow().isoformat()
            self.db.update_last_sync_time(space_id, current_time)

        logger.info(f"Synced {synced_count} messages from space {space_id}")
        return synced_count

    def _sync_message_to_post(self, message: Dict[str, Any], 
                             space_id: str, category_id: int) -> bool:
        """
        Sync a single Google Chat message to a Discourse post.

        Args:
            message: Google Chat message object
            space_id: Google Chat space ID
            category_id: Discourse category ID

        Returns:
            True if synced successfully, False otherwise
        """
        message_id = message.get('name', '')
        
        # Check if already synced
        if self.db.get_post_id(message_id):
            logger.debug(f"Message {message_id} already synced")
            return False

        # Extract message content
        text = message.get('text', '')
        if not text:
            logger.debug(f"Skipping empty message {message_id}")
            return False

        # Get thread information
        thread = message.get('thread', {})
        thread_id = thread.get('name', '')

        # Check if we have a topic for this thread
        topic_id = None
        if thread_id:
            topic_id = self.db.get_topic_id(thread_id)

        # If no topic exists, create one
        if not topic_id:
            title_trimmed, body_raw = make_title_and_body(text, max_title_len=255)

            payload = {"title": title_trimmed, "raw": body_raw, "category": category_id}
            result = self.discourse.create_topic(title=title_trimmed, raw=body_raw, category_id=category_id)

            if not result:
                logger.error(f"Failed to create topic for message {message_id}")
                logger.error(
                    "Create topic payload for message %s: %s",
                    message_id,
                    _format_response(payload, context=f"create_topic_payload {message_id}"),
                )
                return False

            # CreateTopicResponse contains .topic_id and .post (Post dataclass)
            if isinstance(result, CreateTopicResponse):
                topic_id = getattr(result, "topic_id", None)
                post_id = getattr(result.post, "id", None) if getattr(result, "post", None) else None
            else:
                # Fallback for older shapes
                topic_id = result.get("topic_id") if isinstance(result, dict) else None
                post_id = result.get("id") if isinstance(result, dict) else None

            # If we didn't get expected ids, log full response to help debug
            if topic_id is None or post_id is None:
                resp_repr = _format_response(result, context=f"create_topic {message_id}")
                logger.error(
                    "Create topic returned unexpected shape for message %s: topic_id=%s post_id=%s response=%s",
                    message_id,
                    topic_id,
                    post_id,
                    resp_repr,
                )
                # Log payload that we attempted to create
                logger.error(
                    "Create topic payload for message %s: %s",
                    message_id,
                    _format_response(payload, context=f"create_topic_payload {message_id}"),
                )

            # Store thread-to-topic mapping (only if we have a valid topic_id)
            if thread_id and isinstance(topic_id, int):
                self.db.add_thread_topic_mapping(thread_id, topic_id, space_id)

            # Store message-to-post mapping (only if we have a valid post_id)
            if isinstance(post_id, int):
                self.db.add_message_post_mapping(message_id, post_id, thread_id or "")
            
            logger.info(f"Created topic {topic_id} for message {message_id}")
            return True
        else:
            # Create a reply in the existing topic
            payload = {"topic_id": topic_id, "raw": text}
            result = self.discourse.create_post(topic_id=topic_id, raw=text)

            if not result:
                logger.error(f"Failed to create post for message {message_id}")
                logger.error(
                    "Create post payload for message %s: %s",
                    message_id,
                    _format_response(payload, context=f"create_post_payload {message_id}"),
                )
                return False

            # PostDetailsResponse contains .post (Post dataclass)
            if isinstance(result, PostDetailsResponse):
                post_id = getattr(result.post, "id", None) if getattr(result, "post", None) else None
            else:
                post_id = result.get("id") if isinstance(result, dict) else None

            if post_id is None:
                resp_repr = _format_response(result, context=f"create_post {message_id}")
                logger.error(
                    "Create post returned unexpected shape for message %s: post_id=%s response=%s",
                    message_id,
                    post_id,
                    resp_repr,
                )
                # Log payload that we attempted to create
                logger.error(
                    "Create post payload for message %s: %s",
                    message_id,
                    _format_response(payload, context=f"create_post_payload {message_id}"),
                )
            
            # Store message-to-post mapping (only if we have a valid post_id)
            if isinstance(post_id, int):
                self.db.add_message_post_mapping(message_id, post_id, thread_id)
            
            logger.info(f"Created post {post_id} for message {message_id}")
            return True

    def sync_message_update(self, message_id: str, new_text: str) -> bool:
        """
        Sync a message update from Google Chat to Discourse.

        Args:
            message_id: Google Chat message ID
            new_text: Updated message text

        Returns:
            True if updated successfully, False otherwise
        """
        post_id = self.db.get_post_id(message_id)
        if not post_id:
            logger.warning(f"No post mapping found for message {message_id}")
            return False

        result = self.discourse.update_post(post_id, new_text)
        if result:
            logger.info(f"Updated post {post_id} for message {message_id}")
            return True
        
        return False
