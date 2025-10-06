"""
Sync logic for Google Chat to Discourse direction.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from google_chat_client import GoogleChatClient
from discourse_client import DiscourseClient
from db import SyncDatabase

logger = logging.getLogger(__name__)


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

    def _ensure_user_exists(self, sender: Dict[str, Any]) -> Optional[str]:
        """
        Ensure a Discourse user exists for a Google Chat user.

        Args:
            sender: Sender object from Google Chat message

        Returns:
            Discourse username or None if error
        """
        # Extract user information from sender
        user_name = sender.get('name', '')  # e.g., 'users/12345'
        display_name = sender.get('displayName', 'Unknown User')
        user_type = sender.get('type', '')
        
        # Skip bot users
        if user_type == 'BOT':
            logger.debug(f"Skipping bot user: {display_name}")
            return None
        
        # Extract user ID from name
        if not user_name or '/' not in user_name:
            logger.warning(f"Invalid user name format: {user_name}")
            return None
        
        user_id = user_name.split('/')[-1]
        
        # Check if user mapping already exists
        existing_username = self.db.get_discourse_username(user_id)
        if existing_username:
            return existing_username
        
        # Create a Discourse username from the display name
        # Replace spaces and special characters with underscores
        username = display_name.lower().replace(' ', '_').replace('-', '_')
        # Remove any non-alphanumeric characters except underscores
        username = ''.join(c for c in username if c.isalnum() or c == '_')
        # Prefix with gchat_ to avoid conflicts
        username = f"gchat_{username}"
        # Truncate to reasonable length (Discourse has username length limits)
        username = username[:20]
        
        # Generate a fake email for the user
        email = f"{username}@gchat-sync.local"
        
        # Check if username already exists
        counter = 1
        original_username = username
        while self.discourse.user_exists(username):
            username = f"{original_username}_{counter}"
            counter += 1
        
        # Create the user in Discourse
        result = self.discourse.create_user(
            name=display_name,
            email=email,
            username=username,
            active=True
        )
        
        if not result:
            logger.error(f"Failed to create user for Google Chat user {user_id}")
            return None
        
        # Store the mapping
        self.db.add_user_mapping(user_id, display_name, username)
        logger.info(f"Created Discourse user {username} for Google Chat user {display_name}")
        
        return username

    def sync_dm_space_to_chat_channel(self, space_id: str) -> Optional[int]:
        """
        Sync a Google Chat DM space to a Discourse chat channel.

        Args:
            space_id: Google Chat DM space ID

        Returns:
            The Discourse chat channel ID or None if error
        """
        # Get space details
        space = self.gchat.get_space(space_id)
        if not space:
            logger.error(f"Could not fetch space {space_id}")
            return None
        
        # Verify it's a DM space
        if not self.gchat.is_dm_space(space):
            logger.warning(f"Space {space_id} is not a DM space")
            return None
        
        # Check if mapping already exists
        existing_channel_id = self.db.get_chat_channel_id(space_id)
        if existing_channel_id:
            logger.info(f"DM space {space_id} already mapped to chat channel {existing_channel_id}")
            return existing_channel_id
        
        # Get space members
        members = self.gchat.get_space_members(space_id)
        if not members:
            logger.error(f"Could not fetch members for space {space_id}")
            return None
        
        # Create Discourse users for all members
        usernames = []
        for membership in members:
            member = membership.get('member', {})
            sender_info = member
            
            # Ensure user exists in Discourse
            username = self._ensure_user_exists(sender_info)
            if username:
                usernames.append(username)
        
        if not usernames:
            logger.error(f"No valid users found for DM space {space_id}")
            return None
        
        # Create a chat channel in Discourse
        space_name = space.get('displayName', f"DM {space_id}")
        result = self.discourse.create_chat_channel(
            name=space_name,
            usernames=usernames,
            description=f"Direct message from Google Chat (space: {space_id})"
        )
        
        if not result or 'chat_channel' not in result:
            logger.error(f"Failed to create chat channel for DM space {space_id}")
            return None
        
        channel_id = result['chat_channel']['id']
        
        # Store mapping
        self.db.add_dm_channel_mapping(space_id, channel_id)
        logger.info(f"Synced DM space {space_id} to chat channel {channel_id}")
        
        return channel_id

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
                parent_category_id=parent_category_id
            )
            if not result or 'category' not in result:
                logger.error(f"Failed to create category for space {space_id}")
                return None
            final_category_id = result['category']['id']

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
        # Check if this is a DM space
        space = self.gchat.get_space(space_id)
        if space and self.gchat.is_dm_space(space):
            # Use DM sync logic instead
            return self.sync_dm_messages_to_chat(space_id, since_timestamp)
        
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

    def sync_dm_messages_to_chat(self, space_id: str, 
                                 since_timestamp: Optional[str] = None) -> int:
        """
        Sync messages from a Google Chat DM space to Discourse chat.

        Args:
            space_id: Google Chat DM space ID
            since_timestamp: Only sync messages after this timestamp

        Returns:
            Number of messages synced
        """
        # Get the chat channel ID for this DM space
        channel_id = self.db.get_chat_channel_id(space_id)
        if not channel_id:
            logger.error(f"No chat channel mapping found for DM space {space_id}")
            return 0

        synced_count = 0
        page_token = None

        # Fetch messages from Google Chat
        while True:
            response = self.gchat.list_messages(space_id, page_token=page_token)
            messages = response.get('messages', [])

            for message in messages:
                if self._sync_dm_message_to_chat(message, space_id, channel_id):
                    synced_count += 1

            page_token = response.get('nextPageToken')
            if not page_token:
                break

        # Update last sync timestamp
        if synced_count > 0:
            current_time = datetime.utcnow().isoformat()
            self.db.update_last_sync_time(space_id, current_time)

        logger.info(f"Synced {synced_count} DM messages from space {space_id}")
        return synced_count

    def _sync_dm_message_to_chat(self, message: Dict[str, Any], 
                                 space_id: str, channel_id: int) -> bool:
        """
        Sync a single Google Chat DM message to a Discourse chat message.

        Args:
            message: Google Chat message object
            space_id: Google Chat DM space ID
            channel_id: Discourse chat channel ID

        Returns:
            True if synced successfully, False otherwise
        """
        message_id = message.get('name', '')
        
        # Check if already synced
        if self.db.get_chat_message_id(message_id):
            logger.debug(f"DM message {message_id} already synced")
            return False

        # Extract message content
        text = message.get('text', '')
        if not text:
            logger.debug(f"Skipping empty DM message {message_id}")
            return False

        # Get sender information
        sender = message.get('sender', {})
        
        # Ensure the sender user exists in Discourse
        username = self._ensure_user_exists(sender)
        if not username:
            logger.warning(f"Could not create/find user for message {message_id}")
            # Still try to send the message, but it will be from the API user
        
        # TODO: In a production system, we would need to impersonate the user
        # or use a different mechanism to attribute messages correctly.
        # For now, messages will be sent as the API user with attribution in the message.
        
        # Add attribution if we have a username
        if username:
            attributed_text = f"**@{username}**: {text}"
        else:
            attributed_text = text
        
        # Create the chat message
        result = self.discourse.create_chat_message(
            channel_id=channel_id,
            message=attributed_text
        )
        
        if not result:
            logger.error(f"Failed to create chat message for DM message {message_id}")
            return False

        chat_message_id = result.get('id')
        
        # Store message mapping
        self.db.add_dm_message_mapping(message_id, chat_message_id, space_id)
        
        logger.info(f"Created chat message {chat_message_id} for DM message {message_id}")
        return True

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
            # Use first message as topic title
            title = text[:100] + ('...' if len(text) > 100 else '')
            result = self.discourse.create_topic(
                title=title,
                raw=text,
                category_id=category_id
            )
            
            if not result:
                logger.error(f"Failed to create topic for message {message_id}")
                return False

            topic_id = result.get('topic_id')
            post_id = result.get('id')

            # Store thread-to-topic mapping
            if thread_id:
                self.db.add_thread_topic_mapping(thread_id, topic_id, space_id)

            # Store message-to-post mapping
            self.db.add_message_post_mapping(message_id, post_id, thread_id or '')
            
            logger.info(f"Created topic {topic_id} for message {message_id}")
            return True
        else:
            # Create a reply in the existing topic
            result = self.discourse.create_post(
                topic_id=topic_id,
                raw=text
            )
            
            if not result:
                logger.error(f"Failed to create post for message {message_id}")
                return False

            post_id = result.get('id')
            
            # Store message-to-post mapping
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
