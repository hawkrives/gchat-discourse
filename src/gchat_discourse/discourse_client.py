"""
Discourse API client module for interacting with Discourse forum.
"""

import logging
import requests
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Category:
    id: Optional[int]
    name: Optional[str]
    color: Optional[str] = None
    text_color: Optional[str] = None
    parent_category_id: Optional[int] = None
    slug: Optional[str] = None
    topic_count: Optional[int] = None
    post_count: Optional[int] = None
    description: Optional[str] = None
    read_restricted: Optional[bool] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Category":
        if data is None:
            return cls(None, None)
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            color=data.get("color"),
            text_color=data.get("text_color") or data.get("text-color"),
            parent_category_id=data.get("parent_category_id")
            or data.get("parent_category_id"),
            slug=data.get("slug"),
            topic_count=data.get("topic_count") or data.get("topic_count"),
            post_count=data.get("post_count"),
            description=data.get("description"),
            read_restricted=data.get("read_restricted"),
            raw=data,
        )


@dataclass
class Topic:
    id: Optional[int]
    title: Optional[str]
    fancy_title: Optional[str] = None
    posts_count: Optional[int] = None
    reply_count: Optional[int] = None
    views: Optional[int] = None
    highest_post_number: Optional[int] = None
    created_at: Optional[str] = None
    last_posted_at: Optional[str] = None
    archetype: Optional[str] = None
    closed: Optional[bool] = None
    bumped: Optional[bool] = None
    slug: Optional[str] = None
    category_id: Optional[int] = None
    excerpt: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Topic":
        if data is None:
            return cls(None, None)
        return cls(
            id=data.get("id") or data.get("topic_id"),
            title=data.get("title") or data.get("fancy_title"),
            fancy_title=data.get("fancy_title"),
            posts_count=data.get("posts_count") or data.get("post_count"),
            reply_count=data.get("reply_count"),
            views=data.get("views"),
            highest_post_number=data.get("highest_post_number"),
            created_at=data.get("created_at"),
            last_posted_at=data.get("last_posted_at"),
            archetype=data.get("archetype"),
            closed=data.get("closed"),
            bumped=data.get("bumped"),
            slug=data.get("slug"),
            category_id=data.get("category_id") or data.get("category"),
            excerpt=data.get("excerpt"),
            raw=data,
        )


@dataclass
class Post:
    id: Optional[int]
    topic_id: Optional[int]
    post_number: Optional[int] = None
    username: Optional[str] = None
    name: Optional[str] = None
    cooked: Optional[str] = None
    raw: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    reply_to_post_number: Optional[int] = None
    raw_meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Post":
        if data is None:
            return cls(None, None)
        return cls(
            id=data.get("id"),
            topic_id=data.get("topic_id") or data.get("topic"),
            post_number=data.get("post_number"),
            username=data.get("username"),
            name=data.get("name"),
            cooked=data.get("cooked"),
            raw=data.get("raw"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            reply_to_post_number=data.get("reply_to_post_number"),
            raw_meta=data,
        )


@dataclass
class User:
    id: Optional[int]
    username: Optional[str]
    name: Optional[str] = None
    avatar_template: Optional[str] = None
    admin: Optional[bool] = None
    moderator: Optional[bool] = None
    title: Optional[str] = None
    created_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    trust_level: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "User":
        if data is None:
            return cls(None, None)
        return cls(
            id=data.get("id"),
            username=data.get("username"),
            name=data.get("name"),
            avatar_template=data.get("avatar_template"),
            admin=data.get("admin"),
            moderator=data.get("moderator"),
            title=data.get("title"),
            created_at=data.get("created_at"),
            last_seen_at=data.get("last_seen_at"),
            trust_level=data.get("trust_level"),
            raw=data,
        )


@dataclass
class CategoryShowResponse:
    category: Optional[Category]
    topic_list: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CategoryShowResponse":
        if data is None:
            return cls(None)
        cat = data.get("category")
        return cls(
            category=Category.from_dict(cat) if cat else None,
            topic_list=data.get("topic_list"),
            raw=data,
        )


@dataclass
class CreateCategoryResponse:
    category: Optional[Category]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CreateCategoryResponse":
        if data is None:
            return cls(None)
        cat = data.get("category") or data.get("basic_category") or data
        return cls(
            category=Category.from_dict(cat) if isinstance(cat, dict) else None,
            raw=data,
        )


@dataclass
class TopicDetailsResponse:
    topic: Optional[Topic]
    post_stream: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TopicDetailsResponse":
        if data is None:
            return cls(None)
        t = data.get("topic") or data
        post_stream = data.get("post_stream")
        # if top-level contains topic fields (e.g., GET /t/{id}.json), map accordingly
        topic_obj = None
        if isinstance(t, dict):
            topic_obj = Topic.from_dict(t)
        return cls(topic=topic_obj, post_stream=post_stream, raw=data)


@dataclass
class CreateTopicResponse:
    post: Optional[Post]
    topic_id: Optional[int] = None
    topic_slug: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CreateTopicResponse":
        if data is None:
            return cls(None)
        post = data.get("post") or data
        return cls(
            post=Post.from_dict(post) if isinstance(post, dict) else None,
            topic_id=data.get("topic_id") or data.get("id"),
            topic_slug=data.get("topic_slug") or data.get("slug"),
            raw=data,
        )


@dataclass
class PostDetailsResponse:
    post: Optional[Post]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PostDetailsResponse":
        if data is None:
            return cls(None)
        p = data.get("post") or data
        return cls(post=Post.from_dict(p) if isinstance(p, dict) else None, raw=data)


@dataclass
class ListTopicsResponse:
    category: Optional[Category]
    topics: List[Topic]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ListTopicsResponse":
        if data is None:
            return cls(None, [])
        cat = data.get("category")
        topic_list = data.get("topic_list") or {}
        topics_raw = topic_list.get("topics") if isinstance(topic_list, dict) else None
        topics = [Topic.from_dict(t) for t in topics_raw] if topics_raw else []
        return cls(
            category=Category.from_dict(cat) if cat else None, topics=topics, raw=data
        )


@dataclass
class ListPostsResponse:
    topic: Optional[Topic]
    posts: List[Post]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ListPostsResponse":
        if data is None:
            return cls(None, [])
        # Discourse returns posts in `post_stream.posts` for topic endpoints
        post_stream = data.get("post_stream") or {}
        posts_raw = post_stream.get("posts") if isinstance(post_stream, dict) else None
        posts = [Post.from_dict(p) for p in posts_raw] if posts_raw else []
        topic = data.get("topic") or data
        topic_obj = Topic.from_dict(topic) if isinstance(topic, dict) else None
        return cls(topic=topic_obj, posts=posts, raw=data)


@dataclass
class UserResponse:
    user: Optional[User]
    primary_group_name: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserResponse":
        if data is None:
            return cls(None)
        u = data.get("user") or data
        return cls(
            user=User.from_dict(u) if isinstance(u, dict) else None,
            primary_group_name=data.get("primary_group_name"),
            raw=data,
        )


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
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.api_username = api_username
        self.headers = {
            "Api-Key": api_key,
            "Api-Username": api_username,
            "Content-Type": "application/json",
        }
        # If True, re-raise HTTP errors from _make_request so callers can
        # decide to terminate the process (used by the service's -E flag).
        self.raise_on_error: bool = False
        logger.info(f"Discourse API client initialized for {self.url}")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        allow_errors: bool = False,
        impersonate_username: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Make an HTTP request to the Discourse API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path
            data: Request body data
            params: URL parameters
            impersonate_username: Username to impersonate (overrides default Api-Username)

        Returns:
            Response JSON or None if error
        """
        url = f"{self.url}/{endpoint.lstrip('/')}"

        # Build headers, optionally overriding Api-Username for impersonation
        headers = self.headers.copy()
        if impersonate_username:
            headers["Api-Username"] = impersonate_username

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

        except requests.exceptions.RequestException as e:
            # Provide richer logging for HTTP errors so callers can debug
            # issues like 4xx/5xx responses. If allow_errors is set, return
            # a lightweight structured dict so callers can implement retry
            # or backoff behavior.
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
            headers = dict(resp.headers) if resp is not None and getattr(resp, "headers", None) is not None else None
            body = None
            text = None
            if resp is not None:
                try:
                    body = resp.json()
                except Exception:
                    try:
                        text = resp.text
                    except Exception:
                        text = None
                    body = {"_text": text}

            # Log a detailed error message with method/endpoint/url/status/body snippet
            try:
                logger.error(
                    "Error making %s request to %s (%s): %s; status=%s; body=%s; headers=%s",
                    method,
                    endpoint,
                    url,
                    e,
                    status,
                    body,
                    headers,
                )
            except Exception:
                # Fallback to minimal logging if formatting fails
                logger.error("Error making %s request to %s: %s", method, endpoint, e)

            if allow_errors and resp is not None:
                err = {"_status_code": status, "body": body, "headers": headers or {}}
                if self.raise_on_error:
                    # Turn into an exception so callers with exit-on-error can stop
                    raise requests.exceptions.HTTPError(
                        f"{status} Error", response=resp
                    )
                return err

            if self.raise_on_error and resp is not None:
                # Re-raise the original HTTPError
                raise

            return None

        # Some endpoints return no content
        if response.status_code == 204:
            return {}

        return response.json()

    # Category operations
    def get_category(self, category_id: int) -> Optional[CategoryShowResponse]:
        """Get category details."""
        result = self._make_request("GET", f"/c/{category_id}/show.json")
        return CategoryShowResponse.from_dict(result) if result is not None else None

    def create_category(
        self,
        name: str,
        color: str = "0088CC",
        text_color: str = "FFFFFF",
        parent_category_id: Optional[int] = None,
    ) -> Optional[CreateCategoryResponse]:
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
        data: dict[str, str | int] = {
            "name": name,
            "color": color,
            "text_color": text_color,
        }

        if parent_category_id:
            data["parent_category_id"] = parent_category_id

        result = self._make_request("POST", "/categories.json", data=data)
        if result:
            logger.info(f"Created category: {name}")
        return CreateCategoryResponse.from_dict(result) if result is not None else None

    def update_category(
        self, category_id: int, **kwargs
    ) -> Optional[CreateCategoryResponse]:
        """Update category details."""
        result = self._make_request(
            "PUT", f"/categories/{category_id}.json", data=kwargs
        )
        return CreateCategoryResponse.from_dict(result) if result is not None else None

    # Topic operations
    def get_topic(self, topic_id: int) -> Optional[TopicDetailsResponse]:
        """Get topic details."""
        result = self._make_request("GET", f"/t/{topic_id}.json")
        return TopicDetailsResponse.from_dict(result) if result is not None else None

    def validate_api_key(self) -> bool:
        """Validate that the configured Api-Key/Api-Username are accepted by the server.

        This performs a lightweight request for the configured username. If the
        server returns a valid user object we consider the credentials valid.
        Returns True on success, False otherwise.
        """
        # Try to fetch the user resource for the API username
        try:
            endpoint = f"/u/{self.api_username}.json"
            result = self._make_request("GET", endpoint)
            if not result:
                logger.error(
                    "Discourse credential validation failed: no response or error from server"
                )
                return False

            # Discourse typically returns a top-level 'user' dict for this endpoint
            if isinstance(result, dict) and (
                "user" in result or result.get("username") == self.api_username
            ):
                return True

            # Some instances may return the user object at top-level
            user = result.get("user") if isinstance(result, dict) else None
            if user and user.get("username") == self.api_username:
                return True

            logger.error(
                "Discourse credential validation failed: unexpected response shape"
            )
            return False
        except Exception as e:
            logger.error(f"Exception during Discourse credential validation: {e}")
            return False

    def create_topic(
        self, title: str, raw: str, category_id: int, impersonate_username: Optional[str] = None
    ) -> Optional[CreateTopicResponse]:
        """
        Create a new topic.

        Args:
            title: Topic title
            raw: Topic content (raw Markdown)
            category_id: Category ID where the topic should be created
            impersonate_username: Username to post as (uses API impersonation)

        Returns:
            Created topic details or None if error
        """
        data = {"title": title, "raw": raw, "category": category_id}

        result = self._make_request(
            "POST", "/posts.json", data=data, impersonate_username=impersonate_username
        )
        if result:
            logger.info(f"Created topic: {title}")
        return CreateTopicResponse.from_dict(result) if result is not None else None

    def update_topic(self, topic_id: int, **kwargs) -> Optional[TopicDetailsResponse]:
        """Update topic details."""
        result = self._make_request("PUT", f"/t/{topic_id}.json", data=kwargs)
        return TopicDetailsResponse.from_dict(result) if result is not None else None

    # Post operations
    def get_post(self, post_id: int) -> Optional[PostDetailsResponse]:
        """Get post details."""
        result = self._make_request("GET", f"/posts/{post_id}.json")
        return PostDetailsResponse.from_dict(result) if result is not None else None

    def create_post(
        self, topic_id: int, raw: str, impersonate_username: Optional[str] = None
    ) -> Optional[PostDetailsResponse]:
        """
        Create a new post in a topic.

        Args:
            topic_id: Topic ID where the post should be created
            raw: Post content (raw Markdown)
            impersonate_username: Username to post as (uses API impersonation)

        Returns:
            Created post details or None if error
        """
        data = {"topic_id": topic_id, "raw": raw}

        result = self._make_request(
            "POST", "/posts.json", data=data, impersonate_username=impersonate_username
        )
        if result:
            logger.info(f"Created post in topic {topic_id}")
        return PostDetailsResponse.from_dict(result) if result is not None else None

    def update_post(self, post_id: int, raw: str) -> Optional[PostDetailsResponse]:
        """
        Update a post.

        Args:
            post_id: Post ID to update
            raw: New post content (raw Markdown)

        Returns:
            Updated post details or None if error
        """
        data = {"post": {"raw": raw}}
        result = self._make_request("PUT", f"/posts/{post_id}.json", data=data)
        if result:
            logger.info(f"Updated post {post_id}")
        return PostDetailsResponse.from_dict(result) if result is not None else None

    def delete_post(self, post_id: int) -> bool:
        """Delete a post."""
        result = self._make_request("DELETE", f"/posts/{post_id}.json")
        return result is not None

    # List operations
    def list_topics_in_category(
        self, category_id: int, page: int = 0
    ) -> Optional[ListTopicsResponse]:
        """List topics in a category."""
        result = self._make_request(
            "GET", f"/c/{category_id}.json", params={"page": page}
        )
        return ListTopicsResponse.from_dict(result) if result is not None else None

    def list_posts_in_topic(self, topic_id: int) -> Optional[ListPostsResponse]:
        """List all posts in a topic."""
        result = self._make_request("GET", f"/t/{topic_id}.json")
        return ListPostsResponse.from_dict(result) if result is not None else None

    # User operations
    def get_user(self, username: str) -> Optional[UserResponse]:
        """Get user details."""
        result = self._make_request("GET", f"/users/{username}.json")
        return UserResponse.from_dict(result) if result is not None else None

    def create_user(
        self,
        name: str,
        email: str,
        password: str,
        username: str,
        active: bool = True,
        approved: bool = True,
    ) -> Optional[UserResponse]:
        """
        Create a new user.

        Args:
            name: Full name of the user
            email: Email address
            password: Password for the user
            username: Username (must be unique)
            active: Whether the user is active
            approved: Whether the user is approved

        Returns:
            Created user details or None if error
        """
        data = {
            "name": name,
            "email": email,
            "password": password,
            "username": username,
            "active": active,
            "approved": approved,
        }

        result = self._make_request("POST", "/users.json", data=data, allow_errors=True)
        if result and result.get("_status_code"):
            # Check if user already exists
            status = result.get("_status_code")
            if status == 422:  # Unprocessable Entity - user might exist
                logger.info(f"User {username} might already exist, attempting to fetch")
                return self.get_user(username)
            logger.error(f"Failed to create user {username}: {result}")
            return None
        
        if result:
            logger.info(f"Created user: {username}")
        return UserResponse.from_dict(result) if result is not None else None
