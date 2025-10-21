# ABOUTME: Tests for activity tracking and adaptive polling
# ABOUTME: Verifies poll interval calculation and space selection logic

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from datetime import datetime, timedelta

import pytest

from gchat_mirror.sync.activity_tracker import ActivityTracker


@pytest.fixture
def test_db(chat_db) -> Generator[sqlite3.Connection, None, None]:
    """Create a test database with migrations applied."""
    db_conn = chat_db.conn
    assert db_conn is not None
    yield db_conn


def test_activity_tracker_active_space(test_db: sqlite3.Connection) -> None:
    """Test that active spaces get short poll intervals."""
    # Config with default thresholds
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    # Create space
    test_db.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES (?, ?, ?, ?)
        """,
        ("space1", "spaces/space1", "Active Space", "active"),
    )

    # Add recent messages (15 messages in last 24 hours)
    now = datetime.now()
    for i in range(15):
        msg_time = (now - timedelta(hours=i)).isoformat()
        test_db.execute(
            """
            INSERT INTO messages (id, space_id, text, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (f"msg{i}", "space1", "test message", msg_time),
        )

    test_db.commit()

    # Update activity
    poll_interval = tracker.update_space_activity("space1")

    assert poll_interval == 10  # Active threshold

    # Verify database updated
    cursor = test_db.execute(
        """
        SELECT message_count_24h, poll_interval_seconds 
        FROM spaces WHERE id = ?
        """,
        ("space1",),
    )
    row = cursor.fetchone()
    assert row["message_count_24h"] >= 10
    assert row["poll_interval_seconds"] == 10


def test_activity_tracker_quiet_space(test_db: sqlite3.Connection) -> None:
    """Test that quiet spaces get long poll intervals."""
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    # Create space with no recent messages
    test_db.execute(
        """
        INSERT INTO spaces (id, name, display_name, sync_status)
        VALUES (?, ?, ?, ?)
        """,
        ("space1", "spaces/space1", "Quiet Space", "active"),
    )
    test_db.commit()

    # Update activity
    poll_interval = tracker.update_space_activity("space1")

    assert poll_interval == 300  # Quiet threshold

    cursor = test_db.execute(
        """
        SELECT message_count_24h, poll_interval_seconds 
        FROM spaces WHERE id = ?
        """,
        ("space1",),
    )
    row = cursor.fetchone()
    assert row["message_count_24h"] == 0
    assert row["poll_interval_seconds"] == 300


def test_activity_tracker_custom_thresholds(test_db: sqlite3.Connection) -> None:
    """Test that custom thresholds from config are respected."""
    # Custom config with different thresholds
    config = {"polling": {"active_threshold": 5, "active_interval": 30, "quiet_interval": 600}}
    tracker = ActivityTracker(test_db, config)

    # Create space with 6 recent messages (above custom threshold of 5)
    test_db.execute(
        """
        INSERT INTO spaces (id, name, sync_status)
        VALUES (?, ?, ?)
        """,
        ("space1", "Test Space", "active"),
    )

    now = datetime.now()
    for i in range(6):
        msg_time = (now - timedelta(hours=i)).isoformat()
        test_db.execute(
            """
            INSERT INTO messages (id, space_id, text, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (f"msg{i}", "space1", "test", msg_time),
        )

    test_db.commit()

    # Update activity
    poll_interval = tracker.update_space_activity("space1")

    assert poll_interval == 30  # Custom active interval


def test_get_spaces_to_poll_never_synced(test_db: sqlite3.Connection) -> None:
    """Test that spaces never synced are returned for polling."""
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    # Create spaces with no last_synced_at
    test_db.execute(
        """
        INSERT INTO spaces (id, name, sync_status, poll_interval_seconds)
        VALUES 
        ('space1', 'Never Synced 1', 'active', 60),
        ('space2', 'Never Synced 2', 'active', 60)
        """,
    )
    test_db.commit()

    # Get spaces to poll
    to_poll = tracker.get_spaces_to_poll()

    assert "space1" in to_poll
    assert "space2" in to_poll


def test_get_spaces_to_poll_respects_intervals(test_db: sqlite3.Connection) -> None:
    """Test that spaces are selected based on their poll intervals."""
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    # Create spaces with different last sync times
    # Use UTC times that clearly exceed or fall short of the interval
    from datetime import timezone

    now = datetime.now(timezone.utc)
    old_sync = (now - timedelta(minutes=10)).isoformat()
    recent_sync = (now - timedelta(seconds=30)).isoformat()

    test_db.execute(
        """
        INSERT INTO spaces 
        (id, name, sync_status, poll_interval_seconds, last_synced_at)
        VALUES 
        ('space1', 'Old Sync', 'active', 60, ?),
        ('space2', 'Recent Sync', 'active', 600, ?)
        """,
        (old_sync, recent_sync),
    )
    test_db.commit()

    # Get spaces to poll
    to_poll = tracker.get_spaces_to_poll()

    # space1 should be in list (10 minutes > 60 seconds interval)
    assert "space1" in to_poll
    # space2 should NOT be in list (30 seconds < 600 seconds interval)
    assert "space2" not in to_poll


def test_get_spaces_to_poll_excludes_access_denied(test_db: sqlite3.Connection) -> None:
    """Test that access_denied spaces are not returned for polling."""
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    test_db.execute(
        """
        INSERT INTO spaces 
        (id, name, sync_status, poll_interval_seconds)
        VALUES 
        ('space1', 'Active', 'active', 60),
        ('space2', 'Denied', 'access_denied', 60)
        """,
    )
    test_db.commit()

    to_poll = tracker.get_spaces_to_poll()

    assert "space1" in to_poll
    assert "space2" not in to_poll


def test_log_activity_window(test_db: sqlite3.Connection) -> None:
    """Test logging activity for a time window."""
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    # Create space and messages
    test_db.execute(
        """
        INSERT INTO spaces (id, name)
        VALUES (?, ?)
        """,
        ("space1", "Test Space"),
    )

    # Add messages in specific time window
    window_start = datetime(2025, 1, 15, 0, 0, 0)
    window_end = datetime(2025, 1, 16, 0, 0, 0)

    for i in range(5):
        msg_time = (window_start + timedelta(hours=i)).isoformat()
        test_db.execute(
            """
            INSERT INTO messages (id, space_id, text, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (f"msg{i}", "space1", "test", msg_time),
        )

    test_db.commit()

    # Log activity
    tracker.log_activity_window("space1", window_start, window_end)

    # Verify log entry
    cursor = test_db.execute(
        """
        SELECT space_id, message_count, window_start, window_end
        FROM space_activity_log
        WHERE space_id = ?
        """,
        ("space1",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row["space_id"] == "space1"
    assert row["message_count"] == 5
    assert row["window_start"] == window_start.isoformat()
    assert row["window_end"] == window_end.isoformat()


def test_activity_tracker_updates_last_activity_check(test_db: sqlite3.Connection) -> None:
    """Test that update_space_activity sets last_activity_check timestamp."""
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    # Create space
    test_db.execute(
        """
        INSERT INTO spaces (id, name, sync_status)
        VALUES (?, ?, ?)
        """,
        ("space1", "Test Space", "active"),
    )
    test_db.commit()

    # Verify last_activity_check is initially NULL
    cursor = test_db.execute("SELECT last_activity_check FROM spaces WHERE id = ?", ("space1",))
    row = cursor.fetchone()
    assert row["last_activity_check"] is None

    # Update activity
    tracker.update_space_activity("space1")

    # Verify last_activity_check is now set
    cursor = test_db.execute("SELECT last_activity_check FROM spaces WHERE id = ?", ("space1",))
    row = cursor.fetchone()
    assert row["last_activity_check"] is not None


def test_activity_tracker_counts_7d_messages(test_db: sqlite3.Connection) -> None:
    """Test that 7-day message count is tracked correctly."""
    config = {"polling": {"active_threshold": 10, "active_interval": 10, "quiet_interval": 300}}
    tracker = ActivityTracker(test_db, config)

    # Create space
    test_db.execute(
        """
        INSERT INTO spaces (id, name, sync_status)
        VALUES (?, ?, ?)
        """,
        ("space1", "Test Space", "active"),
    )

    # Add messages: 5 in last 24h, 10 more in last 7 days
    now = datetime.now()
    for i in range(5):
        msg_time = (now - timedelta(hours=i)).isoformat()
        test_db.execute(
            """
            INSERT INTO messages (id, space_id, text, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (f"msg_24h_{i}", "space1", "recent", msg_time),
        )

    for i in range(10):
        msg_time = (now - timedelta(days=2 + i / 10)).isoformat()
        test_db.execute(
            """
            INSERT INTO messages (id, space_id, text, create_time)
            VALUES (?, ?, ?, ?)
            """,
            (f"msg_7d_{i}", "space1", "older", msg_time),
        )

    test_db.commit()

    # Update activity
    tracker.update_space_activity("space1")

    # Verify counts
    cursor = test_db.execute(
        """
        SELECT message_count_24h, message_count_7d
        FROM spaces WHERE id = ?
        """,
        ("space1",),
    )
    row = cursor.fetchone()
    assert row["message_count_24h"] == 5
    assert row["message_count_7d"] >= 10  # At least the 7-day messages
