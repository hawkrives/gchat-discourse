# ABOUTME: Discourse API client for creating and updating content
# ABOUTME: Handles authentication, rate limiting, and error handling

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import structlog

logger = structlog.get_logger()


class DiscourseClient:
    """Client for Discourse API."""

    def __init__(self, base_url: str, api_key: str, api_username: str = "system"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_username = api_username

        self.client = httpx.Client(
            base_url=self.base_url, headers=self._get_headers(), timeout=30.0
        )

        logger.info("discourse_client_initialized", url=base_url)

    def _get_headers(self) -> Dict[str, str]:
        """Get API headers."""
        return {
            "Api-Key": self.api_key,
            "Api-Username": self.api_username,
            "Content-Type": "application/json",
        }

    def _handle_rate_limit(self, response: httpx.Response) -> None:
        """Handle rate limit response."""
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            logger.warning("discourse_rate_limited", retry_after=retry_after)
            raise DiscourseRateLimitError(int(retry_after))

    # Categories

    def create_category(
        self,
        name: str,
        color: str = "0088CC",
        text_color: str = "FFFFFF",
        parent_category_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a Discourse category.

        Args:
            name: Category name
            color: Hex color (without #)
            text_color: Text hex color (without #)
            parent_category_id: Parent category ID if subcategory

        Returns:
            Category data including id
        """
        data: Dict[str, Any] = {"name": name, "color": color, "text_color": text_color}

        if parent_category_id:
            data["parent_category_id"] = parent_category_id

        response = self.client.post("/categories.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()

        category = response.json()["category"]
        logger.info("category_created", name=name, id=category["id"])

        return category

    def get_category(self, category_id: int) -> Optional[Dict[str, Any]]:
        """Get category by ID."""
        try:
            response = self.client.get(f"/c/{category_id}/show.json")
            response.raise_for_status()
            return response.json()["category"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # Topics

    def create_topic(
        self,
        title: str,
        raw: str,
        category_id: int,
        created_at: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a Discourse topic (thread).

        Args:
            title: Topic title
            raw: First post content (markdown)
            category_id: Category to post in
            created_at: ISO timestamp for post backdating
            tags: List of tag names

        Returns:
            Topic data including id and post id
        """
        data: Dict[str, Any] = {"title": title, "raw": raw, "category": category_id}

        if created_at:
            data["created_at"] = created_at

        if tags:
            data["tags"] = tags

        response = self.client.post("/posts.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()

        result = response.json()
        logger.info("topic_created", title=title, topic_id=result["topic_id"])

        return result

    def get_topic(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """Get topic by ID."""
        try:
            response = self.client.get(f"/t/{topic_id}.json")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # Posts

    def create_post(
        self,
        topic_id: int,
        raw: str,
        created_at: Optional[str] = None,
        reply_to_post_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a post in an existing topic.

        Args:
            topic_id: Topic to post in
            raw: Post content (markdown)
            created_at: ISO timestamp for backdating
            reply_to_post_number: Post number this is replying to

        Returns:
            Post data including id
        """
        data: Dict[str, Any] = {"topic_id": topic_id, "raw": raw}

        if created_at:
            data["created_at"] = created_at

        if reply_to_post_number:
            data["reply_to_post_number"] = reply_to_post_number

        response = self.client.post("/posts.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()

        post = response.json()
        logger.info("post_created", topic_id=topic_id, post_id=post["id"])

        return post

    def update_post(self, post_id: int, raw: str) -> Dict[str, Any]:
        """Update a post's content."""
        data = {"post": {"raw": raw}}

        response = self.client.put(f"/posts/{post_id}.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()

        post = response.json()["post"]
        logger.info("post_updated", post_id=post_id)

        return post

    # Uploads

    def upload_file(
        self, filename: str, file_data: bytes, content_type: str = "application/octet-stream"
    ) -> Dict[str, Any]:
        """
        Upload a file to Discourse.

        Args:
            filename: Name of file
            file_data: File bytes
            content_type: MIME type

        Returns:
            Upload data including URL
        """
        files = {"file": (filename, file_data, content_type)}

        # Uploads use different headers
        headers = {"Api-Key": self.api_key, "Api-Username": self.api_username}

        response = self.client.post(
            "/uploads.json", files=files, headers=headers, params={"type": "composer"}
        )

        self._handle_rate_limit(response)
        response.raise_for_status()

        upload = response.json()
        logger.info(
            "file_uploaded", filename=filename, url=upload.get("url", upload.get("short_url"))
        )

        return upload

    # Users

    def create_user(
        self, email: str, username: str, name: str, password: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a Discourse user.

        Args:
            email: User email
            username: Username
            name: Display name
            password: Password (auto-generated if None)

        Returns:
            User data including id
        """
        import secrets

        data = {
            "email": email,
            "username": username,
            "name": name,
            "password": password or secrets.token_urlsafe(32),
            "active": True,
        }

        response = self.client.post("/users.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()

        user = response.json()
        logger.info("user_created", username=username, user_id=user.get("user_id"))

        return user

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        try:
            response = self.client.get(f"/users/{username}.json")
            response.raise_for_status()
            return response.json()["user"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    # Chat (Discourse Chat plugin)

    def create_chat_channel(
        self, name: str, description: str = "", auto_join_users: bool = True
    ) -> Dict[str, Any]:
        """
        Create a chat channel (requires Discourse Chat plugin).

        Args:
            name: Channel name
            description: Channel description
            auto_join_users: Whether users auto-join

        Returns:
            Channel data including id
        """
        data = {
            "channel": {
                "name": name,
                "description": description,
                "auto_join_users": auto_join_users,
            }
        }

        response = self.client.post("/chat/api/channels.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()

        channel = response.json()["channel"]
        logger.info("chat_channel_created", name=name, id=channel["id"])

        return channel

    def send_chat_message(
        self, channel_id: int, message: str, created_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a message to a chat channel."""
        data: Dict[str, Any] = {"message": message, "channel_id": channel_id}

        if created_at:
            data["created_at"] = created_at

        response = self.client.post(f"/chat/api/channels/{channel_id}/messages.json", json=data)

        self._handle_rate_limit(response)
        response.raise_for_status()

        msg = response.json()["message"]
        logger.info("chat_message_sent", channel_id=channel_id, message_id=msg["id"])

        return msg

    # Private Messages

    def create_private_message(
        self, title: str, raw: str, target_usernames: List[str], created_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a private message.

        Args:
            title: PM title
            raw: First message content
            target_usernames: List of recipient usernames
            created_at: ISO timestamp for backdating

        Returns:
            Topic data including id
        """
        data: Dict[str, Any] = {
            "title": title,
            "raw": raw,
            "target_usernames": ",".join(target_usernames),
            "archetype": "private_message",
        }

        if created_at:
            data["created_at"] = created_at

        response = self.client.post("/posts.json", json=data)
        self._handle_rate_limit(response)
        response.raise_for_status()

        result = response.json()
        logger.info("private_message_created", topic_id=result["topic_id"])

        return result

    def close(self) -> None:
        """Close HTTP client."""
        self.client.close()


class DiscourseRateLimitError(Exception):
    """Raised when rate limited by Discourse."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after} seconds")
