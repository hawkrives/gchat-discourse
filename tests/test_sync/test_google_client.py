# ABOUTME: Tests for Google Chat API client wrapper
# ABOUTME: Ensures HTTP requests are formed and parsed correctly

from __future__ import annotations

from unittest.mock import Mock

import pytest  # type: ignore

from gchat_mirror.sync.google_client import GoogleChatClient


@pytest.fixture
def google_creds() -> Mock:
    creds = Mock()
    creds.token = "test-token"
    return creds


def test_list_spaces_returns_results(httpx_mock, google_creds: Mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://chat.googleapis.com/v1/spaces",
        json={"spaces": [{"name": "spaces/AAA", "displayName": "Alpha"}]},
    )

    client = GoogleChatClient(google_creds)
    spaces = client.list_spaces()

    assert spaces == [{"name": "spaces/AAA", "displayName": "Alpha"}]


def test_list_messages_supports_pagination(httpx_mock, google_creds: Mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://chat.googleapis.com/v1/spaces/AAA/messages?pageSize=50",
        json={
            "messages": [
                {"name": "spaces/AAA/messages/MSG1", "text": "Hello"},
                {"name": "spaces/AAA/messages/MSG2", "text": "Hi"},
            ],
            "nextPageToken": "token",
        },
    )

    client = GoogleChatClient(google_creds)
    response = client.list_messages("spaces/AAA", page_token=None, page_size=50)

    assert len(response["messages"]) == 2
    assert response["nextPageToken"] == "token"


def test_get_message_fetches_single_message(httpx_mock, google_creds: Mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://chat.googleapis.com/v1/spaces/AAA/messages/MSG1",
        json={"name": "spaces/AAA/messages/MSG1", "text": "Hello"},
    )

    client = GoogleChatClient(google_creds)
    message = client.get_message("spaces/AAA/messages/MSG1")

    assert message["text"] == "Hello"
