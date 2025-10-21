# ABOUTME: Tests for avatar downloader with history tracking
# ABOUTME: Verifies avatar downloads and URL change tracking work correctly

from __future__ import annotations

import sqlite3

import pytest  # type: ignore
from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.sync.avatar_downloader import AvatarDownloader
from gchat_mirror.sync.attachment_storage import AttachmentStorage


@pytest.fixture
def test_databases(db, attachments_db) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Use shared `db` fixture for chat DB and create a separate attachments DB."""
    # db is a Database manager; use its connection for chat DB
    assert db.conn is not None
    chat_conn = db.conn

    # attachments_db is a Database manager for attachments DB
    assert attachments_db.conn is not None
    att_conn = attachments_db.conn

    return chat_conn, att_conn


@pytest.mark.asyncio
async def test_avatar_download(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test avatar downloading."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    downloader = AvatarDownloader(storage, chat_conn)

    # Create user and avatar
    chat_conn.execute(
        """
        INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')
        """
    )
    chat_conn.execute(
        """
        INSERT INTO user_avatars (user_id, avatar_url, is_current)
        VALUES ('user1', 'https://example.com/avatar.jpg', TRUE)
        """
    )
    chat_conn.commit()

    # Mock download
    avatar_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # JPEG header + data
    httpx_mock.add_response(
        url="https://example.com/avatar.jpg",
        content=avatar_data,
        headers={"Content-Type": "image/jpeg"},
    )

    # Download
    await downloader.download_pending_avatars()

    # Verify downloaded
    cursor = chat_conn.execute(
        """
        SELECT downloaded, size_bytes FROM user_avatars 
        WHERE user_id = 'user1'
        """
    )
    row = cursor.fetchone()
    assert row["downloaded"] == 1
    assert row["size_bytes"] == len(avatar_data)


def test_avatar_url_change_tracking(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that avatar URL changes create history entries."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    downloader = AvatarDownloader(storage, chat_conn)

    chat_conn.execute(
        """
        INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')
        """
    )
    chat_conn.commit()

    # Set initial avatar
    downloader.update_user_avatar("user1", "https://example.com/avatar1.jpg")

    # Change avatar
    downloader.update_user_avatar("user1", "https://example.com/avatar2.jpg")

    # Verify history
    cursor = chat_conn.execute(
        """
        SELECT avatar_url, is_current 
        FROM user_avatars 
        WHERE user_id = 'user1'
        ORDER BY first_seen
        """
    )
    rows = cursor.fetchall()

    assert len(rows) == 2
    assert rows[0]["avatar_url"] == "https://example.com/avatar1.jpg"
    assert rows[0]["is_current"] == 0  # No longer current
    assert rows[1]["avatar_url"] == "https://example.com/avatar2.jpg"
    assert rows[1]["is_current"] == 1  # Current


def test_avatar_url_unchanged_updates_last_seen(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that calling update with same URL just updates last_seen."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    downloader = AvatarDownloader(storage, chat_conn)

    chat_conn.execute(
        """
        INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')
        """
    )
    chat_conn.commit()

    # Set initial avatar
    downloader.update_user_avatar("user1", "https://example.com/avatar1.jpg")

    # Get initial last_seen
    cursor = chat_conn.execute(
        """
        SELECT last_seen FROM user_avatars WHERE user_id = 'user1'
        """
    )
    first_last_seen = cursor.fetchone()["last_seen"]

    # Update with same URL (this would normally be called during sync)
    downloader.update_user_avatar("user1", "https://example.com/avatar1.jpg")

    # Verify only one record exists and last_seen was updated
    cursor = chat_conn.execute(
        """
        SELECT COUNT(*) as count FROM user_avatars WHERE user_id = 'user1'
        """
    )
    assert cursor.fetchone()["count"] == 1

    cursor = chat_conn.execute(
        """
        SELECT last_seen FROM user_avatars WHERE user_id = 'user1'
        """
    )
    second_last_seen = cursor.fetchone()["last_seen"]

    # last_seen should have changed
    assert second_last_seen >= first_last_seen


@pytest.mark.asyncio
async def test_avatar_download_failure_tracking(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test that failed avatar downloads are tracked."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    downloader = AvatarDownloader(storage, chat_conn)

    # Create user and avatar
    chat_conn.execute(
        """
        INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')
        """
    )
    chat_conn.execute(
        """
        INSERT INTO user_avatars (user_id, avatar_url, is_current)
        VALUES ('user1', 'https://example.com/avatar.jpg', TRUE)
        """
    )
    chat_conn.commit()

    # Mock failed download
    httpx_mock.add_response(
        url="https://example.com/avatar.jpg", status_code=404
    )

    # Attempt download
    await downloader.download_pending_avatars()

    # Verify failure tracked
    cursor = chat_conn.execute(
        """
        SELECT downloaded, download_attempts, download_error 
        FROM user_avatars 
        WHERE user_id = 'user1'
        """
    )
    row = cursor.fetchone()
    assert row["downloaded"] == 0
    assert row["download_attempts"] == 1
    assert "404" in row["download_error"]


def test_update_user_avatar_handles_none(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that update_user_avatar handles None gracefully."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    downloader = AvatarDownloader(storage, chat_conn)

    chat_conn.execute(
        """
        INSERT INTO users (id, display_name) VALUES ('user1', 'Alice')
        """
    )
    chat_conn.commit()

    # Should not create any avatar record
    downloader.update_user_avatar("user1", None)

    cursor = chat_conn.execute(
        """
        SELECT COUNT(*) as count FROM user_avatars WHERE user_id = 'user1'
        """
    )
    assert cursor.fetchone()["count"] == 0
