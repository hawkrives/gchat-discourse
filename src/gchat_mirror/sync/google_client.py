# ABOUTME: Google Chat API client wrapper
# ABOUTME: Provides helpers for fetching spaces and messages

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from google.oauth2.credentials import Credentials
import structlog

logger = structlog.get_logger()


class GoogleChatClient:
    """Client for Google Chat API endpoints used in the sync daemon."""

    BASE_URL = "https://chat.googleapis.com/v1"

    def __init__(self, credentials: Credentials):
        self.credentials = credentials
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            headers=self._get_headers(),
            timeout=30.0,
        )

    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.credentials.token}"}

    def list_spaces(self) -> List[Dict[str, Any]]:
        """Fetch spaces accessible to the user."""
        response = self.client.get("spaces")
        response.raise_for_status()
        data = response.json()
        spaces = data.get("spaces", [])
        logger.info("spaces_fetched", count=len(spaces))
        return spaces

    def list_messages(
        self,
        space_id: str,
        page_token: Optional[str] = None,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """Fetch messages from a space."""
        params: Dict[str, Any] = {"pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token

        response = self.client.get(f"{space_id}/messages", params=params)
        response.raise_for_status()
        payload = response.json()
        logger.info(
            "messages_fetched",
            space_id=space_id,
            count=len(payload.get("messages", [])),
            has_more="nextPageToken" in payload,
        )
        return payload

    def get_message(self, message_id: str) -> Dict[str, Any]:
        """Fetch a single message by name."""
        response = self.client.get(message_id)
        response.raise_for_status()
        message = response.json()
        logger.info("message_fetched", message_id=message_id)
        return message

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "GoogleChatClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
