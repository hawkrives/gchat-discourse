"""
Discourse API client module for interacting with Discourse forum.
"""

import logging
import requests
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class DiscourseClient:
    """Client for interacting with Discourse API."""

    def __init__(self, url: str, api_key: str, api_username: str):
        """
        Initialize the Discourse API client.

        Args:
            url: Base URL of the Discourse instance
            api_key: API key for authentication
            api_username: Username associated with the API key
        """
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.api_username = api_username
        self.headers = {
            'Api-Key': api_key,
            'Api-Username': api_username,
            'Content-Type': 'application/json'
        }
        logger.info(f"Discourse API client initialized for {self.url}")

    def _make_request(self, method: str, endpoint: str, 
                     data: Optional[Dict] = None, 
                     params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Make an HTTP request to the Discourse API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            data: Request body data
            params: URL parameters

        Returns:
            Response JSON or None if error
        """
        url = f"{self.url}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            # Some endpoints return no content
            if response.status_code == 204:
                return {}
            
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making {method} request to {endpoint}: {e}")
            return None

    # Category operations
    def get_category(self, category_id: int) -> Optional[Dict[str, Any]]:
        """Get category details."""
        return self._make_request('GET', f'/c/{category_id}/show.json')

    def create_category(self, name: str, color: str = "0088CC", 
                       text_color: str = "FFFFFF",
                       parent_category_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Create a new category.

        Args:
            name: Category name
            color: Category color (hex without #)
            text_color: Text color (hex without #)
            parent_category_id: Optional parent category ID for sub-categories

        Returns:
            Created category details or None if error
        """
        data = {
            'name': name,
            'color': color,
            'text_color': text_color
        }
        
        if parent_category_id:
            data['parent_category_id'] = parent_category_id

        result = self._make_request('POST', '/categories.json', data=data)
        if result:
            logger.info(f"Created category: {name}")
        return result

    def update_category(self, category_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        """Update category details."""
        return self._make_request('PUT', f'/categories/{category_id}.json', data=kwargs)

    # Topic operations
    def get_topic(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """Get topic details."""
        return self._make_request('GET', f'/t/{topic_id}.json')

    def create_topic(self, title: str, raw: str, category_id: int) -> Optional[Dict[str, Any]]:
        """
        Create a new topic.

        Args:
            title: Topic title
            raw: Topic content (raw Markdown)
            category_id: Category ID where the topic should be created

        Returns:
            Created topic details or None if error
        """
        data = {
            'title': title,
            'raw': raw,
            'category': category_id
        }
        
        result = self._make_request('POST', '/posts.json', data=data)
        if result:
            logger.info(f"Created topic: {title}")
        return result

    def update_topic(self, topic_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        """Update topic details."""
        return self._make_request('PUT', f'/t/{topic_id}.json', data=kwargs)

    # Post operations
    def get_post(self, post_id: int) -> Optional[Dict[str, Any]]:
        """Get post details."""
        return self._make_request('GET', f'/posts/{post_id}.json')

    def create_post(self, topic_id: int, raw: str) -> Optional[Dict[str, Any]]:
        """
        Create a new post in a topic.

        Args:
            topic_id: Topic ID where the post should be created
            raw: Post content (raw Markdown)

        Returns:
            Created post details or None if error
        """
        data = {
            'topic_id': topic_id,
            'raw': raw
        }
        
        result = self._make_request('POST', '/posts.json', data=data)
        if result:
            logger.info(f"Created post in topic {topic_id}")
        return result

    def update_post(self, post_id: int, raw: str) -> Optional[Dict[str, Any]]:
        """
        Update a post.

        Args:
            post_id: Post ID to update
            raw: New post content (raw Markdown)

        Returns:
            Updated post details or None if error
        """
        data = {'post': {'raw': raw}}
        result = self._make_request('PUT', f'/posts/{post_id}.json', data=data)
        if result:
            logger.info(f"Updated post {post_id}")
        return result

    def delete_post(self, post_id: int) -> bool:
        """Delete a post."""
        result = self._make_request('DELETE', f'/posts/{post_id}.json')
        return result is not None

    # List operations
    def list_topics_in_category(self, category_id: int, page: int = 0) -> Optional[Dict[str, Any]]:
        """List topics in a category."""
        return self._make_request('GET', f'/c/{category_id}.json', params={'page': page})

    def list_posts_in_topic(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """List all posts in a topic."""
        return self._make_request('GET', f'/t/{topic_id}.json')

    # User operations
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user details."""
        return self._make_request('GET', f'/users/{username}.json')
