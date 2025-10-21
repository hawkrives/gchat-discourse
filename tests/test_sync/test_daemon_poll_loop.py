# ABOUTME: Tests for sync daemon continuous polling behavior
# ABOUTME: Ensures daemon enters poll loop after initial sync

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import Mock, patch
import random

import pytest

from gchat_mirror.sync.daemon import SyncDaemon


@pytest.fixture
def daemon(tmp_path: Path) -> SyncDaemon:
    # Use a random port to avoid port conflicts between tests
    port = random.randint(10000, 60000)
    config = {"credential_key": "test-key", "monitoring": {"health_check_port": port}}
    return SyncDaemon(tmp_path, config)


def test_daemon_enters_poll_loop_after_initial_sync(
    monkeypatch: pytest.MonkeyPatch, daemon: SyncDaemon
) -> None:
    """Test that daemon can be started and then enter continuous polling mode."""
    mock_creds = Mock()
    monkeypatch.setattr("gchat_mirror.sync.daemon.authenticate", lambda key: mock_creds)

    # Mock the Google Chat client
    mock_client = Mock()
    mock_client.list_spaces.return_value = []
    monkeypatch.setattr("gchat_mirror.sync.daemon.GoogleChatClient", lambda creds: mock_client)

    # First call start() to initialize (this should not enter the poll loop)
    daemon.start()
    
    # Verify daemon is initialized
    assert daemon.client is not None
    
    # Patch poll_loop to track if it's called
    poll_loop_called = False
    original_poll_loop = daemon.poll_loop

    async def mock_poll_loop():
        nonlocal poll_loop_called
        poll_loop_called = True
        # Stop immediately to allow test to complete
        daemon.running = False
        await original_poll_loop()

    with patch.object(daemon, "poll_loop", mock_poll_loop):
        # Now run_forever should enter the poll loop
        daemon.run_forever()

    # Verify poll_loop was entered
    assert poll_loop_called, "daemon.run_forever() should enter poll_loop()"


def test_poll_loop_stops_when_running_false(
    monkeypatch: pytest.MonkeyPatch, daemon: SyncDaemon, tmp_path: Path
) -> None:
    """Test that poll_loop respects the running flag."""
    from gchat_mirror.sync.activity_tracker import ActivityTracker
    
    # Set up minimal daemon state without calling start() which would block
    # The daemon fixture already has chat_db initialized from __init__
    daemon.chat_db.connect()
    
    # Create activity tracker with the database connection
    if daemon.chat_db.conn is None:
        raise RuntimeError("Database connection is None")
        
    daemon.activity_tracker = ActivityTracker(
        daemon.chat_db.conn,
        config={"activity": {"active_threshold_days": 10}}
    )
    
    # Set running to False before entering poll loop
    daemon.running = False

    # Poll loop should exit immediately without hanging
    asyncio.run(daemon.poll_loop())
    # If we get here without hanging, the test passes
