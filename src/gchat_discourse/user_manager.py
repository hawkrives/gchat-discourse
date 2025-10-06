"""
User management module for syncing users between Google Chat and Discourse.
"""

import logging
import re
from typing import Optional, Dict, Any

from gchat_discourse.discourse_client import DiscourseClient
from gchat_discourse.db import SyncDatabase

logger = logging.getLogger(__name__)


def sanitize_username(name: str) -> str:
    """
    Convert a display name into a valid Discourse username.
    
    Discourse usernames must be:
    - 3-20 characters
    - Alphanumeric, dashes, underscores only
    - No spaces
    
    Args:
        name: Display name to convert
    
    Returns:
        Sanitized username
    """
    # Remove special characters and replace spaces with underscores
    username = re.sub(r'[^\w\s-]', '', name.lower())
    username = re.sub(r'[\s]+', '_', username)
    username = re.sub(r'[_-]+', '_', username)
    
    # Ensure it starts with alphanumeric
    username = re.sub(r'^[^a-z0-9]+', '', username)
    
    # Truncate to 20 characters
    username = username[:20]
    
    # Ensure minimum length of 3
    if len(username) < 3:
        username = username + "_user"
    
    # Remove trailing underscores/dashes
    username = username.rstrip('_-')
    
    return username


def generate_email_from_gchat_user(gchat_user_id: str, domain: str = "gchat.local") -> str:
    """
    Generate an email address for a Google Chat user.
    
    Args:
        gchat_user_id: Google Chat user ID (e.g., 'users/123456')
        domain: Email domain to use
    
    Returns:
        Generated email address
    """
    # Extract numeric ID from user ID
    user_id = gchat_user_id.split('/')[-1]
    return f"gchat_{user_id}@{domain}"


class UserManager:
    """Manages user synchronization between Google Chat and Discourse."""

    def __init__(self, discourse_client: DiscourseClient, db: SyncDatabase):
        """
        Initialize the user manager.
        
        Args:
            discourse_client: Discourse API client
            db: Database for user mappings
        """
        self.discourse = discourse_client
        self.db = db

    def get_or_create_discourse_user(
        self, gchat_sender: Dict[str, Any]
    ) -> Optional[str]:
        """
        Get or create a Discourse user for a Google Chat sender.
        
        Args:
            gchat_sender: Google Chat sender object with fields:
                - name: User ID (e.g., 'users/123456')
                - displayName: User's display name
                - email: User's email (may not be present)
        
        Returns:
            Discourse username or None if error
        """
        gchat_user_id = gchat_sender.get('name', '')
        if not gchat_user_id:
            logger.error("No user ID in sender object")
            return None

        # Check if we already have a mapping
        discourse_username = self.db.get_discourse_username(gchat_user_id)
        if discourse_username:
            logger.debug(f"Found existing mapping: {gchat_user_id} -> {discourse_username}")
            return discourse_username

        # Need to create a new user
        display_name = gchat_sender.get('displayName', 'Unknown User')
        gchat_email = gchat_sender.get('email')
        
        # Generate username and email
        username = sanitize_username(display_name)
        
        # Use Google Chat email if available, otherwise generate one
        if gchat_email:
            email = gchat_email
        else:
            email = generate_email_from_gchat_user(gchat_user_id)

        # Try to create the user in Discourse
        # Generate a random password - user won't use it for login in this integration
        import secrets
        password = secrets.token_urlsafe(32)

        user_response = self.discourse.create_user(
            name=display_name,
            email=email,
            password=password,
            username=username,
            active=True,
            approved=True,
        )

        if not user_response or not user_response.user:
            logger.error(f"Failed to create Discourse user for {gchat_user_id}")
            return None

        actual_username = user_response.user.username
        logger.info(f"Created Discourse user: {actual_username} for Google Chat user {gchat_user_id}")

        # Store the mapping
        self.db.add_user_mapping(
            gchat_user_id=gchat_user_id,
            discourse_username=actual_username,
            gchat_display_name=display_name,
            gchat_email=gchat_email,
        )

        return actual_username
