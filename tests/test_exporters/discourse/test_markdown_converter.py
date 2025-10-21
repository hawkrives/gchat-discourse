# ABOUTME: Tests for Google Chat to Discourse markdown conversion
# ABOUTME: Verifies formatting, mentions, and attachment handling

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest  # type: ignore

from gchat_mirror.exporters.discourse.markdown_converter import MarkdownConverter


@pytest.fixture
def setup_test_chat_db(tmp_path: Path) -> sqlite3.Connection:
    """Set up test chat database."""
    chat_db_path = tmp_path / "chat.db"
    chat_conn = sqlite3.Connection(chat_db_path)
    chat_conn.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            display_name TEXT
        )
    """)
    chat_conn.commit()
    return chat_conn


def test_markdown_converter_basic_formatting(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test basic formatting conversion."""
    converter = MarkdownConverter(setup_test_chat_db, Mock(), {})

    result = converter.convert_message(
        "This is **bold** and *italic* and ~~strikethrough~~", "msg1", []
    )

    assert "**bold**" in result
    assert "*italic*" in result
    assert "~~strikethrough~~" in result


def test_markdown_converter_underline(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test underline conversion."""
    converter = MarkdownConverter(setup_test_chat_db, Mock(), {})

    result = converter.convert_message("This is _underlined_ text", "msg1", [])

    assert "<u>underlined</u>" in result


def test_markdown_converter_mentions(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test mention conversion."""
    chat_conn = setup_test_chat_db

    chat_conn.execute("""
        INSERT INTO users (id, display_name)
        VALUES ('user1', 'Alice')
    """)
    chat_conn.commit()

    user_mapper = Mock()
    user_mapper.get_or_create_discourse_user.return_value = "alice"

    converter = MarkdownConverter(chat_conn, user_mapper, {})

    result = converter.convert_message("Hey <users/user1>, can you help?", "msg1", [])

    assert "@alice" in result
    assert "<users/user1>" not in result


def test_markdown_converter_mention_fallback(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test mention fallback when user mapping fails."""
    chat_conn = setup_test_chat_db

    chat_conn.execute("""
        INSERT INTO users (id, display_name)
        VALUES ('user1', 'Alice')
    """)
    chat_conn.commit()

    user_mapper = Mock()
    user_mapper.get_or_create_discourse_user.return_value = None

    converter = MarkdownConverter(chat_conn, user_mapper, {})

    result = converter.convert_message("Hey <users/user1>, can you help?", "msg1", [])

    # Should use display name as fallback
    assert "@Alice" in result


def test_markdown_converter_images(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test image attachment embedding."""
    attachments = [{"id": "attach1", "name": "photo.jpg", "content_type": "image/jpeg"}]

    cache = {"attach1": "https://discourse.example.com/uploads/photo.jpg"}

    converter = MarkdownConverter(setup_test_chat_db, Mock(), cache)

    result = converter.convert_message("Check this out!", "msg1", attachments)

    assert "Check this out!" in result
    assert "![photo.jpg](https://discourse.example.com/uploads/photo.jpg)" in result


def test_markdown_converter_files(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test file attachment linking."""
    attachments = [{"id": "attach1", "name": "document.pdf", "content_type": "application/pdf"}]

    cache = {"attach1": "https://discourse.example.com/uploads/document.pdf"}

    converter = MarkdownConverter(setup_test_chat_db, Mock(), cache)

    result = converter.convert_message("See attached document", "msg1", attachments)

    assert "[document.pdf](https://discourse.example.com/uploads/document.pdf)" in result


def test_markdown_converter_multiple_attachments(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test multiple attachments."""
    attachments = [
        {"id": "attach1", "name": "photo.jpg", "content_type": "image/jpeg"},
        {"id": "attach2", "name": "doc.pdf", "content_type": "application/pdf"},
    ]

    cache = {
        "attach1": "https://discourse.example.com/uploads/photo.jpg",
        "attach2": "https://discourse.example.com/uploads/doc.pdf",
    }

    converter = MarkdownConverter(setup_test_chat_db, Mock(), cache)

    result = converter.convert_message("Files attached", "msg1", attachments)

    assert "![photo.jpg]" in result
    assert "[doc.pdf]" in result


def test_markdown_converter_missing_attachment_url(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test handling missing attachment URL."""
    attachments = [{"id": "attach1", "name": "photo.jpg", "content_type": "image/jpeg"}]

    # No cache entry for this attachment
    converter = MarkdownConverter(setup_test_chat_db, Mock(), {})

    result = converter.convert_message("Check this out", "msg1", attachments)

    # Should show placeholder
    assert "*[Attachment: photo.jpg]*" in result


def test_markdown_converter_empty_message(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test empty message handling."""
    converter = MarkdownConverter(setup_test_chat_db, Mock(), {})

    result = converter.convert_message("", "msg1", [])

    assert result == ""


def test_markdown_converter_none_message(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test None message handling."""
    converter = MarkdownConverter(setup_test_chat_db, Mock(), {})

    result = converter.convert_message(None, "msg1", [])

    assert result == ""


def test_markdown_converter_code_blocks(setup_test_chat_db: sqlite3.Connection) -> None:
    """Test code block preservation."""
    converter = MarkdownConverter(setup_test_chat_db, Mock(), {})

    result = converter.convert_message(
        "Here's some `inline code` and:\n```\ncode block\n```", "msg1", []
    )

    # Code blocks should be preserved
    assert "`inline code`" in result
    assert "```" in result
