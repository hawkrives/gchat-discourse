"""
Sync logic for Discourse to Google Chat direction.
"""

import logging
from typing import Dict, Any

from gchat_discourse.google_chat_client import GoogleChatClient
from gchat_discourse.discourse_client import DiscourseClient
from gchat_discourse.db import SyncDatabase

logger = logging.getLogger(__name__)


class DiscourseToGChatSync:
    """Handles synchronization from Discourse to Google Chat."""

    def __init__(self, gchat_client: GoogleChatClient,
                 discourse_client: DiscourseClient,
                 db: SyncDatabase,
                 api_username: str):
        """
        Initialize the sync handler.

        Args:
            gchat_client: Google Chat API client
            discourse_client: Discourse API client
            db: Database for state management
            api_username: Discourse API username (to prevent loops)
        """
        self.gchat = gchat_client
        self.discourse = discourse_client
        self.db = db
        self.api_username = api_username

    def sync_post_to_message(self, post_data: Dict[str, Any]) -> bool:
        """
        Sync a Discourse post to Google Chat.

        Args:
            post_data: Post data from Discourse webhook

        Returns:
            True if synced successfully, False otherwise
        """
        post_id = post_data.get('id')
        topic_id = post_data.get('topic_id')
        raw_content = post_data.get('raw', '')
        username = post_data.get('username', '')

        # Prevent infinite loops - ignore posts created by the API user
        if username == self.api_username:
            logger.debug(f"Ignoring post {post_id} created by API user")
            return False

        # Check if this post originated from Google Chat
        if self.db.get_message_id(post_id):
            logger.debug(f"Post {post_id} originated from Google Chat, ignoring")
            return False

        # Find the corresponding Google Chat thread
        thread_id = self.db.get_thread_id(topic_id)
        if not thread_id:
            logger.warning(f"No Google Chat thread found for topic {topic_id}")
            return False

        # Extract space ID from thread ID
        # Thread IDs are in format: spaces/SPACE_ID/threads/THREAD_ID
        space_id = '/'.join(thread_id.split('/')[:2])

        # Create message in Google Chat
        message = self.gchat.create_message(
            space_id=space_id,
            text=raw_content,
            thread_id=thread_id
        )

        if not message:
            logger.error(f"Failed to create Google Chat message for post {post_id}")
            return False

        message_id = message.get('name', '')
        
        # Store the mapping to prevent re-syncing
        self.db.add_message_post_mapping(message_id, post_id, thread_id)
        
        logger.info(f"Synced post {post_id} to Google Chat message {message_id}")
        return True

    def sync_post_update(self, post_data: Dict[str, Any]) -> bool:
        """
        Sync a Discourse post update to Google Chat.

        Args:
            post_data: Updated post data from Discourse webhook

        Returns:
            True if synced successfully, False otherwise
        """
        post_id = post_data.get('id')
        username = post_data.get('username', '')

        # Prevent infinite loops
        if username == self.api_username:
            logger.debug(f"Ignoring post update {post_id} by API user")
            return False

        # Check if this post has a corresponding Google Chat message
        message_id = self.db.get_message_id(post_id)
        if not message_id:
            logger.debug(f"No Google Chat message found for post {post_id}")
            return False

        raw_content = post_data.get('raw', '')

        # Update the message in Google Chat
        result = self.gchat.update_message(message_id, raw_content)
        
        if result:
            logger.info(f"Updated Google Chat message {message_id} for post {post_id}")
            return True
        
        return False

    def handle_topic_creation(self, topic_data: Dict[str, Any]) -> bool:
        """
        Handle a new topic created in Discourse.

        Args:
            topic_data: Topic data from webhook

        Returns:
            True if handled successfully, False otherwise
        """
        # For new topics created in Discourse, we need to determine if they should
        # be synced to Google Chat. This is more complex as we need to create a
        # new thread in the appropriate space.
        
        category_id = topic_data.get('category_id')
        
        # Find the corresponding Google Chat space
        space_id = self.db.get_space_id(category_id)
        if not space_id:
            logger.debug(f"No Google Chat space found for category {category_id}")
            return False

        # Get the first post content
        topic_id = topic_data.get('id')
        topic_details = self.discourse.get_topic(topic_id)
        
        if not topic_details:
            logger.error(f"Could not fetch topic {topic_id}")
            return False

        posts = topic_details.get('post_stream', {}).get('posts', [])
        if not posts:
            logger.warning(f"No posts found in topic {topic_id}")
            return False

        first_post = posts[0]
        username = first_post.get('username', '')

        # Prevent loops
        if username == self.api_username:
            logger.debug(f"Ignoring topic {topic_id} created by API user")
            return False

        # Create a message in Google Chat (which creates a new thread)
        message = self.gchat.create_message(
            space_id=space_id,
            text=first_post.get('cooked', '')  # Use cooked (HTML) or raw
        )

        if not message:
            logger.error(f"Failed to create Google Chat message for topic {topic_id}")
            return False

        # Extract thread ID from the message
        thread_id = message.get('thread', {}).get('name', '')
        message_id = message.get('name', '')

        if thread_id:
            # Store thread-to-topic mapping
            self.db.add_thread_topic_mapping(thread_id, topic_id, space_id)
            
        # Store message-to-post mapping
        post_id = first_post.get('id')
        self.db.add_message_post_mapping(message_id, post_id, thread_id)

        logger.info(f"Created Google Chat thread for topic {topic_id}")
        return True
