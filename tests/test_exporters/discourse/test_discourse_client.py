# ABOUTME: Tests for Discourse API client
# ABOUTME: Verifies API interactions, rate limiting, and error handling

from __future__ import annotations

import pytest  # type: ignore
from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.exporters.discourse.discourse_client import (
    DiscourseClient,
    DiscourseRateLimitError,
)


def test_discourse_create_category(httpx_mock: HTTPXMock) -> None:
    """Test creating a Discourse category."""
    httpx_mock.add_response(
        url="https://discourse.example.com/categories.json",
        method="POST",
        json={"category": {"id": 123, "name": "Test Category", "color": "0088CC"}},
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    category = client.create_category("Test Category")

    assert category["id"] == 123
    assert category["name"] == "Test Category"


def test_discourse_create_topic(httpx_mock: HTTPXMock) -> None:
    """Test creating a Discourse topic."""
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"id": 456, "topic_id": 789, "topic_slug": "test-topic"},
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    result = client.create_topic("Test Topic", "This is the content", category_id=123)

    assert result["topic_id"] == 789
    assert result["id"] == 456


def test_discourse_create_post(httpx_mock: HTTPXMock) -> None:
    """Test creating a post in an existing topic."""
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"id": 999, "topic_id": 789},
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    result = client.create_post(topic_id=789, raw="Reply content")

    assert result["id"] == 999
    assert result["topic_id"] == 789


def test_discourse_rate_limit_handling(httpx_mock: HTTPXMock) -> None:
    """Test handling of rate limit responses."""
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        status_code=429,
        headers={"Retry-After": "60"},
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    with pytest.raises(DiscourseRateLimitError) as exc_info:
        client.create_post(123, "test")

    assert exc_info.value.retry_after == 60


def test_discourse_upload_file(httpx_mock: HTTPXMock) -> None:
    """Test uploading a file."""
    httpx_mock.add_response(
        url="https://discourse.example.com/uploads.json?type=composer",
        method="POST",
        json={
            "url": "https://discourse.example.com/uploads/test.pdf",
            "short_url": "/uploads/short/abc123.pdf",
        },
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    result = client.upload_file(
        filename="test.pdf", file_data=b"PDF content here", content_type="application/pdf"
    )

    assert result["url"] == "https://discourse.example.com/uploads/test.pdf"


def test_discourse_create_user(httpx_mock: HTTPXMock) -> None:
    """Test creating a Discourse user."""
    httpx_mock.add_response(
        url="https://discourse.example.com/users.json",
        method="POST",
        json={"user_id": 42, "username": "testuser"},
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    result = client.create_user(email="test@example.com", username="testuser", name="Test User")

    assert result["user_id"] == 42


def test_discourse_get_user_by_username(httpx_mock: HTTPXMock) -> None:
    """Test getting a user by username."""
    httpx_mock.add_response(
        url="https://discourse.example.com/users/testuser.json",
        method="GET",
        json={"user": {"id": 42, "username": "testuser"}},
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    user = client.get_user_by_username("testuser")

    assert user is not None
    assert user["id"] == 42
    assert user["username"] == "testuser"


def test_discourse_get_user_not_found(httpx_mock: HTTPXMock) -> None:
    """Test getting a user that doesn't exist."""
    httpx_mock.add_response(
        url="https://discourse.example.com/users/nonexistent.json", method="GET", status_code=404
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    user = client.get_user_by_username("nonexistent")

    assert user is None


def test_discourse_create_private_message(httpx_mock: HTTPXMock) -> None:
    """Test creating a private message."""
    httpx_mock.add_response(
        url="https://discourse.example.com/posts.json",
        method="POST",
        json={"id": 111, "topic_id": 222},
    )

    client = DiscourseClient("https://discourse.example.com", "test_api_key")

    result = client.create_private_message(
        title="PM Title", raw="PM content", target_usernames=["user1", "user2"]
    )

    assert result["topic_id"] == 222
