# ABOUTME: User mapping and auto-creation for Discourse
# ABOUTME: Creates Discourse users on-demand from Google Chat users

from __future__ import annotations

import re
import sqlite3
from typing import Optional

import structlog

from gchat_mirror.exporters.discourse.discourse_client import DiscourseClient

logger = structlog.get_logger()


class UserMapper:
    """Map Google Chat users to Discourse users."""

    def __init__(
        self,
        discourse_client: DiscourseClient,
        state_conn: sqlite3.Connection,
        chat_conn: sqlite3.Connection,
    ):
        self.discourse = discourse_client
        self.state_conn = state_conn
        self.chat_conn = chat_conn

    def get_or_create_discourse_user(self, gchat_user_id: str) -> Optional[str]:
        """
        Get Discourse username for Google Chat user, creating if needed.

        Args:
            gchat_user_id: Google Chat user ID

        Returns:
            Discourse username, or None if user creation fails
        """
        # Check if we have a mapping
        cursor = self.state_conn.execute(
            """
            SELECT discourse_id FROM export_mappings
            WHERE source_type = 'user' AND source_id = ?
        """,
            (gchat_user_id,),
        )

        result = cursor.fetchone()
        if result:
            return result[0]  # discourse_id is the username

        # Get Google Chat user data
        cursor = self.chat_conn.execute(
            """
            SELECT display_name, email FROM users WHERE id = ?
        """,
            (gchat_user_id,),
        )

        user_data = cursor.fetchone()
        if not user_data:
            logger.error("user_not_found", user_id=gchat_user_id)
            return None

        display_name, email = user_data

        # Generate Discourse username
        username = self._generate_username(display_name, email)

        # Check if user already exists in Discourse
        existing = self.discourse.get_user_by_username(username)

        if not existing:
            # Create user
            try:
                result = self.discourse.create_user(
                    email=email or f"{username}@generated.local",
                    username=username,
                    name=display_name,
                )

                logger.info(
                    "discourse_user_created", gchat_user=gchat_user_id, discourse_username=username
                )

            except Exception as e:
                logger.error("user_creation_failed", gchat_user=gchat_user_id, error=str(e))
                return None

        # Store mapping
        self.state_conn.execute(
            """
            INSERT INTO export_mappings 
            (source_type, source_id, discourse_type, discourse_id)
            VALUES ('user', ?, 'user', ?)
        """,
            (gchat_user_id, username),
        )
        self.state_conn.commit()

        return username

    def _generate_username(self, display_name: str, email: Optional[str]) -> str:
        """
        Generate Discourse-compatible username from display name.

        Rules:
        - Lowercase
        - Alphanumeric + underscore only
        - 3-20 characters
        - No consecutive underscores
        """
        # Start with display name
        username = display_name.lower()

        # Replace spaces with underscores
        username = username.replace(" ", "_")

        # Remove non-alphanumeric except underscores
        username = re.sub(r"[^a-z0-9_]", "", username)

        # Remove consecutive underscores
        username = re.sub(r"_+", "_", username)

        # Strip leading/trailing underscores
        username = username.strip("_")

        # Trim to length
        username = username[:20]

        # Ensure minimum length
        if len(username) < 3:
            if email:
                # Try email local part
                username = email.split("@")[0].lower()
                username = re.sub(r"[^a-z0-9_]", "", username)[:20]

        # Still too short? Add random suffix
        if len(username) < 3:
            import random

            username = username + "_" + str(random.randint(100, 999))

        # Ensure uniqueness by checking database
        base_username = username
        counter = 1
        while self._username_exists(username):
            username = f"{base_username}_{counter}"
            # Ensure it doesn't exceed 20 chars
            if len(username) > 20:
                # Truncate base to make room for counter
                max_base_len = 20 - len(f"_{counter}")
                username = f"{base_username[:max_base_len]}_{counter}"
            counter += 1

        return username

    def _username_exists(self, username: str) -> bool:
        """Check if username already mapped."""
        cursor = self.state_conn.execute(
            """
            SELECT 1 FROM export_mappings
            WHERE source_type = 'user' AND discourse_id = ?
        """,
            (username,),
        )
        return cursor.fetchone() is not None
