# ABOUTME: Tests for notification queue management
# ABOUTME: Verifies enqueueing, retrieval, and processing of notifications

from __future__ import annotations

import pytest  # type: ignore

from gchat_mirror.common.notifications import NotificationManager


@pytest.fixture
def notification_manager(db) -> NotificationManager:
    """Create a NotificationManager backed by the shared `db` fixture."""
    assert db.conn is not None
    return NotificationManager(db.conn)


def test_notification_manager_enqueue(notification_manager: NotificationManager) -> None:
    """Test enqueueing notifications."""
    # Enqueue notifications
    notification_manager.enqueue("message", "msg1", "created", {"text": "hello"})
    notification_manager.enqueue("message", "msg2", "created", {"text": "world"})

    # Get pending
    pending = notification_manager.get_pending()
    assert len(pending) == 2
    assert pending[0]["entity_id"] == "msg1"
    assert pending[1]["entity_id"] == "msg2"


def test_notification_manager_mark_processed(
    notification_manager: NotificationManager,
) -> None:
    """Test marking notifications as processed."""
    # Enqueue notifications
    notification_manager.enqueue("message", "msg1", "created", {"text": "hello"})
    notification_manager.enqueue("message", "msg2", "created", {"text": "world"})

    # Get pending
    pending = notification_manager.get_pending()
    assert len(pending) == 2

    # Mark processed
    notification_ids = [p["id"] for p in pending]
    notification_manager.mark_processed(notification_ids)

    # Verify no longer pending
    pending = notification_manager.get_pending()
    assert len(pending) == 0


def test_notification_manager_get_pending_limit(
    notification_manager: NotificationManager,
) -> None:
    """Test that get_pending respects limit."""
    # Enqueue many notifications
    for i in range(10):
        notification_manager.enqueue("message", f"msg{i}", "created")

    # Get with limit
    pending = notification_manager.get_pending(limit=5)
    assert len(pending) == 5


def test_notification_manager_mark_processed_empty_list(
    notification_manager: NotificationManager,
) -> None:
    """Test that mark_processed handles empty list gracefully."""
    # Should not raise an error
    notification_manager.mark_processed([])
