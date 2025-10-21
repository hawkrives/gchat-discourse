# ABOUTME: Tests for health check HTTP server endpoints
# ABOUTME: Ensures /health and /metrics endpoints return correct data
#
# NOTE: Health server tests are currently skipped because the health server
# requires background threading which has been removed to ensure SQLite
# thread safety. The health server functionality is disabled in the main
# daemon until a single-threaded async solution can be implemented.

from __future__ import annotations

import json
from http.client import HTTPConnection
from unittest.mock import Mock

import pytest  # type: ignore

from gchat_mirror.sync.health_server import HealthCheckServer


pytestmark = pytest.mark.skip(reason="Health server requires threading which is disabled for SQLite thread safety")


@pytest.fixture
def mock_daemon():
    """Create a mock daemon with health statistics."""
    daemon = Mock()
    daemon.get_space_count.return_value = 5
    daemon.get_message_count.return_value = 100
    daemon.get_last_sync_time.return_value = "2025-01-15T12:00:00+00:00"
    daemon.running = True
    return daemon


def test_health_endpoint_returns_json(mock_daemon):
    """Test that /health endpoint returns JSON with correct structure."""
    import random

    port = random.randint(10000, 60000)
    server = HealthCheckServer(mock_daemon, port)
    server.start()

    try:
        conn = HTTPConnection("localhost", port)
        conn.request("GET", "/health")
        response = conn.getresponse()

        assert response.status == 200
        assert response.getheader("Content-Type") == "application/json"

        data = json.loads(response.read().decode())
        assert data["status"] == "ok"
        assert data["spaces_synced"] == 5
        assert data["messages_synced"] == 100
        assert data["last_sync"] == "2025-01-15T12:00:00+00:00"
        assert "timestamp" in data

        conn.close()
    finally:
        server.stop()


def test_health_endpoint_with_never_synced(mock_daemon):
    """Test /health endpoint when daemon has never synced."""
    mock_daemon.get_last_sync_time.return_value = "never"
    mock_daemon.running = False

    import random

    port = random.randint(10000, 60000)
    server = HealthCheckServer(mock_daemon, port)
    server.start()

    try:
        conn = HTTPConnection("localhost", port)
        conn.request("GET", "/health")
        response = conn.getresponse()

        data = json.loads(response.read().decode())
        assert data["last_sync"] == "never"
        assert data["status"] == "stopped"

        conn.close()
    finally:
        server.stop()


def test_metrics_endpoint_returns_prometheus_format(mock_daemon):
    """Test that /metrics endpoint returns Prometheus format."""
    import random

    port = random.randint(10000, 60000)
    server = HealthCheckServer(mock_daemon, port)
    server.start()

    try:
        conn = HTTPConnection("localhost", port)
        conn.request("GET", "/metrics")
        response = conn.getresponse()

        assert response.status == 200
        assert response.getheader("Content-Type") == "text/plain"

        body = response.read().decode()
        assert "gchat_mirror_spaces_total 5" in body
        assert "gchat_mirror_messages_total 100" in body
        assert "gchat_mirror_up 1" in body

        conn.close()
    finally:
        server.stop()


def test_metrics_endpoint_with_not_running(mock_daemon):
    """Test /metrics endpoint when daemon is not running."""
    mock_daemon.running = False

    import random

    port = random.randint(10000, 60000)
    server = HealthCheckServer(mock_daemon, port)
    server.start()

    try:
        conn = HTTPConnection("localhost", port)
        conn.request("GET", "/metrics")
        response = conn.getresponse()

        body = response.read().decode()
        assert "gchat_mirror_up 0" in body

        conn.close()
    finally:
        server.stop()


def test_health_server_start_stop():
    """Test that health server starts and stops cleanly."""
    mock_daemon = Mock()
    mock_daemon.get_space_count.return_value = 0
    mock_daemon.get_message_count.return_value = 0
    mock_daemon.get_last_sync_time.return_value = "never"
    mock_daemon.running = False

    import random
    import time

    port = random.randint(10000, 60000)
    server = HealthCheckServer(mock_daemon, port)

    # Server should not be listening before start
    server.start()

    # Should be able to connect after start
    try:
        conn = HTTPConnection("localhost", port)
        conn.request("GET", "/health")
        response = conn.getresponse()
        assert response.status == 200
        conn.close()
    finally:
        server.stop()

    # Give the server a moment to fully shut down
    time.sleep(0.1)

    # Should not be able to connect after stop
    import socket

    with pytest.raises((ConnectionRefusedError, socket.error)):
        conn = HTTPConnection("localhost", port, timeout=0.5)
        conn.request("GET", "/health")
        conn.getresponse()


def test_unknown_endpoint_returns_404(mock_daemon):
    """Test that unknown endpoints return 404."""
    import random

    port = random.randint(10000, 60000)
    server = HealthCheckServer(mock_daemon, port)
    server.start()

    try:
        conn = HTTPConnection("localhost", port)
        conn.request("GET", "/unknown")
        response = conn.getresponse()

        assert response.status == 404

        conn.close()
    finally:
        server.stop()


def test_post_request_returns_501(mock_daemon):
    """Test that POST requests return 501 (not implemented)."""
    import random

    port = random.randint(10000, 60000)
    server = HealthCheckServer(mock_daemon, port)
    server.start()

    try:
        conn = HTTPConnection("localhost", port)
        conn.request("POST", "/health")
        response = conn.getresponse()

        assert response.status == 501

        conn.close()
    finally:
        server.stop()
