# ABOUTME: Tests for attachment downloader with rate limiting and prioritization
# ABOUTME: Verifies parallel downloads and retry logic work correctly

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest  # type: ignore
from pytest_httpx import HTTPXMock  # type: ignore

from gchat_mirror.sync.attachment_downloader import AttachmentDownloader
from gchat_mirror.sync.attachment_storage import AttachmentStorage


@pytest.fixture
def test_databases(chat_db, attachments_db) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Create test chat.db and attachments.db with proper schemas."""
    chat_conn = chat_db.conn
    assert chat_conn is not None

    att_conn = attachments_db.conn
    assert att_conn is not None

    return chat_conn, att_conn


@pytest.mark.asyncio
async def test_attachment_downloader(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test parallel attachment downloading."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )

    # Create pending attachments
    for i in range(3):
        chat_conn.execute(
            """
            INSERT INTO messages (id, space_id, create_time)
            VALUES (?, ?, ?)
        """,
            (f"msg{i}", "space1", "2025-01-15T10:00:00Z"),
        )

        chat_conn.execute(
            """
            INSERT INTO attachments
            (id, message_id, name, size_bytes, source_url, downloaded)
            VALUES (?, ?, ?, ?, ?, FALSE)
        """,
            (f"att{i}", f"msg{i}", f"file{i}.txt", 100, f"https://example.com/file{i}"),
        )
    chat_conn.commit()

    # Mock downloads
    for i in range(3):
        httpx_mock.add_response(url=f"https://example.com/file{i}", content=b"X" * 100)

    # Download
    downloader = AttachmentDownloader(storage, max_workers=2)
    await downloader.download_pending_async(batch_size=10)

    # Verify all downloaded
    cursor = chat_conn.execute(
        """
        SELECT COUNT(*) FROM attachments WHERE downloaded = TRUE
    """
    )
    assert cursor.fetchone()[0] == 3

    # Verify stats
    assert downloader.stats["downloaded"] == 3
    assert downloader.stats["failed"] == 0
    assert downloader.stats["bytes_downloaded"] == 300


@pytest.mark.asyncio
async def test_rate_limit_handling(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test handling of 429 rate limit responses."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )

    # Create pending attachment
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, create_time)
        VALUES ('msg1', 'space1', '2025-01-15T10:00:00Z')
        """
    )
    chat_conn.execute(
        """
        INSERT INTO attachments
        (id, message_id, name, size_bytes, source_url, downloaded)
        VALUES ('att1', 'msg1', 'file.txt', 100, 'https://example.com/file', FALSE)
        """
    )
    chat_conn.commit()

    # Mock rate limit response
    httpx_mock.add_response(
        url="https://example.com/file", status_code=429, headers={"Retry-After": "5"}
    )

    downloader = AttachmentDownloader(storage, max_workers=1)
    await downloader.download_pending_async(batch_size=10)

    # Should have failed (not downloaded)
    assert downloader.stats["failed"] == 1
    assert downloader.stats["downloaded"] == 0

    # Check rate limit was recorded
    domain = "example.com"
    assert domain in downloader.rate_limits
    assert downloader.rate_limits[domain].retry_after_until is not None


@pytest.mark.asyncio
async def test_download_prioritization(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that recent messages with small files get priority."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )

    # Create attachments with different dates and sizes
    test_data = [
        ("att1", "msg1", "2025-01-10T10:00:00Z", 1000000),  # Old, large
        ("att2", "msg2", "2025-01-15T10:00:00Z", 100),  # Recent, small (should be first)
        ("att3", "msg3", "2025-01-15T10:00:00Z", 500000),  # Recent, medium (should be second)
    ]

    for att_id, msg_id, create_time, size in test_data:
        chat_conn.execute(
            """
            INSERT INTO messages (id, space_id, create_time)
            VALUES (?, ?, ?)
            """,
            (msg_id, "space1", create_time),
        )

        chat_conn.execute(
            """
            INSERT INTO attachments
            (id, message_id, name, size_bytes, source_url, downloaded)
            VALUES (?, ?, ?, ?, ?, FALSE)
            """,
            (att_id, msg_id, f"{att_id}.bin", size, f"https://example.com/{att_id}"),
        )

    chat_conn.commit()

    downloader = AttachmentDownloader(storage, max_workers=1)

    # Get prioritized tasks
    pending = downloader._get_pending_downloads(10)
    tasks = downloader._prioritize_tasks(pending)

    # Verify order: recent and small first
    assert tasks[0].attachment_id == "att2"  # Recent, smallest
    assert tasks[1].attachment_id == "att3"  # Recent, medium
    assert tasks[2].attachment_id == "att1"  # Old, large


@pytest.mark.asyncio
async def test_retry_after_numeric(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test parsing numeric Retry-After header."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Create pending attachment
    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, create_time)
        VALUES ('msg1', 'space1', '2025-01-15T10:00:00Z')
        """
    )
    chat_conn.execute(
        """
        INSERT INTO attachments
        (id, message_id, name, size_bytes, source_url, downloaded)
        VALUES ('att1', 'msg1', 'file.txt', 100, 'https://example.com/file', FALSE)
        """
    )
    chat_conn.commit()

    # Mock rate limit with numeric retry-after
    httpx_mock.add_response(
        url="https://example.com/file", status_code=429, headers={"Retry-After": "120"}
    )

    downloader = AttachmentDownloader(storage, max_workers=1)
    await downloader.download_pending_async(batch_size=10)

    # Check rate limit was set correctly
    domain = "example.com"
    assert domain in downloader.rate_limits
    retry_after_until = downloader.rate_limits[domain].retry_after_until
    assert retry_after_until is not None

    # Should be roughly 120 seconds in the future (allow some variance)
    wait_time = (retry_after_until - datetime.now()).total_seconds()
    assert 115 <= wait_time <= 125


@pytest.mark.asyncio
async def test_retry_after_http_date(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test parsing HTTP-date format Retry-After header."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Create pending attachment
    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, create_time)
        VALUES ('msg1', 'space1', '2025-01-15T10:00:00Z')
        """
    )
    chat_conn.execute(
        """
        INSERT INTO attachments
        (id, message_id, name, size_bytes, source_url, downloaded)
        VALUES ('att1', 'msg1', 'file.txt', 100, 'https://example.com/file', FALSE)
        """
    )
    chat_conn.commit()

    # Create an HTTP-date string for ~60 seconds in the future
    from email.utils import formatdate

    future_time = datetime.now().timestamp() + 60
    http_date = formatdate(future_time, usegmt=True)

    # Mock rate limit with HTTP-date retry-after
    httpx_mock.add_response(
        url="https://example.com/file", status_code=429, headers={"Retry-After": http_date}
    )

    downloader = AttachmentDownloader(storage, max_workers=1)
    await downloader.download_pending_async(batch_size=10)

    # Check rate limit was set correctly
    domain = "example.com"
    assert domain in downloader.rate_limits
    retry_after_until = downloader.rate_limits[domain].retry_after_until
    assert retry_after_until is not None

    # Should be roughly 60 seconds in the future (allow some variance)
    wait_time = (retry_after_until - datetime.now()).total_seconds()
    assert 55 <= wait_time <= 65


@pytest.mark.asyncio
async def test_exponential_backoff(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that failed downloads have exponential backoff."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Create a message
    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, create_time)
        VALUES ('msg1', 'space1', '2025-01-15T10:00:00Z')
        """
    )

    # Create attachments with different attempt counts
    test_cases = [
        ("att0", 0),  # First attempt - should be included
        ("att1", 1),  # Second attempt - should be included only after 5 min
        ("att2", 2),  # Third attempt - should be included only after 20 min
        ("att5", 5),  # Too many attempts - should be excluded
    ]

    for att_id, attempts in test_cases:
        chat_conn.execute(
            """
            INSERT INTO attachments (id, message_id, name, size_bytes, source_url, downloaded, download_attempts, created_at)
            VALUES (?, ?, ?, ?, ?, FALSE, ?, datetime('now', '-' || ? || ' minutes'))
            """,
            (
                att_id,
                "msg1",
                f"{att_id}.txt",
                100,
                f"https://example.com/{att_id}",
                attempts,
                attempts * attempts * 5 + 1,  # Just past the backoff period
            ),
        )

    chat_conn.commit()

    downloader = AttachmentDownloader(storage, max_workers=1)
    pending = downloader._get_pending_downloads(10)

    # Should get att0, att1, att2 (not att5 which has too many attempts)
    pending_ids = {row["id"] for row in pending}
    assert "att0" in pending_ids
    assert "att1" in pending_ids
    assert "att2" in pending_ids
    assert "att5" not in pending_ids


@pytest.mark.asyncio
async def test_http_error_handling(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test handling of various HTTP error codes."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)
    
    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )

    # Create pending attachments
    error_codes = [404, 403, 500]
    for i, code in enumerate(error_codes):
        chat_conn.execute(
            """
            INSERT INTO messages (id, space_id, create_time)
            VALUES (?, ?, ?)
            """,
            (f"msg{i}", "space1", "2025-01-15T10:00:00Z"),
        )

        chat_conn.execute(
            """
            INSERT INTO attachments
            (id, message_id, name, size_bytes, source_url, downloaded)
            VALUES (?, ?, ?, ?, ?, FALSE)
            """,
            (f"att{i}", f"msg{i}", f"file{i}.txt", 100, f"https://example.com/file{i}"),
        )

    chat_conn.commit()

    # Mock error responses
    for i, code in enumerate(error_codes):
        httpx_mock.add_response(url=f"https://example.com/file{i}", status_code=code)

    # Download
    downloader = AttachmentDownloader(storage, max_workers=2)
    await downloader.download_pending_async(batch_size=10)

    # All should have failed
    assert downloader.stats["failed"] == 3
    assert downloader.stats["downloaded"] == 0


@pytest.mark.asyncio
async def test_size_mismatch_handling(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection], httpx_mock: HTTPXMock
) -> None:
    """Test handling when downloaded size doesn't match expected."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Create pending attachment expecting 100 bytes
    chat_conn.execute(
        """
        INSERT INTO spaces (id, display_name, threaded)
        VALUES ('space1', 'Test Space', TRUE)
        """
    )
    chat_conn.execute(
        """
        INSERT INTO messages (id, space_id, create_time)
        VALUES ('msg1', 'space1', '2025-01-15T10:00:00Z')
        """
    )
    chat_conn.execute(
        """
        INSERT INTO attachments
        (id, message_id, name, size_bytes, source_url, downloaded)
        VALUES ('att1', 'msg1', 'file.txt', 100, 'https://example.com/file', FALSE)
        """
    )
    chat_conn.commit()

    # Mock response with wrong size (50 bytes instead of 100)
    httpx_mock.add_response(url="https://example.com/file", content=b"X" * 50)

    # Download
    downloader = AttachmentDownloader(storage, max_workers=1)
    await downloader.download_pending_async(batch_size=10)

    # Should have failed due to size mismatch
    assert downloader.stats["failed"] == 1
    assert downloader.stats["downloaded"] == 0

    # Verify attachment is still marked as not downloaded
    cursor = chat_conn.execute(
        "SELECT downloaded FROM attachments WHERE id = 'att1'"
    )
    assert cursor.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_max_workers_configuration(
    test_databases: tuple[sqlite3.Connection, sqlite3.Connection]
) -> None:
    """Test that max_workers can be configured."""
    chat_conn, att_conn = test_databases
    storage = AttachmentStorage(att_conn, chat_conn)

    # Test default (CPU/2)
    downloader1 = AttachmentDownloader(storage)
    import multiprocessing

    expected_workers = max(1, multiprocessing.cpu_count() // 2)
    assert downloader1.max_workers == expected_workers

    # Test custom value
    downloader2 = AttachmentDownloader(storage, max_workers=4)
    assert downloader2.max_workers == 4
